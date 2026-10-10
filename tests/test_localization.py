import csv
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from woosh_studio.config import StudioPaths
from woosh_studio.jobs import JobControl
from woosh_studio.main import create_app
from woosh_studio.schemas import LocalizationExportRequest, ScriptLine, SpeechGenerationRequest, VoiceProfile, TranscriptionRequest


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("WOOSH_SPEECH_WORKER_FAKE", "1")
    monkeypatch.setenv("WOOSH_ASR_WORKER_FAKE", "1")
    with TestClient(create_app(StudioPaths(tmp_path / "app"))) as client:
        app = client.app.state.studio
        monkeypatch.setattr(app.models, "is_installed", lambda model: True)
        monkeypatch.setattr(app.system, "capabilities", lambda: SimpleNamespace(effective_device="cpu"))
        monkeypatch.setattr(app.dialogue, "translate", lambda text, source, target: {"source_text":text,"source_language":source,"target_language":target,"text":f"{target}: {text}","model_id":"test-translator"})
        root, manifest = app.projects.create(tmp_path, "多语言游戏")
        manifest.script.target_locales = ["zh-CN", "en", "ja"]
        manifest.script.voices = [VoiceProfile(id="hero", name="主角")]
        manifest.script.lines = [ScriptLine(id=f"line-{index}", key=f"scene.greeting.{index}", character="主角", text=f"你好，玩家。{index}", voice_id="hero") for index in range(2)]
        app.projects.save(root, manifest)
        yield app, root, client


def generate(studio, job="batch", **kwargs):
    app, root, _ = studio
    return app.speech.generation_worker(SpeechGenerationRequest(project_path=str(root), **kwargs))(job, lambda **changes: None, JobControl())


def test_two_lines_three_languages_reuse_then_regenerate_only_edited_locale(studio):
    app, root, client = studio
    first = generate(studio)
    assert len(first["asset_ids"]) == 6
    assert app.runtime.status()["load_count"] == 1
    manifest = app.projects.open(root)
    assert all(set(line.localizations) == {"zh-CN", "en", "ja"} for line in manifest.script.lines)
    ids = {locale: manifest.script.lines[0].localizations[locale].asset_id for locale in manifest.script.target_locales}
    second = generate(studio, "batch2")
    assert not second["asset_ids"] and len(second["reused_asset_ids"]) == 6
    script = manifest.script.model_dump(mode="json")
    script["lines"][0]["localizations"]["ja"]["text"] = "ようこそ、冒険者。"
    saved = client.put("/api/v1/projects/script", json={"project_path":str(root),"script":script})
    assert saved.status_code == 200, saved.text
    assert saved.json()["script"]["lines"][0]["localizations"]["ja"]["asset_id"] is None
    third = generate(studio, "batch3")
    assert len(third["asset_ids"]) == 1 and len(third["reused_asset_ids"]) == 5
    latest = app.projects.open(root)
    assert latest.script.lines[0].localizations["en"].asset_id == ids["en"]
    assert latest.script.lines[0].localizations["zh-CN"].asset_id == ids["zh-CN"]
    assert len(app.database.speech_items(job_id="batch3")) == 6


def test_game_export_matches_text_and_audio_and_rejects_missing_file(studio):
    app, root, _ = studio
    generate(studio)
    request = LocalizationExportRequest(project_path=str(root))
    exported = app.exports.export_localization(request)
    package = Path(exported["directory"])
    data = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert len(data["lines"]) == 6
    for row in data["lines"]:
        assert (package / row["audio_path"]).is_file()
        translated = json.loads((package / "text" / f"{row['locale']}.json").read_text(encoding="utf-8"))
        assert translated[row["line_id"]]["audio_path"] == row["audio_path"]
    with (package / "dialogue.csv").open(encoding="utf-8-sig",newline="") as file:
        assert len(list(csv.DictReader(file))) == 6
    source = root / app.projects.open(root).assets[0].relative_path
    source.unlink()
    with pytest.raises(ValueError, match="交付检查"):
        app.exports.export_localization(request)
    assert app.exports.export_localization(request.model_copy(update={"mode":"text"}))["line_count"] == 6


def test_locked_translation_is_not_overwritten_after_source_edit(studio):
    app, root, client = studio
    generate(studio, text_only=True)
    script = app.projects.open(root).script.model_dump(mode="json")
    script["lines"][0]["localizations"]["ja"]["locked"] = True
    script["lines"][0]["text"] = "源文修改了。"
    saved = client.put("/api/v1/projects/script",json={"project_path":str(root),"script":script})
    assert saved.status_code == 200
    result = generate(studio, "edited", text_only=True)
    assert result["partial"] and len(result["errors"]) == 1
    assert "锁定" in result["errors"][0]["message"]
    assert app.projects.open(root).script.lines[0].localizations["ja"].text == script["lines"][0]["localizations"]["ja"]["text"]


