import cv2
import json
import numpy as np

import bcpickup
from bcpickup import process_image
from detector import (
    CARD_LIMIT,
    _Candidate,
    _arbitrate_large_center_card,
    _cluster_candidates,
    _consistent_card_scale,
    _dark_interior_fraction,
    _prefer_region_refinement,
    _merge_color_candidates,
    _merge_single_edge_candidates,
    _opposite_side_imbalance,
    _repair_clipped_corner,
    _reference_card_dimensions,
    _remove_contained_fragments,
    _remove_reconstruction_duplicates,
    _replace_low_contrast_projection,
    _replace_with_stronger_alternative,
    _restore_partial_missing_side,
    _refinement_expansion,
    detect_cards,
    ordered_corners,
    perspective_crop,
    quadrilateral_iou,
    Detection,
    write_image,
)


def test_orders_corners_clockwise_from_top_left():
    shuffled = [[300, 400], [100, 200], [100, 400], [300, 200]]
    assert ordered_corners(shuffled).tolist() == [
        [100, 200],
        [300, 200],
        [300, 400],
        [100, 400],
    ]


def test_quadrilateral_iou():
    first = np.float32([[0, 0], [100, 0], [100, 50], [0, 50]])
    assert quadrilateral_iou(first, first) == 1.0
    shifted = first + [50, 0]
    assert abs(quadrilateral_iou(first, shifted) - 1 / 3) < 1e-6


def test_opposite_side_imbalance_rejects_a_tapered_non_card():
    balanced = np.float32([[0, 0], [100, 0], [100, 60], [0, 60]])
    tapered = np.float32([[0, 0], [100, 0], [80, 60], [45, 40]])

    assert _opposite_side_imbalance(balanced) == 1.0
    assert _opposite_side_imbalance(tapered) > 1.75


def test_perspective_crop_preserves_observed_size():
    image = np.full((500, 800, 3), 255, np.uint8)
    corners = np.float32(
        [[100, 100], [600, 120], [580, 420], [120, 400]]
    )
    cropped = perspective_crop(image, corners)
    assert 490 <= cropped.shape[1] <= 505
    assert 295 <= cropped.shape[0] <= 305


def test_dark_interior_fraction_separates_bright_and_dark_regions():
    corners = np.float32(
        [[20, 20], [180, 20], [180, 120], [20, 120]]
    )
    bright = np.full((140, 200, 3), 230, np.uint8)
    dark = np.full((140, 200, 3), 90, np.uint8)

    assert _dark_interior_fraction(bright, corners) == 0.0
    assert _dark_interior_fraction(dark, corners) == 1.0


def test_detects_synthetic_rotated_cards_once_each():
    photo = np.full((1200, 1600, 3), 180, np.uint8)
    cards = [
        ((350, 300), (420, 254), -8),
        ((1050, 300), (420, 254), 12),
        ((420, 850), (420, 254), 30),
    ]
    for rectangle in cards:
        corners = cv2.boxPoints(rectangle).astype(np.int32)
        cv2.fillPoly(photo, [corners], (245, 245, 245))
        cv2.polylines(photo, [corners], True, (30, 30, 30), 5)
    detections = detect_cards(photo)
    assert len(detections) == len(cards)


def test_candidate_selection_is_capped_at_twelve_cards():
    candidates = [
        _Candidate(
            np.float32(
                [
                    [i * 120, 0],
                    [i * 120 + 100, 0],
                    [i * 120 + 100, 60],
                    [i * 120, 60],
                ]
            ),
            0.90 - i * 0.01,
            "test",
            6000,
            1.0,
        )
        for i in range(13)
    ]

    selected = _consistent_card_scale(candidates)

    assert CARD_LIMIT == 12
    assert len(selected) == CARD_LIMIT


def test_large_bridge_does_not_merge_separate_cards():
    left = _Candidate(
        np.float32([[10, 10], [110, 10], [110, 70], [10, 70]]),
        0.95,
        "test",
        6000,
        1.0,
    )
    right = _Candidate(
        np.float32([[140, 10], [240, 10], [240, 70], [140, 70]]),
        0.94,
        "test",
        6000,
        1.0,
    )
    bridge = _Candidate(
        np.float32([[0, 0], [250, 0], [250, 80], [0, 80]]),
        0.50,
        "test",
        20000,
        0.2,
    )
    selected = _cluster_candidates([bridge, left, right])
    assert len(selected) == 2


def test_full_card_wins_over_a_higher_scoring_fragment():
    full = _Candidate(
        np.float32([[0, 0], [200, 0], [200, 120], [0, 120]]),
        0.718,
        "edge-close-5",
        24000,
        0.4,
    )
    fragment = _Candidate(
        np.float32([[140, 0], [200, 0], [200, 120], [140, 120]]),
        0.795,
        "neutral-bright",
        7200,
        0.8,
    )

    selected = _cluster_candidates([fragment, full])
    assert len(selected) == 1
    assert selected[0] is full


