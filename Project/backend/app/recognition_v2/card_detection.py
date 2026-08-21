"""画像を永続化せず、V2検出器の矩形だけを返す処理。

このモジュールはファイルパス、DB、Storageを受け取らない。入力画像はメモリ上で
decodeし、切り抜きも生成せず、元画像座標の四隅だけをJSON化する。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import cv2
import numpy as np

from . import detector
from .card_semantics import SemanticSelection


SEMANTIC_MIN_CONFIDENCE = 0.60
SemanticFilter = Callable[
    [np.ndarray, list[detector.Detection]], SemanticSelection
]


class InvalidDetectionImage(ValueError):
    """JPEG/PNGとしてdecodeできない入力。"""


class DetectionImageTooLarge(ValueError):
    """展開後の画素数が安全上限を超える入力。"""


def detect_cards_with_fallback(image: np.ndarray) -> list[detector.Detection]:
    """通常のV2検出を行い、0件なら既存パイプライン同様に全画面を1枚とする。"""
    detections = detector.detect_cards(image)
    if detections:
        return detections

    height, width = image.shape[:2]
    return [
        detector.Detection(
            corners=detector.ordered_corners(
                [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]
            ),
            confidence=0.2,
            strategy="full_frame_fallback",
            score=0.0,
            contrast=0.0,
        )
    ]


def _decode_image(payload: bytes, max_pixels: int) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidDetectionImage("JPEG または PNG 画像を読み込めません")
    height, width = image.shape[:2]
    if width * height > max_pixels:
        raise DetectionImageTooLarge(
            f"画像の解像度が上限（{max_pixels:,}画素）を超えています"
        )
    return image


def _corners_json(corners: np.ndarray) -> list[list[float]]:
    return [[round(float(x), 2), round(float(y), 2)] for x, y in corners]


def _refine_semantic_detection(
    image: np.ndarray, detection: detector.Detection
) -> detector.Detection:
    """意味判定を通った候補だけ、原寸画像の局所領域で四隅を再調整する。"""
    corners = detector.ordered_corners(detection.corners)
    candidate = detector._Candidate(
        corners=corners,
        score=float(detection.score),
        strategy=detection.strategy,
        area=abs(float(cv2.contourArea(corners))),
        contrast=float(detection.contrast),
    )
    refined = detector._refine_card_region(
        image, candidate, expansion=1.30, inner_scale=0.56
    )
    selected = detector._prefer_region_refinement(candidate, refined)
    return detector.Detection(
        corners=detector.ordered_corners(selected.corners),
        confidence=detection.confidence,
        strategy=selected.strategy,
        score=detection.score,
        contrast=detection.contrast,
    )


def analyze_card_rectangles(
    payload: bytes,
    max_pixels: int,
    semantic_filter: SemanticFilter | None = None,
) -> dict:
    """encoded画像を解析し、永続化に使えるデータを含まない矩形documentを返す。"""
    image = _decode_image(payload, max_pixels)
    started = time.perf_counter()
    raw_detections = (
        detector.detect_cards(image)
        if semantic_filter is not None
        else detect_cards_with_fallback(image)
    )
    candidate_count = len(raw_detections)
    semantic_selection: SemanticSelection | None = None
    selected: list[tuple[int, detector.Detection]] = list(
        enumerate(raw_detections, 1)
    )
    if semantic_filter is not None and raw_detections:
        semantic_selection = semantic_filter(image, raw_detections)
        selected = [
            (candidate_id, _refine_semantic_detection(image, detection))
            for candidate_id, detection in selected
            if (
                semantic_selection.verdicts[candidate_id].decision
                == "business_card"
                and semantic_selection.verdicts[candidate_id].confidence
                >= SEMANTIC_MIN_CONFIDENCE
            )
        ]
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    cards = []
    for index, (candidate_id, item) in enumerate(selected, 1):
        card = {
            "index": index,
            "candidate_index": candidate_id,
            "corners": _corners_json(item.corners),
            "confidence": round(float(item.confidence), 4),
            "strategy": item.strategy,
            "score": round(float(item.score), 4),
            "contrast": round(float(item.contrast), 4),
        }
        if semantic_selection is not None:
            verdict = semantic_selection.verdicts[candidate_id]
            card["semantic_confidence"] = verdict.confidence
            card["semantic_reason"] = verdict.reason
        cards.append(card)
    semantic_status = (
        "not_requested"
        if semantic_filter is None
        else "completed" if raw_detections else "no_geometric_candidates"
    )
    return {
        "detector_version": detector.DETECTOR_VERSION,
        "authoritative": True,
        "persisted": False,
        "source_size": {
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
        },
        "candidate_count": candidate_count,
        "card_count": len(cards),
        "elapsed_ms": elapsed_ms,
        "semantic_status": semantic_status,
        "semantic_version": (
            semantic_selection.version if semantic_selection is not None else None
        ),
        "semantic_model": (
            semantic_selection.model if semantic_selection is not None else None
        ),
        "semantic_attempts": (
            semantic_selection.attempts if semantic_selection is not None else 0
        ),
        "cards": cards,
    }
