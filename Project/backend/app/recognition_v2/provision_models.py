"""Recognition Pipeline V2 の向きモデルを固定URL・SHA-256検証付きで取得する。

デプロイ時に明示的に実行する（リクエスト時ダウンロードはしない）。
    poetry run python -m app.recognition_v2.provision_models
    poetry run python -m app.recognition_v2.provision_models --verify-only

pickup/provision_models.py と同じ設計（archive SHA-256 → 安全展開 → 各ファイルSHA-256
再検証 → 検証stamp書き込み）で、対象モデルを model_manifest.json (doc_orientationのみ)
に絞ったもの。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

from .model_runtime import write_verification_stamp


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = BASE_DIR / "model_manifest.json"
DEFAULT_MODEL_DIR = BASE_DIR.parent.parent / "models_v2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("model_manifest.jsonのschema_versionが不正です")
    models = document.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError("model_manifest.jsonにmodelsがありません")
    return document


def verify_model(model_root: Path, spec: dict) -> list[str]:
    model_dir = model_root / spec["directory"]
    problems: list[str] = []
    if not model_dir.is_dir():
        return [f"モデルディレクトリがありません: {model_dir}"]
    for relative, expected in spec["files"].items():
        target = model_dir / relative
        if not target.is_file():
            problems.append(f"必須ファイルがありません: {target}")
        elif _sha256(target).casefold() != expected.casefold():
            problems.append(f"SHA-256が一致しません: {target}")
    return problems


def _safe_members(archive: tarfile.TarFile, expected_root: str):
    prefix = expected_root.rstrip("/") + "/"
    for member in archive.getmembers():
        name = member.name.replace("\\", "/")
        if member.issym() or member.islnk():
            raise ValueError(f"リンクを含むモデルarchiveは拒否します: {name}")
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"危険なarchiveパスです: {name}")
        if name != expected_root and not name.startswith(prefix):
            raise ValueError(f"想定外のarchiveルートです: {name}")
        yield member


def _download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "bcman-model-provision/1"})
    with urllib.request.urlopen(request, timeout=90) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def provision_model(model_root: Path, key: str, spec: dict) -> None:
    existing = verify_model(model_root, spec)
    if not existing:
        print(f"OK {key}: 配置済み・SHA-256一致")
        return
    target = model_root / spec["directory"]
    if target.exists():
        raise ValueError(
            f"{target} は存在しますが検証に失敗しました。自動上書きしません: "
            + "; ".join(existing)
        )
    model_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bcman-model-") as temporary_name:
        temporary = Path(temporary_name)
        archive_path = temporary / f"{spec['directory']}.tar"
        print(f"DOWNLOAD {key}: {spec['archive_url']}")
        _download(spec["archive_url"], archive_path)
        actual = _sha256(archive_path)
        if actual.casefold() != spec["archive_sha256"].casefold():
            raise ValueError(
                f"{key} archiveのSHA-256が一致しません: expected="
                f"{spec['archive_sha256']} actual={actual}"
            )
        extracted = temporary / "extracted"
        extracted.mkdir()
        with tarfile.open(archive_path, "r:") as archive:
            archive.extractall(
                extracted,
                members=_safe_members(archive, spec["directory"]),
            )
        shutil.copytree(extracted / spec["directory"], target)
    problems = verify_model(model_root, spec)
    if problems:
        raise ValueError(f"{key} の配置後検証に失敗しました: " + "; ".join(problems))
    print(f"OK {key}: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="固定URLとSHA-256を検証してRecognition Pipeline V2の向きモデルを明示配置"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument(
        "--model",
        action="append",
        help="manifest内のmodel key。複数指定可。省略時は全モデル",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="ネットワーク接続せず配置済みモデルだけを検証",
    )
    args = parser.parse_args()
    document = _load_manifest(args.manifest.resolve())
    selected = args.model or list(document["models"])
    unknown = sorted(set(selected) - set(document["models"]))
    if unknown:
        parser.error("未知のmodel keyです: " + ", ".join(unknown))
    failures = 0
    for key in selected:
        spec = document["models"][key]
        try:
            if args.verify_only:
                problems = verify_model(args.model_dir.resolve(), spec)
                if problems:
                    raise ValueError("; ".join(problems))
                print(f"OK {key}: SHA-256一致")
            else:
                provision_model(args.model_dir.resolve(), key, spec)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            failures += 1
            print(f"FAIL {key}: {exc}")
    if failures == 0:
        write_verification_stamp(args.model_dir.resolve(), document, selected)
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