def test_same_scale_line_candidate_can_recover_a_broken_card_edge():
    strong = _Candidate(
        np.float32([[10, 10], [110, 10], [110, 70], [10, 70]]),
        0.96,
        "edge-close-5",
        6000,
        1.0,
    )
    recovered = _Candidate(
        np.float32([[140, 10], [240, 10], [240, 70], [140, 70]]),
        0.62,
        "line-reconstruction",
        6100,
        1.0,
    )
    weak = _Candidate(
        np.float32([[270, 10], [370, 10], [370, 70], [270, 70]]),
        0.50,
        "line-reconstruction",
        5900,
        1.0,
    )

    selected = _consistent_card_scale([strong, recovered, weak])

    assert selected == [strong, recovered]


def test_single_edge_recovery_requires_a_clear_card_boundary():
    baseline = [
        _Candidate(
            np.float32(
                [[i * 140, 0], [i * 140 + 100, 0],
                 [i * 140 + 100, 60], [i * 140, 60]]
            ),
            0.95,
            "test",
            6000,
            1.0,
        )
        for i in range(3)
    ]
    weak_boundary = _Candidate(
        np.float32([[420, 0], [520, 0], [520, 60], [420, 60]]),
        0.99,
        "single-edge-reconstruction",
        6000,
        0.66,
    )
    clear_boundary = _Candidate(
        weak_boundary.corners,
        0.99,
        "single-edge-reconstruction",
        6000,
        0.70,
    )
    second_clear_boundary = _Candidate(
        np.float32([[560, 0], [660, 0], [660, 60], [560, 60]]),
        0.98,
        "single-edge-reconstruction",
        6000,
        0.75,
    )

    assert _merge_single_edge_candidates(baseline, [weak_boundary]) == baseline
    assert _merge_single_edge_candidates(
        baseline, [clear_boundary, second_clear_boundary]
    ) == (
        baseline + [clear_boundary]
    )


def test_low_contrast_consensus_can_add_multiple_missing_cards():
    baseline = [
        _Candidate(
            np.float32(
                [[i * 140, 0], [i * 140 + 100, 0],
                 [i * 140 + 100, 60], [i * 140, 60]]
            ),
            0.95,
            "test",
            6000,
            1.0,
        )
        for i in range(3)
    ]
    recovered_corners = [
        [[420, 0], [520, 0], [520, 60], [420, 60]],
        [[280, 100], [380, 100], [380, 160], [280, 160]],
    ]
    recovered = [
        _Candidate(
            np.float32(corners),
            0.82,
            "low-contrast-single-edge-reconstruction",
            6000,
            0.20,
        )
        for corners in recovered_corners
    ]

    assert _merge_single_edge_candidates(
        baseline, recovered
    ) == baseline + recovered


def test_low_contrast_projection_cannot_reuse_an_existing_edge():
    baseline = [
        _Candidate(
            np.float32(
                [[i * 140, 0], [i * 140 + 100, 0],
                 [i * 140 + 100, 60], [i * 140, 60]]
            ),
            0.95,
            "test",
            6000,
            1.0,
        )
        for i in range(3)
    ]
    projected = _Candidate(
        np.float32([[0, 60], [100, 60], [100, 120], [0, 120]]),
        0.90,
        "low-contrast-single-edge-reconstruction",
        6000,
        0.40,
    )

    assert _merge_single_edge_candidates(
        baseline, [projected]
    ) == baseline


def test_contained_partial_contour_is_removed():
    full = _Candidate(
        np.float32([[0, 0], [200, 0], [200, 120], [0, 120]]),
        0.72,
        "edge-close-5",
        24000,
        0.5,
    )
    fragment = _Candidate(
        np.float32([[60, 0], [200, 0], [200, 120], [60, 120]]),
        0.80,
        "edge-close-5",
        16800,
        0.7,
    )

    assert _remove_contained_fragments(
        [fragment, full]
    ) == [full]


def test_region_refinement_is_used_only_for_stable_area():
    original = _Candidate(
        np.float32([[0, 0], [100, 0], [100, 60], [0, 60]]),
        0.6,
        "line-reconstruction",
        6000,
        1.0,
    )
    stable = _Candidate(
        original.corners,
        0.6,
        "line-reconstruction+region-refine",
        6300,
        1.0,
    )
    expanded = _Candidate(
        original.corners,
        0.6,
        "line-reconstruction+region-refine",
        7500,
        1.0,
    )

    assert _prefer_region_refinement(original, stable) is stable
    assert _prefer_region_refinement(original, expanded) is original


