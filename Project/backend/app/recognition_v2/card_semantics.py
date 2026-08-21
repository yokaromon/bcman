"""管理下Visionモデルによる、OpenCV候補の「名刺らしさ」選別。

画像はメモリ上で候補ごとに台形補正した一覧シートへ変換し、data URLとして
管理下ykrへ送る。原画像、候補画像、応答のいずれもファイルやDBへ保存しない。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import detector
from .ykr_client import ManagedRecognitionClient


SEMANTIC_FILTER_VERSION = "managed-cardness-v2"
SHEET_MAX_COLUMNS = 3
SHEET_CELL_WIDTH = 500
SHEET_CELL_HEIGHT = 310
SHEET_LABEL_HEIGHT = 46
SHEET_PADDING = 16
REASONS = {
    "one_complete_card",
    "multiple_cards_or_background",
    "partial_card",
    "non_card_object",
    "insufficient_visual_evidence",
}
DECISIONS = {"business_card", "not_business_card", "uncertain"}
BASE_DIR = Path(__file__).resolve().parent


class CardSemanticContractError(ValueError):
    """候補選別のJSON契約に違反した応答。"""


@dataclass(frozen=True)
class SemanticVerdict:
    candidate_id: int
    decision: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class SemanticSelection:
    verdicts: dict[int, SemanticVerdict]
    attempts: int
    model: str
    version: str = SEMANTIC_FILTER_VERSION


def _prompt() -> str:
    return (BASE_DIR / "prompts" / "v1" / "card_candidates.txt").read_text(
        encoding="utf-8"
    ).strip()


def _validate_document(document: dict, expected_ids: set[int]) -> dict:
    if set(document) != {"schema_version", "candidates"}:
        raise CardSemanticContractError("rootのキーが契約と一致しません")
    schema_version = document["schema_version"]
    if (
        isinstance(schema_version, bool)
        or schema_version != 1
        or not isinstance(document["candidates"], list)
    ):
        raise CardSemanticContractError("schema_versionまたはcandidatesが不正です")

    normalized = []
    found_ids: list[int] = []
    required = {"candidate_id", "decision", "confidence", "reason"}
    for item in document["candidates"]:
        if not isinstance(item, dict) or set(item) != required:
            raise CardSemanticContractError("candidateのキーが契約と一致しません")
        candidate_id = item["candidate_id"]
        confidence = item["confidence"]
        if isinstance(candidate_id, bool) or not isinstance(candidate_id, int):
            raise CardSemanticContractError("candidate_idは整数である必要があります")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise CardSemanticContractError("confidenceは数値である必要があります")
        if not 0.0 <= float(confidence) <= 1.0:
            raise CardSemanticContractError("confidenceは0から1の範囲です")
        decision = item["decision"]
        reason = item["reason"]
        if decision not in DECISIONS or reason not in REASONS:
            raise CardSemanticContractError("decisionまたはreasonが契約外です")
        if decision == "business_card" and reason != "one_complete_card":
            raise CardSemanticContractError("business_cardのreasonが矛盾しています")
        if decision == "uncertain" and reason != "insufficient_visual_evidence":
            raise CardSemanticContractError("uncertainのreasonが矛盾しています")
        if decision == "not_business_card" and reason in {
            "one_complete_card", "insufficient_visual_evidence"
        }:
            raise CardSemanticContractError("not_business_cardのreasonが矛盾しています")
        found_ids.append(candidate_id)
        normalized.append(
            {
                "candidate_id": candidate_id,
                "decision": decision,
                "confidence": round(float(confidence), 4),
                "reason": reason,
            }
        )
    if len(found_ids) != len(set(found_ids)) or set(found_ids) != expected_ids:
        raise CardSemanticContractError("候補番号に重複・欠落・追加があります")
    return {"schema_version": 1, "candidates": normalized}


def _candidate_sheet_data_url(
    image: np.ndarray, detections: list[detector.Detection]
) -> str:
    """重なった候補線を排除し、候補ごとの内容を独立して比較できる画像を作る。"""
    if not detections:
        raise ValueError("候補一覧シートには1件以上の候補が必要です")
    columns = min(SHEET_MAX_COLUMNS, max(1, int(np.ceil(np.sqrt(len(detections))))))
    rows = int(np.ceil(len(detections) / columns))
    sheet = np.full(
        (rows * SHEET_CELL_HEIGHT, columns * SHEET_CELL_WIDTH, 3),
        30,
        dtype=np.uint8,
    )
    for candidate_id, detection in enumerate(detections, 1):
        row, column = divmod(candidate_id - 1, columns)
        x = column * SHEET_CELL_WIDTH
        y = row * SHEET_CELL_HEIGHT
        cv2.rectangle(
            sheet,
            (x + 2, y + 2),
            (x + SHEET_CELL_WIDTH - 3, y + SHEET_LABEL_HEIGHT - 1),
            (210, 20, 105),
            -1,
        )
        cv2.putText(
            sheet,
            f"CANDIDATE {candidate_id}",
            (x + 14, y + 33),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.82,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        crop = detector.perspective_crop(image, detection.corners)
        available_width = SHEET_CELL_WIDTH - 2 * SHEET_PADDING
        available_height = (
            SHEET_CELL_HEIGHT - SHEET_LABEL_HEIGHT - 2 * SHEET_PADDING
        )
        scale = min(
            available_width / max(1, crop.shape[1]),
            available_height / max(1, crop.shape[0]),
        )
        resized = cv2.resize(
            crop,
            (
                max(1, round(crop.shape[1] * scale)),
                max(1, round(crop.shape[0] * scale)),
            ),
            interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
        )
        crop_x = x + (SHEET_CELL_WIDTH - resized.shape[1]) // 2
        content_top = y + SHEET_LABEL_HEIGHT
        crop_y = content_top + (SHEET_CELL_HEIGHT - SHEET_LABEL_HEIGHT - resized.shape[0]) // 2
        sheet[crop_y:crop_y + resized.shape[0], crop_x:crop_x + resized.shape[1]] = resized
        cv2.rectangle(
            sheet,
            (crop_x, crop_y),
            (crop_x + resized.shape[1] - 1, crop_y + resized.shape[0] - 1),
            (225, 225, 225),
            2,
        )
    ok, encoded = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("候補ラベル画像を作成できません")
    return "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")


def classify_card_candidates(
    image: np.ndarray,
    detections: list[detector.Detection],
    client: ManagedRecognitionClient,
) -> SemanticSelection:
    expected_ids = set(range(1, len(detections) + 1))
    stage = client.analyze_image_json(
        image_data_url=_candidate_sheet_data_url(image, detections),
        prompt=_prompt(),
        validator=lambda value: _validate_document(value, expected_ids),
        stage="名刺候補選別",
        prompt_version=SEMANTIC_FILTER_VERSION,
    )
    verdicts = {
        item["candidate_id"]: SemanticVerdict(**item)
        for item in stage.document["candidates"]
    }
    return SemanticSelection(verdicts, stage.attempts, stage.model)
