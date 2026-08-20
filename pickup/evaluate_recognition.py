from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

import numpy as np

from detector import quadrilateral_iou
from evaluate import _best_matching, _load_ground_truth
from recognition_contract import _normalized_value


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MINIMUM_CARDS = 300
HIGH_ACCURACY_FIELDS = {
    "person_name", "company_name", "telephone", "mobile", "fax", "email",
    "website", "postal_code",
}
STANDARD_ACCURACY_FIELDS = {
    "address", "department", "position", "person_name_kana", "company_name_kana",
}


def _load_json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"JSON rootがobjectではありません: {path}")
    return document


def _normalized_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(character for character in normalized if not character.isspace())


def _strict_text(value: str | None) -> str:
    return (value or "").replace("\r\n", "\n").replace("\r", "\n")


def edit_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b))
            )
        previous = current
    return previous[-1]


def character_error_rate(expected: str, actual: str) -> float:
    expected = _normalized_text(expected)
    actual = _normalized_text(actual)
    return edit_distance(expected, actual) / max(1, len(expected))


def _artifact_map(extraction_gt: dict, output_dir: Path) -> tuple[dict, list[str]]:
    mapped = {}
    problems = []
    for source_name, annotation in extraction_gt["images"].items():
        result_path = output_dir / Path(source_name).stem / "result.json"
        if not result_path.is_file():
            problems.append(f"{source_name}: result.jsonなし")
            continue
        result = _load_json(result_path)
        detected = result.get("cards", [])
        expected = annotation.get("cards", [])
        ious = [
            [
                quadrilateral_iou(
                    np.float32(card["corners"]), np.float32(found["corners"])
                )
                for found in detected
            ]
            for card in expected
        ]
        pairs = _best_matching(ious)
        paired_expected = set()
        for expected_index, detected_index, iou in pairs:
            if iou < 0.90:
                continue
            paired_expected.add(expected_index)
            expected_card = expected[expected_index]
            card_id = expected_card.get("ground_truth_card_id")
            if not card_id:
                problems.append(f"{source_name} card {expected_index + 1}: 安定IDなし")
                continue
            prefix = Path(detected[detected_index]["filename"]).stem
            mapped[card_id] = {
                "source": source_name,
                "prefix": prefix,
                "directory": result_path.parent,
                "iou": iou,
                "pipeline_elapsed_ms": detected[detected_index].get("pipeline", {}).get(
                    "elapsed_ms"
                ),
            }
        for index, card in enumerate(expected):
            if index not in paired_expected:
                problems.append(
                    f"{source_name} {card.get('ground_truth_card_id', index + 1)}: IoU>=0.90対応なし"
                )
    return mapped, problems


def _predicted_text(artifact: dict, engine: str) -> str:
    if engine == "ykr":
        values = [line.get("text") or "" for line in artifact.get("lines", [])]
    else:
        values = [region.get("text") or "" for region in artifact.get("regions", [])]
    return "\n".join(values)


