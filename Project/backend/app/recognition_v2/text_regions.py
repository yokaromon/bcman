from __future__ import annotations

import math
import re
from dataclasses import dataclass

import cv2
import numpy as np


LOCAL_OCR_SCHEMA_VERSION = 1
_DIRECTIONAL_GLYPHS = re.compile(r"[a-fgjkmnA-FGJKMN2345679]")


def _ordered_quad(polygon: np.ndarray) -> np.ndarray:
    points = np.float32(polygon).reshape(-1, 2)
    if len(points) != 4:
        points = cv2.boxPoints(cv2.minAreaRect(points))
    center = points.mean(axis=0)
    clockwise = points[
        np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))
    ]
    top_left = int(np.argmin(clockwise.sum(axis=1)))
    return np.float32(np.roll(clockwise, -top_left, axis=0))


def crop_text_region(image: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    source = _ordered_quad(polygon)
    top, right, bottom, left = source
    width = max(
        1,
        round(max(np.linalg.norm(right - top), np.linalg.norm(bottom - left))),
    )
    height = max(
        1,
        round(max(np.linalg.norm(left - top), np.linalg.norm(bottom - right))),
    )
    destination = np.float32(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]
    )
    matrix = cv2.getPerspectiveTransform(source, destination)
    return cv2.warpPerspective(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _reading_order(regions: list[dict]) -> list[dict]:
    if not regions:
        return []
    median_height = float(
        np.median(
            [
                max(1.0, np.ptp(np.asarray(item["polygon"], dtype=np.float32)[:, 1]))
                for item in regions
            ]
        )
    )
    row_height = max(8.0, median_height * 0.65)
    return sorted(
        regions,
        key=lambda item: (
            round(float(np.mean(np.asarray(item["polygon"])[:, 1])) / row_height),
            float(np.min(np.asarray(item["polygon"])[:, 0])),
        ),
    )


def _json_polygon(polygon: np.ndarray) -> list[list[float]]:
    return [
        [round(float(x), 2), round(float(y), 2)]
        for x, y in np.float32(polygon).reshape(-1, 2)
    ]


@dataclass(frozen=True)
class TextPipelineOptions:
    detection_min_score: float = 0.35
    recognition_min_score: float = 0.0
    readability_max_regions: int = 16


class LocalTextPipeline:
    def __init__(self, models, options: TextPipelineOptions | None = None):
        self.models = models
        self.options = options or TextPipelineOptions()

    def process(self, image: np.ndarray, *, server: bool = True) -> dict:
        detected = []
        for item in self.models.detect(image):
            score = item.get("score")
            if score is not None and float(score) < self.options.detection_min_score:
                continue
            polygon = np.float32(item["polygon"]).reshape(-1, 2)
            if len(polygon) < 4 or abs(cv2.contourArea(polygon)) < 16:
                continue
            detected.append({"polygon": polygon, "detection_score": score})

        ordered = _reading_order(detected)
        crops = [crop_text_region(image, item["polygon"]) for item in ordered]
        recognized = self.models.recognize(crops, server=server)
        if len(recognized) != len(ordered):
            raise ValueError("文字認識器の応答件数が文字領域数と一致しません")

        regions = []
        for index, (item, result) in enumerate(
            zip(ordered, recognized, strict=True), 1
        ):
            score = float(result.get("score", 0.0))
            text = str(result.get("text") or "")
            regions.append(
                {
                    "region_id": f"region-{index:03d}",
                    "polygon": _json_polygon(item["polygon"]),
                    "detection_score": (
                        round(float(item["detection_score"]), 6)
                        if item["detection_score"] is not None
                        else None
                    ),
                    "text": text or None,
                    "recognition_score": round(score, 6),
                    "recognition_status": (
                        "recognized"
                        if text and score >= self.options.recognition_min_score
                        else "unreadable"
                    ),
                }
            )
        return {
            "schema_version": LOCAL_OCR_SCHEMA_VERSION,
            "models": {
                "detection": "PP-OCRv5_server_det",
                "recognition": (
                    "PP-OCRv5_server_rec" if server else "PP-OCRv5_mobile_rec"
                ),
            },
            "regions": regions,
        }

    def readability(self, image: np.ndarray) -> dict:
        document = self.process(image, server=False)
        regions = [
            region
            for region in document["regions"]
            if region["text"] and region["recognition_score"] > 0
        ]
        regions = sorted(
            regions,
            key=lambda region: region["recognition_score"],
            reverse=True,
        )[: self.options.readability_max_regions]
        if not regions:
            return {"score": 0.0, "recognized_regions": 0}

        confidences = [float(region["recognition_score"]) for region in regions]
        texts = [str(region["text"]) for region in regions]
        character_count = sum(len(text.strip()) for text in texts)
        directional_count = sum(len(_DIRECTIONAL_GLYPHS.findall(text)) for text in texts)
        mean_confidence = sum(confidences) / len(confidences)
        region_coverage = min(1.0, math.log2(len(regions) + 1) / 3.5)
        text_coverage = min(1.0, character_count / 48.0)
        directional_hint = min(1.0, directional_count / 8.0)
        score = (
            0.62 * mean_confidence
            + 0.18 * region_coverage
            + 0.15 * text_coverage
            + 0.05 * directional_hint
        )
        return {
            "score": round(score, 6),
            "recognized_regions": len(regions),
            "mean_confidence": round(mean_confidence, 6),
            "character_count": character_count,
            "directional_glyph_count": directional_count,
        }
