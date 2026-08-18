from __future__ import annotations

from dataclasses import dataclass
from math import exp, log
from pathlib import Path

import cv2
import numpy as np


DETECTOR_VERSION = "opencv-multipass-v30"
CARD_ASPECT = 91 / 55
CARD_ASPECT_MIN = 1.20
CARD_ASPECT_MAX = 2.35
CARD_AREA_MIN_RATIO = 0.006
CARD_AREA_MAX_RATIO = 0.65
CARD_LIMIT = 12
MAX_WORKING_EDGE = 2200
MIN_CANDIDATE_SCORE = 0.35
SINGLE_EDGE_MIN_CONTRAST = 0.68
MAX_OPPOSITE_SIDE_IMBALANCE = 1.75
CORNER_REPAIR_MIN_IMBALANCE = 2.20


@dataclass(frozen=True)
class Detection:
    corners: np.ndarray
    confidence: float
    strategy: str
    score: float
    contrast: float


@dataclass(frozen=True)
class _Candidate:
    corners: np.ndarray
    score: float
    strategy: str
    area: float
    contrast: float


@dataclass(frozen=True)
class _Line:
    start: np.ndarray
    end: np.ndarray
    direction: np.ndarray
    angle: float
    length: float


def read_image(path: Path) -> np.ndarray:
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"画像を読み込めません: {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    extension = path.suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg"}:
        extension = ".png"
    params = (
        [cv2.IMWRITE_PNG_COMPRESSION, 1]
        if extension == ".png"
        else [cv2.IMWRITE_JPEG_QUALITY, 92]
    )
    ok, encoded = cv2.imencode(extension, image, params)
    if not ok:
        raise ValueError(f"画像をエンコードできません: {path}")
    encoded.tofile(path)


def ordered_corners(corners: np.ndarray | list[list[float]]) -> np.ndarray:
    points = np.float32(corners).reshape(4, 2)
    center = points.mean(axis=0)
    clockwise = points[
        np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))
    ]
    top_left = int(np.argmin(clockwise.sum(axis=1)))
    return np.float32(np.roll(clockwise, -top_left, axis=0))


def perspective_crop(
    image: np.ndarray, corners: np.ndarray | list[list[float]]
) -> np.ndarray:
    points = ordered_corners(corners)
    widths = [
        np.linalg.norm(points[1] - points[0]),
        np.linalg.norm(points[2] - points[3]),
    ]
    heights = [
        np.linalg.norm(points[3] - points[0]),
        np.linalg.norm(points[2] - points[1]),
    ]
    output_width = max(1, round(max(widths)))
    output_height = max(1, round(max(heights)))
    destination = np.float32(
        [
            [0, 0],
            [output_width - 1, 0],
            [output_width - 1, output_height - 1],
            [0, output_height - 1],
        ]
    )
    transform = cv2.getPerspectiveTransform(points, destination)
    return cv2.warpPerspective(
        image,
        transform,
        (output_width, output_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def quadrilateral_iou(first: np.ndarray, second: np.ndarray) -> float:
    a = ordered_corners(first)
    b = ordered_corners(second)
    area_a = abs(float(cv2.contourArea(a)))
    area_b = abs(float(cv2.contourArea(b)))
    if area_a <= 0 or area_b <= 0:
        return 0.0
    intersection, _ = cv2.intersectConvexConvex(a, b)
    union = area_a + area_b - float(intersection)
    return float(intersection) / union if union > 0 else 0.0


def _containment(first: np.ndarray, second: np.ndarray) -> float:
    a = ordered_corners(first)
    b = ordered_corners(second)
    area_a = abs(float(cv2.contourArea(a)))
    area_b = abs(float(cv2.contourArea(b)))
    if area_a <= 0 or area_b <= 0:
        return 0.0
    intersection, _ = cv2.intersectConvexConvex(a, b)
    return float(intersection) / min(area_a, area_b)


def _edge_support(edges: np.ndarray, quad: np.ndarray) -> float:
    x, y, width, height = cv2.boundingRect(np.int32(np.round(quad)))
    padding = 9
    left = max(0, x - padding)
    top = max(0, y - padding)
    right = min(edges.shape[1], x + width + padding)
    bottom = min(edges.shape[0], y + height + padding)
    if right <= left or bottom <= top:
        return 0.0
    region = edges[top:bottom, left:right]
    shifted = np.int32(np.round(quad - [left, top]))
    line = np.zeros(region.shape, np.uint8)
    cv2.polylines(line, [shifted], True, 255, 3, cv2.LINE_AA)
    band = cv2.dilate(line, np.ones((5, 5), np.uint8))
    pixels = cv2.countNonZero(band)
    return cv2.countNonZero(cv2.bitwise_and(region, band)) / max(1, pixels)


def _segment_edge_support(
    edges: np.ndarray, start: np.ndarray, end: np.ndarray
) -> float:
    points = np.int32(np.round(np.float32([start, end])))
    x, y, width, height = cv2.boundingRect(points)
    padding = 9
    left = max(0, x - padding)
    top = max(0, y - padding)
    right = min(edges.shape[1], x + width + padding)
    bottom = min(edges.shape[0], y + height + padding)
    if right <= left or bottom <= top:
        return 0.0
    region = edges[top:bottom, left:right]
    shifted = points - [left, top]
    line = np.zeros(region.shape, np.uint8)
    cv2.line(
        line,
        tuple(shifted[0]),
        tuple(shifted[1]),
        255,
        3,
        cv2.LINE_AA,
    )
    band = cv2.dilate(line, np.ones((5, 5), np.uint8))
    pixels = cv2.countNonZero(band)
    return cv2.countNonZero(cv2.bitwise_and(region, band)) / max(1, pixels)


def _segment_color_contrast(
    lab: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
    inside_point: np.ndarray,
) -> float:
    direction = np.float32(end - start)
    length = float(np.linalg.norm(direction))
    if length < 1.0:
        return 0.0
    direction /= length
    normal = np.float32([-direction[1], direction[0]])
    midpoint = 0.5 * (start + end)
    if float(np.dot(inside_point - midpoint, normal)) < 0:
        normal = -normal
    offset = max(3, min(12, round(length * 0.02)))
    thickness = max(4, 2 * offset - 2)
    inside = np.zeros(lab.shape[:2], np.uint8)
    outside = np.zeros(lab.shape[:2], np.uint8)
    cv2.line(
        inside,
        tuple(np.int32(np.round(start + normal * offset))),
        tuple(np.int32(np.round(end + normal * offset))),
        255,
        thickness,
        cv2.LINE_AA,
    )
    cv2.line(
        outside,
        tuple(np.int32(np.round(start - normal * offset))),
        tuple(np.int32(np.round(end - normal * offset))),
        255,
        thickness,
        cv2.LINE_AA,
    )
    if cv2.countNonZero(inside) == 0 or cv2.countNonZero(outside) == 0:
        return 0.0
    inside_mean = np.float32(cv2.mean(lab, mask=inside)[:3])
    outside_mean = np.float32(cv2.mean(lab, mask=outside)[:3])
    return min(2.0, float(np.linalg.norm(inside_mean - outside_mean)) / 60.0)


def _region_contrast(lab: np.ndarray, quad: np.ndarray) -> float:
    x, y, width, height = cv2.boundingRect(np.int32(np.round(quad)))
    (_, _), (rect_width, rect_height), _ = cv2.minAreaRect(quad)
    band_width = max(5, min(35, round(min(rect_width, rect_height) * 0.08)))
    left = max(0, x - band_width)
    top = max(0, y - band_width)
    right = min(lab.shape[1], x + width + band_width)
    bottom = min(lab.shape[0], y + height + band_width)
    region = lab[top:bottom, left:right]
    shifted_float = np.float32(quad - [left, top])
    sample_scale = min(
        1.0,
        280.0 / max(1.0, float(max(region.shape[:2]))),
    )
    if sample_scale < 1.0:
        region = cv2.resize(
            region,
            (
                max(1, round(region.shape[1] * sample_scale)),
                max(1, round(region.shape[0] * sample_scale)),
            ),
            interpolation=cv2.INTER_AREA,
        )
        shifted_float *= sample_scale
        band_width = max(2, round(band_width * sample_scale))
    shifted = np.int32(np.round(shifted_float))
    inside = np.zeros(region.shape[:2], np.uint8)
    cv2.fillConvexPoly(inside, shifted, 255)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * band_width + 1, 2 * band_width + 1)
    )
    inner = cv2.erode(inside, kernel)
    outer = cv2.subtract(cv2.dilate(inside, kernel), inside)
    if cv2.countNonZero(inner) == 0 or cv2.countNonZero(outer) == 0:
        return 0.0
    inner_mean = np.float32(cv2.mean(region, mask=inner)[:3])
    outer_mean = np.float32(cv2.mean(region, mask=outer)[:3])
    difference = inner_mean - outer_mean
    distance = float(
        np.sqrt(
            (difference[0] / 80.0) ** 2
            + (difference[1] / 55.0) ** 2
            + (difference[2] / 55.0) ** 2
        )
    )
    return min(1.0, distance)


