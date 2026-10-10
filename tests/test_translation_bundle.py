import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from woosh_studio.config import StudioPaths
from woosh_studio.main import create_app
from woosh_studio.models import ModelService, MULTILINGUAL_MODEL_ID
from woosh_studio.storage import LibraryDatabase
from woosh_studio.translation_bundle import (
    ARCHIVE_NAME,
    BUNDLE_VERSION,
    MANIFEST_NAME,
    MODEL_ID,
    MODEL_REVISION,
    REQUIRED_FILES,
    install_archive,
    inspect_archive,
    verify_directory,
)


def make_bundle(directory: Path, *, corrupt=False, extra=None):
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / ARCHIVE_NAME
    files = {name: f"fixture: {name}".encode() for name in REQUIRED_FILES}
    manifest = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "bundle_version": BUNDLE_VERSION,
        "files": [
            {
                "path": name,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for name, content in files.items()
        ],
    }
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(f"{MODEL_ID}/{MANIFEST_NAME}", json.dumps(manifest))
        for name, content in files.items():
            if corrupt and name == "model.bin":
                content = b"bad" + content[3:]
            bundle.writestr(f"{MODEL_ID}/{name}", content)
        if extra:
            bundle.writestr(extra, b"unexpected")
    return archive


def test_bundle_installs_with_no_existing_models_and_keeps_readonly_archive(tmp_path):
    archive = make_bundle(tmp_path / "installer")
    target = tmp_path / "共享模型" / MODEL_ID
    archive.chmod(0o444)
    try:
        assert install_archive(archive, target) == target.resolve()
        assert verify_directory(target)["model_id"] == MODEL_ID
        assert archive.is_file()
        stamp = (target / "model.bin").stat().st_mtime_ns
        install_archive(archive, target)
        assert (target / "model.bin").stat().st_mtime_ns == stamp
    finally:
        archive.chmod(0o644)


def test_corrupt_payload_cannot_replace_existing_model(tmp_path):
    target = tmp_path / "models" / MODEL_ID
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("previous model")
    with pytest.raises(ValueError, match="校验失败"):
        install_archive(make_bundle(tmp_path / "installer", corrupt=True), target)
    assert (target / "keep.txt").read_text() == "previous model"
    assert not (target / "model.bin").exists()
    assert not list(target.parent.glob(".*-install-*"))


def test_missing_or_modified_model_is_repaired_from_local_copy(tmp_path):
    archive = make_bundle(tmp_path / "installer")
    target = tmp_path / "models" / MODEL_ID
    install_archive(archive, target)
    original = (target / "model.bin").read_bytes()
    (target / "model.bin").write_bytes(b"x" * len(original))
    install_archive(archive, target)
    assert (target / "model.bin").read_bytes() == original
    (target / "tokenizer/vocab.json").unlink()
    install_archive(archive, target)
    assert verify_directory(target)


@pytest.mark.parametrize(
    "extra", ["../escape", f"{MODEL_ID}/../escape", f"{MODEL_ID}/rogue.txt"]
)
def test_unlisted_archive_paths_rejected_before_extraction(tmp_path, extra):
    archive = make_bundle(tmp_path / "installer", extra=extra)
    with pytest.raises(ValueError, match="清单不匹配"):
        inspect_archive(archive)
    assert not (tmp_path / "escape").exists()


def test_fresh_app_initializes_bundled_translation_before_serving_requests(
    tmp_path, monkeypatch
):
    archive = make_bundle(tmp_path / "installer")
    monkeypatch.setenv("WOOSH_STUDIO_OFFLINE_MODELS", str(archive.parent))
    monkeypatch.setenv("WOOSH_STUDIO_OFFLINE", "1")
    import httpx

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: pytest.fail("startup attempted network access"),
    )
    paths = StudioPaths(tmp_path / "app")
    with TestClient(create_app(paths)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert verify_directory(paths.models / MODEL_ID)
        entries = client.get("/api/v1/models").json()
        model = next(item for item in entries if item["id"] == MODEL_ID)
        assert model["installed"] and model["bundled"]
        assert model["model_source"] == "local"
        assert model["dependencies"] == []
        assert not any(item["id"] == "opus-mt-zh-en" for item in entries)
        assert client.get("/api/v1/jobs").json() == []
        assert client.delete(f"/api/v1/models/{MODEL_ID}").status_code == 400
    assert archive.exists()


def test_new_shared_directory_uses_existing_installer_payload(tmp_path, monkeypatch):
    archive = make_bundle(tmp_path / "installer")
    monkeypatch.setenv("WOOSH_STUDIO_OFFLINE_MODELS", str(archive.parent))
    paths = StudioPaths(tmp_path / "app").ensure()
    database = LibraryDatabase(paths.database)
    models = ModelService(paths, database)
    original = models.ensure_bundled_translation()
    database.save_settings(
        database.get_settings().model_copy(
            update={"model_root": str(tmp_path / "new-model-root")}
        )
    )
    restored = models.ensure_bundled_translation()
    assert restored != original
    assert verify_directory(restored)
    assert verify_directory(original)
    assert models.is_installed(MULTILINGUAL_MODEL_ID)
