import time
from pathlib import Path

from fastapi.testclient import TestClient

from woosh_studio.config import StudioPaths
from woosh_studio.main import create_app


def test_fake_script_speech_generation_registers_voice_lines(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("WOOSH_SPEECH_WORKER_FAKE", "1")
    app = create_app(StudioPaths(tmp_path / "app"))
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/projects",
            json={"parent_directory": str(tmp_path), "name": "剧本项目"},
        ).json()
        manifest = created["manifest"]
        voice = {
            "id": "hero",
            "name": "主角",
            "mode": "custom_voice",
            "language": "Chinese",
            "speaker": "Vivian",
            "instruct": "坚定但温柔",
            "reference_audio": None,
            "reference_text": "",
        }
        line = {
            "id": "line-1",
            "character": "主角",
            "text": "我们出发吧。",
            "voice_id": "hero",
            "language": "Chinese",
            "instruct": "带一点决心",
            "enabled": True,
            "asset_id": None,
        }
        manifest["script"] = {"title": "测试剧本", "voices": [voice], "lines": [line]}
        saved = client.put(
            "/api/v1/projects",
            json={"project_path": created["path"], "manifest": manifest},
        )
        assert saved.status_code == 200
        monkeypatch.setattr(
            app.state.studio.models, "is_installed", lambda _model_id: True
        )
        response = client.post(
            "/api/v1/generations/speech", json={"project_path": created["path"]}
        )
        assert response.status_code == 200
        job_id = response.json()["id"]
        for _ in range(300):
            job = client.get(f"/api/v1/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.03)
        assert job["status"] == "completed", job
        opened = client.post(
            "/api/v1/projects/open", json={"path": created["path"]}
        ).json()
    assert (
        len([asset for asset in opened["assets"] if asset["kind"] == "voice_line"]) == 1
    )
    assert opened["script"]["lines"][0]["asset_id"]


def test_speech_completion_preserves_concurrent_script_edits(tmp_path, monkeypatch):
    from woosh_studio.schemas import ScriptDocument, SpeechGenerationRequest
    from woosh_studio.workbench import parse_script, WORKFLOW_ROOT

    app = create_app(StudioPaths(tmp_path / "app"))
    with TestClient(app):
        studio = app.state.studio
        root, manifest = studio.projects.create(tmp_path, "编辑中")
        script = parse_script(
            (WORKFLOW_ROOT / "assets/script.example.json").read_text(encoding="utf-8")
        )["script"]
        manifest.script = ScriptDocument.model_validate(script)
        studio.projects.save(root, manifest)
        monkeypatch.setattr(studio.models, "is_installed", lambda _id: True)

        def generate_and_edit(payload, control, progress):
            output = Path(payload["output_path"])
            output.parent.mkdir(parents=True, exist_ok=True)
            import soundfile as sf
            import numpy as np
            sf.write(output, np.ones(2400, dtype="float32") * 0.1, 24000)

            def edit(latest):
                latest.script.lines[0].text = "用户的新台词"

            studio.projects.mutate(root, edit)
            return {"sample_rate": 24000, "duration_seconds": 1}

        monkeypatch.setattr(studio.speech, "_run_worker", generate_and_edit)
        worker = studio.speech.generation_worker(
            SpeechGenerationRequest(
                project_path=str(root), line_ids=[manifest.script.lines[0].id]
            )
        )

        class Control:
            def checkpoint(self):
                pass

        result = worker("generation-123", lambda **kwargs: None, Control())
        latest = studio.projects.open(root)
        assert latest.script.lines[0].text == "用户的新台词"
        assert latest.script.lines[0].asset_id is None
        assert len(latest.assets) == 1
        assert latest.assets[0].id in result["asset_ids"]