def _quad_from_contour(contour: np.ndarray) -> tuple[np.ndarray, bool]:
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    for epsilon in (0.01, 0.015, 0.02, 0.03, 0.04):
        approx = cv2.approxPolyDP(hull, epsilon * perimeter, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return ordered_corners(approx.reshape(4, 2)), True
    return ordered_corners(cv2.boxPoints(cv2.minAreaRect(hull))), False


def _candidate_from_contour(
    contour: np.ndarray,
    edge_reference: np.ndarray,
    lab: np.ndarray,
    photo_area: float,
    image_width: int,
    image_height: int,
    strategy: str,
) -> _Candidate | None:
    contour_area = abs(float(cv2.contourArea(contour)))
    if not CARD_AREA_MIN_RATIO * photo_area <= contour_area <= CARD_AREA_MAX_RATIO * photo_area:
        return None

    quad, approximated = _quad_from_contour(contour)
    if np.any(quad[:, 0] <= 1) or np.any(quad[:, 1] <= 1):
        return None
    if np.any(quad[:, 0] >= image_width - 2) or np.any(
        quad[:, 1] >= image_height - 2
    ):
        return None

    quad_area = abs(float(cv2.contourArea(quad)))
    if not CARD_AREA_MIN_RATIO * photo_area <= quad_area <= CARD_AREA_MAX_RATIO * photo_area:
        return None

    (_, _), (rect_width, rect_height), _ = cv2.minAreaRect(quad)
    short_edge, long_edge = min(rect_width, rect_height), max(rect_width, rect_height)
    if short_edge <= 0:
        return None
    aspect = long_edge / short_edge
    if not CARD_ASPECT_MIN <= aspect <= CARD_ASPECT_MAX:
        return None

    rectangularity = min(1.0, contour_area / max(1.0, quad_area))
    aspect_score = exp(-abs(log(aspect / CARD_ASPECT)) / 0.38)
    edge_score = min(1.0, _edge_support(edge_reference, quad) * 3.2)
    contrast = _region_contrast(lab, quad)
    approximation_bonus = 0.08 if approximated else 0.0
    shape_score = (
        0.42 * aspect_score
        + 0.32 * rectangularity
        + 0.26 * edge_score
        + approximation_bonus
    )
    score = shape_score * (0.65 + 0.35 * contrast) + 0.08 * contrast
    return _Candidate(
        quad,
        min(1.0, score),
        strategy,
        quad_area,
        contrast,
    )


def _angle_difference(first: float, second: float) -> float:
    difference = abs(first - second) % np.pi
    return min(difference, np.pi - difference)


def _line_intersection(first: _Line, second: _Line) -> np.ndarray | None:
    cross = float(
        first.direction[0] * second.direction[1]
        - first.direction[1] * second.direction[0]
    )
    if abs(cross) < 1e-5:
        return None
    offset = second.start - first.start
    distance = float(
        (
            offset[0] * second.direction[1]
            - offset[1] * second.direction[0]
        )
        / cross
    )
    return first.start + distance * first.direction


def _long_line_segments(image: np.ndarray) -> list[_Line]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    detector = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    minimum_length = min(image.shape[:2]) * 0.055
    lines = []
    detected = detector.detect(gray)[0]
    raw_lines = list(detected.reshape(-1, 4)) if detected is not None else []
    for raw in raw_lines:
        start = np.float32(raw[:2])
        end = np.float32(raw[2:])
        vector = end - start
        length = float(np.linalg.norm(vector))
        if length < minimum_length:
            continue
        direction = vector / length
        angle = float(np.arctan2(direction[1], direction[0]) % np.pi)
        lines.append(_Line(start, end, direction, angle, length))
    lines.sort(key=lambda line: line.length, reverse=True)

    unique: list[_Line] = []
    for line in lines:
        midpoint = (line.start + line.end) * 0.5
        duplicate = False
        for kept in unique:
            if _angle_difference(line.angle, kept.angle) > np.deg2rad(2.5):
                continue
            normal = np.float32([-kept.direction[1], kept.direction[0]])
            kept_midpoint = (kept.start + kept.end) * 0.5
            if abs(float(np.dot(midpoint - kept_midpoint, normal))) <= 7:
                duplicate = True
                break
        if not duplicate:
            unique.append(line)
        if len(unique) >= 90:
            break
    return unique


def _parallel_line_pairs(
    lines: list[_Line], image_width: int, image_height: int
) -> list[tuple[_Line, _Line, float, np.ndarray]]:
    minimum_separation = min(image_width, image_height) * 0.045
    maximum_separation = max(image_width, image_height) * 0.68
    pairs = []
    for index, first in enumerate(lines):
        for second in lines[index + 1:]:
            difference = _angle_difference(first.angle, second.angle)
            if difference > np.deg2rad(11):
                continue
            second_direction = second.direction
            if float(np.dot(first.direction, second_direction)) < 0:
                second_direction = -second_direction
            direction = first.direction + second_direction
            norm = float(np.linalg.norm(direction))
            if norm < 1e-5:
                continue
            direction = direction / norm
            normal = np.float32([-direction[1], direction[0]])
            first_midpoint = (first.start + first.end) * 0.5
            second_midpoint = (second.start + second.end) * 0.5
            separation = abs(
                float(np.dot(second_midpoint - first_midpoint, normal))
            )
            if not minimum_separation <= separation <= maximum_separation:
                continue
            first_projection = sorted(
                [float(np.dot(first.start, direction)), float(np.dot(first.end, direction))]
            )
            second_projection = sorted(
                [float(np.dot(second.start, direction)), float(np.dot(second.end, direction))]
            )
            overlap = max(
                0.0,
                min(first_projection[1], second_projection[1])
                - max(first_projection[0], second_projection[0]),
            )
            overlap_ratio = overlap / max(
                1.0, min(first.length, second.length)
            )
            if overlap_ratio < 0.22:
                continue
            alignment = np.exp(-difference / np.deg2rad(7))
            score = (
                first.length + second.length
            ) * (0.45 + 0.35 * min(1.0, overlap_ratio) + 0.20 * alignment)
            pairs.append((first, second, float(score), direction))
    pairs.sort(key=lambda pair: pair[2], reverse=True)
    return pairs[:100]


def _line_candidates(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    minimum_score: float | None = None,
) -> list[_Candidate]:
    height, width = image.shape[:2]
    photo_area = float(width * height)
    lines = _long_line_segments(image)
    pairs = _parallel_line_pairs(lines, width, height)
    geometric_candidates = []
    for pair_index, first_pair in enumerate(pairs):
        first_a, first_b, first_score, first_direction = first_pair
        for second_pair in pairs[pair_index + 1:]:
            second_a, second_b, second_score, second_direction = second_pair
            angle = _angle_difference(
                float(np.arctan2(first_direction[1], first_direction[0]) % np.pi),
                float(np.arctan2(second_direction[1], second_direction[0]) % np.pi),
            )
            if not np.deg2rad(50) <= angle <= np.deg2rad(130):
                continue
            intersections = [
                _line_intersection(first_a, second_a),
                _line_intersection(first_b, second_a),
                _line_intersection(first_b, second_b),
                _line_intersection(first_a, second_b),
            ]
            if any(point is None for point in intersections):
                continue
            quad = ordered_corners(np.float32(intersections))
            margin_x = width * 0.035
            margin_y = height * 0.035
            if (
                np.any(quad[:, 0] < -margin_x)
                or np.any(quad[:, 0] > width - 1 + margin_x)
                or np.any(quad[:, 1] < -margin_y)
                or np.any(quad[:, 1] > height - 1 + margin_y)
            ):
                continue
            quad[:, 0] = np.clip(quad[:, 0], 0, width - 1)
            quad[:, 1] = np.clip(quad[:, 1], 0, height - 1)
            area = abs(float(cv2.contourArea(quad)))
            if not CARD_AREA_MIN_RATIO * photo_area <= area <= CARD_AREA_MAX_RATIO * photo_area:
                continue
            (_, _), (rect_width, rect_height), _ = cv2.minAreaRect(quad)
            short_edge, long_edge = min(rect_width, rect_height), max(rect_width, rect_height)
            if short_edge <= 0:
                continue
            aspect = long_edge / short_edge
            if not CARD_ASPECT_MIN <= aspect <= CARD_ASPECT_MAX:
                continue
            side_lengths = [
                float(np.linalg.norm(quad[(index + 1) % 4] - quad[index]))
                for index in range(4)
            ]
            if (
                max(side_lengths[0], side_lengths[2])
                / max(1.0, min(side_lengths[0], side_lengths[2]))
                > 1.75
                or max(side_lengths[1], side_lengths[3])
                / max(1.0, min(side_lengths[1], side_lengths[3]))
                > 1.75
            ):
                continue
            aspect_score = exp(-abs(log(aspect / CARD_ASPECT)) / 0.42)
            perimeter = max(1.0, sum(side_lengths))
            visible = min(
                1.0,
                (
                    first_a.length
                    + first_b.length
                    + second_a.length
                    + second_b.length
                )
                / perimeter,
            )
            pair_strength = min(
                1.0,
                (first_score + second_score) / max(1.0, perimeter * 1.4),
            )
            cheap_score = (
                0.56 * aspect_score
                + 0.24 * visible
                + 0.20 * pair_strength
            )
            geometric_candidates.append(
                (
                    cheap_score,
                    quad,
                    area,
                    aspect_score,
                    visible,
                    pair_strength,
                )
            )

    geometric_candidates.sort(key=lambda item: item[0], reverse=True)
    unique_geometry = []
    for geometry in geometric_candidates:
        quad = geometry[1]
        if any(
            quadrilateral_iou(quad, kept[1]) >= 0.82
            for kept in unique_geometry
        ):
            continue
        unique_geometry.append(geometry)
        if len(unique_geometry) >= 80:
            break

    candidates = []
    for (
        _,
        quad,
        area,
        aspect_score,
        visible,
        pair_strength,
    ) in unique_geometry:
        edge_score = min(1.0, _edge_support(edges, quad) * 3.4)
        contrast = _region_contrast(lab, quad)
        score = (
            0.34 * aspect_score
            + 0.30 * edge_score
            + 0.14 * contrast
            + 0.12 * visible
            + 0.10 * pair_strength
        )
        threshold = (
            MIN_CANDIDATE_SCORE + 0.08
            if minimum_score is None
            else minimum_score
        )
        if score >= threshold:
            candidates.append(
                _Candidate(
                    quad,
                    min(1.0, score),
                    "line-reconstruction",
                    area,
                    contrast,
                )
            )
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates[:180]


def _refine_card_region(
    image: np.ndarray,
    candidate: _Candidate,
    expansion: float = 1.45,
    inner_scale: float = 0.52,
) -> _Candidate | None:
    points = ordered_corners(candidate.corners)
    center = points.mean(axis=0)
    expanded = center + (points - center) * expansion
    expanded[:, 0] = np.clip(expanded[:, 0], 0, image.shape[1] - 1)
    expanded[:, 1] = np.clip(expanded[:, 1], 0, image.shape[0] - 1)
    x, y, width, height = cv2.boundingRect(np.int32(np.round(expanded)))
    if width < 20 or height < 20:
        return None
    region = image[y:y + height, x:x + width]
    scale = min(1.0, 760.0 / max(region.shape[:2]))
    sampled = (
        cv2.resize(
            region,
            (
                max(1, round(region.shape[1] * scale)),
                max(1, round(region.shape[0] * scale)),
            ),
            interpolation=cv2.INTER_AREA,
        )
        if scale < 1.0
        else region
    )
    local_points = (points - [x, y]) * scale
    local_center = local_points.mean(axis=0)
    local_expanded = (expanded - [x, y]) * scale
    local_inner = local_center + (
        local_points - local_center
    ) * inner_scale
    mask = np.full(sampled.shape[:2], cv2.GC_BGD, np.uint8)
    cv2.fillConvexPoly(
        mask, np.int32(np.round(local_expanded)), cv2.GC_PR_BGD
    )
    cv2.fillConvexPoly(
        mask, np.int32(np.round(local_points)), cv2.GC_PR_FGD
    )
    cv2.fillConvexPoly(
        mask, np.int32(np.round(local_inner)), cv2.GC_FGD
    )
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    try:
        cv2.setRNGSeed(0)
        cv2.grabCut(
            sampled,
            mask,
            None,
            background,
            foreground,
            3,
            cv2.GC_INIT_WITH_MASK,
        )
    except cv2.error:
        return None
    foreground_mask = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)
    kernel_size = max(3, round(min(sampled.shape[:2]) * 0.012))
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
    )
    foreground_mask = cv2.morphologyEx(
        foreground_mask, cv2.MORPH_CLOSE, kernel
    )
    contours, _ = cv2.findContours(
        foreground_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    seed = tuple(np.float32(local_center))
    containing = [
        contour
        for contour in contours
        if cv2.pointPolygonTest(contour, seed, False) >= 0
    ]
    contour = max(
        containing or contours,
        key=lambda value: abs(float(cv2.contourArea(value))),
    )
    refined, _ = _quad_from_contour(contour)
    refined = refined / scale + [x, y]
    refined = ordered_corners(refined)
    original_area = abs(float(cv2.contourArea(points)))
    refined_area = abs(float(cv2.contourArea(refined)))
    if not 0.72 * original_area <= refined_area <= 2.15 * original_area:
        return None
    (_, _), (rect_width, rect_height), _ = cv2.minAreaRect(refined)
    if min(rect_width, rect_height) <= 0:
        return None
    aspect = max(rect_width, rect_height) / min(rect_width, rect_height)
    if not CARD_ASPECT_MIN <= aspect <= CARD_ASPECT_MAX:
        return None
    return _Candidate(
        np.float32(refined),
        candidate.score,
        (
            f"{candidate.strategy}+region-refine"
            f"-{expansion:.2f}-{inner_scale:.2f}"
        ),
        refined_area,
        candidate.contrast,
    )


def _center_seeded_large_card_candidate(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
) -> _Candidate | None:
    """中心を覆う大きな1枚を、通常候補とは独立して探索する。"""
    height, width = image.shape[:2]
    photo_area = float(width * height)
    center = np.float32([width * 0.5, height * 0.5])
    candidates: list[_Candidate] = []

    # 横長・縦長の両方を試す。GrabCut の確実な前景は中央だけに置き、
    # カード内の文字やロゴのエッジで探索が止まらないようにする。
    for horizontal in (True, False):
        if horizontal:
            seed_width = width * 0.82
            seed_height = seed_width / CARD_ASPECT
            if seed_height > height * 0.64:
                seed_height = height * 0.64
                seed_width = seed_height * CARD_ASPECT
        else:
            seed_height = height * 0.72
            seed_width = seed_height / CARD_ASPECT
            if seed_width > width * 0.64:
                seed_width = width * 0.64
                seed_height = seed_width * CARD_ASPECT
        seed = ordered_corners(
            np.float32(
                [
                    center + [-seed_width / 2, -seed_height / 2],
                    center + [seed_width / 2, -seed_height / 2],
                    center + [seed_width / 2, seed_height / 2],
                    center + [-seed_width / 2, seed_height / 2],
                ]
            )
        )
        seed_area = abs(float(cv2.contourArea(seed)))
        initial = _Candidate(
            seed,
            0.70,
            "center-seeded",
            seed_area,
            _region_contrast(lab, seed),
        )
        refined = _refine_card_region(
            image,
            initial,
            expansion=1.45,
            inner_scale=0.30,
        )
        if refined is None:
            continue
        rescored = _candidate_from_contour(
            np.float32(refined.corners).reshape(-1, 1, 2),
            edges,
            lab,
            photo_area,
            width,
            height,
            "center-seeded",
        )
        if rescored is None:
            continue
        area_ratio = rescored.area / photo_area
        if area_ratio < 0.12:
            continue
        if cv2.pointPolygonTest(
            np.float32(rescored.corners), tuple(center), False
        ) < 0:
            continue
        candidates.append(rescored)
        boxed_corners = ordered_corners(
            cv2.boxPoints(cv2.minAreaRect(rescored.corners))
        )
        boxed = _candidate_from_contour(
            boxed_corners.reshape(-1, 1, 2),
            edges,
            lab,
            photo_area,
            width,
            height,
            "center-seeded+outer-box",
        )
        if (
            boxed is not None
            and boxed.area / photo_area >= 0.12
            and cv2.pointPolygonTest(
                np.float32(boxed.corners), tuple(center), False
            )
            >= 0
        ):
            candidates.append(boxed)

    if not candidates:
        return None
    return max(
        candidates,
        key=lambda candidate: (
            candidate.score,
            candidate.contrast,
            candidate.area,
        ),
    )


def _contains_image_center(
    candidate: _Candidate, image_width: int, image_height: int
) -> bool:
    center = (float(image_width) * 0.5, float(image_height) * 0.5)
    return (
        cv2.pointPolygonTest(
            np.float32(candidate.corners), center, False
        )
        >= 0
    )


def _touches_image_frame(
    candidate: _Candidate, image_width: int, image_height: int
) -> bool:
    points = ordered_corners(candidate.corners)
    margin = max(3.0, min(image_width, image_height) * 0.004)
    return bool(
        np.any(points[:, 0] <= margin)
        or np.any(points[:, 1] <= margin)
        or np.any(points[:, 0] >= image_width - 1 - margin)
        or np.any(points[:, 1] >= image_height - 1 - margin)
    )


def _arbitrate_large_center_card(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    selected: list[_Candidate],
) -> list[_Candidate]:
    """通常経路と中央起点の1枚仮説を、検出後に比較する。"""
    if len(selected) > 2:
        return selected
    height, width = image.shape[:2]
    photo_area = float(width * height)
    minimum_large_area = photo_area * 0.12
    centered = [
        candidate
        for candidate in selected
        if candidate.area >= minimum_large_area
        and _contains_image_center(candidate, width, height)
    ]

    generated: _Candidate | None = None
    if len(selected) <= 1:
        generated = _center_seeded_large_card_candidate(
            image, edges, lab
        )
        if generated is not None:
            if generated.score < 0.80:
                generated = _prefer_region_refinement(
                    generated,
                    _refine_card_region(
                        image,
                        generated,
                        expansion=1.45,
                        inner_scale=0.52,
                    ),
                )
            current_anchor = (
                max(centered, key=lambda candidate: candidate.score)
                if centered
                else None
            )
            if (
                current_anchor is not None
                and generated.score >= 0.80
                and generated.score >= current_anchor.score + 0.10
                and quadrilateral_iou(
                    generated.corners, current_anchor.corners
                )
                >= 0.30
            ):
                selected = [generated]
                centered = [generated]
            elif current_anchor is not None:
                generated = None

        if generated is not None and not centered:
            # 既存の唯一候補が、中央を外したフレーム接触の線復元なら、
            # 背景の机やPC面を拾った可能性が高い。
            if (
                len(selected) == 1
                and selected[0].strategy.startswith("line-reconstruction")
                and _touches_image_frame(selected[0], width, height)
                and not _contains_image_center(selected[0], width, height)
            ):
                selected = [generated]
            else:
                selected = [
                    candidate
                    for candidate in selected
                    if quadrilateral_iou(
                        candidate.corners, generated.corners
                    )
                    < 0.28
                    and _containment(
                        candidate.corners, generated.corners
                    )
                    < 0.72
                ]
                selected.append(generated)
            centered = [generated]

    if not centered:
        return selected
    anchor = max(
        centered,
        key=lambda candidate: (
            not _touches_image_frame(candidate, width, height),
            candidate.score,
            candidate.area,
        ),
    )
    if anchor.area < photo_area * 0.18:
        return selected

    filtered: list[_Candidate] = []
    for candidate in selected:
        if candidate is anchor:
            filtered.append(candidate)
            continue
        is_frame_line = (
            candidate.strategy.startswith("line-reconstruction")
            and _touches_image_frame(candidate, width, height)
            and not _contains_image_center(candidate, width, height)
        )
        overlap = quadrilateral_iou(
            candidate.corners, anchor.corners
        )
        if is_frame_line and overlap >= 0.025:
            continue
        if (
            anchor.strategy.startswith("center-seeded")
            and anchor.area >= photo_area * 0.22
            and candidate.area <= 0.45 * anchor.area
            and candidate.strategy.startswith("color-kmeans")
            and candidate.score < 0.80
        ):
            continue
        filtered.append(candidate)
    return filtered


def _color_region_candidates(
    image: np.ndarray, edges: np.ndarray, lab: np.ndarray
) -> list[_Candidate]:
    height, width = image.shape[:2]
    scale = min(1.0, 560.0 / max(height, width))
    sampled = cv2.resize(
        image,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
    sampled_lab = cv2.cvtColor(sampled, cv2.COLOR_BGR2LAB)
    sample_height, sample_width = sampled.shape[:2]
    grid_y, grid_x = np.mgrid[0:sample_height, 0:sample_width]
    features = np.column_stack(
        (
            sampled_lab.reshape(-1, 3).astype(np.float32),
            (grid_x.reshape(-1) / max(1, sample_width - 1) * 24).astype(np.float32),
            (grid_y.reshape(-1) / max(1, sample_height - 1) * 24).astype(np.float32),
        )
    )
    cv2.setRNGSeed(0)
    _, labels, centers = cv2.kmeans(
        features,
        9,
        None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 18, 0.8),
        1,
        cv2.KMEANS_PP_CENTERS,
    )
    labels = labels.reshape(sample_height, sample_width)
    label_sets = [(index,) for index in range(len(centers))]
    for first in range(len(centers)):
        for second in range(first + 1, len(centers)):
            color_distance = float(
                np.linalg.norm(centers[first, :3] - centers[second, :3])
            )
            if color_distance <= 34:
                label_sets.append((first, second))

    candidates = []
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    photo_area = float(width * height)
    for selected_labels in label_sets:
        mask = np.isin(labels, selected_labels).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in contours:
            scaled_contour = np.float32(contour) / scale
            candidate = _candidate_from_contour(
                scaled_contour,
                edges,
                lab,
                photo_area,
                width,
                height,
                "color-kmeans",
            )
            if candidate is not None:
                candidates.append(candidate)
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates[:120]


def _prefer_region_refinement(
    candidate: _Candidate, refined: _Candidate | None
) -> _Candidate:
    if refined is None:
        return candidate
    area_ratio = refined.area / max(1.0, candidate.area)
    if candidate.strategy.startswith(
        "low-contrast-single-edge-reconstruction"
    ):
        maximum_ratio = 1.45
    else:
        maximum_ratio = (
            1.25 if candidate.strategy == "color-kmeans" else 1.12
        )
    return refined if 0.85 <= area_ratio <= maximum_ratio else candidate


def _refinement_expansion(
    candidate: _Candidate, photo_area: float
) -> float:
    if candidate.strategy == "partial-side-reconstruction":
        return 1.15
    if candidate.strategy.startswith(
        "low-contrast-single-edge-reconstruction"
    ):
        return 1.65
    if (
        candidate.strategy == "line-reconstruction"
        and candidate.score < 0.52
    ):
        return 1.65
    if candidate.strategy != "color-kmeans":
        return 1.45
    if candidate.area / max(1.0, photo_area) < 0.18:
        return 1.65
    if candidate.contrast < 0.25:
        return 1.52
    return 1.45


def _merge_color_candidates(
    baseline: list[_Candidate], color_candidates: list[_Candidate]
) -> list[_Candidate]:
    colors = _cluster_candidates(color_candidates)
    if not colors:
        return baseline
    if not baseline:
        selected = _consistent_card_scale(colors)
        if not selected:
            return []
        peak = max(candidate.score for candidate in selected)
        return [
            candidate
            for candidate in selected
            if candidate.score >= peak - 0.12
        ]

    merged = list(baseline)
    for index, candidate in enumerate(merged):
        replacements = [
            color
            for color in colors
            if quadrilateral_iou(candidate.corners, color.corners) >= 0.35
            and color.score >= candidate.score + 0.04
            and 0.55
            <= color.area / max(1.0, candidate.area)
            <= 1.80
        ]
        if replacements:
            merged[index] = max(
                replacements, key=lambda color: color.score
            )

    reference_area = float(np.median([candidate.area for candidate in merged]))
    for color in colors:
        scale_ratio = max(reference_area, color.area) / max(
            1.0, min(reference_area, color.area)
        )
        if (
            color.score >= 0.72
            and scale_ratio <= 1.45
            and all(
                quadrilateral_iou(color.corners, candidate.corners) < 0.20
                for candidate in merged
            )
        ):
            merged.append(color)
    return merged[:CARD_LIMIT]


def _reference_card_dimensions(
    candidates: list[_Candidate],
    center_y: float | None = None,
) -> tuple[float, float, float]:
    """Return robust long edge, short edge and area estimates for one scene."""
    if center_y is not None and len(candidates) > 3:
        candidates = sorted(
            candidates,
            key=lambda candidate: abs(
                float(candidate.corners[:, 1].mean()) - center_y
            ),
        )[:3]
    long_edges = []
    short_edges = []
    areas = []
    for candidate in candidates:
        points = ordered_corners(candidate.corners)
        first_pair = 0.5 * (
            float(np.linalg.norm(points[1] - points[0]))
            + float(np.linalg.norm(points[2] - points[3]))
        )
        second_pair = 0.5 * (
            float(np.linalg.norm(points[3] - points[0]))
            + float(np.linalg.norm(points[2] - points[1]))
        )
        long_edges.append(max(first_pair, second_pair))
        short_edges.append(min(first_pair, second_pair))
        areas.append(candidate.area)
    return (
        float(np.median(long_edges)),
        float(np.median(short_edges)),
        float(np.median(areas)),
    )


def _neutral_bright_fraction(image: np.ndarray, quad: np.ndarray) -> float:
    x, y, width, height = cv2.boundingRect(np.int32(np.round(quad)))
    left = max(0, x)
    top = max(0, y)
    right = min(image.shape[1], x + width)
    bottom = min(image.shape[0], y + height)
    if right <= left or bottom <= top:
        return 0.0
    region = image[top:bottom, left:right]
    shifted = np.float32(quad - [left, top])
    scale = min(1.0, 260.0 / max(region.shape[:2]))
    if scale < 1.0:
        region = cv2.resize(
            region,
            (
                max(1, round(region.shape[1] * scale)),
                max(1, round(region.shape[0] * scale)),
            ),
            interpolation=cv2.INTER_AREA,
        )
        shifted *= scale
    mask = np.zeros(region.shape[:2], np.uint8)
    cv2.fillConvexPoly(mask, np.int32(np.round(shifted)), 255)
    pixel_count = cv2.countNonZero(mask)
    if pixel_count == 0:
        return 0.0
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    neutral_bright = cv2.inRange(
        hsv,
        np.array([0, 0, 115], np.uint8),
        np.array([180, 85, 255], np.uint8),
    )
    return cv2.countNonZero(cv2.bitwise_and(neutral_bright, mask)) / pixel_count


def _dark_interior_fraction(
    image: np.ndarray, quad: np.ndarray
) -> float:
    """Measure dark pixels away from the proposed outer boundary."""
    x, y, width, height = cv2.boundingRect(
        np.int32(np.round(quad))
    )
    left = max(0, x)
    top = max(0, y)
    right = min(image.shape[1], x + width)
    bottom = min(image.shape[0], y + height)
    if right <= left or bottom <= top:
        return 1.0
    region = image[top:bottom, left:right]
    shifted = np.float32(quad - [left, top])
    scale = min(1.0, 260.0 / max(region.shape[:2]))
    if scale < 1.0:
        region = cv2.resize(
            region,
            (
                max(1, round(region.shape[1] * scale)),
                max(1, round(region.shape[0] * scale)),
            ),
            interpolation=cv2.INTER_AREA,
        )
        shifted *= scale
    mask = np.zeros(region.shape[:2], np.uint8)
    cv2.fillConvexPoly(
        mask, np.int32(np.round(shifted)), 255
    )
    (_, _), (rect_width, rect_height), _ = cv2.minAreaRect(
        shifted
    )
    inset = max(
        3, round(min(rect_width, rect_height) * 0.12)
    )
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * inset + 1, 2 * inset + 1)
    )
    inner = cv2.erode(mask, kernel)
    pixels = cv2.countNonZero(inner)
    if pixels == 0:
        return 1.0
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    dark = cv2.inRange(gray, 0, 155)
    return (
        cv2.countNonZero(cv2.bitwise_and(dark, inner))
        / pixels
    )


