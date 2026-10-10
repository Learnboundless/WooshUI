from __future__ import annotations

import os
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

import soundfile as sf

from .jobs import JobCancelled, JobControl
from .languages import LOCALES, locale_for
from .localization import (edit_signature, effective_voice, file_digest, prepare_text,
                           source_language, speech_fingerprint, text_current)
from .model_runtime import ModelRuntimeManager, model_revision
from .models import QWEN_TTS_BASE_MODEL_ID, QWEN_TTS_CUSTOM_MODEL_ID
from .schemas import DialogueTranslation, GeneratedAsset, JobStatus, LocalizedLine


class SpeechCoordinator:
    def __init__(self):
        self.lock = RLock()


class SpeechService:
    def __init__(self, models, projects, system, coordinator, translator=None, runtime=None):
        self.models, self.projects, self.system = models, projects, system
        self.coordinator, self.translator = coordinator, translator
        self.runtime = runtime or ModelRuntimeManager(lambda: models.models_root)
        self.database = models.database

    def _selected(self, manifest, request):
        selected = [line for line in manifest.script.lines if line.enabled and (not request.line_ids or line.id in request.line_ids)]
        if not selected:
            raise ValueError("剧本中没有可生成的启用台词")
        if request.line_ids and set(request.line_ids) - {line.id for line in selected}:
            raise ValueError("选中的台词已删除或停用，请刷新后重试")
        return selected

    def _locales(self, script, line, request):
        return request.target_locales or script.target_locales or [locale_for(line.language if line.language != "Auto" else source_language(script, line))]

    @staticmethod
    def _model_id(voice):
        return QWEN_TTS_BASE_MODEL_ID if voice.mode == "clone" else QWEN_TTS_CUSTOM_MODEL_ID

    def _reference(self, root, voice):
        if not voice.reference_audio:
            return None
        path = Path(voice.reference_audio).expanduser()
        return path.resolve() if path.is_absolute() else self.projects.resolve_project_file(root, voice.reference_audio)

    def validate_request(self, request):
        root = Path(request.project_path).expanduser().resolve()
        manifest = self.projects.open(root)
        voices = {voice.id: voice for voice in manifest.script.voices}
        for line in self._selected(manifest, request):
            if source_language(manifest.script, line) not in {value[0] for value in LOCALES.values()}:
                raise ValueError("不支持的原文语言")
            if not line.text.strip():
                raise ValueError(f"角色“{line.character}”有空台词")
            for locale in self._locales(manifest.script, line, request):
                if locale not in LOCALES:
                    raise ValueError(f"不支持的语言: {locale}")
                if request.text_only:
                    continue
                profile = voices.get(line.voice_id)
                if profile is None:
                    raise ValueError(f"角色“{line.character}”没有绑定音色")
                voice = effective_voice(profile, locale)
                model_id = self._model_id(voice)
                if not self.models.is_installed(model_id):
                    raise ValueError(f"模型尚未安装: {model_id}")
                if voice.mode == "clone":
                    reference = self._reference(root, voice)
                    if reference is None or not voice.reference_text.strip():
                        raise ValueError(f"角色“{profile.name}”需要参考音频及其准确台词文本")
                    if not reference.is_file():
                        raise ValueError(f"角色“{profile.name}”的参考音频不存在：{reference}")

    def _attach(self, root, data):
        asset = GeneratedAsset.model_validate(data["asset"])
        localized = LocalizedLine.model_validate(data["localized"])
        def attach(latest):
            if not any(item.id == asset.id for item in latest.assets):
                latest.assets.append(asset)
            current = next((line for line in latest.script.lines if line.id == data["line_id"]), None)
            profile = next((voice for voice in latest.script.voices if current and voice.id == current.voice_id), None)
            if current and profile and edit_signature(current) == data["line_signature"]:
                voice = effective_voice(profile, data["locale"])
                reference = self._reference(root, voice)
                reference_hash = file_digest(reference) if reference and reference.is_file() else ""
                present = current.localizations.get(data["locale"])
                candidate = present if present is not None else localized
                fingerprint = speech_fingerprint(latest.script, current, data["locale"], candidate, voice, data["model_revision"], reference_hash)
                if fingerprint == data["fingerprint"] and text_current(latest.script, current, candidate):
                    # Keep a concurrently edited display-only subtitle or review state.
                    result = candidate.model_copy(update={"asset_id": asset.id, "input_fingerprint": fingerprint})
                    current.localizations[data["locale"]] = result
                    if current.language == LOCALES[data["locale"]][0] or len(latest.script.target_locales) == 1:
                        current.asset_id = asset.id
                        current.translation = DialogueTranslation(source_text=result.source_text, source_language=result.source_language,
                            target_language=LOCALES[data["locale"]][0], text=result.text, model_id=result.model_id)
            latest.timeline.duration_seconds = max(latest.timeline.duration_seconds, asset.duration_seconds)
        self.projects.mutate(root, attach)

    def reconcile(self, root):
        for item in self.database.speech_items(project_path=root, status="committing"):
            data = item["data"]["commit"]
            try:
                final = self.projects.resolve_project_file(root, data["asset"]["relative_path"])
                temporary = self.projects.resolve_project_file(root, data["temporary_path"])
                if not final.is_file() and temporary.is_file():
                    os.replace(temporary, final)
                if not final.is_file() or file_digest(final) != data["asset"]["music_metadata"]["audio_sha256"]:
                    raise ValueError("待恢复配音文件缺失或校验失败")
                self._attach(root, data)
                self.database.save_speech_item(item["job_id"], item["line_id"], item["locale"], root, "completed", item["fingerprint"], asset_id=data["asset"]["id"])
            except (OSError, ValueError, RuntimeError) as error:
                self.database.save_speech_item(item["job_id"], item["line_id"], item["locale"], root, "failed", error=str(error))

    def generation_worker(self, request):
        def worker(job_id, update, control: JobControl) -> dict[str, Any]:
            self.validate_request(request)
            root = Path(request.project_path).expanduser().resolve()
            created, reused, errors = [], [], []
            update(status=JobStatus.QUEUED, stage="等待模型服务", progress=0)
            with self.runtime.sequence(control):
                self.reconcile(root)
                manifest = self.projects.open(root)
                voices = {voice.id: voice for voice in manifest.script.voices}
                items = [(line, locale) for line in self._selected(manifest, request) for locale in self._locales(manifest.script, line, request)]
                if not request.text_only:
                    items.sort(key=lambda item: (self._model_id(effective_voice(voices[item[0].voice_id], item[1])), item[0].voice_id, item[1]))
                for line, locale in items:
                    self.database.save_speech_item(job_id, line.id, locale, root, "queued")
                for index, (line, locale) in enumerate(items):
                    control.checkpoint()
                    temporary = None
                    commit_pending = False
                    fingerprint = None
                    try:
                        self.database.save_speech_item(job_id, line.id, locale, root, "running")
                        update(status=JobStatus.RUNNING, stage=f"准备 {LOCALES[locale][1]}文本 {index + 1}/{len(items)}", progress=index / len(items))
                        original_locale = line.localizations.get(locale)
                        original_dump = original_locale.model_dump() if original_locale else None
                        localized = prepare_text(manifest.script, line, locale, self.translator)
                        def save_text(latest):
                            current = next((item for item in latest.script.lines if item.id == line.id), None)
                            if current and edit_signature(current) == edit_signature(line) and source_language(latest.script, current) == source_language(manifest.script, line):
                                present = current.localizations.get(locale)
                                if (present.model_dump() if present else None) == original_dump:
                                    current.localizations[locale] = localized.model_copy(deep=True)
                        self.projects.mutate(root, save_text)
                        if request.text_only:
                            self.database.save_speech_item(job_id, line.id, locale, root, "completed", text=localized.text)
                            continue
                        voice = effective_voice(voices[line.voice_id], locale)
                        model_id = self._model_id(voice)
                        model_path = self.models.model_path(model_id)
                        version = model_revision(model_path)
                        reference = self._reference(root, voice)
                        reference_hash = file_digest(reference) if reference else ""
                        fingerprint = speech_fingerprint(manifest.script, line, locale, localized, voice, version, reference_hash)
                        asset = next((item for item in manifest.assets if item.id == localized.asset_id), None)
                        if not request.force and asset and localized.input_fingerprint == fingerprint:
                            file = self.projects.resolve_project_file(root, asset.relative_path)
                            if file.is_file() and (asset.music_metadata or {}).get("audio_sha256") == file_digest(file):
                                reused.append(asset.id)
                                self.database.save_speech_item(job_id, line.id, locale, root, "completed", fingerprint, asset_id=asset.id, reused=True)
                                continue
                        spoken = (localized.spoken_text or localized.text).strip()
                        if __import__("re").search(r"\{[^{}]+\}|%\d*\$?[sd]|<[^<>]+>", spoken):
                            raise ValueError("朗读文本包含变量或富文本标记，请填写实际朗读文本")
                        output = root / "Generated" / "Voice" / locale / f"{uuid4().hex}.wav"
                        temporary = output.with_suffix(".partial.wav")
                        worker_result = self._run_worker({
                            "command": "generate", "job_id": job_id, "item_id": f"{line.id}:{locale}",
                            "model_id": model_id, "model_path": str(model_path), "model_revision": version,
                            "output_path": str(temporary), "mode": voice.mode, "text": spoken,
                            "language": LOCALES[locale][0], "speaker": voice.speaker,
                            "instruct": line.instruct or voice.instruct, "reference_audio": str(reference) if reference else None,
                            "reference_text": voice.reference_text, "device": self.system.capabilities().effective_device,
                        }, control, lambda event: update(status=JobStatus.LOADING if event.get("progress", 1) < 0.1 else JobStatus.RUNNING,
                            stage=f"{event.get('stage', '生成配音')} · {locale} {index + 1}/{len(items)}",
                            progress=(index + float(event.get("progress", 0))) / len(items)))
                        if not temporary.is_file():
                            raise RuntimeError(f"配音进程未在目标位置写入音频：{temporary}")
                        info = sf.info(temporary)
                        if info.frames <= 0 or info.duration <= 0:
                            raise RuntimeError("模型返回空音频")
                        asset = GeneratedAsset(name=f"{line.character}_{locale}_{line.key or line.id}",
                            relative_path=output.relative_to(root).as_posix(), kind="voice_line", model_id=model_id,
                            sample_rate=info.samplerate, channel_count=info.channels, duration_seconds=info.duration,
                            music_metadata={"script_line_id": line.id, "locale": locale, "language": LOCALES[locale][0],
                                "source_text": line.text, "spoken_text": spoken, "character": line.character,
                                "voice_id": line.voice_id, "voice_name": voices[line.voice_id].name,
                                "voice_mode": voice.mode, "model_revision": version, "input_fingerprint": fingerprint,
                                "audio_sha256": file_digest(temporary), "reference_sha256": reference_hash, "speech_diagnostics": worker_result.get("diagnostics",{})})
                        localized = localized.model_copy(update={"asset_id": asset.id, "input_fingerprint": fingerprint})
                        data = {"asset": asset.model_dump(mode="json"), "localized": localized.model_dump(),
                                "line_id": line.id, "locale": locale, "line_signature": edit_signature(line),
                                "fingerprint": fingerprint, "model_revision": version,
                                "temporary_path": temporary.relative_to(root).as_posix()}
                        # Journal first; restart reconciles a crash between rename and registration.
                        self.database.save_speech_item(job_id, line.id, locale, root, "committing", fingerprint, commit=data)
                        commit_pending = True
                        os.replace(temporary, output)
                        self._attach(root, data)
                        created.append(asset.id)
                        self.database.save_speech_item(job_id, line.id, locale, root, "completed", fingerprint, asset_id=asset.id)
                        commit_pending = False
                    except JobCancelled:
                        self.database.save_speech_item(job_id, line.id, locale, root, "cancelled", fingerprint)
                        raise
                    except Exception as error:
                        errors.append({"line_id": line.id, "locale": locale, "message": str(error)})
                        if not commit_pending:
                            self.database.save_speech_item(job_id, line.id, locale, root, "failed", fingerprint, error=str(error))
                        if not request.continue_on_error:
                            raise
                    finally:
                        if temporary and temporary.exists() and not commit_pending:
                            temporary.unlink()
                if errors and len(errors) == len(items):
                    raise RuntimeError("；".join(error["message"] for error in errors[:3]))
            return {"project_path": str(root), "asset_ids": created, "reused_asset_ids": reused,
                    "total": len(items), "completed": len(items) - len(errors), "errors": errors, "partial": bool(errors)}
        return worker

    def _run_worker(self, payload, control, on_progress):
        return self.runtime.run("woosh_studio.speech_worker", payload, control, on_progress)
