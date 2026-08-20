import json

from evaluate_recognition import (
    _strict_text,
    character_error_rate,
    edit_distance,
    evaluate_recognition,
)
from recognition_contract import CONTACT_FIELDS


def test_edit_distance_handles_insert_delete_replace():
    assert edit_distance("abc", "adc") == 1
    assert edit_distance("abc", "ab") == 1
    assert edit_distance("ab", "abc") == 1


def test_cer_normalizes_width_case_and_whitespace():
    assert character_error_rate("ＡＢ C", "ab c") == 0.0
    assert character_error_rate("青柳", "青木") == 0.5
    assert _strict_text("ＡＢ C") != _strict_text("ab c")


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_end_to_end_acceptance_and_holdout_count(tmp_path):
    card_id = "card-fixture"
    corners = [[10, 10], [190, 10], [190, 110], [10, 110]]
    extraction = {
        "schema_version": 2,
        "annotation_method": "manual-four-corner",
        "dataset_role": "holdout",
        "images": {
            "sample.png": {
                "cards": [
                    {"ground_truth_card_id": card_id, "corners": corners}
                ]
            }
        },
    }
    orientation = {
        "schema_version": 1,
        "dataset_role": "holdout",
        "cards": {card_id: {"correction_rotation": 0}},
    }
    expected_contact = {
        name: {"state": "absent", "value": None} for name in CONTACT_FIELDS
    }
    expected_contact["company_name"] = {
        "state": "present",
        "value": "株式会社青柳",
    }
    ocr_ground_truth = {
        "schema_version": 1,
        "dataset_role": "holdout",
        "cards": {
            card_id: {
                "lines": [{"text": "株式会社青柳"}],
                "contact": expected_contact,
            }
        },
    }
    extraction_path = tmp_path / "extraction.json"
    orientation_path = tmp_path / "orientation.json"
    ocr_path = tmp_path / "ocr.json"
    output = tmp_path / "output"
    directory = output / "sample"
    _write(extraction_path, extraction)
    _write(orientation_path, orientation)
    _write(ocr_path, ocr_ground_truth)
    _write(
        directory / "result.json",
        {
            "cards": [
                {
                    "filename": "card01.png",
                    "corners": corners,
                    "pipeline": {"elapsed_ms": 1000},
                }
            ]
        },
    )
    _write(
        directory / "card01.orientation.json",
        {"status": "auto_confirmed", "rotation_applied": 0},
    )
    _write(
        directory / "card01.ocr.ykr.json",
        {"lines": [{"line_id": "line-001", "text": "株式会社青柳"}]},
    )
    actual_fields = {
        name: {
            "state": "absent",
            "display_value": None,
            "normalized_value": None,
            "evidence_status": "not_applicable",
            "review_flags": [],
        }
        for name in CONTACT_FIELDS
    }
    actual_fields["company_name"] = {
        "state": "present",
        "display_value": "株式会社青柳",
        "normalized_value": "株式会社青柳",
        "evidence_status": "supported",
        "review_flags": [],
    }
    _write(directory / "card01.contact.ykr.json", {"fields": actual_fields})

    code, report = evaluate_recognition(
        extraction_path,
        orientation_path,
        ocr_path,
        output,
        minimum_cards=1,
    )
    assert code == 0
    assert report["acceptance"]["passed"] is True
    assert report["ocr"]["strict_cer"] == 0
    assert report["pipeline"]["p95_elapsed_ms"] == 1000

    code, report = evaluate_recognition(
        extraction_path,
        orientation_path,
        ocr_path,
        output,
        minimum_cards=2,
    )
    assert code == 2
    assert report["acceptance"]["passed"] is False

    orientation["dataset_role"] = "development"
    _write(orientation_path, orientation)
    code, report = evaluate_recognition(
        extraction_path,
        orientation_path,
        ocr_path,
        output,
        minimum_cards=1,
    )
    assert code == 2
    assert any("orientation GTはdataset_role=development" in item for item in report["problems"])
