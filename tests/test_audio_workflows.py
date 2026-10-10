from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from woosh_studio.config import StudioPaths
from woosh_studio.dialogue import DialogueTranslator
from woosh_studio.main import create_app
from woosh_studio.models import ModelService, MULTILINGUAL_MODEL_ID
from woosh_studio.schemas import Clip, ScriptLine, Track, VoiceProfile
from woosh_studio.storage import LibraryDatabase


def test_missing_asset_relink_and_remove_preserve_disk_files(tmp_path):
    with TestClient(create_app(StudioPaths(tmp_path / "app"))) as client:
        created = client.post(
            "/api/v1/projects",
            json={"parent_directory": str(tmp_path), "name": "素材验收"},
        ).json()
        root = Path(created["path"])
        source = tmp_path / "音频.wav"
        sf.write(source, np.zeros(1600), 16000)
        imported = client.post(
            "/api/v1/projects/import",
            json={"project_path": str(root), "source_path": str(source)},
        ).json()
        asset = imported["asset"]
        projects = client.app.state.studio.projects

        def bind(manifest):
            manifest.timeline.tracks = [
                Track(
                    clips=[
                        Clip(
                            asset_id=asset["id"],
                            name="片段",
                            source_path=asset["relative_path"],
                        )
                    ]
                )
            ]
            manifest.script.voices = [
                VoiceProfile(
                    id="hero",
                    name="角色",
                    mode="clone",
                    reference_audio=asset["relative_path"],
                )
            ]
            manifest.script.lines = [
                ScriptLine(
                    id="line",
                    character="角色",
                    text="你好",
                    voice_id="hero",
                    asset_id=asset["id"],
                )
            ]

        projects.mutate(root, bind)
        (root / asset["relative_path"]).unlink()
        health = client.post(
            "/api/v1/projects/assets/health", json={"path": str(root)}
        ).json()
        assert health["assets"][0]["exists"] is False
        relinked = client.post(
            f"/api/v1/assets/{asset['id']}/relink",
            json={"project_path": str(root), "source_path": str(source)},
        ).json()
        assert (root / relinked["assets"][0]["relative_path"]).is_file()
        assert (
            relinked["timeline"]["tracks"][0]["clips"][0]["source_path"]
            == relinked["assets"][0]["relative_path"]
        )
        removed = client.request(
            "DELETE",
            "/api/v1/projects/assets",
            json={"project_path": str(root), "asset_ids": [asset["id"]]},
        ).json()
        assert removed["assets"] == []
        assert removed["timeline"]["tracks"][0]["clips"] == []
        assert removed["script"]["lines"][0]["asset_id"] is None
        assert removed["script"]["voices"][0]["reference_audio"] is None
        assert source.is_file()
        assert (root / relinked["assets"][0]["relative_path"]).is_file()


def test_history_retains_actual_failure_after_restart(tmp_path):
    from woosh_studio.jobs import JobManager
    from woosh_studio.schemas import (
        JobEvent,
        JobKind,
        JobStatus,
        StudioError,
        ErrorCode,
    )

    database = LibraryDatabase(tmp_path / "library.sqlite3")
    job = JobEvent(
        kind=JobKind.MUSIC_GENERATION,
        status=JobStatus.FAILED,
        error=StudioError(
            code=ErrorCode.INVALID_REQUEST,
            message="无法打开 mix.wav",
            detail="失败阶段：解码完成",
        ),
    )
    database.save_job(job)
    loaded = JobManager(LibraryDatabase(tmp_path / "library.sqlite3")).get(job.id)
    assert loaded.error.message == "无法打开 mix.wav"
    assert loaded.error.detail == "失败阶段：解码完成"


def test_local_translation_routes_chinese_to_existing_model_and_reports_other_missing_models(
    tmp_path, monkeypatch
):
    paths = StudioPaths(tmp_path / "app").ensure()
    models = ModelService(paths, LibraryDatabase(paths.database))
    monkeypatch.setattr(models, "_translation_valid", lambda path: True)
    translator = DialogueTranslator(
        models, SimpleNamespace(translate=lambda text: "We must survive.")
    )
    result = translator.translate("我们必须活下去。", "Auto", "English")
    assert result["text"] == "We must survive."
    assert result["source_text"] == "我们必须活下去。"
    assert result["model_id"] == "opus-mt-zh-en"
    assert (
        translator.translate("Already English", "Auto", "English")["model_id"]
        == "identity"
    )
    with pytest.raises(RuntimeError, match="m2m100"):
        translator.translate("我们必须活下去。", "Chinese", "Japanese")


