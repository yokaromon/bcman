from __future__ import annotations

import hashlib
import json
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def recognition_fingerprint(
    image_path: Path,
    *,
    orientation: int,
    local_models: dict,
    ykr_models: dict,
    prompt_versions: dict,
    schema_version: int,
) -> str:
    payload = {
        "image_sha256": file_sha256(image_path),
        "orientation": orientation,
        "local_models": local_models,
        "ykr_models": ykr_models,
        "prompt_versions": prompt_versions,
        "schema_version": schema_version,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
