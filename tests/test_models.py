import zipfile
from contextlib import nullcontext
from pathlib import Path

import httpx
import pytest

from woosh_studio.config import StudioPaths
from woosh_studio.jobs import JobControl
from woosh_studio import models as models_module
from woosh_studio.models import (
    OFFLINE_ASSETS,
    ModelService,
    install_checkpoint_archive,
    safe_extract_zip,
)
from woosh_studio.storage import LibraryDatabase


def test_safe_extract_zip_extracts_checkpoint(tmp_path: Path) -> None:
    archive = tmp_path / "valid.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("model/config.yaml", "model: test")
        bundle.writestr("model/weights.safetensors", "weights")
    destination = tmp_path / "output"
    safe_extract_zip(archive, destination)
    assert (destination / "model" / "config.yaml").read_text() == "model: test"


def test_safe_extract_zip_rejects_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "no")
    with pytest.raises(RuntimeError, match="不安全路径"):
        safe_extract_zip(archive, tmp_path / "output")


def test_install_checkpoint_archive_flattens_model_directory(tmp_path: Path) -> None:
    archive = tmp_path / "model.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("checkpoints/release/config.yaml", "model: test")
        bundle.writestr("checkpoints/release/weights.safetensors", "weights")
    destination = tmp_path / "installed"

    install_checkpoint_archive(archive, destination)

    assert (destination / "config.yaml").is_file()
    assert (destination / "weights.safetensors").is_file()


def test_install_offline_archives_installs_and_removes_archives(tmp_path: Path) -> None:
    paths = StudioPaths(tmp_path / "app").ensure()
    archives = tmp_path / "archives"
    archives.mkdir()
    for asset in OFFLINE_ASSETS:
        model_id = Path(asset).stem
        with zipfile.ZipFile(archives / asset, "w") as bundle:
            bundle.writestr(f"checkpoints/{model_id}/config.yaml", "model: test")
            bundle.writestr(
                f"checkpoints/{model_id}/weights.safetensors", "weights"
            )

    database = LibraryDatabase(paths.database)
    service = ModelService(paths, database)
    service.install_offline_archives(archives)

    for asset in OFFLINE_ASSETS:
        assert service._checkpoint_valid(paths.models / Path(asset).stem)
        assert not (archives / asset).exists()
    assert database.license_accepted("Woosh-DFlow", "v1.0.0")
    assert database.license_accepted("Woosh-Flow", "v1.0.0")


def test_install_offline_archives_supports_dflow_only(tmp_path: Path) -> None:
    paths = StudioPaths(tmp_path / "app").ensure()
    archives = tmp_path / "archives"
    archives.mkdir()
    selected_assets = (
        "Woosh-DFlow.zip",
        "Woosh-AE.zip",
        "TextConditionerA.zip",
    )
    for asset in selected_assets:
        model_id = Path(asset).stem
        with zipfile.ZipFile(archives / asset, "w") as bundle:
            bundle.writestr(f"checkpoints/{model_id}/config.yaml", "model: test")
            bundle.writestr(
                f"checkpoints/{model_id}/weights.safetensors", "weights"
            )

    database = LibraryDatabase(paths.database)
    service = ModelService(paths, database)
    service.install_offline_archives(archives)

    assert service.is_installed("Woosh-DFlow")
    assert not service.is_installed("Woosh-Flow")
    assert database.license_accepted("Woosh-DFlow", "v1.0.0")
    assert not database.license_accepted("Woosh-Flow", "v1.0.0")
    assert not any(archives.iterdir())


def test_music_download_urls_support_domestic_and_official_sources() -> None:
    modelscope = ModelService._model_file_url(
        "modelscope",
        "HeartMuLa/HeartCodec-oss-20260123",
        "config.json",
    )
    huggingface = ModelService._model_file_url(
        "huggingface",
        "HeartMuLa/HeartCodec-oss-20260123",
        "config.json",
    )

    assert modelscope.startswith("https://www.modelscope.cn/models/")
    assert "/resolve/master/config.json" in modelscope
    assert huggingface.startswith("https://huggingface.co/")
    assert "/resolve/main/config.json" in huggingface


def test_download_uses_expected_size_when_content_length_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = StudioPaths(tmp_path / "app").ensure()
    service = ModelService(paths, LibraryDatabase(paths.database))
    payload = b"known-size-payload"
    request = httpx.Request("GET", "https://models.example/test.bin")
    response = httpx.Response(200, request=request, content=payload)
    monkeypatch.setattr(
        models_module.httpx,
        "stream",
        lambda *args, **kwargs: nullcontext(response),
    )
    progress: list[float] = []
    destination = tmp_path / "test.bin"

    service._download_file(
        str(request.url),
        destination,
        JobControl(),
        lambda value, _speed: progress.append(value),
        expected_size=len(payload),
    )

    assert destination.read_bytes() == payload
    assert progress[-1] == 1


def test_download_keeps_partial_file_when_expected_size_is_not_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = StudioPaths(tmp_path / "app").ensure()
    service = ModelService(paths, LibraryDatabase(paths.database))
    payload = b"incomplete"
    request = httpx.Request("GET", "https://models.example/test.bin")
    monkeypatch.setattr(
        models_module.httpx,
        "stream",
        lambda *args, **kwargs: nullcontext(
            httpx.Response(200, request=request, content=payload)
        ),
    )
    monkeypatch.setattr(models_module.time, "sleep", lambda _seconds: None)
    destination = tmp_path / "test.bin"

    with pytest.raises(RuntimeError, match="大小校验失败"):
        service._download_file(
            str(request.url),
            destination,
            JobControl(),
            lambda _value, _speed: None,
            expected_size=len(payload) + 1,
        )

    assert not destination.exists()
    assert destination.with_suffix(".bin.part").read_bytes() == payload


def test_download_retries_network_errors_and_resumes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = StudioPaths(tmp_path / "app").ensure()
    service = ModelService(paths, LibraryDatabase(paths.database))
    payload = b"resumed"
    request = httpx.Request("GET", "https://models.example/test.bin")
    attempts = 0

    def stream(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary", request=request)
        return nullcontext(httpx.Response(200, request=request, content=payload))

    monkeypatch.setattr(models_module.httpx, "stream", stream)
    monkeypatch.setattr(models_module.time, "sleep", lambda _seconds: None)
    destination = tmp_path / "test.bin"

    service._download_file(
        str(request.url),
        destination,
        JobControl(),
        lambda _value, _speed: None,
        expected_size=len(payload),
    )

    assert attempts == 2
    assert destination.read_bytes() == payload
