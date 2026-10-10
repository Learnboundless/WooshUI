from types import SimpleNamespace

import httpx
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from woosh_studio.config import StudioPaths
from woosh_studio.freesound import FreesoundService
from woosh_studio.main import create_app
from woosh_studio.schemas import RuntimeSettings
from woosh_studio.storage import LibraryDatabase
from woosh_studio.projects import ProjectService


def test_freesound_search_uses_official_text_endpoint_and_strips_html(
    monkeypatch, tmp_path
):
    paths = StudioPaths(tmp_path / "app").ensure()
    database = LibraryDatabase(paths.database)
    database.save_settings(RuntimeSettings(freesound_api_key="secret"))
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "id": 123,
                        "name": "Whisper",
                        "description": "<p>Soft <b>voice</b></p>",
                        "username": "actor",
                        "license": "Creative Commons 0",
                        "duration": 2.5,
                        "tags": ["voice"],
                        "previews": {
                            "preview-hq-mp3": "https://cdn.freesound.org/previews/1/123.mp3"
                        },
                        "url": "https://freesound.org/s/123/",
                        "filesize": 12,
                        "samplerate": 48000,
                        "channels": 1,
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "get", get)
    result = FreesoundService(ProjectService(database), database).search(
        "whisper", 1, 20, None
    )
    assert calls[0][0].endswith("/search/text/")
    assert calls[0][1]["params"]["token"] == "secret"
    assert result["results"][0]["description"] == "Soft voice"
    assert result["results"][0]["preview_url"].startswith("https://cdn.freesound.org/")


def test_freesound_search_requires_token_but_status_is_safe(tmp_path):
    paths = StudioPaths(tmp_path / "app").ensure()
    db = LibraryDatabase(paths.database)
    service = FreesoundService(ProjectService(db), db)
    assert service.status() == {"configured": False, "website": "https://freesound.org"}
    with pytest.raises(PermissionError):
        service.search("voice", 1, 20, None)


def test_freesound_import_records_attribution_and_keeps_mp3_when_probe_unavailable(
    monkeypatch, tmp_path
):
    paths = StudioPaths(tmp_path / "app").ensure()
    db = LibraryDatabase(paths.database)
    projects = ProjectService(db)
    root, _ = projects.create(tmp_path, "Freesound 项目")
    mp3 = b"fake-mp3-preview"
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200, content=mp3, headers={"content-type": "audio/mpeg"}
        ),
    )
    monkeypatch.setattr(
        sf,
        "info",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("MP3 codec unavailable")
        ),
    )
    request = SimpleNamespace(
        sound_id=123,
        preview_url="https://cdn.freesound.org/previews/1/123.mp3",
        name="Whisper",
        username="actor",
        license="Creative Commons 0",
        sound_url="https://freesound.org/s/123/",
        duration=2.5,
    )
    result = FreesoundService(projects, db).import_preview(request, root)
    asset = result["asset"]
    assert (root / asset.relative_path).read_bytes() == mp3
    assert asset.duration_seconds == 2.5
    assert asset.music_metadata["sound_id"] == 123
    assert "actor" in asset.music_metadata["attribution"]


def test_freesound_routes_are_available_and_key_can_be_saved(tmp_path):
    with TestClient(create_app(StudioPaths(tmp_path / "app"))) as client:
        status = client.get("/api/v1/freesound/status")
        assert status.status_code == 200
        assert status.json()["configured"] is False
        settings = client.patch(
            "/api/v1/system/settings",
            json={
                "device": "auto",
                "active_model": "Woosh-DFlow",
                "active_music_model": "HeartMuLa-3B",
                "model_root": None,
                "model_download_source": "auto",
                "music_memory_mode": "auto",
                "language": "zh-CN",
                "theme": "system",
                "freesound_api_key": "test-key",
            },
        )
        assert settings.status_code == 200
        assert settings.json()["freesound_api_key"] == "test-key"
        assert client.get("/api/v1/freesound/status").json()["configured"] is True