def test_partial_failure_keeps_successes_and_retry_only_generates_failed_item(studio, monkeypatch):
    app, root, _ = studio
    original = app.speech._run_worker
    def sometimes(payload, control, progress):
        if payload["language"] == "Japanese" and "0" in payload["text"]:
            raise RuntimeError("测试该语言失败")
        return original(payload, control, progress)
    monkeypatch.setattr(app.speech, "_run_worker", sometimes)
    failed = generate(studio)
    assert failed["partial"] and len(failed["asset_ids"]) == 5
    monkeypatch.setattr(app.speech, "_run_worker", original)
    retried = generate(studio, "retry")
    assert len(retried["asset_ids"]) == 1 and len(retried["reused_asset_ids"]) == 5


def test_journal_recovers_audio_after_registration_failure(studio, monkeypatch):
    app, root, _ = studio
    attach = app.speech._attach
    monkeypatch.setattr(app.speech, "_attach", lambda *args: (_ for _ in ()).throw(OSError("interrupted after rename")))
    with pytest.raises(RuntimeError):
        generate(studio, target_locales=["zh-CN"], line_ids=["line-0"])
    assert len(app.database.speech_items(status="committing")) == 1
    monkeypatch.setattr(app.speech, "_attach", attach)
    app.speech.reconcile(root)
    assert len(app.projects.open(root).assets) == 1
    assert app.projects.open(root).script.lines[0].localizations["zh-CN"].asset_id
    app.speech.reconcile(root)
    assert len(app.projects.open(root).assets) == 1


def test_transcription_accepts_project_recording_and_rejects_silence_and_traversal(studio):
    app, root, client = studio
    source = root / "Sources" / "麦克风.wav"
    sf.write(source, np.sin(np.arange(16000) * 0.04) * 0.2, 16000)
    req = TranscriptionRequest(project_path=str(root),reference_audio="Sources/麦克风.wav")
    result = app.transcription.worker(req)("recognition",lambda **changes:None,JobControl())
    assert result["text"] == "这是一段测试录音。"
    assert len(result["source_sha256"]) == 64
    sf.write(source,np.zeros(16000),16000)
    with pytest.raises(RuntimeError,match="没有可识别"):
        app.transcription.worker(req)("silent",lambda **changes:None,JobControl())
    bad = client.post("/api/v1/transcriptions",json={"project_path":str(root),"reference_audio":"../outside.wav"})
    assert bad.status_code == 400


def test_v2_migration_preserves_original_and_all_old_audio(tmp_path):
    legacy = {"schema_version":2,"name":"旧游戏", "script":{"voices":[{"id":"hero","name":"主角"}],"lines":[{"id":"l","character":"主角","text":"你好","language":"English","source_language":"Chinese","voice_id":"hero","translation":{"source_text":"你好","source_language":"Chinese","target_language":"English","text":"Hello","model_id":"old"},"asset_id":"audio"}]}}
    from woosh_studio.localization import migrate_project
    result = migrate_project(legacy)
    assert legacy["schema_version"] == 2 and result["schema_version"] == 3
    line = result["script"]["lines"][0]
    assert line["text"] == "你好" and line["localizations"]["en"]["text"] == "Hello"
    assert line["localizations"]["en"]["asset_id"] == "audio"


def test_import_v2_clears_localized_audio_references():
    from woosh_studio.workbench import parse_script
    data={"type":"woosh.script","version":2,"target_locales":["en"],"voices":[{"id":"v","name":"角色"}],"lines":[{"id":"a","voice_id":"v","character":"角色","text":"你好","localizations":{"en":{"text":"Hello","asset_id":"foreign-asset","input_fingerprint":"foreign-fingerprint"}}}]}
    imported=parse_script(json.dumps(data))["script"]["lines"][0]["localizations"]["en"]
    assert imported["asset_id"] is None and imported["input_fingerprint"] is None


def test_dotted_ids_do_not_overwrite_each_others_export(studio):
    app, root, _ = studio
    manifest = app.projects.open(root)
    manifest.script.target_locales = ["zh-CN"]
    manifest.script.lines[0].id = "chapter.start"
    manifest.script.lines[1].id = "chapter.end"
    manifest.script.lines[0].text = '你好,"玩家"\n欢迎回来。'
    app.projects.save(root,manifest)
    generate(studio)
    package = Path(app.exports.export_localization(LocalizationExportRequest(project_path=str(root)))["directory"])
    records = json.loads((package / "manifest.json").read_text(encoding="utf-8"))["lines"]
    assert len({record["audio_path"] for record in records}) == 2
    with (package / "dialogue.csv").open(encoding="utf-8-sig",newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["text"] == manifest.script.lines[0].text