def _loose_partial_seeds(
    masks: list[tuple[str, np.ndarray]],
    edges: np.ndarray,
    lab: np.ndarray,
    baseline: list[_Candidate],
) -> list[_Candidate]:
    """Keep card-sized mask fragments even when they are not card-shaped yet."""
    _, _, reference_area = _reference_card_dimensions(baseline)
    seeds: list[_Candidate] = []
    for strategy, mask in masks:
        contours, _ = cv2.findContours(
            mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in contours:
            contour_area = abs(float(cv2.contourArea(contour)))
            if not 0.18 * reference_area <= contour_area <= 0.92 * reference_area:
                continue
            quad, approximated = _quad_from_contour(contour)
            quad_area = abs(float(cv2.contourArea(quad)))
            if not 0.20 * reference_area <= quad_area <= 1.05 * reference_area:
                continue
            if any(
                quadrilateral_iou(quad, candidate.corners) >= 0.18
                or _containment(quad, candidate.corners) >= 0.68
                for candidate in baseline
            ):
                continue
            rectangularity = min(1.0, contour_area / max(1.0, quad_area))
            if rectangularity < 0.24:
                continue
            edge_score = min(1.0, _edge_support(edges, quad) * 3.2)
            contrast = _region_contrast(lab, quad)
            score = (
                0.40
                + 0.24 * rectangularity
                + 0.20 * edge_score
                + 0.12 * contrast
                + (0.04 if approximated else 0.0)
            )
            seeds.append(
                _Candidate(
                    quad,
                    min(1.0, score),
                    f"partial-{strategy}",
                    quad_area,
                    contrast,
                )
            )
    return _cluster_candidates(seeds)


def _partial_region_candidates(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    masks: list[tuple[str, np.ndarray]],
    contour_candidates: list[_Candidate],
    baseline: list[_Candidate],
) -> list[_Candidate]:
    """Complete a rectangular card from one intact side and two partial sides."""
    if len(baseline) < 3:
        return []
    global_long, global_short, reference_area = (
        _reference_card_dimensions(baseline)
    )
    seeds = _cluster_candidates(
        contour_candidates + _loose_partial_seeds(masks, edges, lab, baseline)
    )
    proposals: list[_Candidate] = []
    for seed in seeds:
        if not 0.20 * reference_area <= seed.area <= 0.88 * reference_area:
            continue
        if seed.score < 0.58:
            continue
        if any(
            quadrilateral_iou(seed.corners, candidate.corners) >= 0.18
            or _containment(seed.corners, candidate.corners) >= 0.68
            for candidate in baseline
        ):
            continue
        points = ordered_corners(seed.corners)
        center_y = float(points[:, 1].mean())
        row_long, row_short, _ = _reference_card_dimensions(
            baseline, center_y=center_y
        )
        side_lengths = [
            float(np.linalg.norm(points[(index + 1) % 4] - points[index]))
            for index in range(4)
        ]
        for index, anchor_length in enumerate(side_lengths):
            next_index = (index + 1) % 4
            previous_index = (index - 1) % 4
            after_index = (index + 2) % 4
            for anchor_reference, depth_reference, global_depth in (
                (row_short, row_long, global_long),
                (row_long, row_short, global_short),
            ):
                anchor_ratio = anchor_length / max(1.0, anchor_reference)
                if not 0.72 <= anchor_ratio <= 1.28:
                    continue
                target_anchor = anchor_reference * min(
                    1.04, max(1.0, anchor_ratio)
                )
                stable_depth = max(
                    depth_reference,
                    min(global_depth, depth_reference * 1.02),
                )
                target_depth = stable_depth
                first_direction = points[previous_index] - points[index]
                second_direction = points[after_index] - points[next_index]
                first_visible = float(np.linalg.norm(first_direction))
                second_visible = float(np.linalg.norm(second_direction))
                if (
                    min(first_visible, second_visible) < 0.18 * target_depth
                    or max(first_visible, second_visible) > 1.18 * target_depth
                ):
                    continue
                first_direction /= max(1.0, first_visible)
                second_direction /= max(1.0, second_visible)
                if float(np.dot(first_direction, second_direction)) < np.cos(
                    np.deg2rad(24)
                ):
                    continue
                anchor_direction = (
                    points[next_index] - points[index]
                ) / max(1.0, anchor_length)
                if abs(float(np.dot(anchor_direction, first_direction))) > np.cos(
                    np.deg2rad(52)
                ):
                    continue
                anchor_center = 0.5 * (points[index] + points[next_index])
                first_anchor = anchor_center - anchor_direction * (
                    target_anchor * 0.5
                )
                second_anchor = anchor_center + anchor_direction * (
                    target_anchor * 0.5
                )
                completed = points.copy()
                completed[index] = first_anchor
                completed[next_index] = second_anchor
                completed[previous_index] = (
                    first_anchor + first_direction * target_depth
                )
                completed[after_index] = (
                    second_anchor + second_direction * target_depth
                )
                completed = ordered_corners(completed)
                if (
                    np.any(completed[:, 0] < 0)
                    or np.any(completed[:, 0] >= image.shape[1])
                    or np.any(completed[:, 1] < 0)
                    or np.any(completed[:, 1] >= image.shape[0])
                ):
                    continue
                area = abs(float(cv2.contourArea(completed)))
                if not 0.65 * reference_area <= area <= 1.45 * reference_area:
                    continue
                if _containment(completed, seed.corners) < 0.78:
                    continue
                if any(
                    quadrilateral_iou(completed, candidate.corners) >= 0.20
                    for candidate in baseline
                ):
                    continue
                bright_fraction = _neutral_bright_fraction(image, completed)
                if not 0.32 <= bright_fraction <= 0.98:
                    continue
                edge_score = min(1.0, _edge_support(edges, completed) * 3.5)
                score = (
                    0.47 * seed.score
                    + 0.29 * min(1.0, bright_fraction / 0.62)
                    + 0.16 * edge_score
                    + 0.08
                )
                proposals.append(
                    _Candidate(
                        completed,
                        min(1.0, score),
                        "partial-side-reconstruction",
                        area,
                        bright_fraction,
                    )
                )
    remaining = sorted(
        proposals,
        key=lambda candidate: candidate.score
        + 0.40 * _geometry_score(candidate.corners),
        reverse=True,
    )
    clustered: list[_Candidate] = []
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        kept = []
        for candidate in remaining:
            if (
                quadrilateral_iou(candidate.corners, seed.corners) >= 0.28
                or _containment(candidate.corners, seed.corners) >= 0.78
            ):
                cluster.append(candidate)
            else:
                kept.append(candidate)
        remaining = kept
        clustered.append(
            max(
                cluster,
                key=lambda candidate: candidate.score
                + 0.40 * _geometry_score(candidate.corners),
            )
        )
    proposals = sorted(
        clustered,
        key=lambda candidate: candidate.score
        + 0.40 * _geometry_score(candidate.corners),
        reverse=True,
    )
    return proposals[:20]


def _recover_cards_behind_unbalanced_shapes(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    baseline: list[_Candidate],
    proposals: list[_Candidate],
    unbalanced_shapes: list[_Candidate],
) -> list[_Candidate]:
    """Turn a bridged partial region into a card hidden by a thin object."""
    if not proposals or not unbalanced_shapes:
        return proposals
    recovered: list[_Candidate] = []
    for proposal in proposals:
        row_long, row_short, reference_area = _reference_card_dimensions(
            baseline,
            center_y=float(proposal.corners[:, 1].mean()),
        )
        target_short = row_short * 1.10
        target_long = row_long * 1.02
        points = ordered_corners(proposal.corners)
        possible_edges = []
        for index in range(4):
            start = points[index]
            end = points[(index + 1) % 4]
            length = float(np.linalg.norm(end - start))
            if (
                0.82 * row_long <= length <= 1.25 * row_long
                and length >= 1.35 * row_short
                and length > target_short
            ):
                possible_edges.append(
                    (
                        _segment_edge_support(edges, start, end),
                        index,
                        length,
                    )
                )
        if not possible_edges:
            recovered.append(proposal)
            continue
        _, edge_index, edge_length = max(possible_edges)
        start = points[edge_index]
        end = points[(edge_index + 1) % 4]
        direction = np.float32(end - start) / edge_length
        normal = np.float32([-direction[1], direction[0]])
        midpoint = 0.5 * (start + end)
        if float(np.dot(points.mean(axis=0) - midpoint, normal)) < 0:
            normal = -normal
        excess = edge_length - target_short
        alternatives: list[tuple[float, _Candidate]] = []
        for offset in (0.0, 0.5 * excess, excess):
            first = start + direction * offset
            second = first + direction * target_short
            depth = normal * target_long
            quad = ordered_corners(
                np.float32([first, second, second + depth, first + depth])
            )
            if (
                np.any(quad[:, 0] < 0)
                or np.any(quad[:, 0] >= image.shape[1])
                or np.any(quad[:, 1] < 0)
                or np.any(quad[:, 1] >= image.shape[0])
            ):
                continue
            area = abs(float(cv2.contourArea(quad)))
            if not 0.72 * reference_area <= area <= 1.45 * reference_area:
                continue
            if any(
                quadrilateral_iou(quad, candidate.corners) >= 0.20
                for candidate in baseline
            ):
                continue
            outlier_coverage = max(
                _containment(quad, shape.corners)
                for shape in unbalanced_shapes
            )
            if outlier_coverage < 0.75:
                continue
            bright_fraction = _neutral_bright_fraction(image, quad)
            if not 0.32 <= bright_fraction <= 0.98:
                continue
            edge_score = min(1.0, _edge_support(edges, quad) * 3.5)
            geometry = _geometry_score(quad)
            score = (
                0.30 * proposal.score
                + 0.45 * outlier_coverage
                + 0.15 * geometry
                + 0.06 * edge_score
                + 0.04 * min(1.0, bright_fraction / 0.62)
            )
            alternatives.append(
                (
                    score,
                    _Candidate(
                        quad,
                        min(1.0, score),
                        "partial-occlusion-reconstruction",
                        area,
                        _region_contrast(lab, quad),
                    ),
                )
            )
        recovered.append(
            max(alternatives, key=lambda item: item[0])[1]
            if alternatives
            else proposal
        )
    return recovered


def _restore_partial_missing_side(
    lab: np.ndarray,
    candidate: _Candidate,
    references: list[_Candidate],
) -> _Candidate:
    """Restore one side when region refinement locks onto an interior line."""
    if (
        not candidate.strategy.startswith(
            "partial-side-reconstruction+region-refine"
        )
        or len(references) < 3
    ):
        return candidate
    row_long, row_short, reference_area = _reference_card_dimensions(
        references,
        center_y=float(candidate.corners[:, 1].mean()),
    )
    points = ordered_corners(candidate.corners)
    sides = [
        float(np.linalg.norm(points[(index + 1) % 4] - points[index]))
        for index in range(4)
    ]
    first_pair = 0.5 * (sides[0] + sides[2])
    second_pair = 0.5 * (sides[1] + sides[3])
    if first_pair >= second_pair:
        observed_long = first_pair
        observed_short = second_pair
        boundary_indices = (1, 3)
    else:
        observed_long = second_pair
        observed_short = first_pair
        boundary_indices = (0, 2)
    if (
        observed_long >= 0.93 * row_long
        or not 0.78 * row_short <= observed_short <= 1.22 * row_short
    ):
        return candidate
    center = points.mean(axis=0)
    contrasts = [
        _segment_color_contrast(
            lab,
            points[index],
            points[(index + 1) % 4],
            center,
        )
        for index in boundary_indices
    ]
    stable_offset = int(np.argmax(contrasts))
    weak_contrast = contrasts[1 - stable_offset]
    stable_contrast = contrasts[stable_offset]
    if stable_contrast < 0.20 or stable_contrast < 1.8 * max(
        0.01, weak_contrast
    ):
        return candidate
    stable_index = boundary_indices[stable_offset]
    next_index = (stable_index + 1) % 4
    previous_index = (stable_index - 1) % 4
    after_index = (stable_index + 2) % 4
    first_direction = points[previous_index] - points[stable_index]
    second_direction = points[after_index] - points[next_index]
    first_length = float(np.linalg.norm(first_direction))
    second_length = float(np.linalg.norm(second_direction))
    if min(first_length, second_length) < 1.0:
        return candidate
    first_direction /= first_length
    second_direction /= second_length
    if float(np.dot(first_direction, second_direction)) < np.cos(
        np.deg2rad(24)
    ):
        return candidate
    target_long = row_long * 0.97
    restored = points.copy()
    restored[previous_index] = (
        points[stable_index] + first_direction * target_long
    )
    restored[after_index] = (
        points[next_index] + second_direction * target_long
    )
    restored = ordered_corners(restored)
    if (
        np.any(restored[:, 0] < 0)
        or np.any(restored[:, 0] >= lab.shape[1])
        or np.any(restored[:, 1] < 0)
        or np.any(restored[:, 1] >= lab.shape[0])
    ):
        return candidate
    area = abs(float(cv2.contourArea(restored)))
    if not 0.72 * reference_area <= area <= 1.35 * reference_area:
        return candidate
    return _Candidate(
        restored,
        candidate.score,
        f"{candidate.strategy}+missing-side-restore",
        area,
        candidate.contrast,
    )


def _merge_recovery_candidates(
    baseline: list[_Candidate], proposals: list[_Candidate]
) -> list[_Candidate]:
    merged = list(baseline)
    centers = np.float32(
        [candidate.corners.mean(axis=0) for candidate in baseline]
    )
    _, _, reference_area = _reference_card_dimensions(baseline)
    layout_margin_x = 0.75 * np.sqrt(max(1.0, reference_area))
    layout_margin_y = 0.65 * np.sqrt(max(1.0, reference_area))
    for proposal in proposals:
        if proposal.score < 0.79:
            continue
        center = proposal.corners.mean(axis=0)
        if (
            center[0] < float(centers[:, 0].min()) - layout_margin_x
            or center[0] > float(centers[:, 0].max()) + layout_margin_x
            or center[1] < float(centers[:, 1].min()) - layout_margin_y
            or center[1] > float(centers[:, 1].max()) + layout_margin_y
        ):
            continue
        if any(
            quadrilateral_iou(proposal.corners, candidate.corners) >= 0.20
            for candidate in merged
        ):
            continue
        merged.append(proposal)
        break
    return merged


def _single_edge_card_candidates(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    baseline: list[_Candidate],
    lines: list[_Line] | None = None,
) -> list[_Candidate]:
    """Rebuild cards whose contour is split by overlap or the photo boundary.

    Once several cards establish the photographed scale, one sufficiently long
    visible edge is enough to propose the rest of a same-sized card. Proposals
    still need a card/background colour boundary and additional edge support.
    """
    if len(baseline) < 3:
        return []
    height, width = image.shape[:2]
    reference_long, reference_short, reference_area = (
        _reference_card_dimensions(baseline)
    )
    proposals: list[_Candidate] = []
    for line in (
        lines if lines is not None else _long_line_segments(image)
    ):
        for edge_length, depth in (
            (reference_long, reference_short),
            (reference_short, reference_long),
        ):
            if not 0.38 * edge_length <= line.length <= 1.28 * edge_length:
                continue
            visible_length = min(line.length, edge_length)
            missing_length = max(0.0, edge_length - visible_length)
            midpoint = (line.start + line.end) * 0.5
            direction = line.direction
            normal = np.float32([-direction[1], direction[0]])
            shifts = (
                (0.0,)
                if missing_length < 1.0
                else (0.0, -0.5 * missing_length, 0.5 * missing_length)
            )
            for shift in shifts:
                center = midpoint + direction * shift
                first = center - direction * (edge_length * 0.5)
                second = center + direction * (edge_length * 0.5)
                for side in (-1.0, 1.0):
                    offset = normal * (depth * side)
                    raw_quad = ordered_corners(
                        np.float32([first, second, second + offset, first + offset])
                    )
                    margin_x = width * 0.08
                    margin_y = height * 0.08
                    if (
                        np.any(raw_quad[:, 0] < -margin_x)
                        or np.any(raw_quad[:, 0] > width - 1 + margin_x)
                        or np.any(raw_quad[:, 1] < -margin_y)
                        or np.any(raw_quad[:, 1] > height - 1 + margin_y)
                    ):
                        continue
                    quad = raw_quad.copy()
                    quad[:, 0] = np.clip(quad[:, 0], 0, width - 1)
                    quad[:, 1] = np.clip(quad[:, 1], 0, height - 1)
                    area = abs(float(cv2.contourArea(quad)))
                    area_ratio = area / max(1.0, reference_area)
                    if not 0.62 <= area_ratio <= 1.42:
                        continue
                    if any(
                        quadrilateral_iou(quad, candidate.corners) >= 0.30
                        or _containment(quad, candidate.corners) >= 0.82
                        for candidate in baseline
                    ):
                        continue
                    edge_score = min(1.0, _edge_support(edges, quad) * 3.8)
                    contrast = _region_contrast(lab, quad)
                    visible_score = min(1.0, line.length / max(1.0, edge_length))
                    area_score = exp(-abs(log(area_ratio)) / 0.38)
                    base_score = (
                        0.31 * contrast
                        + 0.29 * edge_score
                        + 0.19 * visible_score
                        + 0.13 * area_score
                        + 0.08
                    )
                    bright_fraction = _neutral_bright_fraction(image, quad)
                    touches_boundary = bool(
                        np.any(raw_quad[:, 0] < 0)
                        or np.any(raw_quad[:, 0] > width - 1)
                        or np.any(raw_quad[:, 1] < 0)
                        or np.any(raw_quad[:, 1] > height - 1)
                    )
                    center_point = quad.mean(axis=0)
                    near_boundary = bool(
                        center_point[0] <= 0.10 * width
                        or center_point[0] >= 0.90 * width
                        or center_point[1] <= 0.10 * height
                        or center_point[1] >= 0.90 * height
                    )
                    strong_boundary_card = (
                        (touches_boundary or near_boundary)
                        and bright_fraction >= 0.80
                        and contrast >= 0.60
                    )
                    if contrast < 0.34 or (
                        base_score < 0.70
                        and not strong_boundary_card
                    ):
                        continue
                    score = (
                        base_score
                        + 0.25 * bright_fraction
                        + (0.12 if strong_boundary_card else 0.0)
                    )
                    proposals.append(
                        _Candidate(
                            quad,
                            min(1.0, score),
                            "single-edge-reconstruction",
                            area,
                            contrast,
                        )
                    )

    proposals = _cluster_candidates(proposals)
    proposals.sort(key=lambda candidate: candidate.score, reverse=True)
    return proposals[:40]


def _low_contrast_single_edge_candidates(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    baseline: list[_Candidate],
    lines: list[_Line] | None = None,
) -> list[_Candidate]:
    """Recover card-sized rectangles whose outer boundary is partly faint."""
    if len(baseline) < 3:
        return []
    height, width = image.shape[:2]
    reference_long, reference_short, reference_area = (
        _reference_card_dimensions(baseline)
    )
    seeds: list[tuple[_Candidate, float, float]] = []
    for line in (
        lines if lines is not None else _long_line_segments(image)
    ):
        for edge_length, depth in (
            (reference_long, reference_short),
            (reference_short, reference_long),
        ):
            if not 0.30 * edge_length <= line.length <= 1.35 * edge_length:
                continue
            visible_score = min(
                1.0, line.length / max(1.0, edge_length)
            )
            missing_length = max(0.0, edge_length - line.length)
            midpoint = (line.start + line.end) * 0.5
            direction = line.direction
            normal = np.float32([-direction[1], direction[0]])
            shifts = (
                (0.0,)
                if missing_length < 1.0
                else (
                    0.0,
                    -0.5 * missing_length,
                    0.5 * missing_length,
                )
            )
            for shift in shifts:
                center = midpoint + direction * shift
                first = center - direction * (edge_length * 0.5)
                second = center + direction * (edge_length * 0.5)
                for side in (-1.0, 1.0):
                    offset = normal * (depth * side)
                    quad = ordered_corners(
                        np.float32(
                            [
                                first,
                                second,
                                second + offset,
                                first + offset,
                            ]
                        )
                    )
                    if (
                        np.any(quad[:, 0] < 0)
                        or np.any(quad[:, 0] >= width)
                        or np.any(quad[:, 1] < 0)
                        or np.any(quad[:, 1] >= height)
                    ):
                        continue
                    if any(
                        quadrilateral_iou(
                            quad, candidate.corners
                        )
                        >= 0.25
                        or _containment(
                            quad, candidate.corners
                        )
                        >= 0.80
                        for candidate in baseline
                    ):
                        continue
                    area = abs(float(cv2.contourArea(quad)))
                    area_ratio = area / max(1.0, reference_area)
                    if not 0.62 <= area_ratio <= 1.42:
                        continue
                    contrast = _region_contrast(lab, quad)
                    raw_edge_support = _edge_support(edges, quad)
                    bright_fraction = _neutral_bright_fraction(
                        image, quad
                    )
                    if (
                        bright_fraction < 0.80
                        or contrast < 0.14
                        or raw_edge_support < 0.025
                        or _dark_interior_fraction(
                            image, quad
                        )
                        > 0.30
                    ):
                        continue
                    cheap_score = (
                        0.30 * min(1.0, contrast / 0.55)
                        + 0.25
                        * min(1.0, raw_edge_support / 0.10)
                        + 0.30
                        * min(1.0, bright_fraction / 0.90)
                        + 0.15 * visible_score
                    )
                    seeds.append(
                        (
                            _Candidate(
                                quad,
                                cheap_score,
                                (
                                    "low-contrast-single-edge-"
                                    "reconstruction"
                                ),
                                area,
                                contrast,
                            ),
                            bright_fraction,
                            visible_score,
                        )
                    )

    remaining = sorted(
        seeds, key=lambda item: item[0].score, reverse=True
    )
    candidates: list[_Candidate] = []
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        kept: list[tuple[_Candidate, float, float]] = []
        for item in remaining:
            if (
                quadrilateral_iou(
                    seed[0].corners, item[0].corners
                )
                >= 0.42
                or _containment(
                    seed[0].corners, item[0].corners
                )
                >= 0.82
            ):
                cluster.append(item)
            else:
                kept.append(item)
        remaining = kept
        representative, bright_fraction, visible_score = max(
            cluster, key=lambda item: item[0].score
        )
        points = ordered_corners(representative.corners)
        center = points.mean(axis=0)
        side_colors = sorted(
            [
                _segment_color_contrast(
                    lab,
                    points[index],
                    points[(index + 1) % 4],
                    center,
                )
                for index in range(4)
            ],
            reverse=True,
        )
        side_edges = sorted(
            [
                _segment_edge_support(
                    edges,
                    points[index],
                    points[(index + 1) % 4],
                )
                for index in range(4)
            ],
            reverse=True,
        )
        score = (
            0.18 * min(1.0, bright_fraction / 0.90)
            + 0.14 * min(
                1.0, representative.contrast / 0.55
            )
            + 0.17 * min(1.0, side_colors[0] / 0.80)
            + 0.15 * min(1.0, side_colors[1] / 0.55)
            + 0.08 * min(1.0, side_colors[2] / 0.35)
            + 0.13 * min(1.0, side_edges[0] / 0.14)
            + 0.09 * min(1.0, side_edges[1] / 0.09)
            + 0.06 * visible_score
            + min(0.12, 0.025 * log(1.0 + len(cluster)))
        )
        if score >= 0.80:
            candidates.append(
                _Candidate(
                    representative.corners,
                    min(1.0, score),
                    representative.strategy,
                    representative.area,
                    representative.contrast,
                )
            )
    candidates.sort(
        key=lambda candidate: candidate.score, reverse=True
    )
    return candidates[:24]


def _shares_existing_card_edge(
    proposal: _Candidate,
    baseline: list[_Candidate],
) -> bool:
    """Reject a projected neighbour made from an already detected card edge."""
    points = ordered_corners(proposal.corners)
    for candidate in baseline:
        reference = ordered_corners(candidate.corners)
        for index in range(4):
            first = points[index]
            second = points[(index + 1) % 4]
            length = max(1.0, float(np.linalg.norm(second - first)))
            for reference_index in range(4):
                reference_first = reference[reference_index]
                reference_second = reference[
                    (reference_index + 1) % 4
                ]
                aligned = min(
                    max(
                        float(np.linalg.norm(first - reference_first)),
                        float(np.linalg.norm(second - reference_second)),
                    ),
                    max(
                        float(np.linalg.norm(first - reference_second)),
                        float(np.linalg.norm(second - reference_first)),
                    ),
                )
                if aligned / length <= 0.10:
                    return True
    return False


def _merge_single_edge_candidates(
    baseline: list[_Candidate], proposals: list[_Candidate]
) -> list[_Candidate]:
    if not proposals or len(baseline) >= CARD_LIMIT:
        return baseline
    merged = list(baseline)
    strict_additions = 0
    _, _, reference_area = _reference_card_dimensions(baseline)
    reference_spacing = np.sqrt(max(1.0, reference_area))
    for proposal in proposals:
        center = proposal.corners.mean(axis=0)
        nearest = min(
            float(np.linalg.norm(center - candidate.corners.mean(axis=0)))
            for candidate in baseline
        )
        low_contrast = proposal.strategy.startswith(
            "low-contrast-single-edge-reconstruction"
        )
        if nearest > 2.65 * reference_spacing:
            continue
        if low_contrast:
            if (
                proposal.score < 0.80
                or _shares_existing_card_edge(
                    proposal, baseline
                )
            ):
                continue
        elif (
            proposal.score < 0.90
            or proposal.contrast < SINGLE_EDGE_MIN_CONTRAST
            or (len(baseline) == 3 and strict_additions >= 1)
        ):
            continue
        if any(
            quadrilateral_iou(proposal.corners, candidate.corners) >= 0.20
            for candidate in merged
        ):
            continue
        merged.append(proposal)
        if not low_contrast:
            strict_additions += 1
        if len(merged) >= CARD_LIMIT:
            break
    return merged


def _remove_reconstruction_duplicates(
    candidates: list[_Candidate],
) -> list[_Candidate]:
    """Prefer an original contour when recovery converges on the same card."""
    primary = [
        candidate
        for candidate in candidates
        if "reconstruction" not in candidate.strategy
    ]
    merged = list(primary)
    for candidate in candidates:
        if "reconstruction" not in candidate.strategy:
            continue
        if any(
            quadrilateral_iou(candidate.corners, kept.corners) >= 0.20
            or _containment(candidate.corners, kept.corners) >= 0.78
            for kept in merged
        ):
            continue
        merged.append(candidate)
    return merged


def _remove_contained_fragments(
    candidates: list[_Candidate],
) -> list[_Candidate]:
    """Remove a partial contour already covered by a larger card contour."""
    kept: list[_Candidate] = []
    for candidate in sorted(
        candidates, key=lambda item: item.area, reverse=True
    ):
        if any(
            candidate.area <= 0.84 * reference.area
            and _containment(
                candidate.corners, reference.corners
            )
            >= 0.96
            for reference in kept
        ):
            continue
        kept.append(candidate)
    return kept


def _third_side_evidence(
    edges: np.ndarray,
    lab: np.ndarray,
    candidate: _Candidate,
) -> tuple[float, float]:
    """Return consensus evidence, ignoring the single strongest side."""
    points = ordered_corners(candidate.corners)
    center = points.mean(axis=0)
    colors = sorted(
        [
            _segment_color_contrast(
                lab,
                points[index],
                points[(index + 1) % 4],
                center,
            )
            for index in range(4)
        ],
        reverse=True,
    )
    side_edges = sorted(
        [
            _segment_edge_support(
                edges,
                points[index],
                points[(index + 1) % 4],
            )
            for index in range(4)
        ],
        reverse=True,
    )
    return colors[2], side_edges[2]


def _weakest_side_evidence(
    edges: np.ndarray,
    lab: np.ndarray,
    candidate: _Candidate,
) -> tuple[float, float]:
    points = ordered_corners(candidate.corners)
    center = points.mean(axis=0)
    colors = [
        _segment_color_contrast(
            lab,
            points[index],
            points[(index + 1) % 4],
            center,
        )
        for index in range(4)
    ]
    side_edges = [
        _segment_edge_support(
            edges,
            points[index],
            points[(index + 1) % 4],
        )
        for index in range(4)
    ]
    return min(colors), min(side_edges)


def _dominant_large_single_candidate(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    selected: list[_Candidate],
    alternatives: list[_Candidate],
) -> _Candidate | None:
    """Find one complete card currently split into several card-like pieces."""
    if len(selected) < 2:
        return None
    height, width = image.shape[:2]
    photo_area = float(height * width)
    possible: list[tuple[float, _Candidate]] = []
    for candidate in alternatives:
        if (
            candidate.score < 0.48
            or candidate.area < 0.20 * photo_area
            or not _contains_image_center(candidate, width, height)
            or _opposite_side_imbalance(candidate.corners) > 1.45
        ):
            continue
        covered = [
            item
            for item in selected
            if quadrilateral_iou(candidate.corners, item.corners) >= 0.20
        ]
        if len(covered) < 2:
            continue
        # A very strong complete contour is already a card in its own right.
        # Do not collapse it together with a neighbouring card merely because
        # a larger line rectangle happens to cover both of them.
        if max(item.score for item in covered) >= 0.88:
            continue
        covered_area = float(np.median([item.area for item in covered]))
        if candidate.area < 1.65 * covered_area:
            continue
        color_consensus, edge_consensus = _third_side_evidence(
            edges, lab, candidate
        )
        weakest_color, weakest_edge = _weakest_side_evidence(
            edges, lab, candidate
        )
        if (
            color_consensus < 0.22
            or edge_consensus < 0.025
            or weakest_color < 0.20
            or weakest_edge < 0.020
        ):
            continue
        evidence = (
            candidate.score
            + 0.10 * min(1.0, color_consensus / 0.60)
            + 0.08 * min(1.0, edge_consensus / 0.06)
            + 0.06 * min(1.0, weakest_color / 0.35)
            + 0.04 * min(1.0, weakest_edge / 0.05)
            + 0.02 * min(3, len(covered))
        )
        possible.append((evidence, candidate))
    return max(possible, key=lambda item: item[0])[1] if possible else None


def _replace_shared_edge_candidate(
    selected: list[_Candidate],
    alternatives: list[_Candidate],
) -> list[_Candidate]:
    """Replace a projected card that reuses an adjacent card's exact edge."""
    if len(selected) < 2:
        return selected
    reference_area = float(np.median([item.area for item in selected]))
    for first_index, first in enumerate(selected):
        for second_index in range(first_index + 1, len(selected)):
            second = selected[second_index]
            if not (
                _shares_existing_card_edge(first, [second])
                or _shares_existing_card_edge(second, [first])
            ):
                continue
            removed_index = (
                first_index if first.score <= second.score else second_index
            )
            removed = selected[removed_index]
            kept = [
                item
                for index, item in enumerate(selected)
                if index != removed_index
            ]
            replacements = []
            for candidate in alternatives:
                area_ratio = max(reference_area, candidate.area) / max(
                    1.0, min(reference_area, candidate.area)
                )
                overlap = quadrilateral_iou(
                    candidate.corners, removed.corners
                )
                if (
                    candidate is removed
                    or candidate.score < removed.score - 0.10
                    or area_ratio > 1.55
                    or not 0.30 <= overlap < 0.82
                    or any(
                        quadrilateral_iou(
                            candidate.corners, item.corners
                        )
                        >= 0.20
                        for item in kept
                    )
                    or _shares_existing_card_edge(candidate, kept)
                ):
                    continue
                replacements.append(candidate)
            if replacements:
                replacement = max(
                    replacements,
                    key=lambda item: (item.score, item.area),
                )
                return kept + [replacement]
    return selected


def _replace_overlapping_reconstructions(
    selected: list[_Candidate],
    alternatives: list[_Candidate],
) -> list[_Candidate]:
    """Replace two overlapping partial quads with one complete alternative."""
    if len(selected) < 2:
        return selected
    reference_area = float(np.median([item.area for item in selected]))
    for first_index, first in enumerate(selected):
        for second_index in range(first_index + 1, len(selected)):
            second = selected[second_index]
            overlap = quadrilateral_iou(first.corners, second.corners)
            if (
                not 0.07 <= overlap < 0.28
                or max(first.score, second.score) > 0.58
                or "line-reconstruction" not in first.strategy
                or "line-reconstruction" not in second.strategy
            ):
                continue
            kept = [
                item
                for index, item in enumerate(selected)
                if index not in {first_index, second_index}
            ]
            replacements = []
            for candidate in alternatives:
                area_ratio = max(reference_area, candidate.area) / max(
                    1.0, min(reference_area, candidate.area)
                )
                if (
                    candidate.score < min(first.score, second.score) - 0.12
                    or area_ratio > 1.50
                    or quadrilateral_iou(
                        candidate.corners, first.corners
                    )
                    < 0.28
                    or quadrilateral_iou(
                        candidate.corners, second.corners
                    )
                    < 0.28
                    or any(
                        quadrilateral_iou(
                            candidate.corners, item.corners
                        )
                        >= 0.20
                        for item in kept
                    )
                ):
                    continue
                replacements.append(candidate)
            if replacements:
                replacement = max(
                    replacements,
                    key=lambda item: (item.score, item.area),
                )
                return kept + [replacement]
    return selected


def _replace_with_stronger_alternative(
    selected: list[_Candidate],
    alternatives: list[_Candidate],
) -> list[_Candidate]:
    """Restore a stronger same-scale quad suppressed by an overlap cluster."""
    if not selected or len(selected) > 4:
        return selected
    reference_area = float(np.median([item.area for item in selected]))
    merged = list(selected)
    for index, current in enumerate(list(merged)):
        kept = [
            item for other, item in enumerate(merged) if other != index
        ]
        replacements = []
        for candidate in alternatives:
            overlap = quadrilateral_iou(
                candidate.corners, current.corners
            )
            area_ratio = max(reference_area, candidate.area) / max(
                1.0, min(reference_area, candidate.area)
            )
            if (
                candidate.score < current.score + 0.04
                or candidate.strategy == current.strategy
                or not 0.28 <= overlap < 0.82
                or area_ratio > 1.45
                or any(
                    quadrilateral_iou(candidate.corners, item.corners)
                    >= 0.20
                    for item in kept
                )
            ):
                continue
            replacements.append(candidate)
        if replacements:
            merged[index] = max(
                replacements, key=lambda item: (item.score, item.area)
            )
    return merged


def _weak_center_single_candidate(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    selected: list[_Candidate],
    alternatives: list[_Candidate],
) -> _Candidate | None:
    """Refine a weak central quad when the normal path found one bad card."""
    if len(selected) != 1:
        return None
    current = selected[0]
    height, width = image.shape[:2]
    photo_area = float(height * width)
    if (
        current.score >= 0.52
        and _contains_image_center(current, width, height)
    ):
        return None

    seeds = []
    for candidate in alternatives:
        area_ratio = candidate.area / max(1.0, photo_area)
        if (
            candidate.score < 0.30
            or not 0.12 <= area_ratio <= 0.40
            or not _contains_image_center(candidate, width, height)
            or _touches_image_frame(candidate, width, height)
            or _opposite_side_imbalance(candidate.corners) > 1.75
        ):
            continue
        seeds.append(candidate)
    seeds.sort(key=lambda item: (item.score, item.area), reverse=True)

    unique: list[_Candidate] = []
    for seed in seeds:
        if any(
            quadrilateral_iou(seed.corners, kept.corners) >= 0.62
            for kept in unique
        ):
            continue
        unique.append(seed)
        if len(unique) >= 2:
            break

    possible: list[_Candidate] = []
    for seed in unique:
        expansion, inner_scale = (
            (1.65, 0.52)
            if seed.strategy == "color-kmeans"
            else (1.25, 0.42)
        )
        refined = _refine_card_region(
            image,
            seed,
            expansion=expansion,
            inner_scale=inner_scale,
        )
        if refined is None:
            continue
        rescored = _candidate_from_contour(
            np.float32(refined.corners).reshape(-1, 1, 2),
            edges,
            lab,
            photo_area,
            width,
            height,
            "weak-center-single",
        )
        if rescored is not None:
            possible.append(rescored)

        box = ordered_corners(
            cv2.boxPoints(cv2.minAreaRect(refined.corners))
        )
        box_area = abs(float(cv2.contourArea(box)))
        if box_area > 1.22 * max(1.0, refined.area):
            continue
        boxed = _candidate_from_contour(
            box.reshape(-1, 1, 2),
            edges,
            lab,
            photo_area,
            width,
            height,
            "weak-center-single+outer-box",
        )
        if boxed is not None:
            possible.append(boxed)

    if not possible:
        return None
    best = max(possible, key=lambda item: (item.score, item.area))
    return best if best.score >= current.score - 0.03 else None


def _select_candidate_hypothesis(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    selected: list[_Candidate],
    alternatives: list[_Candidate],
) -> list[_Candidate]:
    """Compare single-card and multi-card interpretations before refinement."""
    single = _dominant_large_single_candidate(
        image, edges, lab, selected, alternatives
    )
    if single is not None:
        return [single]
    selected = _replace_with_stronger_alternative(
        selected, alternatives
    )
    selected = _replace_shared_edge_candidate(selected, alternatives)
    return _replace_overlapping_reconstructions(selected, alternatives)


def _replace_low_contrast_projection(
    edges: np.ndarray,
    lab: np.ndarray,
    selected: list[_Candidate],
    alternatives: list[_Candidate],
) -> list[_Candidate]:
    """Replace a projected low-contrast strip with a complete raw quad."""
    if len(selected) < 3:
        return selected
    reference_area = float(np.median([item.area for item in selected]))
    merged = list(selected)
    for index, current in enumerate(list(merged)):
        if not current.strategy.startswith(
            "low-contrast-single-edge-reconstruction"
        ):
            continue
        kept = [
            item for other, item in enumerate(merged) if other != index
        ]
        possible: list[tuple[float, _Candidate]] = []
        for candidate in alternatives:
            overlap = quadrilateral_iou(
                candidate.corners, current.corners
            )
            area_ratio = max(reference_area, candidate.area) / max(
                1.0, min(reference_area, candidate.area)
            )
            if (
                candidate.score < 0.60
                or not 0.25 <= overlap <= 0.68
                or not 1.12 * reference_area <= candidate.area
                or area_ratio > 1.55
                or any(
                    quadrilateral_iou(candidate.corners, item.corners)
                    >= 0.20
                    for item in kept
                )
            ):
                continue
            color, edge = _third_side_evidence(
                edges, lab, candidate
            )
            quality = (
                candidate.score
                + 0.10 * min(1.0, color / 0.25)
                + 0.12 * min(1.0, edge / 0.06)
            )
            possible.append((quality, candidate))
        if possible:
            merged[index] = max(possible, key=lambda item: item[0])[1]
    return merged


def _restore_nonoverlapping_alternatives(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    selected: list[_Candidate],
    alternatives: list[_Candidate],
) -> list[_Candidate]:
    """Restore same-scale line quads lost inside a broader overlap cluster."""
    if not 3 <= len(selected) < CARD_LIMIT:
        return selected
    if len(selected) > 6:
        return selected
    if (
        len(selected) > 3
        and not any(
            candidate.strategy.startswith(
                "low-contrast-single-edge-reconstruction"
            )
            for candidate in selected
        )
    ):
        return selected
    reference_area = float(np.median([item.area for item in selected]))
    possible: list[tuple[float, _Candidate]] = []
    for candidate in alternatives:
        if "line-reconstruction" not in candidate.strategy:
            continue
        area_ratio = max(reference_area, candidate.area) / max(
            1.0, min(reference_area, candidate.area)
        )
        if (
            candidate.score < 0.50
            or area_ratio > 1.80
            or any(
                quadrilateral_iou(candidate.corners, item.corners)
                >= 0.12
                for item in selected
            )
        ):
            continue
        color, edge = _third_side_evidence(edges, lab, candidate)
        if color < 0.04 or edge < 0.018:
            continue
        scale_fit = exp(-abs(log(area_ratio)) / 0.48)
        quality = (
            candidate.score
            + 0.12 * min(1.0, color / 0.20)
            + 0.12 * min(1.0, edge / 0.06)
            + 0.12 * scale_fit
        )
        possible.append((quality, candidate))

    possible.sort(key=lambda item: item[0], reverse=True)
    if len(selected) <= 3 and len(possible) < 2:
        return selected
    addition_limit = 2 if len(selected) <= 3 else 1
    merged = list(selected)
    for quality, candidate in possible:
        if quality < 0.68:
            continue
        if any(
            quadrilateral_iou(candidate.corners, item.corners) >= 0.12
            for item in merged
        ):
            continue
        merged.append(candidate)
        if len(merged) - len(selected) >= addition_limit:
            break
    return merged


def _recenter_weak_line_from_inner_region(
    image: np.ndarray,
    selected: list[_Candidate],
    alternatives: list[_Candidate],
) -> list[_Candidate]:
    """Recenter a weak outer quad from a contained colour region and column."""
    if len(selected) < 3:
        return selected
    merged = list(selected)
    for index, candidate in enumerate(list(merged)):
        if (
            candidate.strategy != "line-reconstruction"
            or not 0.50 <= candidate.score <= 0.58
        ):
            continue
        center = candidate.corners.mean(axis=0)
        scale = np.sqrt(max(1.0, candidate.area))
        references = [
            item
            for other, item in enumerate(merged)
            if other != index
            and item.corners[:, 1].mean() < center[1]
            and center[1] - item.corners[:, 1].mean() <= 1.65 * scale
        ]
        if not references:
            continue
        reference = min(
            references,
            key=lambda item: abs(
                float(item.corners[:, 0].mean() - center[0])
            ),
        )
        reference_center = reference.corners.mean(axis=0)
        before_alignment = abs(float(center[0] - reference_center[0]))

        inner_regions = []
        for inner in alternatives:
            if inner.strategy != "color-kmeans" or inner.score < 0.35:
                continue
            area_ratio = inner.area / max(1.0, candidate.area)
            if not 0.20 <= area_ratio <= 0.65:
                continue
            if _containment(candidate.corners, inner.corners) < 0.90:
                continue
            shift = inner.corners.mean(axis=0) - center
            shift_length = float(np.linalg.norm(shift))
            if not 0.12 * scale <= shift_length <= 0.35 * scale:
                continue
            after_alignment = abs(
                float(center[0] + shift[0] - reference_center[0])
            )
            if (
                after_alignment > 0.18 * scale
                or after_alignment > before_alignment - 0.12 * scale
            ):
                continue
            shifted = candidate.corners + shift
            if (
                np.any(shifted[:, 0] < 0)
                or np.any(shifted[:, 0] >= image.shape[1])
                or np.any(shifted[:, 1] < 0)
                or np.any(shifted[:, 1] >= image.shape[0])
            ):
                continue
            inner_regions.append(
                (
                    after_alignment,
                    _Candidate(
                        np.float32(shifted),
                        candidate.score,
                        "line-reconstruction+inner-center-recenter",
                        candidate.area,
                        candidate.contrast,
                    ),
                )
            )
        if inner_regions:
            merged[index] = min(
                inner_regions, key=lambda item: item[0]
            )[1]
    return merged


def _refine_line_dominated_alternatives(
    image: np.ndarray,
    edges: np.ndarray,
    lab: np.ndarray,
    selected: list[_Candidate],
    alternatives: list[_Candidate],
) -> list[_Candidate]:
    """Rescue a few weak line quads in scenes where masks find no cards."""
    if len(selected) < 3:
        return selected
    photo_area = float(image.shape[0] * image.shape[1])
    reference_area = float(np.median([item.area for item in selected]))
    replacement_seeds: dict[int, list[_Candidate]] = {}
    addition_seeds: list[_Candidate] = []
    for candidate in alternatives:
        area_ratio = max(reference_area, candidate.area) / max(
            1.0, min(reference_area, candidate.area)
        )
        if (
            candidate.score < 0.37
            or area_ratio > 1.50
            or _opposite_side_imbalance(candidate.corners)
            > MAX_OPPOSITE_SIDE_IMBALANCE
        ):
            continue
        overlaps = [
            index
            for index, item in enumerate(selected)
            if quadrilateral_iou(candidate.corners, item.corners) >= 0.20
        ]
        if len(overlaps) == 1:
            index = overlaps[0]
            target = selected[index]
            target_color, target_edge = _third_side_evidence(
                edges, lab, target
            )
            if (
                area_ratio > 1.22
                or candidate.score > target.score
                or (target_color >= 0.10 and target_edge >= 0.015)
                or quadrilateral_iou(candidate.corners, target.corners) < 0.30
                or quadrilateral_iou(candidate.corners, target.corners) >= 0.78
                or target.score > 0.56
                or candidate.score < target.score - 0.18
            ):
                continue
            replacement_seeds.setdefault(index, []).append(candidate)
        elif not overlaps and candidate.score >= 0.38:
            addition_seeds.append(candidate)

    seeds: list[_Candidate] = []
    for candidates in replacement_seeds.values():
        candidates.sort(key=lambda item: item.score, reverse=True)
        seeds.extend(candidates[:1])
    addition_seeds.sort(
        key=lambda item: (
            item.score,
            -abs(log(item.area / max(1.0, reference_area))),
        ),
        reverse=True,
    )
    seeds.extend(addition_seeds[:1])

    unique_seeds: list[_Candidate] = []
    for seed in seeds:
        if any(
            quadrilateral_iou(seed.corners, item.corners) >= 0.65
            for item in unique_seeds
        ):
            continue
        unique_seeds.append(seed)
        if len(unique_seeds) >= 3:
            break

    refined_candidates: list[_Candidate] = []
    for seed in unique_seeds:
        refined = _refine_card_region(
            image, seed, expansion=1.45, inner_scale=0.52
        )
        if refined is None:
            continue
        rescored = _candidate_from_contour(
            np.float32(refined.corners).reshape(-1, 1, 2),
            edges,
            lab,
            photo_area,
            image.shape[1],
            image.shape[0],
            "line-reconstruction+alternative-refined",
        )
        if rescored is not None and rescored.score >= 0.52:
            refined_candidates.append(rescored)

    merged = list(selected)
    def selection_quality(candidate: _Candidate) -> float:
        scale_fit = exp(
            -abs(log(candidate.area / max(1.0, reference_area)))
            / 0.35
        )
        return candidate.score + 0.16 * scale_fit

    for candidate in sorted(
        refined_candidates, key=lambda item: item.score, reverse=True
    ):
        overlaps = [
            index
            for index, item in enumerate(merged)
            if quadrilateral_iou(candidate.corners, item.corners) >= 0.20
        ]
        if len(overlaps) == 1:
            index = overlaps[0]
            if selection_quality(candidate) > selection_quality(
                merged[index]
            ):
                merged[index] = candidate
        elif not overlaps and candidate.score >= 0.56:
            centers = np.float32(
                [item.corners.mean(axis=0) for item in merged]
            )
            margin = 1.55 * np.sqrt(max(1.0, reference_area))
            center = candidate.corners.mean(axis=0)
            if (
                centers[:, 0].min() - margin <= center[0]
                <= centers[:, 0].max() + margin
                and centers[:, 1].min() - margin <= center[1]
                <= centers[:, 1].max() + margin
            ):
                merged.append(candidate)
        if len(merged) >= CARD_LIMIT:
            break
    return merged


def _opposite_side_imbalance(points: np.ndarray) -> float:
    points = ordered_corners(points)
    sides = [
        float(np.linalg.norm(points[(index + 1) % 4] - points[index]))
        for index in range(4)
    ]
    if min(sides) <= 0:
        return float("inf")
    return max(
        max(sides[0], sides[2]) / min(sides[0], sides[2]),
        max(sides[1], sides[3]) / min(sides[1], sides[3]),
    )


def _geometry_score(points: np.ndarray) -> float:
    sides = [
        float(np.linalg.norm(points[(index + 1) % 4] - points[index]))
        for index in range(4)
    ]
    if min(sides) <= 0:
        return 0.0
    (_, _), (rect_width, rect_height), _ = cv2.minAreaRect(points)
    if min(rect_width, rect_height) <= 0:
        return 0.0
    aspect = max(rect_width, rect_height) / min(rect_width, rect_height)
    aspect_score = exp(-abs(log(aspect / CARD_ASPECT)) / 0.42)
    balance = exp(
        -abs(log(sides[0] / sides[2]))
        -abs(log(sides[1] / sides[3]))
    )
    return 0.62 * aspect_score + 0.38 * balance


def _repair_clipped_corner(
    candidate: _Candidate,
    image_width: int,
    image_height: int,
    *,
    allow_inset_repair: bool = False,
) -> _Candidate:
    if candidate.strategy == "line-reconstruction":
        return candidate
    points = ordered_corners(candidate.corners)
    opposite_imbalance = _opposite_side_imbalance(points)
    original_area = abs(float(cv2.contourArea(points)))
    original_score = _geometry_score(points)
    inset_corner_repair = (
        allow_inset_repair
        and "region-refine" in candidate.strategy
        and original_score < 0.75
    )
    if (
        opposite_imbalance < CORNER_REPAIR_MIN_IMBALANCE
        and not inset_corner_repair
    ):
        return candidate
    best = points
    best_score = original_score
    for index in range(4):
        previous = points[(index - 1) % 4]
        following = points[(index + 1) % 4]
        opposite = points[(index + 2) % 4]
        predicted = previous + following - opposite
        if not (
            0 <= predicted[0] < image_width
            and 0 <= predicted[1] < image_height
        ):
            continue
        repaired = points.copy()
        repaired[index] = predicted
        repaired = ordered_corners(repaired)
        area = abs(float(cv2.contourArea(repaired)))
        minimum_area = 0.95 if inset_corner_repair else 1.18
        maximum_area = 1.35 if inset_corner_repair else 2.5
        if not (
            minimum_area * original_area
            <= area
            <= maximum_area * original_area
        ):
            continue
        score = _geometry_score(repaired)
        if score > best_score:
            best = repaired
            best_score = score
    required_improvement = 0.18 if inset_corner_repair else 0.16
    if best_score < original_score + required_improvement:
        return candidate
    return _Candidate(
        best,
        candidate.score,
        f"{candidate.strategy}+corner-repair",
        abs(float(cv2.contourArea(best))),
        candidate.contrast,
    )


def _masks(image: np.ndarray) -> tuple[np.ndarray, list[tuple[str, np.ndarray]]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    median = float(np.median(blurred))
    lower = max(15, int(0.55 * median))
    upper = max(lower + 30, min(240, int(1.45 * median)))
    auto_edges = cv2.Canny(blurred, lower, upper)
    fixed_edges = cv2.Canny(blurred, 40, 140)
    edges = cv2.bitwise_or(auto_edges, fixed_edges)

    masks: list[tuple[str, np.ndarray]] = []
    for size in (5, 9):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
        masks.append(
            (f"edge-close-{size}", cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel))
        )

    smooth = cv2.GaussianBlur(gray, (11, 11), 0)
    _, otsu = cv2.threshold(
        smooth, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    for name, binary in (
        ("otsu-light", otsu),
        ("otsu-dark", cv2.bitwise_not(otsu)),
    ):
        cleaned = cv2.morphologyEx(
            binary,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)),
        )
        cleaned = cv2.morphologyEx(
            cleaned,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        )
        masks.append((name, cleaned))

    adaptive = cv2.adaptiveThreshold(
        smooth,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        51,
        5,
    )
    masks.append(
        (
            "adaptive-light",
            cv2.morphologyEx(
                adaptive,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)),
            ),
        )
    )

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    neutral_bright = cv2.inRange(
        hsv,
        np.array([0, 0, 135], np.uint8),
        np.array([180, 90, 255], np.uint8),
    )
    neutral_bright = cv2.morphologyEx(
        neutral_bright,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)),
    )
    neutral_bright = cv2.morphologyEx(
        neutral_bright,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
    )
    masks.append(("neutral-bright", neutral_bright))
    return edges, masks