def test_stronger_alternative_does_not_replace_the_same_strategy():
    current = _Candidate(
        np.float32([[0, 0], [100, 0], [100, 60], [0, 60]]),
        0.60,
        "line-reconstruction",
        6000,
        0.5,
    )
    shifted_line = _Candidate(
        np.float32([[30, 0], [130, 0], [130, 60], [30, 60]]),
        0.75,
        "line-reconstruction",
        6000,
        0.5,
    )
    contour = _Candidate(
        shifted_line.corners,
        0.75,
        "edge-close-5",
        6000,
        0.5,
    )

    assert _replace_with_stronger_alternative(
        [current], [shifted_line]
    ) == [current]
    assert _replace_with_stronger_alternative(
        [current], [contour]
    ) == [contour]


def test_low_contrast_projection_replacement_must_restore_area():
    current = _Candidate(
        np.float32([[0, 0], [100, 0], [100, 60], [0, 60]]),
        0.80,
        "low-contrast-single-edge-reconstruction",
        6000,
        0.2,
    )
    references = [
        _Candidate(
            np.float32([[x, 0], [x + 100, 0], [x + 100, 60], [x, 60]]),
            0.90,
            "edge-close-5",
            6000,
            0.8,
        )
        for x in (300, 500)
    ]
    same_area = _Candidate(
        np.float32([[30, 0], [130, 0], [130, 60], [30, 60]]),
        0.70,
        "line-reconstruction",
        6000,
        0.4,
    )
    restored_area = _Candidate(
        np.float32([[20, 0], [140, 0], [140, 60], [20, 60]]),
        0.70,
        "line-reconstruction",
        7200,
        0.4,
    )
    edges = np.zeros((200, 800), np.uint8)
    lab = np.zeros((200, 800, 3), np.uint8)

    selected = [current] + references
    assert _replace_low_contrast_projection(
        edges, lab, selected, [same_area]
    ) == selected
    assert _replace_low_contrast_projection(
        edges, lab, selected, [restored_area]
    )[0] is restored_area


def test_inset_corner_repair_is_limited_to_multi_card_scenes():
    clipped = _Candidate(
        np.float32(
            [
                [186.5, 343.1],
                [1246.5, 373.8],
                [1295.2, 1787.2],
                [457.9, 1743.7],
            ]
        ),
        0.66,
        "line-reconstruction+region-refine-1.45-0.52",
        1_328_853,
        0.9,
    )

    assert _repair_clipped_corner(clipped, 1536, 2048) is clipped
    repaired = _repair_clipped_corner(
        clipped, 1536, 2048, allow_inset_repair=True
    )
    assert repaired.strategy.endswith("+corner-repair")


def test_centered_large_card_suppresses_overlapping_frame_line():
    image = np.full((800, 1000, 3), 180, np.uint8)
    edges = np.zeros(image.shape[:2], np.uint8)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    frame_line = _Candidate(
        np.float32([[100, 0], [900, 0], [900, 300], [100, 300]]),
        0.55,
        "line-reconstruction",
        240000,
        0.5,
    )
    centered_card = _Candidate(
        np.float32([[100, 260], [900, 260], [900, 740], [100, 740]]),
        0.80,
        "color-kmeans+region-refine-1.45-0.52",
        384000,
        0.9,
    )

    selected = _arbitrate_large_center_card(
        image, edges, lab, [frame_line, centered_card]
    )

    assert selected == [centered_card]


def test_center_seed_does_not_merge_two_off_center_cards():
    image = np.full((800, 1000, 3), 180, np.uint8)
    edges = np.zeros(image.shape[:2], np.uint8)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    upper = _Candidate(
        np.float32([[100, 80], [900, 80], [900, 350], [100, 350]]),
        0.80,
        "edge-close-5",
        216000,
        0.9,
    )
    lower = _Candidate(
        np.float32([[100, 450], [900, 450], [900, 720], [100, 720]]),
        0.79,
        "edge-close-5",
        216000,
        0.9,
    )

    selected = _arbitrate_large_center_card(
        image, edges, lab, [upper, lower]
    )

    assert selected == [upper, lower]


def test_partial_refinement_restores_only_the_missing_side():
    lab = np.full((180, 220, 3), [50, 128, 128], np.uint8)
    lab[40:101, 10:141] = [200, 128, 128]
    candidate = _Candidate(
        np.float32([[40, 40], [140, 40], [140, 100], [40, 100]]),
        0.8,
        "partial-side-reconstruction+region-refine-1.15-0.52",
        6000,
        0.6,
    )
    references = [
        _Candidate(
            np.float32(
                [[20, y], [150, y], [150, y + 60], [20, y + 60]]
            ),
            0.9,
            "test",
            7800,
            1.0,
        )
        for y in (0, 60, 120)
    ]

    restored = _restore_partial_missing_side(lab, candidate, references)

    assert restored.strategy.endswith("+missing-side-restore")
    assert 10 <= restored.corners[:, 0].min() <= 20
    assert restored.corners[:, 0].max() == 140


