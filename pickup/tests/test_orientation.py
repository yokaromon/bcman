import numpy as np

from orientation import OrientationEngine, OrientationThresholds, rotate_clockwise


class FakeModels:
    def __init__(self, predictions):
        self.predictions = predictions

    def classify(self, images):
        assert len(images) == 4
        return self.predictions


def test_rotate_clockwise_changes_dimensions_and_can_restore_image():
    image = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
    rotated = rotate_clockwise(image, 90)
    assert rotated.shape == (3, 2, 3)
    assert np.array_equal(rotate_clockwise(rotated, 270), image)


def test_classifier_self_consistency_applies_correction():
    models = FakeModels([
        {"label": 90, "score": 0.95}, {"label": 180, "score": 0.94},
        {"label": 270, "score": 0.93}, {"label": 0, "score": 0.92},
    ])
    oriented, result = OrientationEngine(models).analyze(
        np.zeros((20, 30, 3), np.uint8)
    )
    assert result["status"] == "auto_confirmed"
    assert result["rotation_applied"] == 270
    assert result["method"] == "classifier_self_consistency"
    assert oriented.shape == (30, 20, 3)


def test_disagreement_abstains_when_ocr_is_too_close():
    models = FakeModels([
        {"label": 0, "score": 0.95}, {"label": 90, "score": 0.94},
        {"label": 90, "score": 0.93}, {"label": 270, "score": 0.92},
    ])
    scores = iter([0.60, 0.62, 0.61, 0.59])
    _, result = OrientationEngine(models).analyze(
        np.zeros((20, 30, 3), np.uint8),
        readability_scorer=lambda image: {
            "score": next(scores), "recognized_regions": 4,
        },
    )
    assert result["status"] == "uncertain"
    assert result["rotation_applied"] == 0
    assert result["method"] == "none"


def test_ocr_fallback_can_confirm_a_clear_winner():
    models = FakeModels([
        {"label": 0, "score": 0.70}, {"label": 90, "score": 0.71},
        {"label": 180, "score": 0.72}, {"label": 270, "score": 0.73},
    ])
    by_rotation = iter([0.40, 0.45, 0.78, 0.43])
    oriented, result = OrientationEngine(
        models, OrientationThresholds(ocr_min_margin=0.10)
    ).analyze(
        np.zeros((20, 30, 3), np.uint8),
        readability_scorer=lambda image: {
            "score": next(by_rotation), "recognized_regions": 5,
        },
    )
    assert result["status"] == "auto_confirmed"
    assert result["rotation_applied"] == 180
    assert result["method"] == "ocr_readability"
    assert oriented.shape == (20, 30, 3)