def evaluate_recognition(
    extraction_gt_path: Path,
    orientation_gt_path: Path,
    ocr_gt_path: Path,
    output_dir: Path,
    *,
    engine: str = "ykr",
    minimum_cards: int = DEFAULT_MINIMUM_CARDS,
    required_dataset_role: str = "holdout",
) -> tuple[int, dict]:
    extraction = _load_ground_truth(extraction_gt_path)
    orientation = _load_json(orientation_gt_path)
    ocr = _load_json(ocr_gt_path)
    mapped, problems = _artifact_map(extraction, output_dir)
    annotated_ids = set(orientation.get("cards", {})) & set(ocr.get("cards", {}))
    report = {
        "schema_version": 1,
        "engine": engine,
        "minimum_cards": minimum_cards,
        "required_dataset_role": required_dataset_role,
        "annotated_unique_cards": len(annotated_ids),
        "mapped_cards": 0,
        "orientation": {
            "known": 0,
            "auto_confirmed": 0,
            "auto_correct": 0,
            "auto_wrong": 0,
            "uncertain": 0,
        },
        "ocr": {
            "cards": 0,
            "strict_character_errors": 0,
            "strict_expected_characters": 0,
            "normalized_character_errors": 0,
            "normalized_expected_characters": 0,
        },
        "contact": {
            "states": 0,
            "state_correct": 0,
            "present_values": 0,
            "value_correct": 0,
            "absent_fields": 0,
            "hallucinated_absent": 0,
            "unreadable_fields": 0,
            "unreadable_review_flagged": 0,
            "unsupported_candidates": 0,
            "per_field": {},
            "notes_character_errors": 0,
            "notes_expected_characters": 0,
        },
        "pipeline": {"measured_cards": 0, "p95_elapsed_ms": None},
        "acceptance": {"passed": False, "checks": []},
        "problems": problems,
    }
    if len(annotated_ids) < minimum_cards:
        report["problems"].append(
            f"固定holdoutが{len(annotated_ids)}枚です。最低{minimum_cards}枚必要です"
        )
    roles = {
        "extraction": extraction.get("dataset_role"),
        "orientation": orientation.get("dataset_role"),
        "ocr": ocr.get("dataset_role"),
    }
    report["dataset_roles"] = roles
    for stage, role in roles.items():
        if role != required_dataset_role:
            report["problems"].append(
                f"{stage} GTはdataset_role={role}です。{required_dataset_role}が必要です"
            )
    for card_id in sorted(annotated_ids):
        location = mapped.get(card_id)
        if location is None:
            continue
        report["mapped_cards"] += 1
        if location.get("pipeline_elapsed_ms") is not None:
            report["pipeline"].setdefault("elapsed_values", []).append(
                float(location["pipeline_elapsed_ms"])
            )
        prefix = location["prefix"]
        directory = location["directory"]
        try:
            orientation_result = _load_json(directory / f"{prefix}.orientation.json")
            ocr_result = _load_json(directory / f"{prefix}.ocr.{engine}.json")
            contact_result = _load_json(directory / f"{prefix}.contact.{engine}.json")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            report["problems"].append(f"{card_id}: artifact不正 ({type(exc).__name__})")
            continue

        expected_rotation = orientation["cards"][card_id]["correction_rotation"]
        if expected_rotation != "unknown":
            metric = report["orientation"]
            metric["known"] += 1
            if orientation_result.get("status") == "auto_confirmed":
                metric["auto_confirmed"] += 1
                if orientation_result.get("rotation_applied") == expected_rotation:
                    metric["auto_correct"] += 1
                else:
                    metric["auto_wrong"] += 1
            else:
                metric["uncertain"] += 1

        expected_ocr = ocr["cards"][card_id]
        expected_text = "\n".join(
            line.get("text") or "" for line in expected_ocr.get("lines", [])
        )
        actual_text = _predicted_text(ocr_result, engine)
        strict_expected = _strict_text(expected_text)
        strict_actual = _strict_text(actual_text)
        normalized_expected = _normalized_text(expected_text)
        normalized_actual = _normalized_text(actual_text)
        report["ocr"]["cards"] += 1
        report["ocr"]["strict_character_errors"] += edit_distance(
            strict_expected, strict_actual
        )
        report["ocr"]["strict_expected_characters"] += len(strict_expected)
        report["ocr"]["normalized_character_errors"] += edit_distance(
            normalized_expected, normalized_actual
        )
        report["ocr"]["normalized_expected_characters"] += len(normalized_expected)

        actual_fields = contact_result.get("fields", {})
        for name, expected_field in expected_ocr.get("contact", {}).items():
            actual_field = actual_fields.get(name, {})
            report["contact"]["states"] += 1
            if actual_field.get("state") == expected_field.get("state"):
                report["contact"]["state_correct"] += 1
            if actual_field.get("evidence_status") == "unsupported":
                report["contact"]["unsupported_candidates"] += 1
            if expected_field.get("state") == "present":
                report["contact"]["present_values"] += 1
                actual_value = actual_field.get("normalized_value")
                if actual_value is None:
                    actual_value = _normalized_value(name, actual_field.get("display_value"))
                expected_value = _normalized_value(name, expected_field.get("value"))
                value_correct = _normalized_text(actual_value) == _normalized_text(
                    expected_value
                )
                per_field = report["contact"]["per_field"].setdefault(
                    name, {"present": 0, "value_correct": 0}
                )
                per_field["present"] += 1
                if value_correct:
                    report["contact"]["value_correct"] += 1
                    per_field["value_correct"] += 1
                if name == "notes":
                    expected_notes = _normalized_text(expected_field.get("value"))
                    actual_notes = _normalized_text(actual_value)
                    report["contact"]["notes_character_errors"] += edit_distance(
                        expected_notes, actual_notes
                    )
                    report["contact"]["notes_expected_characters"] += len(
                        expected_notes
                    )
            elif expected_field.get("state") == "absent":
                report["contact"]["absent_fields"] += 1
                if actual_field.get("state") == "present" or actual_field.get(
                    "display_value"
                ):
                    report["contact"]["hallucinated_absent"] += 1
            elif expected_field.get("state") == "unreadable":
                report["contact"]["unreadable_fields"] += 1
                if "unreadable" in actual_field.get("review_flags", []):
                    report["contact"]["unreadable_review_flagged"] += 1

    ocr_metric = report["ocr"]
    ocr_metric["strict_cer"] = round(
        ocr_metric["strict_character_errors"]
        / max(1, ocr_metric["strict_expected_characters"]),
        6,
    )
    ocr_metric["normalized_cer"] = round(
        ocr_metric["normalized_character_errors"]
        / max(1, ocr_metric["normalized_expected_characters"]),
        6,
    )
    orientation_metric = report["orientation"]
    orientation_metric["auto_accuracy"] = round(
        orientation_metric["auto_correct"] / max(1, orientation_metric["auto_confirmed"]), 6
    )
    contact_metric = report["contact"]
    contact_metric["state_accuracy"] = round(
        contact_metric["state_correct"] / max(1, contact_metric["states"]), 6
    )
    contact_metric["present_value_accuracy"] = round(
        contact_metric["value_correct"] / max(1, contact_metric["present_values"]), 6
    )
    for metric in contact_metric["per_field"].values():
        metric["accuracy"] = round(
            metric["value_correct"] / max(1, metric["present"]), 6
        )
    contact_metric["notes_cer"] = round(
        contact_metric["notes_character_errors"]
        / max(1, contact_metric["notes_expected_characters"]),
        6,
    )
    elapsed = report["pipeline"].pop("elapsed_values", [])
    report["pipeline"]["measured_cards"] = len(elapsed)
    if elapsed:
        report["pipeline"]["p95_elapsed_ms"] = round(
            float(np.percentile(elapsed, 95)), 2
        )

    checks = report["acceptance"]["checks"]

    def check(name: str, passed: bool, actual: object, target: str) -> None:
        checks.append(
            {"name": name, "passed": bool(passed), "actual": actual, "target": target}
        )

    check(
        "holdout_unique_cards",
        len(annotated_ids) >= minimum_cards,
        len(annotated_ids),
        f">={minimum_cards}",
    )
    check(
        "all_annotated_cards_mapped",
        report["mapped_cards"] == len(annotated_ids),
        report["mapped_cards"],
        str(len(annotated_ids)),
    )
    if orientation_metric["known"]:
        uncertainty_rate = orientation_metric["uncertain"] / orientation_metric["known"]
        orientation_metric["uncertainty_rate"] = round(uncertainty_rate, 6)
        check(
            "orientation_auto_accuracy",
            orientation_metric["auto_accuracy"] >= 0.99,
            orientation_metric["auto_accuracy"],
            ">=0.99",
        )
        check(
            "orientation_uncertainty_rate",
            uncertainty_rate <= 0.15,
            round(uncertainty_rate, 6),
            "<=0.15",
        )
    check(
        "ocr_normalized_cer",
        ocr_metric["normalized_cer"] <= 0.02,
        ocr_metric["normalized_cer"],
        "<=0.02",
    )
    for name, target in [
        *((name, 0.99) for name in sorted(HIGH_ACCURACY_FIELDS)),
        *((name, 0.95) for name in sorted(STANDARD_ACCURACY_FIELDS)),
    ]:
        metric = contact_metric["per_field"].get(name)
        if metric and metric["present"]:
            check(
                f"contact_{name}",
                metric["accuracy"] >= target,
                metric["accuracy"],
                f">={target}",
            )
    if contact_metric["notes_expected_characters"]:
        check(
            "contact_notes_cer",
            contact_metric["notes_cer"] <= 0.05,
            contact_metric["notes_cer"],
            "<=0.05",
        )
    check(
        "absent_hallucinations",
        contact_metric["hallucinated_absent"] == 0,
        contact_metric["hallucinated_absent"],
        "0",
    )
    if contact_metric["unreadable_fields"]:
        check(
            "unreadable_review_routing",
            contact_metric["unreadable_review_flagged"]
            == contact_metric["unreadable_fields"],
            contact_metric["unreadable_review_flagged"],
            str(contact_metric["unreadable_fields"]),
        )
    if report["pipeline"]["p95_elapsed_ms"] is not None:
        check(
            "pipeline_p95_elapsed_ms",
            report["pipeline"]["p95_elapsed_ms"] <= 30_000,
            report["pipeline"]["p95_elapsed_ms"],
            "<=30000",
        )
    report["acceptance"]["passed"] = not report["problems"] and all(
        item["passed"] for item in checks
    )
    return (0 if report["acceptance"]["passed"] else 2), report


def main() -> int:
    parser = argparse.ArgumentParser(description="向き・OCR・連絡先を固定人手GTで評価")
    parser.add_argument("--extraction-ground-truth", type=Path, default=BASE_DIR / "ground_truth.json")
    parser.add_argument("--orientation-ground-truth", type=Path, default=BASE_DIR / "orientation_ground_truth.json")
    parser.add_argument("--ocr-ground-truth", type=Path, default=BASE_DIR / "ocr_ground_truth.json")
    parser.add_argument("--output-dir", type=Path, default=BASE_DIR / "output")
    parser.add_argument("--engine", choices=("paddle", "ykr"), default="ykr")
    parser.add_argument("--minimum-cards", type=int, default=DEFAULT_MINIMUM_CARDS)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--dataset-role",
        choices=("development", "holdout"),
        default="holdout",
    )
    args = parser.parse_args()
    try:
        code, report = evaluate_recognition(
            args.extraction_ground_truth.resolve(),
            args.orientation_ground_truth.resolve(),
            args.ocr_ground_truth.resolve(),
            args.output_dir.resolve(),
            engine=args.engine,
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
