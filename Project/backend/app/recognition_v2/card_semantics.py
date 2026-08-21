"""管理下Visionモデルによる、OpenCV候補の「名刺らしさ」選別。

画像はメモリ上で候補番号を描画し、data URLとして管理下ykrへ送る。原画像、
候補画像、応答のいずれも、この処理からファイルやDBへ保存しない。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import detector
from .ykr_client import ManagedRecognitionClient


SEMANTIC_FILTER_VERSION = "managed-cardness-v1"
ANNOTATION_MAX_EDGE = 1600
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


def _annotated_data_url(
    image: np.ndarray, detections: list[detector.Detection]
) -> str:
    height, width = image.shape[:2]
    scale = min(1.0, ANNOTATION_MAX_EDGE / float(max(height, width)))
    annotated = (
        cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        if scale < 1.0
        else image.copy()
    )
    line_width = max(3, round(max(annotated.shape[:2]) / 420))
    font_scale = max(0.8, max(annotated.shape[:2]) / 1100)
    for candidate_id, detection in enumerate(detections, 1):
        points = np.int32(np.round(detector.ordered_corners(detection.corners) * scale))
        cv2.polylines(annotated, [points], True, (20, 220, 40), line_width, cv2.LINE_AA)
        anchor_x = int(np.clip(points[0][0], 0, annotated.shape[1] - 1))
        anchor_y = int(np.clip(points[0][1], 28, annotated.shape[0] - 1))
        label = str(candidate_id)
        (text_width, text_height), _ = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, line_width
        )
        cv2.rectangle(
            annotated,
            (anchor_x, max(0, anchor_y - text_height - 12)),
            (
                min(annotated.shape[1] - 1, anchor_x + text_width + 12),
                min(annotated.shape[0] - 1, anchor_y + 6),
            ),
            (210, 20, 105),
            -1,
        )
        cv2.putText(
            annotated,
            label,
            (anchor_x + 5, anchor_y - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            line_width,
            cv2.LINE_AA,
        )
    ok, encoded = cv2.imencode(
        ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 88]
    )
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
        image_data_url=_annotated_data_url(image, detections),
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
