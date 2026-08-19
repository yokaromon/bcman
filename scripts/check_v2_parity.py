"""pickup/ と Project/backend/app/recognition_v2/ の移植元ファイルが揃っているか確認する。

Recognition Pipeline V2 は pickup/ で検証したコードを Project/backend/app/recognition_v2/
へ移植したもの。一部のファイル（detector.py・orientation.py・alignment.py・text_regions.py・
recognition_contract.py・prompts・schemas）は両側で同一内容であることを前提にしている。
本番側だけを直して pickup へ戻し忘れる事故が実際に起きたため（2026-08-18、model_runtime.py
のスレッドセーフ化・std::exceptionリトライ）、このスクリプトで機械的に検知する。

使い方:
    python scripts/check_v2_parity.py

コミット前フックからは scripts/hooks/pre-commit 経由で自動実行される
（有効化は `git config core.hooksPath scripts/hooks` を一度実行するだけ）。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PICKUP = REPO_ROOT / "pickup"
V2 = REPO_ROOT / "Project" / "backend" / "app" / "recognition_v2"

# 両側でバイト同一（改行コード差は無視）であるべきファイル。
# ここに載っているファイルを片方だけ直したら、このスクリプトが差分を検知する。
SHARED_FILES = [
    "detector.py",
    "orientation.py",
    "alignment.py",
    "text_regions.py",
    "recognition_contract.py",
    "local_contact.py",
    "prompts/v1/ocr.txt",
    "prompts/v2/contact.txt",
    "schemas/v1/contact_response.schema.json",
    "schemas/v1/ykr_ocr_response.schema.json",
]

# 意図的に内容が異なる（本番固有の配線がある）ファイル。差分があっても失敗にはしないが、
# 一方を直したときはもう一方も見るべきかどうかを人手で判断してほしいという注意喚起だけ出す。
ADAPTED_FILES = [
    "ykr_client.py",
    "model_runtime.py",
    "model_manifest.json",
]


def _normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def main() -> int:
    if not PICKUP.is_dir() or not V2.is_dir():
        print(f"SKIP: {PICKUP} または {V2} が見つかりません")
        return 0

    mismatches: list[str] = []
    missing: list[str] = []

    for relative in SHARED_FILES:
        pickup_path, v2_path = PICKUP / relative, V2 / relative
        if not pickup_path.is_file() or not v2_path.is_file():
            missing.append(relative)
            continue
        if _normalized(pickup_path) != _normalized(v2_path):
            mismatches.append(relative)

    if missing:
        print("MISSING（片方にしか無い。移植漏れの可能性）:")
        for name in missing:
            print(f"  - {name}")

    if mismatches:
        print("DIFF（pickup/ と Project/backend/app/recognition_v2/ で内容が違う）:")
        for name in mismatches:
            print(f"  - {name}")
        print()
        print("本番側だけ直した場合は pickup/ へ、pickup/ 側だけ直した場合は")
        print("Project/backend/app/recognition_v2/ へ同じ修正を反映してください。")

    for relative in ADAPTED_FILES:
        pickup_path, v2_path = PICKUP / relative, V2 / relative
        if pickup_path.is_file() and v2_path.is_file() and _normalized(pickup_path) != _normalized(v2_path):
            print(f"NOTE: {relative} は意図的な適応差分があります（要否は人手で判断）")

    if missing or mismatches:
        return 1
    print(f"OK: 共有ファイル{len(SHARED_FILES)}件、一致を確認しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
