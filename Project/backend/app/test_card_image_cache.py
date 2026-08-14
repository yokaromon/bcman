from types import SimpleNamespace

from PIL import Image

from app.services import card_image_revision, card_thumbnail


def _card(path, orientation=0):
    return SimpleNamespace(oriented_image_path=str(path), corrected_image_path=str(path), orientation=orientation)


def test_image_revision_changes_when_oriented_image_changes(tmp_path):
    first = tmp_path / "oriented-0.jpg"
    second = tmp_path / "oriented-90-1.jpg"
    Image.new("RGB", (80, 50), "white").save(first)
    Image.new("RGB", (50, 80), "white").save(second)

    assert card_image_revision(_card(first, 0)) != card_image_revision(_card(second, 90))


def test_thumbnail_is_stored_per_oriented_image_revision(tmp_path):
    first = tmp_path / "oriented-0.jpg"
    second = tmp_path / "oriented-90-1.jpg"
    Image.new("RGB", (80, 50), "red").save(first)
    Image.new("RGB", (50, 80), "blue").save(second)

    first_thumb = card_thumbnail(_card(first, 0))
    second_thumb = card_thumbnail(_card(second, 90))

    assert first_thumb != second_thumb
    assert first_thumb.exists()
    assert second_thumb.exists()
