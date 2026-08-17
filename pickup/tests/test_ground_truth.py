import json

import numpy as np
import pytest

from annotate_ground_truth import (
    ANNOTATION_METHOD,
    _load_document,
    save_annotation,
)
from detector import write_image
from evaluate import evaluate


def test_old_detector_derived_ground_truth_is_rejected(tmp_path):
    target = tmp_path / "ground_truth.json"
    target.write_text(
        json.dumps({"schema_version": 1, "images": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="旧形式"):
        _load_document(target)


def test_manual_annotation_is_saved_without_detector_output(tmp_path):
    input_dir = tmp_path / "picture"
    input_dir.mkdir()
    source = input_dir / "sample.png"
    write_image(source, np.full((500, 800, 3), 255, np.uint8))
    target = tmp_path / "ground_truth.json"

    saved = save_annotation(
        target,
        input_dir,
        source.name,
        [[[100, 100], [700, 100], [700, 450], [100, 450]]],
    )

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["schema_version"] == 2
    assert document["annotation_method"] == ANNOTATION_METHOD
    assert saved["annotation_method"] == ANNOTATION_METHOD
    assert len(saved["cards"]) == 1


def test_manual_annotation_has_no_card_count_ceiling(tmp_path):
    input_dir = tmp_path / "picture"
    input_dir.mkdir()
    source = input_dir / "many-cards.png"
    write_image(source, np.full((500, 800, 3), 255, np.uint8))
    target = tmp_path / "ground_truth.json"
    corners = [[100, 100], [700, 100], [700, 450], [100, 450]]

    saved = save_annotation(
        target,
        input_dir,
        source.name,
        [corners for _ in range(13)],
    )

    assert len(saved["cards"]) == 13


def test_evaluation_fails_when_an_input_is_not_annotated(tmp_path, capsys):
    input_dir = tmp_path / "picture"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    write_image(
        input_dir / "unannotated.png",
        np.full((500, 800, 3), 255, np.uint8),
    )
    target = tmp_path / "ground_truth.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "annotation_method": ANNOTATION_METHOD,
                "dataset_role": "development",
                "images": {},
            }
        ),
        encoding="utf-8",
    )

    assert evaluate(target, output_dir, input_dir) == 2
    assert "人手アノテーションがありません" in capsys.readouterr().out


def test_annotated_only_evaluates_registered_subset(tmp_path):
    input_dir = tmp_path / "picture"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    annotated = input_dir / "annotated.png"
    write_image(annotated, np.full((500, 800, 3), 255, np.uint8))
    write_image(
        input_dir / "not-yet.png",
        np.full((500, 800, 3), 255, np.uint8),
    )
    corners = [[100, 100], [700, 100], [700, 450], [100, 450]]
    target = tmp_path / "ground_truth.json"
    save_annotation(target, input_dir, annotated.name, [corners])
    result_dir = output_dir / annotated.stem
    result_dir.mkdir()
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "elapsed_ms": 100,
                "cards": [{"corners": corners}],
            }
        ),
        encoding="utf-8",
    )

    assert (
        evaluate(
            target,
            output_dir,
            input_dir,
            require_all_inputs=False,
        )
        == 0
    )
