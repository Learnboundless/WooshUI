import time
from pathlib import Path

from fastapi.testclient import TestClient

from woosh_studio.config import StudioPaths
from woosh_studio.main import create_app


def test_fake_music_generation_registers_mix_and_four_stems(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("WOOSH_MUSIC_WORKER_FAKE", "1")
    app = create_app(StudioPaths(tmp_path / "app"))
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/projects",
            json={"parent_directory": str(tmp_path), "name": "Music Project"},
        ).json()
        monkeypatch.setattr(
            app.state.studio.models,
            "is_installed",
            lambda _model_id: True,
        )

        response = client.post(
            "/api/v1/generations/music",
            json={
                "project_path": created["path"],
                "title": "Test BGM",
                "mode": "instrumental",
                "tags": ["cinematic", "120 bpm"],
                "duration_seconds": 30,
                "count": 1,
                "separate_stems": True,
                "settings": {
                    "model_id": "HeartMuLa-3B",
                    "temperature": 1,
                    "top_k": 50,
                    "cfg_scale": 1.5,
                    "seed": 42,
                    "seed_mode": "fixed",
                },
            },
        )
        assert response.status_code == 200
        job_id = response.json()["id"]
        for _ in range(400):
            job = client.get(f"/api/v1/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)

        assert job["status"] == "completed", job
        manifest = client.post(
            "/api/v1/projects/open",
            json={"path": created["path"]},
        ).json()

    assert manifest["schema_version"] == 3
    assert {asset["kind"] for asset in manifest["assets"]} == {
        "music_mix",
        "stem",
    }
    assert {asset["stem_role"] for asset in manifest["assets"]} == {
        None,
        "vocals",
        "drums",
        "bass",
        "other",
    }
    assert len({asset["generation_group_id"] for asset in manifest["assets"]}) == 1