def test_color_candidate_can_replace_or_add_without_weak_false_positive():
    baseline = _Candidate(
        np.float32([[0, 0], [100, 0], [100, 60], [0, 60]]),
        0.55,
        "line-reconstruction",
        6000,
        1.0,
    )
    replacement = _Candidate(
        np.float32([[2, 2], [102, 2], [102, 62], [2, 62]]),
        0.75,
        "color-kmeans",
        6000,
        1.0,
    )
    added = _Candidate(
        np.float32([[140, 0], [240, 0], [240, 60], [140, 60]]),
        0.78,
        "color-kmeans",
        6100,
        1.0,
    )
    weak = _Candidate(
        np.float32([[280, 0], [380, 0], [380, 60], [280, 60]]),
        0.66,
        "color-kmeans",
        6000,
        1.0,
    )

    merged = _merge_color_candidates(
        [baseline], [replacement, added, weak]
    )

    assert merged == [replacement, added]


def test_color_refinement_expands_small_or_low_contrast_regions_more():
    corners = np.float32([[0, 0], [100, 0], [100, 60], [0, 60]])
    small = _Candidate(
        corners, 0.7, "color-kmeans", 1700, 0.8
    )
    low_contrast = _Candidate(
        corners, 0.7, "color-kmeans", 2500, 0.2
    )
    ordinary = _Candidate(
        corners, 0.7, "color-kmeans", 2500, 0.8
    )

    assert _refinement_expansion(small, 10_000) == 1.65
    assert _refinement_expansion(low_contrast, 10_000) == 1.52
    assert _refinement_expansion(ordinary, 10_000) == 1.45


def test_repairs_one_corner_clipped_by_an_occluder():
    clipped = _Candidate(
        np.float32(
            [[2352, 444], [2724, 239], [3173, 1111], [1836, 1846]]
        ),
        0.8,
        "neutral-bright",
        1_000_000,
        1.0,
    )

    repaired = _repair_clipped_corner(clipped, 4284, 5712)

    assert repaired.strategy.endswith("+corner-repair")
    assert np.linalg.norm(repaired.corners[0] - [1387, 974]) < 2


def test_reference_dimensions_ignore_card_rotation():
    horizontal = _Candidate(
        np.float32([[0, 0], [165, 0], [165, 100], [0, 100]]),
        0.9,
        "test",
        16_500,
        1.0,
    )
    vertical = _Candidate(
        np.float32([[300, 0], [400, 0], [400, 165], [300, 165]]),
        0.9,
        "test",
        16_500,
        1.0,
    )

    long_edge, short_edge, area = _reference_card_dimensions(
        [horizontal, vertical]
    )

    assert long_edge == 165
    assert short_edge == 100
    assert area == 16_500


def test_original_contour_wins_when_recovery_becomes_a_duplicate():
    original = _Candidate(
        np.float32([[0, 0], [165, 0], [165, 100], [0, 100]]),
        0.8,
        "neutral-bright+corner-repair",
        16_500,
        0.8,
    )
    duplicate = _Candidate(
        np.float32([[20, 0], [185, 0], [185, 100], [20, 100]]),
        0.99,
        "single-edge-reconstruction",
        16_500,
        0.8,
    )

    assert _remove_reconstruction_duplicates([duplicate, original]) == [
        original
    ]


def test_reprocessing_replaces_stale_cards_on_detection_failure(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.png"
    output = tmp_path / "output"
    write_image(source, np.full((400, 700, 3), 255, np.uint8))
    detection = Detection(
        np.float32([[50, 50], [650, 50], [650, 350], [50, 350]]),
        1.0,
        "test",
        1.0,
        1.0,
    )
    monkeypatch.setattr(bcpickup, "detect_cards", lambda image: [detection])
    first = process_image(source, output)
    target = output / "source"
    assert first["status"] == "detected"
    assert (target / "card01.png").exists()
    (target / "stale.txt").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(bcpickup, "detect_cards", lambda image: [])
    second = process_image(source, output)
    assert second["status"] == "detection_failed"
    assert not list(target.glob("card*.png"))
    assert not (target / "stale.txt").exists()
    saved = json.loads((target / "result.json").read_text(encoding="utf-8"))
    assert saved["status"] == "detection_failed"
    assert saved["cards"] == []
