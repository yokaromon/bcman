from alignment import align_ocr_lines


def test_alignment_preserves_unmatched_lines_from_both_sides():
    local = {
        "regions": [
            {"region_id": "region-001", "text": "株式会社青柳"},
            {"region_id": "region-002", "text": "東京都港区"},
        ]
    }
    ykr = {
        "lines": [
            {"line_id": "line-001", "text": "株式会社 青柳", "source": "printed", "legibility": "readable"},
            {"line_id": "line-002", "text": "example@example.jp", "source": "printed", "legibility": "readable"},
        ]
    }
    result = align_ocr_lines(local, ykr)
    assert result[0]["alignment_status"] == "matched"
    assert result[0]["region_id"] == "region-001"
    assert any(item["line_id"] == "line-002" and item["region_id"] is None for item in result)
    assert any(item["line_id"] is None and item["region_id"] == "region-002" for item in result)
