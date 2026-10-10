from __future__ import annotations

import json
from pathlib import Path

import pytest

from woosh_studio.runtime import validate_music_bundle, verify_runtime_manifest


def test_runtime_manifest_verifies_hash_and_rejects_tampering(tmp_path: Path) -> None:
    target = tmp_path / "python.exe"
    target.write_bytes(b"runtime")
    import hashlib
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = tmp_path / "runtime-manifest.json"
    manifest.write_text(json.dumps({"version": "test", "files": [{"path": "python.exe", "size_bytes": 7, "sha256": digest}]}), encoding="utf-8")

    assert verify_runtime_manifest(manifest) == (True, "test")
    target.write_bytes(b"changed")
    assert verify_runtime_manifest(manifest) == (False, None)


def test_music_bundle_validation_requires_local_files(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="本地模型包不完整"):
        validate_music_bundle(tmp_path)

    mula = tmp_path / "HeartMuLa-oss-3B-happy-new-year"
    codec = tmp_path / "HeartCodec-oss"
    mula.mkdir()
    codec.mkdir()
    for path in (mula / "config.json", codec / "config.json", tmp_path / "tokenizer.json", tmp_path / "gen_config.json"):
        path.write_text("{}", encoding="utf-8")
    (mula / "model-00001-of-00004.safetensors").write_bytes(b"model")
    (codec / "model-00001-of-00002.safetensors").write_bytes(b"codec")
    validate_music_bundle(tmp_path)
