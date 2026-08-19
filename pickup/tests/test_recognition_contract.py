import copy

import pytest

from recognition_contract import (
    CONTACT_FIELDS,
    RecognitionContractError,
    enrich_contact,
    parse_json_object,
    validate_contact_response,
    validate_ocr_response,
)


def _ocr():
    return validate_ocr_response(
        {
            "schema_version": 1,
            "lines": [
                {"text": "info@example.jp", "source": "printed", "legibility": "readable"},
                {"text": "TEL 03-1234-5678", "source": "printed", "legibility": "readable"},
            ],
        }
    )


def _contact():
    fields = {
        name: {
            "state": "absent",
            "display_value": None,
            "candidate_value": None,
            "source_line_ids": [],
        }
        for name in CONTACT_FIELDS
    }
    fields["email"] = {
        "state": "present",
        "display_value": "info@example.jp",
        "candidate_value": None,
        "source_line_ids": ["line-001"],
    }
    return {"schema_version": 1, "fields": fields}


def test_ocr_adapter_owns_stable_line_ids():
    result = _ocr()
    assert [line["line_id"] for line in result["lines"]] == [
        "line-001", "line-002"
    ]


def test_markdown_fence_is_not_accepted_as_strict_json():
    with pytest.raises(RecognitionContractError, match="JSON object"):
        parse_json_object("```json\n{}\n```")


def test_email_can_be_absent():
    value = _contact()
    value["fields"]["email"] = {
        "state": "absent", "display_value": None,
        "candidate_value": None, "source_line_ids": [],
    }
    assert validate_contact_response(value, _ocr())["fields"]["email"]["state"] == "absent"


def test_contact_rejects_unknown_evidence_line():
    value = _contact()
    value["fields"]["email"]["source_line_ids"] = ["line-999"]
    with pytest.raises(RecognitionContractError, match="存在しない"):
        validate_contact_response(value, _ocr())


def test_absent_field_cannot_carry_a_value():
    value = _contact()
    value["fields"]["fax"]["display_value"] = "03-0000-0000"
    with pytest.raises(RecognitionContractError, match="absent"):
        validate_contact_response(value, _ocr())


def test_display_and_normalized_values_are_both_preserved():
    value = validate_contact_response(_contact(), _ocr())
    result = enrich_contact(value, _ocr())
    assert result["fields"]["email"]["display_value"] == "info@example.jp"
    assert result["fields"]["email"]["normalized_value"] == "info@example.jp"
    assert result["fields"]["email"]["review_flags"] == []


def test_field_supported_only_by_unmatched_text_is_review_flagged():
    value = validate_contact_response(_contact(), _ocr())
    result = enrich_contact(
        value,
        _ocr(),
        # 対応しなかった組は行側と領域側の2件に分かれる。領域側があること自体が
        # 「ローカル検出は動いたが一致しなかった」証拠になる
        [
            {"line_id": "line-001", "region_id": None, "alignment_status": "unmatched"},
            {"line_id": None, "region_id": "region-001", "alignment_status": "unmatched"},
        ],
    )
    assert "unmatched_text_only" in result["fields"]["email"]["review_flags"]


def test_no_local_regions_does_not_flag_every_field():
    """ローカル検出が0件のときは突き合わせる材料が無いだけで、根拠なしの証拠にはならない。

    区別しないと全項目にフラグが立ち、一括登録できないカードが量産される
    （2026-08-19、本番の未確認32件に173個の偽陽性が溜まっていた）。
    """
    value = validate_contact_response(_contact(), _ocr())
    result = enrich_contact(
        value,
        _ocr(),
        [{"line_id": "line-001", "region_id": None, "alignment_status": "unmatched"}],
    )
    assert result["fields"]["email"]["review_flags"] == []


def test_present_value_with_empty_source_text_is_unsupported():
    ocr = _ocr()
    ocr["lines"][0]["text"] = None
    value = validate_contact_response(_contact(), ocr)
    result = enrich_contact(value, ocr)
    assert result["fields"]["email"]["evidence_status"] == "unsupported"
    assert "missing_text_evidence" in result["fields"]["email"]["review_flags"]
