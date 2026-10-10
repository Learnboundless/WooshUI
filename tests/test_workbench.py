import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from woosh_studio.config import StudioPaths
from woosh_studio.main import create_app
from woosh_studio.workbench import WORKFLOW_ROOT, parse_script


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(StudioPaths(tmp_path / "app"))) as test_client:
        yield test_client


def create_project(client, tmp_path):
    response = client.post(
        "/api/v1/projects", json={"parent_directory": str(tmp_path), "name": "导入测试"}
    )
    assert response.status_code == 200
    return response.json()


def example():
    return json.loads(
        (WORKFLOW_ROOT / "assets/script.example.json").read_text(encoding="utf-8")
    )


def test_template_catalog_round_trips_and_zip_is_portable(client):
    catalog = client.get("/api/v1/agent/templates").json()
    for template in catalog:
        if template["id"] in {"script", "voices", "multilingual"}:
            response = client.post(
                "/api/v1/scripts/preview", json={"text": template["template"]}
            )
            assert response.status_code == 200, response.text
            assert response.json()["script"]["voices"]
    response = client.get("/api/v1/agent/workflow.zip")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "woosh-studio/SKILL.md" in archive.namelist()
        assert "woosh-studio/scripts/woosh_agent.py" in archive.namelist()
        assert "woosh-studio/references/api.md" in archive.namelist()
        assert all(
            not name.startswith("/") and ".." not in name for name in archive.namelist()
        )


def test_script_parser_handles_code_fences_and_never_imports_asset_links():
    data = example()
    del data["lines"][0]["voice_id"]
    data["lines"][0]["asset_id"] = "foreign-result"
    result = parse_script("```json\n" + json.dumps(data, ensure_ascii=False) + "\n```")
    assert result["script"]["lines"][0]["voice_id"] == "narrator"
    assert result["script"]["lines"][0]["asset_id"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["lines"][0].update(voice_id="missing"),
        lambda data: data["voices"].append(data["voices"][0].copy()),
        lambda data: data["lines"].append(data["lines"][0].copy()),
        lambda data: data.update(run_command="remove files"),
        lambda data: data["voices"][0].update(language="invented"),
    ],
)
def test_script_parser_rejects_ambiguous_or_unknown_fields(mutation):
    data = example()
    mutation(data)
    with pytest.raises(ValueError):
        parse_script(json.dumps(data))


def test_folder_import_preserves_nested_paths_and_existing_project(client, tmp_path):
    created = create_project(client, tmp_path)
    folder = tmp_path / "演员素材"
    (folder / "voices").mkdir(parents=True)
    sf.write(folder / "voices" / "台词.wav", np.zeros(8000), 16000)
    (folder / "script.json").write_text(json.dumps(example()), encoding="utf-8")
    (folder / "readme.exe").write_bytes(b"not executable")
    (folder / "bad.wav").write_text("not audio", encoding="utf-8")
    response = client.post(
        "/api/v1/projects/resources/import",
        json={"project_path": created["path"], "paths": [str(folder)]},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["assets"]) == 1
    assert len(result["documents"]) == 1
    assert any("bad.wav" in warning for warning in result["warnings"])
    asset = result["assets"][0]
    assert asset["relative_path"].endswith("演员素材/voices/台词.wav")
    assert asset["duration_seconds"] == 0.5
    assert (Path(created["path"]) / asset["relative_path"]).is_file()
    assert (folder / "voices" / "台词.wav").is_file()
    resolved = client.post(
        "/api/v1/projects/resources/resolve",
        json={"project_path": created["path"], "paths": [asset["relative_path"]]},
    ).json()[0]
    assert resolved["exists"]
    assert Path(resolved["absolute_path"]).is_file()
    # Script-only saving cannot overwrite newly imported audio assets.
    saved = client.put(
        "/api/v1/projects/script",
        json={
            "project_path": created["path"],
            "script": parse_script(json.dumps(example()))["script"],
        },
    ).json()
    assert len(saved["assets"]) == 1
    assert len(saved["script"]["lines"]) == 3


