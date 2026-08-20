import hashlib
import json

import pytest

import model_runtime
from model_runtime import ModelConfigurationError, verify_model_files


def _manifest(content: bytes):
    return {
        "schema_version": 1,
        "runtime": {},
        "models": {
            "sample": {
                "directory": "sample-model",
                "files": {"inference.bin": hashlib.sha256(content).hexdigest()},
            }
        },
    }


def test_verification_stamp_skips_unchanged_file_rehash(tmp_path, monkeypatch):
    content = b"pinned model"
    directory = tmp_path / "sample-model"
    directory.mkdir()
    target = directory / "inference.bin"
    target.write_bytes(content)
    manifest = _manifest(content)
    verify_model_files(["sample"], tmp_path, manifest)

    monkeypatch.setattr(
        model_runtime,
        "_sha256",
        lambda path: (_ for _ in ()).throw(AssertionError("rehashされた")),
    )
    assert verify_model_files(["sample"], tmp_path, manifest)["sample"] == directory.resolve()


def test_changed_model_cannot_use_old_verification_stamp(tmp_path):
    content = b"pinned model"
    directory = tmp_path / "sample-model"
    directory.mkdir()
    target = directory / "inference.bin"
    target.write_bytes(content)
    manifest = _manifest(content)
    verify_model_files(["sample"], tmp_path, manifest)
    target.write_bytes(content + b" changed")
    with pytest.raises(ModelConfigurationError, match="SHA-256"):
        verify_model_files(["sample"], tmp_path, manifest)
