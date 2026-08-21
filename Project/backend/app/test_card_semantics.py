"""管理下Visionへ渡す名刺候補ラベルと厳密なJSON契約。"""

import json

import numpy as np
import pytest

from app.recognition_v2 import detector
from app.recognition_v2.card_semantics import (
    CardSemanticContractError,
    _validate_document,
    classify_card_candidates,
)
from app.recognition_v2.ykr_client import ManagedRecognitionClient, YkrSettings


def _response(value):
    return {"choices": [{"message": {"content": json.dumps(value)}}]}


def _client(post):
    return ManagedRecognitionClient(
        YkrSettings(
            "https://app.ykr.ltd/ai/v1",
            "test-secret",
            "vision-fixed",
            "vision-fixed",
        ),
        post_json=post,
    )


def _detections():
    return [
        detector.Detection(
            corners=np.float32([[20, 20], [300, 20], [300, 180], [20, 180]]),
            confidence=0.8, strategy="first", score=0.8, contrast=0.5,
        ),
        detector.Detection(
            corners=np.float32([[330, 30], [610, 30], [610, 190], [330, 190]]),
            confidence=0.7, strategy="second", score=0.7, contrast=0.4,
        ),
    ]


def test_candidate_classifier_sends_one_labeled_image_and_validates_every_id():
    calls = []

    def post(_url, _headers, payload, _timeout):
        calls.append(payload)
        return _response({
            "schema_version": 1,
            "candidates": [
                {
                    "candidate_id": 1,
                    "decision": "not_business_card",
                    "confidence": 0.98,
                    "reason": "multiple_cards_or_background",
                },
                {
                    "candidate_id": 2,
                    "decision": "business_card",
                    "confidence": 0.92,
                    "reason": "one_complete_card",
                },
            ],
        })

    result = classify_card_candidates(
        np.full((240, 640, 3), 245, np.uint8),
        _detections(),
        _client(post),
    )

    assert result.verdicts[1].decision == "not_business_card"
    assert result.verdicts[2].decision == "business_card"
    assert result.model == "vision-fixed"
    assert len(calls) == 1
    content = calls[0]["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_candidate_contract_rejects_missing_or_duplicate_ids():
    base = {
        "schema_version": 1,
        "candidates": [
            {
                "candidate_id": 1,
                "decision": "business_card",
                "confidence": 0.9,
                "reason": "one_complete_card",
            }
        ],
    }
    with pytest.raises(CardSemanticContractError, match="重複・欠落・追加"):
        _validate_document(base, {1, 2})
    duplicate = {**base, "candidates": [base["candidates"][0], base["candidates"][0]]}
    with pytest.raises(CardSemanticContractError, match="重複・欠落・追加"):
        _validate_document(duplicate, {1})


def test_candidate_contract_rejects_semantic_contradiction():
    document = {
        "schema_version": 1,
        "candidates": [
            {
                "candidate_id": 1,
                "decision": "business_card",
                "confidence": 0.9,
                "reason": "partial_card",
            }
        ],
    }
    with pytest.raises(CardSemanticContractError, match="矛盾"):
        _validate_document(document, {1})


def test_candidate_contract_rejects_boolean_schema_version():
    document = {
        "schema_version": True,
        "candidates": [],
    }
    with pytest.raises(CardSemanticContractError, match="schema_version"):
        _validate_document(document, set())
