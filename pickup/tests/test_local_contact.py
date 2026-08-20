from local_contact import extract_local_contact


def test_local_contact_extracts_only_format_reliable_fields():
    result = extract_local_contact(
        {
            "regions": [
                {"region_id": "region-001", "text": "info@Example.JP"},
                {"region_id": "region-002", "text": "FAX 03-1234-5678"},
                {"region_id": "region-003", "text": "〒100-0001"},
            ]
        }
    )
    assert result["fields"]["email"]["normalized_value"] == "info@example.jp"
    assert result["fields"]["fax"]["state"] == "present"
    assert result["fields"]["postal_code"]["normalized_value"] == "1000001"
    assert result["fields"]["person_name"]["state"] == "absent"