def test_multilingual_translation_uses_source_and_target_tokens(tmp_path, monkeypatch):
    import ctranslate2
    import transformers

    paths = StudioPaths(tmp_path / "app").ensure()
    models = ModelService(paths, LibraryDatabase(paths.database))
    monkeypatch.setattr(models, "_multilingual_valid", lambda path: True)

    class Tokenizer:
        src_lang = ""

        def encode(self, text):
            assert self.src_lang == "zh"
            return [1, 2]

        def get_lang_id(self, language):
            assert language == "ja"
            return 3

        def convert_ids_to_tokens(self, ids):
            return "__ja__" if ids == 3 else ["__zh__", "source"]

        def convert_tokens_to_ids(self, tokens):
            assert tokens == ["__ja__", "translation"]
            return [3, 4]

        def decode(self, ids, skip_special_tokens):
            return "生き延びよう。"

    class Engine:
        def __init__(self, path, device, compute_type):
            assert device == "cpu" and compute_type == "int8"

        def translate_batch(self, tokens, target_prefix, **kwargs):
            assert tokens == [["__zh__", "source"]]
            assert target_prefix == [["__ja__"]]
            return [SimpleNamespace(hypotheses=[["__ja__", "translation"]])]

    monkeypatch.setattr(
        transformers.M2M100Tokenizer,
        "from_pretrained",
        lambda *args, **kwargs: Tokenizer(),
    )
    monkeypatch.setattr(ctranslate2, "Translator", Engine)
    result = DialogueTranslator(models, None).translate(
        "我们要活下去。", "Chinese", "Japanese"
    )
    assert result["text"] == "生き延びよう。"
    assert result["model_id"] == MULTILINGUAL_MODEL_ID


def test_speech_sends_translated_text_and_keeps_original(tmp_path, monkeypatch):
    with TestClient(create_app(StudioPaths(tmp_path / "app"))) as client:
        studio = client.app.state.studio
        root, manifest = studio.projects.create(tmp_path, "翻译对白")
        manifest.script.target_locales = ["en"]
        manifest.script.voices = [
            VoiceProfile(id="hero", name="主角", language="English")
        ]
        manifest.script.lines = [
            ScriptLine(
                id="line",
                character="主角",
                voice_id="hero",
                text="我们要活下去。",
                language="English",
            )
        ]
        studio.projects.save(root, manifest)
        monkeypatch.setattr(studio.models, "is_installed", lambda model: True)
        monkeypatch.setattr(
            studio.dialogue,
            "translate",
            lambda text, source, target: {
                "source_text": text,
                "source_language": "Chinese",
                "target_language": "English",
                "text": "We must survive.",
                "model_id": "opus-mt-zh-en",
            },
        )

        def worker(payload, *args):
            assert payload["text"] == "We must survive."
            output = Path(payload["output_path"])
            output.parent.mkdir(parents=True, exist_ok=True)
            sf.write(output, np.zeros(1600), 16000)
            return {"sample_rate": 16000, "duration_seconds": 0.1}

        monkeypatch.setattr(studio.speech, "_run_worker", worker)
        from woosh_studio.schemas import SpeechGenerationRequest
        from woosh_studio.jobs import JobControl

        studio.speech.generation_worker(
            SpeechGenerationRequest(project_path=str(root))
        )("job", lambda **kwargs: None, JobControl())
        saved = studio.projects.open(root)
        assert saved.script.lines[0].text == "我们要活下去。"
        assert saved.script.lines[0].translation.text == "We must survive."
        asset = saved.assets[0]
        assert (
            client.get(
                "/api/v1/projects/audio",
                params={
                    "project_path": str(root),
                    "relative_path": asset.relative_path,
                },
                headers={"Range": "bytes=0-43"},
            ).status_code
            == 206
        )
        assert saved.script.lines[0].asset_id == asset.id
