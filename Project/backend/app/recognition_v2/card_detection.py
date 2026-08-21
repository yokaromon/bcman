"""画像を永続化せず、V2検出器の矩形だけを返す処理。

このモジュールはファイルパス、DB、Storageを受け取らない。入力画像はメモリ上で
decodeし、切り抜きも生成せず、元画像座標の四隅だけをJSON化する。
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from . import detector


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


def analyze_card_rectangles(payload: bytes, max_pixels: int) -> dict:
    """encoded画像を解析し、永続化に使えるデータを含まない矩形documentを返す。"""
    image = _decode_image(payload, max_pixels)
    started = time.perf_counter()
    detections = detect_cards_with_fallback(image)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    cards = [
        {
            "index": index,
            "corners": _corners_json(item.corners),
            "confidence": round(float(item.confidence), 4),
            "strategy": item.strategy,
            "score": round(float(item.score), 4),
            "contrast": round(float(item.contrast), 4),
        }
        for index, item in enumerate(detections, 1)
    ]
    return {
        "detector_version": detector.DETECTOR_VERSION,
        "authoritative": True,
        "persisted": False,
        "source_size": {
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
        },
        "card_count": len(cards),
        "elapsed_ms": elapsed_ms,
        "cards": cards,
    }
