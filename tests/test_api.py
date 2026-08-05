from pathlib import Path
from threading import Event

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from woosh_studio.config import StudioPaths
from woosh_studio.main import create_app


def test_health_project_and_models(tmp_path: Path) -> None:
    app = create_app(StudioPaths(tmp_path / "app"))
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        created = client.post(
            "/api/v1/projects",
            json={"parent_directory": str(tmp_path), "name": "API Project"},
        )
        assert created.status_code == 200
        project_path = created.json()["path"]
        opened = client.post("/api/v1/projects/open", json={"path": project_path})
        assert opened.status_code == 200
        assert opened.json()["name"] == "API Project"
        models = client.get("/api/v1/models")
        assert models.status_code == 200
        assert {model["id"] for model in models.json()} >= {
            "Woosh-DFlow",
            "Woosh-Flow",
            "HeartMuLa-3B",
            "Demucs-htdemucs",
            "opus-mt-zh-en",
        }


def test_recent_project_can_be_removed_without_deleting_project(tmp_path: Path) -> None:
    app = create_app(StudioPaths(tmp_path / "app"))
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/projects",
            json={"parent_directory": str(tmp_path), "name": "Recent Project"},
        ).json()
        project_path = created["path"]
        assert any(
            item["path"] == project_path
            for item in client.get("/api/v1/projects/recent").json()
        )

        removed = client.request(
            "DELETE",
            "/api/v1/projects/recent",
            json={"path": project_path},
        )

        assert removed.status_code == 200
        assert removed.json() == {"removed": True}
        assert Path(project_path).exists()
        assert all(
            item["path"] != project_path
            for item in client.get("/api/v1/projects/recent").json()
        )


def test_token_authentication(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WOOSH_STUDIO_TOKEN", "test-token")
    app = create_app(StudioPaths(tmp_path / "app"))
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 401
        assert (
            client.get(
                "/api/v1/health", headers={"X-Woosh-Token": "test-token"}
            ).status_code
            == 200
        )


def test_token_authentication_allows_cors_preflight(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WOOSH_STUDIO_TOKEN", "test-token")
    app = create_app(StudioPaths(tmp_path / "app"))
    with TestClient(app) as client:
        for origin in ("http://tauri.localhost", "https://tauri.localhost"):
            response = client.options(
                "/api/v1/models",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "x-woosh-token",
                },
            )

            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin


def test_duplicate_model_download_returns_active_job(tmp_path: Path, monkeypatch) -> None:
    app = create_app(StudioPaths(tmp_path / "app"))
    release_worker = Event()

    def worker(_job_id, _update, _control):
        release_worker.wait(timeout=2)
        return {"installed": []}

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.studio.models, "download_worker", lambda _model_id: worker)
        first = client.post("/api/v1/models/Woosh-DFlow/download")
        second = client.post("/api/v1/models/Woosh-DFlow/download")
        release_worker.set()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_trim_asset_api_creates_derived_project_asset(tmp_path: Path) -> None:
    app = create_app(StudioPaths(tmp_path / "app"))
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/projects",
            json={"parent_directory": str(tmp_path), "name": "Trim API"},
        ).json()
        root = Path(created["path"])
        source = tmp_path / "input.wav"
        audio = np.zeros(48000, dtype=np.float32)
        audio[12000:36000] = 0.2
        sf.write(source, audio, 48000)
        imported = client.post(
            "/api/v1/projects/import",
            json={"project_path": str(root), "source_path": str(source)},
        ).json()

        response = client.post(
            f"/api/v1/assets/{imported['asset']['id']}/trim",
            json={"project_path": str(root), "mode": "trim_silence"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset"]["parent_asset_id"] == imported["asset"]["id"]
    assert payload["asset"]["source"] == "rendered"
    assert len(payload["manifest"]["assets"]) == 2
