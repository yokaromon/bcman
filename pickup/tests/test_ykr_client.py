import json

from PIL import Image

from recognition_contract import CONTACT_FIELDS
from ykr_client import ManagedRecognitionClient, YkrSettings
from ykr_client import ManagedRecognitionError
import pytest


def _response(value):
    return {"choices": [{"message": {"content": json.dumps(value)}}]}


def _settings():
    return YkrSettings("https://app.ykr.ltd/ai/v1", "test-secret", "ocr-fixed", "contact-fixed")


def _empty_contact():
    return {
        "schema_version": 1,
        "fields": {
            name: {
                "state": "absent", "display_value": None,
                "candidate_value": None, "source_line_ids": [],
            }
            for name in CONTACT_FIELDS
        },
    }


def test_invalid_first_ocr_response_consumes_one_retry(tmp_path):
    image = tmp_path / "card.png"
    Image.new("RGB", (120, 80), "white").save(image)
    calls = []

    def post(url, headers, payload, timeout):
        calls.append((url, headers, payload, timeout))
        if len(calls) == 1:
            return _response({"unexpected": True})
        return _response({
            "schema_version": 1,
            "lines": [{"text": "青柳", "source": "printed", "legibility": "readable"}],
        })

    result = ManagedRecognitionClient(_settings(), post_json=post).run_ocr(image)
    assert result.attempts == 2
    assert result.document["lines"][0]["line_id"] == "line-001"
    assert len(calls) == 2
    assert calls[0][2]["response_format"] == {"type": "json_object"}
    assert len(calls[1][2]["messages"]) == 2
    assert "契約違反" in calls[1][2]["messages"][1]["content"]


def test_contact_retry_does_not_rerun_ocr():
    calls = []
    contact = _empty_contact()

    def post(url, headers, payload, timeout):
        calls.append(payload)
        return _response(contact)

    ocr = {
        "schema_version": 1,
        "lines": [{"line_id": "line-001", "text": "青柳", "source": "printed", "legibility": "readable"}],
    }
    result = ManagedRecognitionClient(_settings(), post_json=post).structure_contact(
        ocr,
        [{"line_id": "line-001", "region_id": "region-001", "alignment_status": "matched"}],
    )
    assert result.attempts == 1
    assert len(calls) == 1
    assert calls[0]["model"] == "contact-fixed"
    assert "alignment" in calls[0]["messages"][0]["content"]


def test_unmanaged_server_is_rejected():
    with pytest.raises(ManagedRecognitionError, match="app.ykr.ltd"):
        YkrSettings("https://unmanaged.example/v1", "secret", "ocr-fixed", "contact-fixed").validate()
