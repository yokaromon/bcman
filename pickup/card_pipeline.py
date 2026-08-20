from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from alignment import align_ocr_lines
from detector import read_image, write_image
from local_contact import extract_local_contact
from model_runtime import PaddleModels
from orientation import OrientationEngine
from recognition_contract import enrich_contact
from recognition_fingerprint import recognition_fingerprint
from text_regions import LocalTextPipeline
from ykr_client import ManagedRecognitionClient, ManagedRecognitionError, YkrSettings


PIPELINE_SCHEMA_VERSION = 1
LOCAL_MODEL_VERSIONS = {
    "orientation": "PP-LCNet_x1_0_doc_ori",
    "detection": "PP-OCRv5_server_det",
    "recognition": "PP-OCRv5_server_rec",
}
PROMPT_VERSIONS = {"ocr": "ocr-v1", "contact": "contact-v2"}


def _write_json(path: Path, document: dict) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _cached(path: Path, fingerprint: str) -> dict | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        document.get("recognition_fingerprint") == fingerprint
        and document.get("status") == "succeeded"
    ):
        return document
    return None


class PickupCardPipeline:
    def __init__(
        self,
        mode: str = "local",
        *,
        models=None,
        ykr_client: ManagedRecognitionClient | None = None,
    ) -> None:
        if mode not in {"orientation", "local", "full"}:
            raise ValueError(f"未知のpipeline modeです: {mode}")
        self.mode = mode
        self.models = models or PaddleModels()
        self.text = LocalTextPipeline(self.models)
        self.orientation = OrientationEngine(self.models)
        if mode == "full":
            self.ykr = ykr_client or ManagedRecognitionClient(
                YkrSettings.from_environment()
            )
        else:
            self.ykr = None

    def _fingerprint(self, image_path: Path, rotation: int) -> str:
        ykr_models = (
            {
                "ocr": self.ykr.settings.ocr_model,
                "contact": self.ykr.settings.contact_model,
            }
            if self.ykr is not None
            else {}
        )
        return recognition_fingerprint(
            image_path,
            orientation=rotation,
            local_models=LOCAL_MODEL_VERSIONS,
            ykr_models=ykr_models,
            prompt_versions=PROMPT_VERSIONS,
            schema_version=PIPELINE_SCHEMA_VERSION,
        )

    def process_card(
        self,
        card_path: Path,
        *,
        prefix: str,
        previous_dir: Path | None = None,
        force_recognition: bool = False,
    ) -> dict:
        started = time.perf_counter()
        directory = card_path.parent
        image = read_image(card_path)
        oriented, orientation_document = self.orientation.analyze(
            image, readability_scorer=self.text.readability
        )
        oriented_path = directory / f"{prefix}.oriented.png"
        orientation_path = directory / f"{prefix}.orientation.json"
        write_image(oriented_path, oriented)
        _write_json(orientation_path, orientation_document)

        if self.mode == "orientation":
            placeholder_paths = {
                "ocr_paddle": directory / f"{prefix}.ocr.paddle.json",
                "ocr_ykr": directory / f"{prefix}.ocr.ykr.json",
                "contact_paddle": directory / f"{prefix}.contact.paddle.json",
                "contact_ykr": directory / f"{prefix}.contact.ykr.json",
            }
            for name, path in placeholder_paths.items():
                _write_json(
                    path,
                    {
                        "schema_version": 1,
                        "stage": "ocr" if name.startswith("ocr") else "contact",
                        "status": "not_requested",
                    },
                )
            fingerprint = self._fingerprint(
                oriented_path, orientation_document["rotation_applied"]
            )
            return {
                "schema_version": PIPELINE_SCHEMA_VERSION,
                "mode": self.mode,
                "status": "orientation_completed",
                "orientation_status": orientation_document["status"],
                "rotation_applied": orientation_document["rotation_applied"],
                "recognition_fingerprint": fingerprint,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "artifacts": {
                    "orientation": orientation_path.name,
                    "oriented_image": oriented_path.name,
                    **{name: path.name for name, path in placeholder_paths.items()},
                },
            }

        local_ocr = self.text.process(oriented, server=True)
        local_ocr.update(
            {
                "stage": "ocr",
                "status": "succeeded",
                "orientation_status": orientation_document["status"],
            }
        )
        local_ocr_path = directory / f"{prefix}.ocr.paddle.json"
        _write_json(local_ocr_path, local_ocr)
        local_contact = extract_local_contact(local_ocr)
        local_contact.update({"stage": "contact", "status": "succeeded"})
        local_contact_path = directory / f"{prefix}.contact.paddle.json"
        _write_json(local_contact_path, local_contact)

        fingerprint = self._fingerprint(
            oriented_path, orientation_document["rotation_applied"]
        )
        ykr_ocr_path = directory / f"{prefix}.ocr.ykr.json"
        ykr_contact_path = directory / f"{prefix}.contact.ykr.json"
        if self.ykr is None:
            _write_json(
                ykr_ocr_path,
                {"schema_version": 1, "stage": "ocr", "status": "not_requested"},
            )
            _write_json(
                ykr_contact_path,
                {
                    "schema_version": 1,
                    "stage": "contact",
                    "status": "not_requested",
                },
            )
            status = "local_completed"
        else:
            if force_recognition and previous_dir is not None:
                self._archive_previous(previous_dir, directory, prefix)
            status = self._run_managed(
                oriented_path=oriented_path,
                local_ocr=local_ocr,
                prefix=prefix,
                ykr_ocr_path=ykr_ocr_path,
                ykr_contact_path=ykr_contact_path,
                previous_dir=previous_dir,
                fingerprint=fingerprint,
                force_recognition=force_recognition,
            )

        return {
            "schema_version": PIPELINE_SCHEMA_VERSION,
            "mode": self.mode,
            "status": status,
            "orientation_status": orientation_document["status"],
            "rotation_applied": orientation_document["rotation_applied"],
            "recognition_fingerprint": fingerprint,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "artifacts": {
                "orientation": orientation_path.name,
                "oriented_image": oriented_path.name,
                "ocr_paddle": local_ocr_path.name,
                "ocr_ykr": ykr_ocr_path.name,
                "contact_paddle": local_contact_path.name,
                "contact_ykr": ykr_contact_path.name,
            },
        }

    @staticmethod
    def _archive_previous(previous_dir: Path, directory: Path, prefix: str) -> None:
        history = directory / "recognition_history"
        history.mkdir(parents=True, exist_ok=True)
        revision = f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
        for kind in ("ocr.ykr.json", "contact.ykr.json"):
            source = previous_dir / f"{prefix}.{kind}"
            if source.is_file():
                shutil.copy2(source, history / f"{prefix}.{revision}.{kind}")

    def _run_managed(
        self,
        *,
        oriented_path: Path,
        local_ocr: dict,
        prefix: str,
        ykr_ocr_path: Path,
        ykr_contact_path: Path,
        previous_dir: Path | None,
        fingerprint: str,
        force_recognition: bool,
    ) -> str:
        previous_ocr = (
            _cached(previous_dir / f"{prefix}.ocr.ykr.json", fingerprint)
            if previous_dir is not None and not force_recognition
            else None
        )
        if previous_ocr is not None:
            ocr_artifact = previous_ocr
            ocr_artifact["cache_reused"] = True
        else:
            try:
                result = self.ykr.run_ocr(oriented_path)
                alignment = align_ocr_lines(local_ocr, result.document)
                ocr_artifact = {
                    "schema_version": 1,
                    "stage": "ocr",
                    "status": "succeeded",
                    "recognition_fingerprint": fingerprint,
                    "model": result.model,
                    "prompt_version": result.prompt_version,
                    "attempts": result.attempts,
                    "cache_reused": False,
                    "lines": result.document["lines"],
                    "alignment": alignment,
                }
            except Exception as exc:
                _write_json(
                    ykr_ocr_path,
                    {
                        "schema_version": 1,
                        "stage": "ocr",
                        "status": "failed",
                        "recognition_fingerprint": fingerprint,
                        "retry_required": True,
                        "error_type": type(exc).__name__,
                    },
                )
                _write_json(
                    ykr_contact_path,
                    {
                        "schema_version": 1,
                        "stage": "contact",
                        "status": "blocked",
                        "recognition_fingerprint": fingerprint,
                        "reason": "ocr_failed",
                        "retry_required": True,
                    },
                )
                return "partial"
        _write_json(ykr_ocr_path, ocr_artifact)

        previous_contact = (
            _cached(previous_dir / f"{prefix}.contact.ykr.json", fingerprint)
            if previous_dir is not None and not force_recognition
            else None
        )
        if previous_contact is not None:
            contact_artifact = previous_contact
            contact_artifact["cache_reused"] = True
            _write_json(ykr_contact_path, contact_artifact)
            return "completed"
        try:
            ocr_document = {
                "schema_version": 1,
                "lines": ocr_artifact["lines"],
            }
            result = self.ykr.structure_contact(
                ocr_document, ocr_artifact.get("alignment", [])
            )
            enriched = enrich_contact(
                result.document,
                ocr_document,
                ocr_artifact.get("alignment", []),
            )
            contact_artifact = {
                **enriched,
                "stage": "contact",
                "status": "succeeded",
                "recognition_fingerprint": fingerprint,
                "model": result.model,
                "prompt_version": result.prompt_version,
                "attempts": result.attempts,
                "cache_reused": False,
            }
            _write_json(ykr_contact_path, contact_artifact)
            return "completed"
        except Exception as exc:
            _write_json(
                ykr_contact_path,
                {
                    "schema_version": 1,
                    "stage": "contact",
                    "status": "failed",
                    "recognition_fingerprint": fingerprint,
                    "retry_required": True,
                    "error_type": type(exc).__name__,
                },
            )
            return "partial"
