from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from evaluate import _load_ground_truth
from evaluate_recognition import _artifact_map, _load_json


BASE_DIR = Path(__file__).resolve().parent


def evaluate_orientation(
    extraction_gt_path: Path,
    orientation_gt_path: Path,
    output_dir: Path,
    *,
    minimum_cards: int = 300,
    required_dataset_role: str = "holdout",
) -> tuple[int, dict]:
    extraction = _load_ground_truth(extraction_gt_path)
    orientation = _load_json(orientation_gt_path)
    mapped, mapping_problems = _artifact_map(extraction, output_dir)
    annotated = orientation.get("cards", {})
    report = {
        "schema_version": 1,
        "minimum_cards": minimum_cards,
        "required_dataset_role": required_dataset_role,
        "annotated_cards": len(annotated),
        "evaluated_known_cards": 0,
        "indeterminate_cards": 0,
        "auto_confirmed": 0,
        "auto_correct": 0,
        "auto_wrong": 0,
        "uncertain": 0,
        "problems": mapping_problems,
        "wrong_cards": [],
    }
    roles = {
        "extraction": extraction.get("dataset_role"),
        "orientation": orientation.get("dataset_role"),
    }
    report["dataset_roles"] = roles
    for stage, role in roles.items():
        if role != required_dataset_role:
            report["problems"].append(
                f"{stage} GTはdataset_role={role}です。{required_dataset_role}が必要です"
            )
    if len(annotated) < minimum_cards:
        report["problems"].append(
            f"向きGTが{len(annotated)}枚です。最低{minimum_cards}枚必要です"
        )
    elapsed = []
    for card_id, expected in annotated.items():
        location = mapped.get(card_id)
        if location is None:
            report["problems"].append(f"{card_id}: IoU>=0.90の抽出結果なし")
            continue
        correction = expected.get("correction_rotation")
        if correction == "unknown":
            report["indeterminate_cards"] += 1
            continue
        artifact_path = location["directory"] / f"{location['prefix']}.orientation.json"
        try:
            actual = _load_json(artifact_path)
        except (OSError, json.JSONDecodeError, ValueError):
            report["problems"].append(f"{card_id}: orientation artifact不正")
            continue
        report["evaluated_known_cards"] += 1
        if actual.get("elapsed_ms") is not None:
            elapsed.append(float(actual["elapsed_ms"]))
        if actual.get("status") == "auto_confirmed":
            report["auto_confirmed"] += 1
            if actual.get("rotation_applied") == correction:
                report["auto_correct"] += 1
            else:
                report["auto_wrong"] += 1
                report["wrong_cards"].append(
                    {
                        "ground_truth_card_id": card_id,
                        "source": location["source"],
                        "expected": correction,
                        "actual": actual.get("rotation_applied"),
                    }
                )
        else:
            report["uncertain"] += 1
    report["auto_accuracy"] = round(
        report["auto_correct"] / max(1, report["auto_confirmed"]), 6
    )
    report["uncertainty_rate"] = round(
        report["uncertain"] / max(1, report["evaluated_known_cards"]), 6
    )
    report["p95_elapsed_ms"] = (
        round(float(np.percentile(elapsed, 95)), 2) if elapsed else None
    )
    checks = {
        "minimum_cards": len(annotated) >= minimum_cards,
        "auto_accuracy": report["auto_accuracy"] >= 0.99,
        "uncertainty_rate": report["uncertainty_rate"] <= 0.15,
        "p95_elapsed_ms": report["p95_elapsed_ms"] is not None
        and report["p95_elapsed_ms"] <= 6000,
    }
    report["acceptance_checks"] = checks
    report["passed"] = not report["problems"] and all(checks.values())
    return (0 if report["passed"] else 2), report


def main() -> int:
    parser = argparse.ArgumentParser(description="向きだけを人手GTで単独評価")
    parser.add_argument("--extraction-ground-truth", type=Path, default=BASE_DIR / "ground_truth.json")
    parser.add_argument("--orientation-ground-truth", type=Path, default=BASE_DIR / "orientation_ground_truth.json")
    parser.add_argument("--output-dir", type=Path, default=BASE_DIR / "output")
    parser.add_argument("--minimum-cards", type=int, default=300)
    parser.add_argument("--dataset-role", choices=("development", "holdout"), default="holdout")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        code, report = evaluate_orientation(
            args.extraction_ground_truth.resolve(),
            args.orientation_ground_truth.resolve(),
            args.output_dir.resolve(),
            minimum_cards=args.minimum_cards,
            required_dataset_role=args.dataset_role,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
