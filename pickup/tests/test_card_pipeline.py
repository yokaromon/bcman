import json

import cv2
import numpy as np

from card_pipeline import PickupCardPipeline
from recognition_contract import CONTACT_FIELDS
from ykr_client import StageResult, YkrSettings


class FakeModels:
    def classify(self, images):
        return [
            {"label": 0, "score": 0.95},
            {"label": 90, "score": 0.95},
            {"label": 180, "score": 0.95},
            {"label": 270, "score": 0.95},
        ]

    def detect(self, image):
        return [{
            "polygon": np.float32([[10, 10], [150, 10], [150, 35], [10, 35]]),
            "score": 0.98,
        }]

    def recognize(self, images, *, server=False):
        return [{"text": "info@example.jp", "score": 0.97} for _ in images]


class FakeYkr:
    def __init__(self, *, contact_fails=False):
        self.settings = YkrSettings("https://app.ykr.ltd/ai/v1", "secret", "ocr-v1-fixed", "contact-v1-fixed")
        self.contact_fails = contact_fails
        self.ocr_calls = 0
        self.contact_calls = 0

    def run_ocr(self, image_path):
        self.ocr_calls += 1
        return StageResult(
            {"schema_version": 1, "lines": [{
                "line_id": "line-001", "text": "info@example.jp",
                "source": "printed", "legibility": "readable",
            }]},
            1, "ocr-v1-fixed", "ocr-v1",
        )

    def structure_contact(self, ocr_document, alignment=None):
        self.contact_calls += 1
        if self.contact_fails:
            raise RuntimeError("fixture failure")
        fields = {
            name: {
                "state": "absent", "display_value": None,
                "candidate_value": None, "source_line_ids": [],
            }
            for name in CONTACT_FIELDS
        }
        fields["email"] = {
            "state": "present", "display_value": "info@example.jp",
            "candidate_value": None, "source_line_ids": ["line-001"],
        }
        return StageResult(
            {"schema_version": 1, "fields": fields},
            1, "contact-v1-fixed", "contact-v1",
        )


def _card(path):
    assert cv2.imwrite(str(path), np.full((100, 180, 3), 255, np.uint8))


def test_local_pipeline_writes_the_complete_artifact_shape(tmp_path):
    card = tmp_path / "card01.png"
    _card(card)
    result = PickupCardPipeline("local", models=FakeModels()).process_card(
        card, prefix="card01"
    )
    assert result["status"] == "local_completed"
    for suffix in (
        "orientation.json", "oriented.png", "ocr.paddle.json", "ocr.ykr.json",
        "contact.paddle.json", "contact.ykr.json",
    ):
        assert (tmp_path / f"card01.{suffix}").exists()
    ykr = json.loads((tmp_path / "card01.ocr.ykr.json").read_text(encoding="utf-8"))
    assert ykr["status"] == "not_requested"


def test_orientation_only_pipeline_does_not_run_text_ocr(tmp_path):
    card = tmp_path / "card01.png"
    _card(card)
    models = FakeModels()
    models.detect = lambda image: (_ for _ in ()).throw(
        AssertionError("文字検出が呼ばれた")
    )
    result = PickupCardPipeline("orientation", models=models).process_card(
        card, prefix="card01"
    )
    assert result["status"] == "orientation_completed"
    assert (tmp_path / "card01.oriented.png").exists()
    placeholder = json.loads(
        (tmp_path / "card01.ocr.paddle.json").read_text(encoding="utf-8")
    )
    assert placeholder["status"] == "not_requested"


def test_contact_failure_keeps_successful_ocr_for_independent_retry(tmp_path):
    card = tmp_path / "card01.png"
    _card(card)
    ykr = FakeYkr(contact_fails=True)
    result = PickupCardPipeline(
        "full", models=FakeModels(), ykr_client=ykr
    ).process_card(card, prefix="card01")
    ocr = json.loads((tmp_path / "card01.ocr.ykr.json").read_text(encoding="utf-8"))
    contact = json.loads((tmp_path / "card01.contact.ykr.json").read_text(encoding="utf-8"))
    assert result["status"] == "partial"
    assert ocr["status"] == "succeeded"
    assert contact["status"] == "failed"
    assert ykr.ocr_calls == 1
    assert ykr.contact_calls == 1


def test_cache_reuse_and_force_recognition_history(tmp_path):
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    forced = tmp_path / "forced"
    previous.mkdir(); current.mkdir(); forced.mkdir()
    for directory in (previous, current, forced):
        _card(directory / "card01.png")
    ykr = FakeYkr()
    pipeline = PickupCardPipeline("full", models=FakeModels(), ykr_client=ykr)
    pipeline.process_card(previous / "card01.png", prefix="card01")
    reused = pipeline.process_card(
        current / "card01.png", prefix="card01", previous_dir=previous
    )
    assert reused["status"] == "completed"
    assert ykr.ocr_calls == 1
    cached = json.loads((current / "card01.ocr.ykr.json").read_text(encoding="utf-8"))
    assert cached["cache_reused"] is True

    pipeline.process_card(
        forced / "card01.png",
        prefix="card01",
        previous_dir=current,
        force_recognition=True,
    )
    assert ykr.ocr_calls == 2
    assert len(list((forced / "recognition_history").glob("card01.*.ocr.ykr.json"))) == 1
