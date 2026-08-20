from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import time
from typing import Callable

import cv2
import numpy as np


RIGHT_ANGLES = (0, 90, 180, 270)
ORIENTATION_SCHEMA_VERSION = 1


def rotate_clockwise(image: np.ndarray, degrees: int) -> np.ndarray:
    """画像を時計回りに0/90/180/270度回転する。"""
    normalized = degrees % 360
    if normalized == 0:
        return image.copy()
    if normalized == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if normalized == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if normalized == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError(f"直角以外の回転は扱えません: {degrees}")


@dataclass(frozen=True)
class OrientationThresholds:
    classifier_min_score: float = 0.80
    classifier_mean_score: float = 0.88
    ocr_min_score: float = 0.42
    ocr_min_margin: float = 0.08


ReadabilityScorer = Callable[[np.ndarray], dict]


class OrientationEngine:
    """4方向の自己整合性とOCR可読性から、棄権可能な向き判定を行う。"""

    def __init__(self, models, thresholds: OrientationThresholds | None = None):
        self.models = models
        self.thresholds = thresholds or OrientationThresholds()

    def analyze(
        self,
        image: np.ndarray,
        *,
        readability_scorer: ReadabilityScorer | None = None,
    ) -> tuple[np.ndarray, dict]:
        started = time.perf_counter()
        rotated = [rotate_clockwise(image, angle) for angle in RIGHT_ANGLES]
        predictions = self.models.classify(rotated)
        if len(predictions) != len(RIGHT_ANGLES):
            raise ValueError("向き分類器の応答件数が入力件数と一致しません")

        evidence = []
        inferred_angles = []
        scores = []
        for applied, prediction in zip(RIGHT_ANGLES, predictions, strict=True):
            label = int(prediction["label"]) % 360
            if label not in RIGHT_ANGLES:
                raise ValueError(f"向き分類器が直角以外を返しました: {label}")
            score = float(prediction["score"])
            original_angle = (label - applied) % 360
            inferred_angles.append(original_angle)
            scores.append(score)
            evidence.append(
                {
                    "input_rotation": applied,
                    "predicted_label": label,
                    "score": round(score, 6),
                    "inferred_original_angle": original_angle,
                }
            )

        votes = Counter(inferred_angles)
        consensus_angle, consensus_count = votes.most_common(1)[0]
        mean_score = sum(scores) / len(scores)
        classifier_confirmed = (
            consensus_count == len(RIGHT_ANGLES)
            and min(scores) >= self.thresholds.classifier_min_score
            and mean_score >= self.thresholds.classifier_mean_score
        )

        rotation_applied = (-consensus_angle) % 360 if classifier_confirmed else 0
        status = "auto_confirmed" if classifier_confirmed else "uncertain"
        method = "classifier_self_consistency" if classifier_confirmed else "none"
        ocr_evidence: list[dict] = []

        if not classifier_confirmed and readability_scorer is not None:
            for correction in RIGHT_ANGLES:
                value = readability_scorer(rotate_clockwise(image, correction))
                ocr_evidence.append(
                    {
                        "correction": correction,
                        "score": round(float(value.get("score", 0.0)), 6),
                        "recognized_regions": int(
                            value.get("recognized_regions", 0)
                        ),
                    }
                )
            ranked = sorted(
                ocr_evidence,
                key=lambda item: (item["score"], item["recognized_regions"]),
                reverse=True,
            )
            best = ranked[0]
            second = ranked[1]
            if (
                best["score"] >= self.thresholds.ocr_min_score
                and best["score"] - second["score"]
                >= self.thresholds.ocr_min_margin
            ):
                rotation_applied = int(best["correction"])
                status = "auto_confirmed"
                method = "ocr_readability"

        oriented = rotate_clockwise(image, rotation_applied)
        document = {
            "schema_version": ORIENTATION_SCHEMA_VERSION,
            "status": status,
            "rotation_applied": rotation_applied,
            "method": method,
            "classifier": {
                "model": "PP-LCNet_x1_0_doc_ori",
                "consensus_original_angle": (
                    consensus_angle if consensus_count == len(RIGHT_ANGLES) else None
                ),
                "consensus_count": consensus_count,
                "mean_score": round(mean_score, 6),
                "predictions": evidence,
            },
            "ocr_readability": ocr_evidence,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        return oriented, document
