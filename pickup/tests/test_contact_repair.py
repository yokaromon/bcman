"""契約に満たない応答を、項目単位の減点で救済できることを確かめる。

1項目の崩れで残り13項目の正解まで捨てていた実インシデント(2026-08-19、
fields.addressのcandidate_valueキー欠落)の再発防止。
"""

import pytest

from local_contact import contact_from_ocr_lines
from recognition_contract import (
    CONTACT_FIELDS,
    RecognitionContractError,
    coerce_contact_document,
    enrich_contact,
    repair_contact_document,
    validate_contact_response,
)


def _ocr_document():
    return {
        "schema_version": 1,
        "lines": [
            {"line_id": "line-001", "text": "株式会社サンプル", "source": "printed", "legibility": "readable"},
            {"line_id": "line-002", "text": "東京都港区芝大門2-11-8", "source": "printed", "legibility": "readable"},
            {"line_id": "line-003", "text": "TEL 03-1234-5678 FAX 03-1234-5679", "source": "printed", "legibility": "readable"},
            {"line_id": "line-004", "text": "info@example.co.jp", "source": "printed", "legibility": "readable"},
        ],
    }


def _field(state="absent", display=None, candidate=None, lines=()):
    return {
        "state": state,
        "display_value": display,
        "candidate_value": candidate,
        "source_line_ids": list(lines),
    }


def _document(**overrides):
    fields = {name: _field() for name in CONTACT_FIELDS}
    fields.update(overrides)
    return {"schema_version": 1, "fields": fields}


def test_missing_candidate_value_key_no_longer_loses_the_whole_card():
    """本番で実際に起きた崩れ方。addressのキー1つ欠落で全項目を失っていた。"""
    document = _document(
        company_name=_field("present", "株式会社サンプル", lines=["line-001"]),
        telephone=_field("present", "03-1234-5678", lines=["line-003"]),
    )
    del document["fields"]["address"]["candidate_value"]

    with pytest.raises(RecognitionContractError):
        validate_contact_response(document, _ocr_document())

    repaired, repairs = repair_contact_document(document, _ocr_document())
    assert repaired["fields"]["company_name"]["display_value"] == "株式会社サンプル"
    assert repaired["fields"]["telephone"]["display_value"] == "03-1234-5678"
    assert repaired["fields"]["address"]["candidate_value"] is None
    # 救済後は契約を満たしているので、通常経路と同じ検証を通せる
    validate_contact_response(repaired, _ocr_document())
    assert [repair["field"] for repair in repairs] == ["address"]


def test_root_level_fields_are_lifted():
    document = {"schema_version": 1, **_document()["fields"]}
    document["person_name"] = _field("present", "山田太郎", lines=["line-001"])
    repaired, repairs = repair_contact_document(document, _ocr_document())
    assert repaired["fields"]["person_name"]["display_value"] == "山田太郎"
    assert any(repair["field"] is None for repair in repairs)


def test_unknown_source_lines_are_dropped_instead_of_rejecting_the_document():
    document = _document(
        email=_field("present", "info@example.co.jp", lines=["line-004", "line-999"]),
    )
    repaired, repairs = repair_contact_document(document, _ocr_document())
    assert repaired["fields"]["email"]["source_line_ids"] == ["line-004"]
    assert repaired["fields"]["email"]["display_value"] == "info@example.co.jp"
    assert any("line-999" in repair["detail"] for repair in repairs)


@pytest.mark.parametrize(
    "broken, expected_state",
    [
        (_field("absent", "株式会社サンプル", lines=["line-001"]), "present"),
        (_field("present", None, lines=["line-001"]), "unreadable"),
        (_field("nonsense", "株式会社サンプル", lines=["line-001"]), "present"),
    ],
)
def test_broken_states_are_repaired_per_field(broken, expected_state):
    repaired, _ = repair_contact_document(_document(company_name=broken), _ocr_document())
    assert repaired["fields"]["company_name"]["state"] == expected_state
    validate_contact_response(repaired, _ocr_document())


def test_coercion_fixes_types_and_drops_unknown_keys():
    document = _document()
    document["fields"]["postal_code"] = {
        "state": "present",
        "display_value": "105-0012",
        "candidate_value": None,
        "source_line_ids": "line-002",
        "confidence": 0.9,
    }
    coerced, repairs = coerce_contact_document(document)
    assert coerced["fields"]["postal_code"]["source_line_ids"] == ["line-002"]
    assert "confidence" not in coerced["fields"]["postal_code"]
    assert any("confidence" in repair["detail"] for repair in repairs)


def test_format_baseline_keeps_the_reliable_fields_when_structuring_dies():
    """構造化が全滅しても0点にしない下限。形式で断定できる項目だけを拾う。"""
    document = contact_from_ocr_lines(_ocr_document())
    fields = document["fields"]
    assert fields["email"]["display_value"] == "info@example.co.jp"
    assert fields["telephone"]["display_value"] == "03-1234-5678"
    assert fields["fax"]["display_value"] == "03-1234-5679"
    assert fields["email"]["source_line_ids"] == ["line-004"]
    # 形式で判別できない項目を推測してはいけない
    assert fields["person_name"]["state"] == "absent"
    assert fields["company_name"]["state"] == "absent"
    validate_contact_response(document, _ocr_document())


def test_baseline_output_survives_enrichment():
    document = contact_from_ocr_lines(_ocr_document())
    enriched = enrich_contact(document, _ocr_document(), alignment=[])
    assert enriched["fields"]["telephone"]["normalized_value"] == "0312345678"
    assert enriched["fields"]["email"]["evidence_status"] == "supported"
