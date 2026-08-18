from __future__ import annotations

import re
from difflib import SequenceMatcher


def _normalized(value: str | None) -> str:
    return re.sub(r"\W", "", value or "", flags=re.UNICODE).casefold()


def _similarity(left: str | None, right: str | None) -> float:
    a, b = _normalized(left), _normalized(right)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b)) + 0.25
    return SequenceMatcher(None, a, b).ratio()


def align_ocr_lines(local_document: dict, ykr_document: dict) -> list[dict]:
    """順序を壊さないDPでykr行とローカル文字領域を対応付ける。"""
    local = local_document.get("regions", [])
    lines = ykr_document.get("lines", [])
    n, m = len(lines), len(local)
    gap = -0.34
    scores = [[0.0] * (m + 1) for _ in range(n + 1)]
    moves = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        scores[i][0], moves[i][0] = scores[i - 1][0] + gap, "line"
    for j in range(1, m + 1):
        scores[0][j], moves[0][j] = scores[0][j - 1] + gap, "region"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            similarity = _similarity(lines[i - 1].get("text"), local[j - 1].get("text"))
            candidates = {
                "match": scores[i - 1][j - 1] + similarity - 0.25,
                "line": scores[i - 1][j] + gap,
                "region": scores[i][j - 1] + gap,
            }
            move = max(candidates, key=candidates.get)
            scores[i][j], moves[i][j] = candidates[move], move

    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i or j:
        move = moves[i][j]
        if move == "match":
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif move == "line":
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()

    result = []
    for line_index, region_index in pairs:
        line = lines[line_index] if line_index is not None else None
        region = local[region_index] if region_index is not None else None
        similarity = _similarity(
            line.get("text") if line else None,
            region.get("text") if region else None,
        )
        matched = line is not None and region is not None and similarity >= 0.42
        if line is not None and region is not None and not matched:
            result.append(
                {
                    **line,
                    "region_id": None,
                    "local_text": None,
                    "alignment_status": "unmatched",
                    "alignment_score": round(similarity, 6),
                }
            )
            result.append(
                {
                    "line_id": None,
                    "text": None,
                    "source": None,
                    "legibility": None,
                    "region_id": region["region_id"],
                    "local_text": region.get("text"),
                    "alignment_status": "unmatched",
                    "alignment_score": round(similarity, 6),
                }
            )
        else:
            result.append(
                {
                    "line_id": line.get("line_id") if line else None,
                    "text": line.get("text") if line else None,
                    "source": line.get("source") if line else None,
                    "legibility": line.get("legibility") if line else None,
                    "region_id": region.get("region_id") if region and matched else None,
                    "local_text": region.get("text") if region else None,
                    "alignment_status": "matched" if matched else "unmatched",
                    "alignment_score": round(similarity, 6),
                }
            )
    return result