def _cluster_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    if not candidates:
        return []
    remaining = sorted(candidates, key=lambda item: item.score, reverse=True)
    clusters: list[list[_Candidate]] = []
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        kept: list[_Candidate] = []
        for candidate in remaining:
            if (
                quadrilateral_iou(candidate.corners, seed.corners) >= 0.28
                or _containment(candidate.corners, seed.corners) >= 0.78
            ):
                cluster.append(candidate)
            else:
                kept.append(candidate)
        remaining = kept
        clusters.append(cluster)

    selected: list[_Candidate] = []
    for cluster in clusters:
        largest = max(item.area for item in cluster)
        selected.append(
            max(
                cluster,
                key=lambda item: item.score
                + 0.12 * (item.area / max(1.0, largest)),
            )
        )
    selected = [item for item in selected if item.score >= MIN_CANDIDATE_SCORE]
    selected.sort(key=lambda item: item.score, reverse=True)
    return selected


def _consistent_card_scale(candidates: list[_Candidate]) -> list[_Candidate]:
    if len(candidates) <= 1:
        return candidates
    scale_ratio = 1.8
    clusters = []
    for seed in candidates:
        cluster = [
            candidate
            for candidate in candidates
            if max(seed.area, candidate.area) / max(1.0, min(seed.area, candidate.area))
            <= scale_ratio
        ]
        clusters.append(cluster)
    best = max(
        clusters,
        key=lambda cluster: (
            sum(
                (candidate.area ** 1.15) * candidate.score
                for candidate in cluster
            ),
            len(cluster),
            float(np.median([candidate.area for candidate in cluster])),
        ),
    )
    if len(best) == 1:
        return [max(candidates, key=lambda candidate: (candidate.area, candidate.score))]
    peak_score = max(candidate.score for candidate in best)
    best = [
        candidate
        for candidate in best
        if candidate.score >= peak_score - 0.18
        or (
            candidate.strategy == "line-reconstruction"
            and candidate.score >= peak_score - 0.38
        )
    ]
    best.sort(key=lambda candidate: candidate.score, reverse=True)
    return best[:CARD_LIMIT]


