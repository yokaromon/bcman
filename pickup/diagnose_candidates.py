from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from bcpickup import DEFAULT_INPUT_DIR
from detector import (
    CARD_AREA_MAX_RATIO,
    CARD_AREA_MIN_RATIO,
    MAX_WORKING_EDGE,
    _candidate_from_contour,
    _cluster_candidates,
    _color_region_candidates,
    _consistent_card_scale,
    _edge_support,
    _line_candidates,
    _masks,
    _refine_card_region,
    _refinement_expansion,
    quadrilateral_iou,
    read_image,
    write_image,
)


BASE_DIR = Path(__file__).resolve().parent


def diagnose(source: Path, target: Path) -> None:
    image = read_image(source)
    height, width = image.shape[:2]
    scale = min(1.0, MAX_WORKING_EDGE / float(max(height, width)))
    working = (
        cv2.resize(
            image,
            (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_AREA,
        )
        if scale < 1.0
        else image
    )
    work_height, work_width = working.shape[:2]
    photo_area = float(work_width * work_height)
    edges, masks = _masks(working)
    lab = cv2.cvtColor(working, cv2.COLOR_BGR2LAB)
    raw = []
    for strategy, mask in masks:
        contours, _ = cv2.findContours(
            mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in contours:
            candidate = _candidate_from_contour(
                contour,
                edges,
                lab,
                photo_area,
                work_width,
                work_height,
                strategy,
            )
            if candidate is not None:
                raw.append(candidate)
    contour_count = len(raw)
    line_candidates = _line_candidates(working, edges, lab)
    color_candidates = _color_region_candidates(working, edges, lab)
    raw.extend(line_candidates)
    raw.extend(color_candidates)
    clustered = _cluster_candidates(raw)
    selected = _consistent_card_scale(clustered)
    selected_ids = {id(candidate) for candidate in selected}
    refinements = [
        refined
        for candidate in selected
        if candidate.strategy in {"line-reconstruction", "color-kmeans"}
        for refined in [
            _refine_card_region(
                working,
                candidate,
                expansion=_refinement_expansion(candidate, photo_area),
            )
        ]
        if refined is not None
    ]
    clustered.extend(refinements)
    overlay = working.copy()
    ground_truth_path = BASE_DIR / "ground_truth.json"
    expected = []
    if ground_truth_path.exists():
        document = json.loads(ground_truth_path.read_text(encoding="utf-8"))
        expected = [
            np.float32(card["corners"]) * scale
            for card in document.get("images", {}).get(source.name, {}).get("cards", [])
        ]
    print(
        f"{source.name}: contours={contour_count} lines={len(line_candidates)} "
        f"colors={len(color_candidates)} "
        f"clustered={len(clustered)} final={len(selected)}"
    )
    print(" id final center_x center_y area_ratio score contrast edge best_iou strategy")
    for index, candidate in enumerate(clustered, 1):
        center = candidate.corners.mean(axis=0)
        is_final = id(candidate) in selected_ids
        color = (0, 255, 0) if is_final else (0, 80, 255)
        points = np.int32(np.round(candidate.corners))
        cv2.polylines(overlay, [points], True, color, 3, cv2.LINE_AA)
        cv2.putText(
            overlay,
            str(index),
            tuple(points[0]),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2,
            cv2.LINE_AA,
        )
        print(
            f"{index:3d} {str(is_final):5s} {center[0] / scale:8.0f} "
            f"{center[1] / scale:8.0f} {candidate.area / photo_area:10.4f} "
            f"{candidate.score:5.3f} {candidate.contrast:8.3f} "
            f"{_edge_support(edges, candidate.corners):5.3f} "
            f"{max((quadrilateral_iou(candidate.corners, card) for card in expected), default=0):8.3f} "
            f"{candidate.strategy}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    write_image(target, overlay)
    print(f"overlay={target}")


def main() -> int:
    parser = argparse.ArgumentParser(description="検出候補の選別過程を可視化")
    parser.add_argument("sources", nargs="+")
    parser.add_argument(
        "--input-dir", type=Path, default=DEFAULT_INPUT_DIR
    )
    parser.add_argument(
        "--output-dir", type=Path, default=BASE_DIR / "diagnostics"
    )
    args = parser.parse_args()
    for name in args.sources:
        source = args.input_dir.resolve() / name
        if not source.is_file():
            parser.error(f"画像がありません: {source}")
        diagnose(source, args.output_dir.resolve() / f"{source.stem}-candidates.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
