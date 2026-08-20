from __future__ import annotations

import json
import os
from pathlib import Path

import cv2

from annotate_ground_truth import ensure_card_ids
from bcpickup import _source_images
from detector import perspective_crop, read_image
from orientation import rotate_clockwise


def atomic_write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def extraction_cards(input_dir: Path, ground_truth: Path) -> list[dict]:
    document = ensure_card_ids(ground_truth)
    sources = {path.name: path for path in _source_images(input_dir)}
    cards = []
    for source_name, annotation in document["images"].items():
        source = sources.get(source_name)
        if source is None:
            continue
        for index, card in enumerate(annotation.get("cards", []), 1):
            cards.append(
                {
                    "ground_truth_card_id": card["ground_truth_card_id"],
                    "source": source_name,
                    "source_path": source,
                    "source_sha256": annotation["source_sha256"],
                    "card_index": index,
                    "corners": card["corners"],
                }
            )
    return cards


def card_by_id(cards: list[dict], card_id: str) -> dict:
    card = next(
        (item for item in cards if item["ground_truth_card_id"] == card_id), None
    )
    if card is None:
        raise ValueError("Ground TruthのカードIDではありません")
    return card


def rendered_card(card: dict, correction_rotation: int = 0):
    image = read_image(card["source_path"])
    cropped = perspective_crop(image, card["corners"])
    return rotate_clockwise(cropped, correction_rotation)


def encoded_png(card: dict, correction_rotation: int = 0) -> bytes:
    success, encoded = cv2.imencode(
        ".png", rendered_card(card, correction_rotation), [cv2.IMWRITE_PNG_COMPRESSION, 3]
    )
    if not success:
        raise ValueError("カード画像をPNG化できません")
    return encoded.tobytes()
