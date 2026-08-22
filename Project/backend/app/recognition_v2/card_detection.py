"""画像を永続化せず、V2検出器の矩形だけを返す処理。

このモジュールはファイルパス、DB、Storageを受け取らない。入力画像はメモリ上で
decodeし、切り抜きも生成せず、元画像座標の四隅だけをJSON化する。
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable

import cv2
import numpy as np

from . import detector
from .card_semantics import SemanticSelection


SEMANTIC_MIN_CONFIDENCE = 0.60
GUIDED_CANDIDATE_LIMIT = 4
GUIDED_MIN_AREA_RATIO = 0.20
GUIDED_CROP_MAX_EDGE = 1800
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


def _guided_seed(image: np.ndarray) -> detector.Detection:
    """中央ガイドへ合わせた1枚を、輪郭が薄い場合にもVisionへ渡す初期候補。"""
    height, width = image.shape[:2]
    return detector.Detection(
        corners=detector.ordered_corners(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]
        ),
        confidence=0.5,
        strategy="guided-roi-seed",
        score=0.5,
        contrast=0.0,
    )


def _guided_candidates(image: np.ndarray) -> list[detector.Detection]:
    """ガイド全体と、その内側で得られた十分大きい局所輪郭だけを候補にする。"""
    height, width = image.shape[:2]
    photo_area = float(width * height)
    seed = _guided_seed(image)
    selected = [seed]
    for item in detector.detect_cards(image):
        corners = detector.ordered_corners(item.corners)
        area_ratio = abs(float(cv2.contourArea(corners))) / photo_area
        center = corners.mean(axis=0)
        centered = (
            abs(float(center[0]) / width - 0.5) <= 0.30
            and abs(float(center[1]) / height - 0.5) <= 0.30
        )
        if area_ratio < GUIDED_MIN_AREA_RATIO or not centered:
            continue
        if any(detector.quadrilateral_iou(corners, other.corners) >= 0.88 for other in selected):
            continue
        selected.append(item)
        if len(selected) >= GUIDED_CANDIDATE_LIMIT:
            break
    return selected


def _crop_quality(image: np.ndarray) -> dict:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return {
        "sharpness": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
        "brightness": round(float(gray.mean()), 2),
        "glare_ratio": round(float(np.mean(gray >= 250)), 4),
    }


def _crop_fingerprint(image: np.ndarray) -> str:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sample = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (sample[:, 1:] >= sample[:, :-1]).reshape(-1)
    value = sum(int(bit) << index for index, bit in enumerate(bits))
    return f"{value:016x}"


def _crop_data_url(image: np.ndarray) -> tuple[str, dict[str, int]]:
    height, width = image.shape[:2]
    scale = min(1.0, GUIDED_CROP_MAX_EDGE / float(max(height, width)))
    encoded_image = (
        cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        if scale < 1.0
        else image
    )
    ok, encoded = cv2.imencode(
        ".jpg", encoded_image, [cv2.IMWRITE_JPEG_QUALITY, 90]
    )
    if not ok:
        raise ValueError("補正済み名刺画像をJPEG化できません")
    return (
        "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii"),
        {"width": int(encoded_image.shape[1]), "height": int(encoded_image.shape[0])},
    )


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


def analyze_guided_card_capture(
    payload: bytes,
    max_pixels: int,
    semantic_filter: SemanticFilter,
) -> dict:
    """中央ガイドから1枚だけを検証・補正し、保存せずクライアントへ返す。"""
    image = _decode_image(payload, max_pixels)
    started = time.perf_counter()
    candidates = _guided_candidates(image)
    semantic_selection = semantic_filter(image, candidates)
    accepted = [
        (candidate_id, detection)
        for candidate_id, detection in enumerate(candidates, 1)
        if (
            semantic_selection.verdicts[candidate_id].decision == "business_card"
            and semantic_selection.verdicts[candidate_id].confidence
            >= SEMANTIC_MIN_CONFIDENCE
        )
    ]
    base = {
        "detector_version": detector.DETECTOR_VERSION,
        "guided_version": "guided-single-card-v1",
        "authoritative": True,
        "persisted": False,
        "source_size": {
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
        },
        "candidate_count": len(candidates),
        "semantic_model": semantic_selection.model,
        "semantic_attempts": semantic_selection.attempts,
    }
    if not accepted:
        return {
            **base,
            "accepted": False,
            "reason": "not_business_card",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "card": None,
        }

    precise = [
        item for item in accepted if item[1].strategy != "guided-roi-seed"
    ]
    candidate_id, selected = max(
        precise or accepted,
        key=lambda item: (
            semantic_selection.verdicts[item[0]].confidence,
            item[1].confidence,
        ),
    )
    refined = _refine_semantic_detection(image, selected)
    crop = detector.perspective_crop(image, refined.corners)
    crop_url, crop_size = _crop_data_url(crop)
    verdict = semantic_selection.verdicts[candidate_id]
    return {
        **base,
        "accepted": True,
        "reason": "accepted",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "card": {
            "corners": _corners_json(refined.corners),
            "confidence": round(float(refined.confidence), 4),
            "semantic_confidence": verdict.confidence,
            "strategy": refined.strategy,
            "quality": _crop_quality(crop),
            "fingerprint": _crop_fingerprint(crop),
            "crop_size": crop_size,
            "crop_data_url": crop_url,
        },
    }
