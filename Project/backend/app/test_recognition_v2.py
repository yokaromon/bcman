"""Recognition Pipeline V2 のうち、Paddleモデル無しで検証できる部分のテスト。

向き分類器の実推論はモデル本体（provision_models.py で配置）が要るので、ここでは扱わない。
"""

import cv2
import numpy as np
import pytest

from app.main import resolve_pipeline_version
from app.models import Contact, User
from app.recognition_v2 import detector
from app.recognition_v2.pipeline import _apply_contact_fields
from app.recognition_v2.recognition_contract import (
    CONTACT_FIELDS,
    RecognitionContractError,
    enrich_contact,
    validate_contact_response,
    validate_ocr_response,
)

PHOTO_WIDTH, PHOTO_HEIGHT = 2000, 1500
CARD_WIDTH, CARD_HEIGHT = 500, 302
CARD_CENTERS = [(350, 251), (1150, 251), (350, 851), (1300, 1050)]
CARD_ANGLES = [0, 0, 0, 30]


def _scattered_cards_photo():
    photo = np.full((PHOTO_HEIGHT, PHOTO_WIDTH, 3), 255, np.uint8)
    for center, angle in zip(CARD_CENTERS, CARD_ANGLES):
        corners = cv2.boxPoints((center, (CARD_WIDTH, CARD_HEIGHT), angle))
        cv2.fillPoly(photo, [corners.astype(np.int32)], (70, 70, 70))
    return photo


def test_v2_detector_finds_each_scattered_card():
    """V1と同じ配置で、移植したpickup側の検出器も各カードの位置を正しく検出できること。

    pickup/detector.py は複数戦略（輪郭・線分・色領域・単一エッジ再構成）を持つ
    実写真向けの検出器で、実際の質感ノイズが皆無なこの合成画像では
    single-edge-reconstruction戦略が実カードの間の空白を誤って拾うことがある
    （実機確認: 4枚の合成画像で7件検出、うち3件が幽霊検出）。
    実写真での検証（pickup/README.mdの開発57画像、56/57通過）はこの過検出を伴わないため、
    ここでは「各カードの位置が高信頼度で検出されているか」だけを検証し、
    合成画像特有の誤検出の有無までは求めない。"""
    detections = detector.detect_cards(_scattered_cards_photo())
    for expected in CARD_CENTERS:
        match = min(
            detections,
            key=lambda item: np.linalg.norm(np.float32(item.corners).mean(axis=0) - np.float32(expected)),
        )
        center = np.float32(match.corners).mean(axis=0)
        assert abs(center[0] - expected[0]) <= 10
        assert abs(center[1] - expected[1]) <= 10
        assert match.confidence >= 0.9


def _member(role="member"):
    return User(role=role, organization_id="org", username="u", name="n", password_hash="", totp_secret="")


def test_v2_follows_only_the_master_switch(monkeypatch):
    """写真ごとのopt-inはやめ、RECOGNITION_PIPELINE_V2_ENABLEDだけがV1/V2を分ける
    （2026-08-18、opt-inチェックボックスを外したまま検証用にV2を使い続けたいという要望）。
    ロールに関係なく、フラグの状態だけで決まる。"""
    from app import main

    monkeypatch.setattr(main.settings, "recognition_pipeline_v2_enabled", False)
    assert resolve_pipeline_version(_member("admin")) == "v1"
    assert resolve_pipeline_version(_member("member")) == "v1"

    monkeypatch.setattr(main.settings, "recognition_pipeline_v2_enabled", True)
    assert resolve_pipeline_version(_member("admin")) == "v2"
    assert resolve_pipeline_version(_member("member")) == "v2"


def _ocr_document(*texts):
    return {
        "schema_version": 1,
        "lines": [
            {"line_id": f"line-{index:03d}", "text": text, "source": "printed", "legibility": "readable"}
            for index, text in enumerate(texts, 1)
        ],
    }


def _contact_fields(**overrides):
    fields = {
        name: {"state": "absent", "display_value": None, "candidate_value": None, "source_line_ids": []}
        for name in CONTACT_FIELDS
    }
    fields.update(overrides)
    return {"schema_version": 1, "fields": fields}


def test_present_field_requires_evidence():
    """根拠行のないpresentは契約違反として弾く（Structured Field Candidateの不変条件）。"""
    ocr = _ocr_document("株式会社青柳")
    document = _contact_fields(
        company_name={"state": "present", "display_value": "株式会社青柳", "candidate_value": None, "source_line_ids": []}
    )
    with pytest.raises(RecognitionContractError):
        validate_contact_response(document, ocr)


def test_unknown_source_line_is_rejected():
    """存在しない根拠IDの引用は登録せず契約違反にする。"""
    ocr = _ocr_document("株式会社青柳")
    document = _contact_fields(
        company_name={"state": "present", "display_value": "株式会社青柳", "candidate_value": None, "source_line_ids": ["line-999"]}
    )
    with pytest.raises(RecognitionContractError):
        validate_contact_response(document, ocr)


def test_contact_states_map_onto_the_existing_contact_row():
    """present は値、absent は None、unreadable は None + Review Flag になる。"""
    ocr = _ocr_document("株式会社青柳", "TEL 092-622-2430")
    document = _contact_fields(
        company_name={"state": "present", "display_value": "株式会社青柳", "candidate_value": None, "source_line_ids": ["line-001"]},
        telephone={"state": "unreadable", "display_value": None, "candidate_value": "092-622-????", "source_line_ids": ["line-002"]},
    )
    enriched = enrich_contact(validate_contact_response(document, ocr), ocr, alignment=None)
    contact = Contact(card_id="card")
    flags = _apply_contact_fields(contact, enriched["fields"])

    assert contact.company_name == "株式会社青柳"
    assert contact.telephone is None
    assert contact.email is None
    assert "telephone" in flags
    assert "company_name" not in flags
    # 確定は既存の /confirm ルートだけが行う。認識段階では絶対に立てない
    assert not contact.confirmed


def test_value_without_supporting_text_is_review_flagged():
    """OCR原文から導けない値は登録可能な確定値にせず、Review Flagで残す。"""
    ocr = _ocr_document("株式会社青柳")
    document = _contact_fields(
        person_name={"state": "present", "display_value": "架空太郎", "candidate_value": None, "source_line_ids": ["line-001"]}
    )
    enriched = enrich_contact(validate_contact_response(document, ocr), ocr, alignment=None)
    assert enriched["fields"]["person_name"]["evidence_status"] == "unsupported"
    contact = Contact(card_id="card")
    assert "person_name" in _apply_contact_fields(contact, enriched["fields"])


def test_unreadable_ocr_line_keeps_no_text():
    """読めない行は推測させず、textをNoneのまま残す。"""
    document = validate_ocr_response(
        {"schema_version": 1, "lines": [{"text": "   ", "source": "printed", "legibility": "unreadable"}]}
    )
    assert document["lines"][0]["text"] is None
