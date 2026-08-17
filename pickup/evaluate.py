from __future__ import annotations

import argparse
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from bcpickup import SUPPORTED_EXTENSIONS
from detector import CARD_LIMIT, quadrilateral_iou


BASE_DIR = Path(__file__).resolve().parent
MAX_ELAPSED_MS = 20_000
GROUND_TRUTH_SCHEMA_VERSION = 2
MANUAL_ANNOTATION_METHOD = "manual-four-corner"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_names(input_dir: Path) -> set[str]:
    return {
        path.name
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    }


def _load_ground_truth(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != GROUND_TRUTH_SCHEMA_VERSION:
        raise ValueError(
            "Ground Truthが旧形式です。検出結果から複製した正解データは評価に"
            "使用できません。annotate_ground_truth.pyで人手アノテーションしてください"
        )
    if data.get("annotation_method") != MANUAL_ANNOTATION_METHOD:
        raise ValueError(
            "Ground Truthはmanual-four-corner方式で作成されていません"
        )
    if not isinstance(data.get("images"), dict):
        raise ValueError("Ground Truthのimagesが不正です")
    return data


def _best_matching(ious: list[list[float]]) -> list[tuple[int, int, float]]:
    expected_count = len(ious)
    detected_count = len(ious[0]) if ious else 0

    @lru_cache(maxsize=None)
    def solve(
        expected_index: int, used: int
    ) -> tuple[float, tuple[tuple[int, int, float], ...]]:
        if expected_index >= expected_count:
            return 0.0, ()
        best_score, best_pairs = solve(expected_index + 1, used)
        for detected_index in range(detected_count):
            bit = 1 << detected_index
            if used & bit:
                continue
            remainder, pairs = solve(expected_index + 1, used | bit)
            score = ious[expected_index][detected_index] + remainder
            if score > best_score:
                best_score = score
                best_pairs = (
                    (
                        expected_index,
                        detected_index,
                        ious[expected_index][detected_index],
                    ),
                ) + pairs
        return best_score, best_pairs

    return list(solve(0, 0)[1])


def evaluate(
    ground_truth_path: Path,
    output_dir: Path,
    input_dir: Path,
    require_all_inputs: bool = True,
) -> int:
    try:
        ground_truth = _load_ground_truth(ground_truth_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL Ground Truth: {exc}")
        return 2

    expected_names = set(ground_truth["images"])
    current_names = _input_names(input_dir)
    failures = 0
    unannotated = sorted(current_names - expected_names)
    if require_all_inputs:
        for source_name in unannotated:
            print(f"FAIL {source_name}: 人手アノテーションがありません")
            failures += 1
    elif unannotated:
        print(
            f"INFO 未アノテーション{len(unannotated)}画像は"
            "--annotated-only評価の対象外です"
        )
    for source_name in sorted(expected_names - current_names):
        print(f"FAIL {source_name}: Ground Truthの原画像がありません")
        failures += 1
    if not current_names & expected_names:
        print("FAIL 評価できる人手アノテーションがありません")
        failures += 1

    for source_name in sorted(current_names & expected_names):
        expected = ground_truth["images"][source_name]
        source = input_dir / source_name
        if expected.get("annotation_method") != MANUAL_ANNOTATION_METHOD:
            print(f"FAIL {source_name}: 人手4隅アノテーションではありません")
            failures += 1
            continue
        if _sha256(source) != expected.get("source_sha256"):
            print(f"FAIL {source_name}: 原画像がアノテーション時と一致しません")
            failures += 1
            continue
        expected_cards = expected.get("cards")
        if not isinstance(expected_cards, list) or not expected_cards:
            print(f"FAIL {source_name}: 正解の名刺が1枚以上ありません")
            failures += 1
            continue
        if len(expected_cards) > CARD_LIMIT:
            print(
                f"INFO {source_name}: 正解{len(expected_cards)}枚は"
                f"自動検出上限{CARD_LIMIT}枚を超えています"
            )

        result_path = output_dir / Path(source_name).stem / "result.json"
        if not result_path.exists():
            print(f"FAIL {source_name}: result.json がありません")
            failures += 1
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        detected_cards = result.get("cards", [])
        ious = [
            [
                quadrilateral_iou(
                    np.float32(expected_card["corners"]),
                    np.float32(detected_card["corners"]),
                )
                for detected_card in detected_cards
            ]
            for expected_card in expected_cards
        ]
        pairs = _best_matching(ious)
        count_ok = len(expected_cards) == len(detected_cards)
        all_ious = len(pairs) == len(expected_cards) and all(
            pair[2] >= 0.90 for pair in pairs
        )
        elapsed_ms = float(result["elapsed_ms"])
        performance_ok = elapsed_ms <= MAX_ELAPSED_MS
        passed = count_ok and all_ious and performance_ok
        failures += not passed
        values = ", ".join(
            f"{value:.3f}" for _, _, value in sorted(pairs)
        )
        print(
            f"{'PASS' if passed else 'FAIL'} {source_name}: "
            f"expected={len(expected_cards)} detected={len(detected_cards)} "
            f"IoU=[{values}] elapsed={elapsed_ms:.0f}ms"
        )
    return 0 if failures == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="独立した人手Ground TruthによるCard Extraction評価"
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=BASE_DIR / "ground_truth.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "output",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=BASE_DIR / "picture",
    )
    parser.add_argument(
        "--annotated-only",
        action="store_true",
        help="未アノテーション画像を除外して登録済み画像だけを評価します",
    )
    args = parser.parse_args()
    return evaluate(
        args.ground_truth.resolve(),
        args.output_dir.resolve(),
        args.input_dir.resolve(),
        require_all_inputs=not args.annotated_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
