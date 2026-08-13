import cv2
import numpy as np
from app.services import _containment, _ordered_corners, card_quads

PHOTO_WIDTH, PHOTO_HEIGHT = 2000, 1500
# 名刺の実寸 91×55mm と同じ比 1.655 になる大きさ
CARD_WIDTH, CARD_HEIGHT = 500, 302
# 机に散らばった状態を模して、1枚だけ傾けて置く
CARD_CENTERS = [(350, 251), (1150, 251), (350, 851), (1300, 1050)]
CARD_ANGLES = [0, 0, 0, 30]


def _scattered_cards_photo():
    """白い机の上に名刺を4枚（うち1枚は傾けて）置いた写真を模した画像を作る。"""
    photo = np.full((PHOTO_HEIGHT, PHOTO_WIDTH, 3), 255, np.uint8)
    for center, angle in zip(CARD_CENTERS, CARD_ANGLES):
        corners = cv2.boxPoints((center, (CARD_WIDTH, CARD_HEIGHT), angle))
        cv2.fillPoly(photo, [corners.astype(np.int32)], (70, 70, 70))
    return photo


def test_scattered_cards_are_detected_once_each():
    """4枚置いた写真は4枚として検出される。
    同じ名刺の内側の輪郭を別候補として数えると枚数が倍に膨らむため、その再発を防ぐ。"""
    quads = card_quads(_scattered_cards_photo())
    assert len(quads) == len(CARD_CENTERS)
    detected_centers = sorted(tuple(np.float32(quad).mean(axis=0).round()) for quad in quads)
    for detected, expected in zip(detected_centers, sorted(map(tuple, np.float32(CARD_CENTERS)))):
        assert abs(detected[0] - expected[0]) <= 10
        assert abs(detected[1] - expected[1]) <= 10


def test_detected_quads_keep_the_card_shape():
    """切り出し枠が名刺の形のままであること。軸平行の外接矩形に落ちると傾けた名刺で比が崩れる。"""
    for quad in card_quads(_scattered_cards_photo()):
        (_, _), (width, height), _ = cv2.minAreaRect(np.float32(quad))
        short_edge, long_edge = min(width, height), max(width, height)
        assert abs(long_edge - CARD_WIDTH) <= 15
        assert abs(short_edge - CARD_HEIGHT) <= 15


def test_blank_photo_yields_no_candidate():
    """名刺の写っていない写真からは候補を作らない（呼び出し側が写真全体を1枚として拾う）。"""
    assert card_quads(np.full((PHOTO_HEIGHT, PHOTO_WIDTH, 3), 255, np.uint8)) == []


def test_corners_are_ordered_clockwise_from_top_left():
    """どの順序で渡しても左上・右上・右下・左下に整う。順序が崩れると鏡像に切り抜かれる。"""
    shuffled = [[300, 400], [100, 200], [100, 400], [300, 200]]
    assert _ordered_corners(shuffled).tolist() == [[100, 200], [300, 200], [300, 400], [100, 400]]


def test_corner_ordering_uses_every_point_once():
    """正方形に近い四角形でも同じ点を二度使わない。重複すると台形補正が壊れる。"""
    ordered = _ordered_corners([[0, 0], [200, 0], [200, 200], [0, 200]])
    assert len({tuple(point) for point in ordered.tolist()} ) == 4


def test_containment_detects_a_box_inside_another():
    """同じ名刺から出た内外の輪郭は、小さい方がほぼ収まる関係になる。"""
    assert _containment((0, 0, 100, 100), (10, 10, 80, 80)) == 1


def test_containment_keeps_touching_neighbours_apart():
    """接して置いた別の名刺は、外接矩形が少し重なっても別候補として残す。"""
    assert _containment((0, 0, 100, 100), (90, 0, 100, 100)) <= .6
