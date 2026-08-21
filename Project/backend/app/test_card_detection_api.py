"""高解像度矩形検出APIが認証だけを行い、画像やDB行を残さないこと。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app, current_user
from app.models import BusinessCard, Photo, User
from app.recognition_v2 import card_detection, detector
from app.recognition_v2.card_semantics import SemanticSelection, SemanticVerdict
from app.settings import settings


def _jpeg(width: int = 640, height: int = 480) -> bytes:
    image = np.full((height, width, 3), 245, np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def _authenticated_user() -> User:
    return User(
        id="detection-user",
        organization_id="detection-org",
        username="detector",
        name="検出利用者",
        role="member",
        password_hash="",
        totp_secret="",
    )


def _stored_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def test_detection_requires_login():
    with TestClient(app) as client:
        response = client.post(
            "/api/card-detections",
            content=_jpeg(),
            headers={"Content-Type": "image/jpeg"},
        )

    assert response.status_code == 401


def test_detection_returns_rectangles_without_persisting(monkeypatch):
    expected = detector.Detection(
        corners=np.float32([[10, 20], [610, 20], [610, 460], [10, 460]]),
        confidence=0.91,
        strategy="test-contour",
        score=0.88,
        contrast=0.73,
    )
    monkeypatch.setattr(card_detection.detector, "detect_cards", lambda _image: [expected])
    app.dependency_overrides[current_user] = _authenticated_user
    before_files = _stored_files(settings.storage_dir)
    with SessionLocal() as db:
        before_rows = (db.query(Photo).count(), db.query(BusinessCard).count())

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/card-detections",
                content=_jpeg(),
                headers={"Content-Type": "image/jpeg"},
            )
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 200
    document = response.json()
    assert document["persisted"] is False
    assert document["authoritative"] is True
    assert document["source_size"] == {"width": 640, "height": 480}
    assert document["card_count"] == 1
    assert document["cards"][0] == {
        "index": 1,
        "candidate_index": 1,
        "corners": [[10.0, 20.0], [610.0, 20.0], [610.0, 460.0], [10.0, 460.0]],
        "confidence": 0.91,
        "strategy": "test-contour",
        "score": 0.88,
        "contrast": 0.73,
    }
    assert _stored_files(settings.storage_dir) == before_files
    with SessionLocal() as db:
        assert (db.query(Photo).count(), db.query(BusinessCard).count()) == before_rows


def test_detection_uses_the_pipeline_full_frame_fallback(monkeypatch):
    monkeypatch.setattr(card_detection.detector, "detect_cards", lambda _image: [])
    result = card_detection.analyze_card_rectangles(_jpeg(320, 240), 48_000_000)

    assert result["card_count"] == 1
    assert result["cards"][0]["strategy"] == "full_frame_fallback"
    assert result["cards"][0]["corners"] == [
        [0.0, 0.0],
        [319.0, 0.0],
        [319.0, 239.0],
        [0.0, 239.0],
    ]


def test_semantic_detection_rejects_non_card_candidates(monkeypatch):
    candidates = [
        detector.Detection(
            corners=np.float32([[10, 20], [300, 20], [300, 200], [10, 200]]),
            confidence=0.81, strategy="candidate-one", score=0.81, contrast=0.5,
        ),
        detector.Detection(
            corners=np.float32([[320, 30], [620, 30], [620, 210], [320, 210]]),
            confidence=0.77, strategy="candidate-two", score=0.77, contrast=0.4,
        ),
    ]
    monkeypatch.setattr(card_detection.detector, "detect_cards", lambda _image: candidates)
    monkeypatch.setattr(card_detection, "_refine_semantic_detection", lambda _image, item: item)

    def semantic_filter(_image, _candidates):
        return SemanticSelection(
            verdicts={
                1: SemanticVerdict(1, "not_business_card", 0.96, "multiple_cards_or_background"),
                2: SemanticVerdict(2, "business_card", 0.91, "one_complete_card"),
            },
            attempts=1,
            model="vision-fixed",
        )

    result = card_detection.analyze_card_rectangles(
        _jpeg(), 48_000_000, semantic_filter
    )

    assert result["candidate_count"] == 2
    assert result["card_count"] == 1
    assert result["semantic_status"] == "completed"
    assert result["semantic_model"] == "vision-fixed"
    assert result["cards"][0]["candidate_index"] == 2
    assert result["cards"][0]["semantic_confidence"] == 0.91
    assert result["cards"][0]["semantic_reason"] == "one_complete_card"


def test_semantic_api_uses_managed_filter_without_persisting(monkeypatch):
    from app import main

    candidate = detector.Detection(
        corners=np.float32([[10, 20], [610, 20], [610, 460], [10, 460]]),
        confidence=0.9, strategy="semantic-test", score=0.9, contrast=0.8,
    )
    monkeypatch.setattr(card_detection.detector, "detect_cards", lambda _image: [candidate])
    monkeypatch.setattr(card_detection, "_refine_semantic_detection", lambda _image, item: item)
    monkeypatch.setattr(
        main,
        "managed_card_semantic_filter",
        lambda _image, _candidates: SemanticSelection(
            {1: SemanticVerdict(1, "business_card", 0.94, "one_complete_card")},
            1,
            "vision-fixed",
        ),
    )
    app.dependency_overrides[current_user] = _authenticated_user
    before_files = _stored_files(settings.storage_dir)
    with SessionLocal() as db:
        before_rows = (db.query(Photo).count(), db.query(BusinessCard).count())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/card-detections?semantic=true",
                content=_jpeg(),
                headers={"Content-Type": "image/jpeg"},
            )
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 200
    assert response.json()["semantic_status"] == "completed"
    assert _stored_files(settings.storage_dir) == before_files
    with SessionLocal() as db:
        assert (db.query(Photo).count(), db.query(BusinessCard).count()) == before_rows


def test_detection_rejects_wrong_media_type_before_running_detector(monkeypatch):
    called = False

    def unexpected(_image):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(card_detection.detector, "detect_cards", unexpected)
    app.dependency_overrides[current_user] = _authenticated_user
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/card-detections",
                content=b"not-an-image",
                headers={"Content-Type": "application/octet-stream"},
            )
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 415
    assert called is False


def test_detection_rejects_compressed_and_expanded_size_limits(monkeypatch):
    app.dependency_overrides[current_user] = _authenticated_user
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    try:
        with TestClient(app) as client:
            compressed = client.post(
                "/api/card-detections",
                content=_jpeg(),
                headers={"Content-Type": "image/jpeg"},
            )
    finally:
        app.dependency_overrides.pop(current_user, None)
    assert compressed.status_code == 413

    with np.testing.assert_raises(card_detection.DetectionImageTooLarge):
        card_detection.analyze_card_rectangles(_jpeg(40, 30), 100)