def test_browser_upload_sanitizes_paths_and_rejects_traversal_resolution(
    client, tmp_path
):
    created = create_project(client, tmp_path)
    wav = io.BytesIO()
    sf.write(wav, np.zeros(8000), 16000, format="WAV")
    response = client.post(
        "/api/v1/projects/resources/upload",
        data={"project_path": created["path"]},
        files=[
            ("files", ("../../voice.wav", wav.getvalue(), "audio/wav")),
            (
                "files",
                (
                    "folder/scene.json",
                    json.dumps(example()).encode(),
                    "application/json",
                ),
            ),
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["assets"]) == 1
    assert ".." not in result["assets"][0]["relative_path"]
    assert len(result["documents"]) == 1
    invalid = client.post(
        "/api/v1/projects/resources/resolve",
        json={"project_path": created["path"], "paths": ["../outside.wav"]},
    )
    assert invalid.status_code == 400


def test_generation_preflight_does_not_queue_incomplete_script(client, tmp_path):
    created = create_project(client, tmp_path)
    document = parse_script(json.dumps(example()))["script"]
    document["lines"][0]["voice_id"] = None
    client.put(
        "/api/v1/projects/script",
        json={"project_path": created["path"], "script": document},
    )
    response = client.post(
        "/api/v1/generations/speech", json={"project_path": created["path"]}
    )
    assert response.status_code == 400
    assert "没有绑定音色" in response.json()["detail"]
    assert client.get("/api/v1/jobs").json() == []


def test_export_workflow_does_not_overwrite_existing_file(client, tmp_path):
    existing = tmp_path / "woosh-studio-skill.zip"
    existing.write_bytes(b"keep")
    response = client.post("/api/v1/agent/export", json={"path": str(tmp_path)})
    assert response.status_code == 200
    assert existing.read_bytes() == b"keep"
    assert Path(response.json()["path"]).name == "woosh-studio-skill_2.zip"


def test_import_keeps_script_edits_made_while_audio_is_copying(
    client, tmp_path, monkeypatch
):
    from woosh_studio import workbench

    created = create_project(client, tmp_path)
    source = tmp_path / "voice.wav"
    sf.write(source, np.zeros(8000), 16000)
    projects = client.app.state.studio.projects
    copy = workbench.shutil.copy2

    def copy_and_edit(*args, **kwargs):
        result = copy(*args, **kwargs)
        if Path(args[0]) == source:
            projects.mutate(
                Path(created["path"]),
                lambda manifest: setattr(manifest.script, "title", "正在编辑的新标题"),
            )
        return result

    monkeypatch.setattr(workbench.shutil, "copy2", copy_and_edit)
    result = client.post(
        "/api/v1/projects/resources/import",
        json={"project_path": created["path"], "paths": [str(source)]},
    ).json()
    assert result["manifest"]["script"]["title"] == "正在编辑的新标题"
    assert len(result["manifest"]["assets"]) == 1


def test_autosave_preserves_new_generation_links_for_unchanged_lines(client, tmp_path):
    created = create_project(client, tmp_path)
    draft = parse_script(json.dumps(example()))["script"]
    client.put(
        "/api/v1/projects/script",
        json={"project_path": created["path"], "script": draft},
    )
    projects = client.app.state.studio.projects
    projects.mutate(
        Path(created["path"]),
        lambda manifest: setattr(
            manifest.script.lines[0], "asset_id", "newly-generated"
        ),
    )
    saved = client.put(
        "/api/v1/projects/script",
        json={"project_path": created["path"], "script": draft},
    ).json()
    assert saved["script"]["lines"][0]["asset_id"] == "newly-generated"
    draft["lines"][0]["text"] = "新内容需要重新生成"
    saved = client.put(
        "/api/v1/projects/script",
        json={"project_path": created["path"], "script": draft},
    ).json()
    assert saved["script"]["lines"][0]["asset_id"] is None
