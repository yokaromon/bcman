from app.services import _iou, _source_corners


def test_normalized_detection_corners_share_local_coordinate_space():
    """1600pxへ縮小してAIへ送っても、原寸座標に戻せばローカル候補と重複する。"""
    ai_box = _source_corners([[.1, .2], [.4, .2], [.4, .5], [.1, .5]], 4000, 3000)
    assert ai_box == [[400.0, 600.0], [1600.0, 600.0], [1600.0, 1500.0], [400.0, 1500.0]]
    assert _iou((400, 600, 1200, 900), (400, 600, 1200, 900)) == 1


def test_invalid_normalized_detection_corners_are_discarded():
    assert _source_corners([[160, 120], [.4, .2], [.4, .5], [.1, .5]], 4000, 3000) is None
    assert _source_corners([[.1, .2]], 4000, 3000) is None
