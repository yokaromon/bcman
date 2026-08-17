from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from detector import (
    DETECTOR_VERSION,
    detect_cards,
    perspective_crop,
    read_image,
    write_image,
)


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = BASE_DIR / "picture"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"
SUPPORTED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="写真から名刺を検出し、台形補正したPNGを画像別に出力します。"
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--source",
        help="指定した1画像だけを処理します。省略時は入力ディレクトリ直下の全画像です。",
    )
    return parser.parse_args()


def _source_images(input_dir: Path, source_name: str | None = None) -> list[Path]:
    if not input_dir.is_dir():
        raise ValueError(f"入力ディレクトリが見つかりません: {input_dir}")
    if source_name:
        source = input_dir / source_name
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"処理対象の画像が見つかりません: {source}")
        return [source]
    return sorted(
        (
            path
            for path in input_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ),
        key=lambda path: path.name.casefold(),
    )


def _json_corners(corners: np.ndarray) -> list[list[float]]:
    return [[round(float(x), 2), round(float(y), 2)] for x, y in corners]


def _overlay(image: np.ndarray, detections) -> np.ndarray:
    preview = image.copy()
    thickness = max(3, round(max(image.shape[:2]) / 1200))
    font_scale = max(0.8, max(image.shape[:2]) / 2600)
    for index, detection in enumerate(detections, 1):
        points = np.int32(np.round(detection.corners))
        cv2.polylines(
            preview, [points], True, (0, 255, 0), thickness, cv2.LINE_AA
        )
        x, y = points[0]
        cv2.putText(
            preview,
            f"{index:02d}",
            (int(x), max(35, int(y) - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 255),
            max(2, thickness - 1),
            cv2.LINE_AA,
        )
    return preview


def _replace_directory(prepared: Path, target: Path) -> None:
    backup = target.with_name(f".{target.name}.old-{uuid.uuid4().hex}")
    moved_old = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved_old = True
        os.replace(prepared, target)
    except Exception:
        if moved_old and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def process_image(source: Path, output_root: Path) -> dict:
    started = time.perf_counter()
    image = read_image(source)
    detections = detect_cards(image)
    detection_elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    target = output_root / source.stem
    prepared = output_root / f".{source.stem}.tmp-{uuid.uuid4().hex}"
    prepared.mkdir(parents=True, exist_ok=False)

    status = "detected" if detections else "detection_failed"
    result = {
        "schema_version": 1,
        "source": source.name,
        "source_size": {"width": image.shape[1], "height": image.shape[0]},
        "status": status,
        "detector": {"name": "bcman-card-pickup", "version": DETECTOR_VERSION},
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "detection_elapsed_ms": detection_elapsed_ms,
        "elapsed_ms": None,
        "cards": [],
    }
    try:
        for index, detection in enumerate(detections, 1):
            filename = f"card{index:02d}.png"
            write_image(
                prepared / filename,
                perspective_crop(image, detection.corners),
            )
            result["cards"].append(
                {
                    "filename": filename,
                    "corners": _json_corners(detection.corners),
                    "confidence": detection.confidence,
                    "strategy": detection.strategy,
                    "contrast": detection.contrast,
                }
            )
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        write_image(prepared / "overlay.jpg", _overlay(image, detections))
        (prepared / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _replace_directory(prepared, target)
    except Exception:
        shutil.rmtree(prepared, ignore_errors=True)
        raise
    return result


def main() -> int:
    args = _arguments()
    try:
        sources = _source_images(args.input_dir.resolve(), args.source)
        if not sources:
            raise ValueError(f"処理対象の画像がありません: {args.input_dir}")
        output_root = args.output_dir.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        failures = 0
        summary = []
        for source in sources:
            try:
                result = process_image(source, output_root)
                summary.append(result)
                failures += result["status"] != "detected"
                print(
                    f"{source.name}: {len(result['cards'])}枚 "
                    f"({result['elapsed_ms']:.0f} ms, {result['status']})"
                )
            except Exception as exc:
                failures += 1
                print(f"{source.name}: error: {exc}", file=sys.stderr)
        (output_root / "summary.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "detector_version": DETECTOR_VERSION,
                    "image_count": len(sources),
                    "failure_count": failures,
                    "results": [
                        {
                            "source": item["source"],
                            "status": item["status"],
                            "card_count": len(item["cards"]),
                            "elapsed_ms": item["elapsed_ms"],
                        }
                        for item in summary
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return 0 if failures == 0 else 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