def _spatial_order(candidates: list[_Candidate]) -> list[_Candidate]:
    if len(candidates) < 2:
        return candidates
    heights = [
        cv2.boundingRect(np.int32(np.round(candidate.corners)))[3]
        for candidate in candidates
    ]
    row_tolerance = max(20.0, float(np.median(heights)) * 0.45)
    rows: list[list[_Candidate]] = []
    row_centers: list[float] = []
    for candidate in sorted(
        candidates, key=lambda item: float(item.corners[:, 1].mean())
    ):
        center_y = float(candidate.corners[:, 1].mean())
        if rows and abs(center_y - row_centers[-1]) <= row_tolerance:
            rows[-1].append(candidate)
            row_centers[-1] = float(
                np.mean([item.corners[:, 1].mean() for item in rows[-1]])
            )
        else:
            rows.append([candidate])
            row_centers.append(center_y)
    ordered: list[_Candidate] = []
    for row in rows:
        ordered.extend(
            sorted(row, key=lambda item: float(item.corners[:, 0].mean()))
        )
    return ordered


def detect_cards(image: np.ndarray) -> list[Detection]:
    height, width = image.shape[:2]
    scale = min(1.0, MAX_WORKING_EDGE / float(max(height, width)))
    if scale < 1.0:
        working = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        working = image

    work_height, work_width = working.shape[:2]
    photo_area = float(work_width * work_height)
    edges, masks = _masks(working)
    lab = cv2.cvtColor(working, cv2.COLOR_BGR2LAB)
    contour_candidates: list[_Candidate] = []
    for strategy, mask in masks:
        contours, _ = cv2.findContours(
            mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in contours:
            candidate = _candidate_from_contour(
                contour,
                edges,
                lab,
                photo_area,
                work_width,
                work_height,
                strategy,
            )
            if candidate is not None:
                contour_candidates.append(candidate)

    contour_clustered = _cluster_candidates(contour_candidates)
    contour_selected = _consistent_card_scale(contour_clustered)
    candidate_alternatives = list(contour_candidates)
    line_dominated = not contour_selected
    if len(contour_selected) <= 2:
        line_candidates = _line_candidates(
            working,
            edges,
            lab,
            minimum_score=(0.30 if line_dominated else None),
        )
        candidate_alternatives.extend(line_candidates)
        strong_line_candidates = [
            candidate
            for candidate in line_candidates
            if candidate.score >= MIN_CANDIDATE_SCORE + 0.08
        ]
        candidates = contour_candidates + strong_line_candidates
        selected_candidates = _consistent_card_scale(
            _cluster_candidates(candidates)
        )
        color_candidates = _color_region_candidates(
            working, edges, lab
        )
        candidate_alternatives.extend(color_candidates)
        selected_candidates = _merge_color_candidates(
            selected_candidates,
            color_candidates,
        )
        selected_candidates = [
            candidate
            for candidate in selected_candidates
            if (
                _opposite_side_imbalance(candidate.corners)
                <= MAX_OPPOSITE_SIDE_IMBALANCE
                or _opposite_side_imbalance(candidate.corners)
                >= CORNER_REPAIR_MIN_IMBALANCE
            )
        ]
    else:
        if len(contour_selected) <= 3:
            candidate_alternatives.extend(
                _line_candidates(working, edges, lab)
            )
        color_candidates = (
            _color_region_candidates(working, edges, lab)
            if len(contour_selected) < CARD_LIMIT
            else []
        )
        candidate_alternatives.extend(color_candidates)
        selected_candidates = _merge_color_candidates(
            contour_selected,
            color_candidates,
        )
        unbalanced_shapes = [
            candidate
            for candidate in selected_candidates
            if (
                MAX_OPPOSITE_SIDE_IMBALANCE
                < _opposite_side_imbalance(candidate.corners)
                < CORNER_REPAIR_MIN_IMBALANCE
            )
        ]
        selected_candidates = [
            candidate
            for candidate in selected_candidates
            if (
                _opposite_side_imbalance(candidate.corners)
                <= MAX_OPPOSITE_SIDE_IMBALANCE
                or _opposite_side_imbalance(candidate.corners)
                >= CORNER_REPAIR_MIN_IMBALANCE
            )
        ]
        if len(selected_candidates) < CARD_LIMIT:
            recovery_candidates = _partial_region_candidates(
                working,
                edges,
                lab,
                masks,
                contour_candidates,
                selected_candidates,
            )
            recovery_candidates = _recover_cards_behind_unbalanced_shapes(
                working,
                edges,
                lab,
                selected_candidates,
                recovery_candidates,
                unbalanced_shapes,
            )
            selected_candidates = _merge_recovery_candidates(
                selected_candidates,
                recovery_candidates,
            )
            if len(selected_candidates) < CARD_LIMIT:
                single_lines = _long_line_segments(working)
                before_single_edge = len(selected_candidates)
                selected_candidates = _merge_single_edge_candidates(
                    selected_candidates,
                    _single_edge_card_candidates(
                        working,
                        edges,
                        lab,
                        selected_candidates,
                        lines=single_lines,
                    ),
                )
                if (
                    len(selected_candidates) == before_single_edge
                    and len(selected_candidates) < CARD_LIMIT
                ):
                    selected_candidates = _merge_single_edge_candidates(
                        selected_candidates,
                        _low_contrast_single_edge_candidates(
                            working,
                            edges,
                            lab,
                            selected_candidates,
                            lines=single_lines,
                        ),
                    )

    if (
        any(
            candidate.strategy.startswith(
                "low-contrast-single-edge-reconstruction"
            )
            for candidate in selected_candidates
        )
        and not any(
            "line-reconstruction" in candidate.strategy
            for candidate in candidate_alternatives
        )
    ):
        candidate_alternatives.extend(
            _line_candidates(working, edges, lab)
        )

    selected_candidates = _select_candidate_hypothesis(
        working,
        edges,
        lab,
        selected_candidates,
        candidate_alternatives,
    )
    weak_single = _weak_center_single_candidate(
        working,
        edges,
        lab,
        selected_candidates,
        candidate_alternatives,
    )
    if weak_single is not None:
        selected_candidates = [weak_single]
    selected_candidates = _replace_low_contrast_projection(
        edges,
        lab,
        selected_candidates,
        candidate_alternatives,
    )
    selected_candidates = _restore_nonoverlapping_alternatives(
        working,
        edges,
        lab,
        selected_candidates,
        candidate_alternatives,
    )
    selected_candidates = _recenter_weak_line_from_inner_region(
        working,
        selected_candidates,
        candidate_alternatives,
    )
    if line_dominated:
        selected_candidates = _refine_line_dominated_alternatives(
            working,
            edges,
            lab,
            selected_candidates,
            candidate_alternatives,
        )

    # Drop candidates that are already covered by stronger contour results
    # before paying the cost of GrabCut. The same checks still run after
    # refinement because some candidates move slightly during segmentation.
    selected_candidates = _remove_contained_fragments(
        selected_candidates
    )
    selected_candidates = _remove_reconstruction_duplicates(
        selected_candidates
    )

    selected_candidates = [
        _prefer_region_refinement(
            candidate,
            (
                _refine_card_region(
                    working,
                    candidate,
                    expansion=_refinement_expansion(
                        candidate, photo_area
                    ),
                )
                if candidate.strategy in {
                    "line-reconstruction",
                    "color-kmeans",
                    "partial-side-reconstruction",
                    "single-edge-reconstruction",
                }
                or (
                    candidate.strategy == "otsu-dark"
                    and candidate.score >= 0.995
                )
                or (
                    candidate.strategy.startswith(
                        "low-contrast-single-edge-reconstruction"
                    )
                    and candidate.score >= 0.84
                )
                else None
            ),
        )
        for candidate in selected_candidates
    ]
    selected_candidates = _arbitrate_large_center_card(
        working,
        edges,
        lab,
        selected_candidates,
    )
    selected_candidates = [
        _restore_partial_missing_side(
            lab,
            candidate,
            [
                reference
                for reference in selected_candidates
                if reference is not candidate
            ],
        )
        for candidate in selected_candidates
    ]
    selected_candidates = [
        _repair_clipped_corner(
            candidate,
            work_width,
            work_height,
            allow_inset_repair=len(selected_candidates) >= 3,
        )
        for candidate in selected_candidates
    ]
    selected_candidates = [
        candidate
        for candidate in selected_candidates
        if _opposite_side_imbalance(candidate.corners)
        <= MAX_OPPOSITE_SIDE_IMBALANCE
    ]
    selected_candidates = _remove_contained_fragments(
        selected_candidates
    )
    selected_candidates = _remove_reconstruction_duplicates(
        selected_candidates
    )

    selected = _spatial_order(selected_candidates)
    inverse_scale = 1.0 / scale
    return [
        Detection(
            corners=ordered_corners(candidate.corners * inverse_scale),
            confidence=round(candidate.score, 4),
            strategy=candidate.strategy,
            score=candidate.score,
            contrast=round(candidate.contrast, 4),
        )
        for candidate in selected
    ]
