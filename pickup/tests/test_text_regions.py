import numpy as np

from text_regions import LocalTextPipeline, crop_text_region


class FakeModels:
    def detect(self, image):
        return [
            {"polygon": np.float32([[50, 60], [150, 60], [150, 80], [50, 80]]), "score": 0.92},
            {"polygon": np.float32([[10, 10], [120, 10], [120, 30], [10, 30]]), "score": 0.96},
        ]

    def recognize(self, images, *, server=False):
        assert len(images) == 2
        return [
            {"text": "株式会社青柳", "score": 0.98},
            {"text": "03-1234-5678", "score": 0.95},
        ]


def test_crop_text_region_rectifies_a_quad():
    image = np.full((100, 180, 3), 255, np.uint8)
    polygon = np.float32([[10, 20], [160, 10], [165, 50], [15, 60]])
    crop = crop_text_region(image, polygon)
    assert crop.shape[1] > crop.shape[0]
    assert crop.size > 0


def test_local_text_pipeline_assigns_stable_reading_order_ids():
    result = LocalTextPipeline(FakeModels()).process(
        np.full((100, 180, 3), 255, np.uint8)
    )
    assert result["models"]["recognition"] == "PP-OCRv5_server_rec"
    assert [item["region_id"] for item in result["regions"]] == [
        "region-001", "region-002",
    ]
    assert result["regions"][0]["polygon"][0] == [10.0, 10.0]
    assert result["regions"][0]["text"] == "株式会社青柳"


def test_directional_glyphs_are_only_a_small_readability_bonus():
    pipeline = LocalTextPipeline(FakeModels())
    pipeline.process = lambda image, server=False: {
        "regions": [{"text": "ABCD2345", "recognition_score": 0.8}]
    }
    result = pipeline.readability(np.zeros((10, 10, 3), np.uint8))
    assert result["directional_glyph_count"] == 8
    assert 0.50 < result["score"] < 0.75
