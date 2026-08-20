from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from detector import read_image
from model_runtime import PaddleModels
from orientation import OrientationEngine, RIGHT_ANGLES, rotate_clockwise
from text_regions import LocalTextPipeline


BASE_DIR = Path(__file__).resolve().parent


def relative_corrections_are_consistent(results: list[dict]) -> bool:
    if len(results) != len(RIGHT_ANGLES):
        return False
    if any(item.get("status") != "auto_confirmed" for item in results):
        return False
    baseline = int(results[0]["rotation_applied"])
    return all(
        int(item["rotation_applied"]) == (baseline - synthetic_rotation) % 360
        for synthetic_rotation, item in zip(RIGHT_ANGLES, results, strict=True)
    )


def evaluate_consistency(
    output_dir: Path,
    *,
    limit: int | None = None,
    use_ocr_fallback: bool = True,
) -> tuple[int, dict]:
    cards = sorted(output_dir.glob("*/card??.png"))
    if limit is not None:
        cards = cards[:limit]
    if not cards:
        raise ValueError(f"card??.pngがありません: {output_dir}")
    models = PaddleModels()
    text = LocalTextPipeline(models)
    engine = OrientationEngine(models)
    started = time.perf_counter()
    report = {
        "schema_version": 1,
        "test": "synthetic-four-rotation-consistency",
        "card_count": len(cards),
        "variant_count": len(cards) * 4,
        "use_ocr_fallback": use_ocr_fallback,
        "consistent_cards": 0,
        "inconsistent_cards": 0,
        "uncertain_variants": 0,
        "failures": [],
    }
    scorer = text.readability if use_ocr_fallback else None
    for card_path in cards:
        image = read_image(card_path)
        results = []
        for synthetic_rotation in RIGHT_ANGLES:
            _, result = engine.analyze(
                rotate_clockwise(image, synthetic_rotation),
                readability_scorer=scorer,
            )
            results.append(result)
        report["uncertain_variants"] += sum(
            item["status"] != "auto_confirmed" for item in results
        )
        if relative_corrections_are_consistent(results):
            report["consistent_cards"] += 1
        else:
            report["inconsistent_cards"] += 1
            report["failures"].append(
                {
                    "card": str(card_path.relative_to(output_dir)),
                    "statuses": [item["status"] for item in results],
                    "corrections": [item["rotation_applied"] for item in results],
                }
            )
    report["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    report["consistency_rate"] = round(
        report["consistent_cards"] / len(cards), 6
    )
    return (0 if report["inconsistent_cards"] == 0 else 2), report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="抽出カードを人工的に4方向へ回し、向き補正の相対整合性を評価"
    )
    parser.add_argument("--output-dir", type=Path, default=BASE_DIR / "output")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--classifier-only", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        code, report = evaluate_consistency(
            args.output_dir.resolve(),
            limit=args.limit,
            use_ocr_fallback=not args.classifier_only,
        )
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
