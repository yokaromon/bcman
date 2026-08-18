from __future__ import annotations

import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path
from typing import Iterable

import numpy as np


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = BASE_DIR / "model_manifest.json"
DEFAULT_MODEL_DIR = BASE_DIR.parent.parent / "models_v2"
DEFAULT_CACHE_DIR = BASE_DIR.parent.parent / ".paddlex-cache"
VERIFICATION_STAMP_NAME = ".bcman-model-verification.json"


class ModelConfigurationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelConfigurationError(f"モデルmanifestを読めません: {path}") from exc
    if document.get("schema_version") != 1 or not isinstance(
        document.get("models"), dict
    ):
        raise ModelConfigurationError(f"モデルmanifestが不正です: {path}")
    return document


def _manifest_digest(manifest: dict) -> str:
    canonical = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _load_verification_stamp(model_root: Path, manifest: dict) -> dict:
    path = model_root / VERIFICATION_STAMP_NAME
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "manifest_sha256": _manifest_digest(manifest), "files": {}}
    if (
        document.get("schema_version") != 1
        or document.get("manifest_sha256") != _manifest_digest(manifest)
        or not isinstance(document.get("files"), dict)
    ):
        return {"schema_version": 1, "manifest_sha256": _manifest_digest(manifest), "files": {}}
    return document


def _stamp_key(key: str, relative: str) -> str:
    return f"{key}/{relative.replace(chr(92), '/')}"


def _stamp_matches(stamp: dict, name: str, target: Path, expected: str) -> bool:
    record = stamp["files"].get(name)
    if not isinstance(record, dict):
        return False
    try:
        stat = target.stat()
    except OSError:
        return False
    return (
        record.get("sha256", "").casefold() == expected.casefold()
        and record.get("size") == stat.st_size
        and record.get("mtime_ns") == stat.st_mtime_ns
    )


def write_verification_stamp(
    model_root: Path,
    manifest: dict,
    keys: Iterable[str],
) -> None:
    stamp = _load_verification_stamp(model_root, manifest)
    for key in keys:
        spec = manifest["models"][key]
        directory = model_root / spec["directory"]
        for relative, expected in spec["files"].items():
            target = directory / relative
            stat = target.stat()
            stamp["files"][_stamp_key(key, relative)] = {
                "sha256": expected,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
    path = model_root / VERIFICATION_STAMP_NAME
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(stamp, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _font_candidates() -> list[Path]:
    configured = os.environ.get("BCMAN_V2_FONT_PATH")
    candidates = [Path(configured)] if configured else []
    candidates.extend(
        [
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path(r"C:\Windows\Fonts\meiryo.ttc"),
            Path(r"C:\Windows\Fonts\YuGothR.ttc"),
        ]
    )
    return candidates


def configure_offline_paddle_environment() -> Path:
    font_path = next((path for path in _font_candidates() if path.is_file()), None)
    if font_path is None:
        raise ModelConfigurationError(
            "PaddleX用ローカルフォントがありません。BCMAN_V2_FONT_PATHへ"
            "既存TTF/TTCの絶対パスを設定してください"
            "（Linuxではfonts-noto-cjkパッケージ等の導入を検討する）"
        )
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["PADDLE_PDX_LOCAL_FONT_FILE_PATH"] = str(font_path.resolve())
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(DEFAULT_CACHE_DIR.resolve()))
    return font_path.resolve()


def verify_runtime_versions(manifest: dict) -> None:
    expected = manifest["runtime"]
    packages = {
        "paddlepaddle": "paddlepaddle",
        "paddleocr": "paddleocr",
        "paddlex": "paddlex",
    }
    problems = []
    for key, package in packages.items():
        actual = version(package)
        if actual != expected[key]:
            problems.append(f"{package}: expected={expected[key]} actual={actual}")
    if problems:
        raise ModelConfigurationError("Paddle runtime版が一致しません: " + "; ".join(problems))


def verify_model_files(
    keys: Iterable[str],
    model_root: Path = DEFAULT_MODEL_DIR,
    manifest: dict | None = None,
) -> dict[str, Path]:
    document = manifest or load_manifest()
    selected = list(keys)
    stamp = _load_verification_stamp(model_root, document)
    resolved: dict[str, Path] = {}
    for key in selected:
        if key not in document["models"]:
            raise ModelConfigurationError(f"未知のmodel keyです: {key}")
        spec = document["models"][key]
        directory = model_root / spec["directory"]
        if not directory.is_dir():
            raise ModelConfigurationError(
                f"モデルがありません: {directory}。provision_models.pyを実行してください"
            )
        for relative, expected in spec["files"].items():
            target = directory / relative
            if not target.is_file():
                raise ModelConfigurationError(f"モデル必須ファイルがありません: {target}")
            stamp_name = _stamp_key(key, relative)
            if not _stamp_matches(stamp, stamp_name, target, expected):
                actual = _sha256(target)
                if actual.casefold() != expected.casefold():
                    raise ModelConfigurationError(
                        f"モデルSHA-256が一致しません: {target}"
                    )
        resolved[key] = directory.resolve()
    try:
        write_verification_stamp(model_root, document, selected)
    except OSError as exc:
        raise ModelConfigurationError("モデル検証stampを書けません") from exc
    return resolved


def _payload(result: object) -> dict:
    value = getattr(result, "json", None)
    if callable(value):
        value = value()
    if not isinstance(value, dict):
        raise ModelConfigurationError("Paddle推論結果がJSON objectではありません")
    payload = value.get("res", value)
    if not isinstance(payload, dict):
        raise ModelConfigurationError("Paddle推論結果のresが不正です")
    return payload


class PaddleModels:
    """固定済みPaddleモデル（向き分類器のみ）を1プロセス内で遅延生成して再利用する。

    pickup/model_runtime.py のトリム版。text_detection/recognitionモデル
    （174MB、ローカルOCR診断専用）は本番では使わないため含めない。"""

    def __init__(
        self,
        model_root: Path = DEFAULT_MODEL_DIR,
        manifest_path: Path = DEFAULT_MANIFEST,
    ) -> None:
        self.manifest = load_manifest(manifest_path)
        verify_runtime_versions(self.manifest)
        self.font_path = configure_offline_paddle_environment()
        self.model_root = model_root.resolve()
        self._paths: dict[str, Path] = {}
        self._orientation = None

    def _path(self, key: str) -> Path:
        if key not in self._paths:
            self._paths.update(
                verify_model_files([key], self.model_root, self.manifest)
            )
        return self._paths[key]

    def _common(self) -> dict:
        return {"device": "cpu", "enable_hpi": False}

    def orientation_model(self):
        if self._orientation is None:
            from paddleocr import DocImgOrientationClassification

            spec = self.manifest["models"]["doc_orientation"]
            self._orientation = DocImgOrientationClassification(
                model_name=spec["model_name"],
                model_dir=str(self._path("doc_orientation")),
                **self._common(),
            )
        return self._orientation

    def classify(self, images: list[np.ndarray]) -> list[dict]:
        results = self.orientation_model().predict(images, batch_size=len(images))
        predictions = []
        for result in results:
            payload = _payload(result)
            labels = payload.get("label_names") or []
            scores = payload.get("scores") or []
            if not labels or not scores:
                raise ModelConfigurationError("向き判定結果にlabelまたはscoreがありません")
            predictions.append(
                {"label": int(labels[0]), "score": float(scores[0])}
            )
        return predictions
