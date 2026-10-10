from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from .audio import AudioRenderService
from .config import StudioPaths
from .exports import ExportService
from .freesound import FreesoundService
from .dialogue import DialogueTranslator
from .inference import InferenceService, TranslationService
from .jobs import JobManager, TERMINAL_STATUSES
from .models import DEMUCS_MODEL_ID, HEARTMULA_MODEL_ID, ModelService
from .music import MusicService
from .speech import SpeechService
from .model_runtime import ModelRuntimeManager
from .transcription import TranscriptionService
from .localization import normalize_edits
from .schemas import (
    TranscriptionRequest,
    LocalizationExportRequest,
    AudioAnalysisRequest,
    AudioProtectionRequest,
)
from .projects import ProjectService
from .runtime import runtime_status
from .schemas import (
    AssetTrimRequest,
    FreesoundSearchRequest,
    FreesoundImportRequest,
    AssetDeleteRequest,
    AssetRelinkRequest,
    ScriptPreviewRequest,
    SaveScriptRequest,
    ResourceImportRequest,
    ResourceResolveRequest,
    CreateProjectRequest,
    CustomModelRequest,
    ExportRequest,
    GenerationRequest,
    ImportAssetRequest,
    JobKind,
    JobStatus,
    LicenseRequest,
    MusicGenerationRequest,
    SpeechGenerationRequest,
    PathRequest,
    RenderRequest,
    RuntimeSettings,
    SaveProjectRequest,
    SeparateAssetRequest,
    TranslationRequest,
)
from .storage import LibraryDatabase
from .system import SystemService
from . import workbench


class StudioContainer:
    def __init__(self, paths: StudioPaths):
        self.paths = paths.ensure()
        self.database = LibraryDatabase(paths.database)
        self.projects = ProjectService(self.database)
        self.freesound = FreesoundService(self.projects, self.database)
        self.system = SystemService(paths, self.database)
        self.models = ModelService(paths, self.database)
        offline_models = os.environ.get("WOOSH_STUDIO_OFFLINE_MODELS")
        if offline_models:
            self.models.install_offline_archives(Path(offline_models))
        else:
            self.models.ensure_bundled_translation()
        self.jobs = JobManager(self.database)
        self.runtime = ModelRuntimeManager(
            lambda: self.models.models_root, self.database.get_settings
        )
        self.coordinator = self.runtime
        self.inference = InferenceService(
            self.models,
            self.projects,
            self.system,
            self.database,
            self.coordinator.lock,
            self.runtime,
        )
        self.translation = TranslationService(self.models)
        self.dialogue = DialogueTranslator(self.models, self.translation)
        self.speech = SpeechService(
            self.models,
            self.projects,
            self.system,
            self.coordinator,
            self.dialogue,
            self.runtime,
        )
        for pending_root in {
            item["project_path"]
            for item in self.database.speech_items(status="committing")
        }:
            self.speech.reconcile(Path(pending_root))
        self.music = MusicService(
            self.models,
            self.projects,
            self.system,
            self.coordinator,
            self.inference.unload,
            self.runtime,
        )
        self.transcription = TranscriptionService(
            self.models, self.projects, self.system, self.runtime
        )
        self.renderer = AudioRenderService(self.projects)
        self.exports = ExportService(self.projects, self.renderer, self.models)


def create_app(paths: StudioPaths | None = None) -> FastAPI:
    paths = (paths or StudioPaths.from_environment()).ensure()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.studio = StudioContainer(paths)
        try:
            yield
        finally:
            await application.state.studio.jobs.shutdown()
            await asyncio.to_thread(application.state.studio.runtime.close)
            application.state.studio.translation.unload()
            application.state.studio.dialogue.unload()

    app = FastAPI(
        title="Woosh Studio API",
        version="0.2.2",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "http://tauri.localhost",
            "tauri://localhost",
            "https://tauri.localhost",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        expected = os.environ.get("WOOSH_STUDIO_TOKEN")
        if (
            expected
            and request.method != "OPTIONS"
            and request.url.path.startswith("/api/v1")
        ):
            provided = request.headers.get("X-Woosh-Token") or request.query_params.get(
                "token"
            )
            if provided != expected:
                return StreamingResponse(
                    iter([json.dumps({"detail": "Invalid application token"})]),
                    status_code=401,
                    media_type="application/json",
                )
        return await call_next(request)

    def studio(request: Request) -> StudioContainer:
        return request.app.state.studio

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/system/capabilities")
    async def system_capabilities(request: Request):
        container = studio(request)
        capabilities = container.system.capabilities()
        status = runtime_status().model_copy(
            update={
                "heartmula_ready": container.models.is_installed(HEARTMULA_MODEL_ID),
                "heartcodec_ready": container.models.is_installed(HEARTMULA_MODEL_ID),
                "demucs_ready": container.models.is_installed(DEMUCS_MODEL_ID),
            }
        )
        return capabilities.model_copy(update={"runtime": status})

    @app.patch("/api/v1/system/settings")
    async def update_system_settings(settings: RuntimeSettings, request: Request):
        container = studio(request)
        previous = container.database.get_settings()

        def change():
            changed_model = any(
                getattr(previous, name) != getattr(settings, name)
                for name in (
                    "device",
                    "active_model",
                    "model_root",
                    "music_memory_mode",
                )
            )
            from contextlib import nullcontext

            with container.runtime.maintenance() if changed_model else nullcontext():
                updated = container.system.update_settings(settings)
                if previous.model_root != updated.model_root:
                    container.translation.unload()
                    container.dialogue.unload()
                    container.models.ensure_bundled_translation()
                return updated

        try:
            updated = await asyncio.to_thread(change)
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return updated

    @app.get("/api/v1/projects/recent")
    async def recent_projects(request: Request):
        return studio(request).database.recent_projects()

    @app.delete("/api/v1/projects/recent")
    async def remove_recent_project(body: PathRequest, request: Request):
        removed = studio(request).database.forget_project(Path(body.path))
        return {"removed": removed}

    @app.post("/api/v1/projects")
    async def create_project(body: CreateProjectRequest, request: Request):
        try:
            root, manifest = studio(request).projects.create(
                Path(body.parent_directory), body.name, body.description
            )
        except FileExistsError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"path": str(root), "manifest": manifest}

    @app.post("/api/v1/projects/open")
    async def open_project(body: PathRequest, request: Request):
        try:
            return studio(request).projects.open(Path(body.path))
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.put("/api/v1/projects")
    async def save_project(body: SaveProjectRequest, request: Request):
        try:
            return studio(request).projects.save(Path(body.project_path), body.manifest)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/v1/projects/assets/health")
    async def asset_health(body: PathRequest, request: Request):
        try:
            return await asyncio.to_thread(
                studio(request).projects.asset_health, Path(body.path)
            )
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.delete("/api/v1/projects/assets")
    async def remove_assets(body: AssetDeleteRequest, request: Request):
        try:
            return studio(request).projects.remove_assets(
                Path(body.project_path), body.asset_ids
            )
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/assets/{asset_id}/relink")
    async def relink_asset(asset_id: str, body: AssetRelinkRequest, request: Request):
        try:
            return studio(request).projects.relink_asset(
                Path(body.project_path), asset_id, Path(body.source_path)
            )
        except (OSError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/projects/import")
    async def import_asset(body: ImportAssetRequest, request: Request):
        try:
            manifest, asset = studio(request).projects.import_asset(
                Path(body.project_path), Path(body.source_path)
            )
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"manifest": manifest, "asset": asset}

    @app.put("/api/v1/projects/script")
    async def save_script(body: SaveScriptRequest, request: Request):
        try:
            projects = studio(request).projects
            root = Path(body.project_path)

            def replace_script(manifest):
                old_lines = {line.id: line for line in manifest.script.lines}
                old_voices = {voice.id: voice for voice in manifest.script.voices}
                new_voices = {voice.id: voice for voice in body.script.voices}
                for line in body.script.lines:
                    old = old_lines.get(line.id)
                    if (
                        old
                        and old.asset_id
                        and line.asset_id is None
                        and old.model_dump(exclude={"asset_id"})
                        == line.model_dump(exclude={"asset_id"})
                        and old_voices.get(line.voice_id)
                        == new_voices.get(line.voice_id)
                    ):
                        line.asset_id = old.asset_id
                normalize_edits(manifest.script, body.script)
                manifest.script = body.script

            return projects.mutate(root, replace_script)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/scripts/preview")
    async def preview_script(body: ScriptPreviewRequest):
        try:
            return workbench.parse_script(body.text)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/v1/agent/templates")
    async def agent_templates():
        return workbench.workflow_catalog()

    @app.get("/api/v1/agent/workflow.zip")
    async def download_workflow():
        return Response(
            workbench.workflow_zip(),
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="woosh-studio-skill.zip"'
            },
        )

    @app.post("/api/v1/agent/export")
    async def export_workflow(body: PathRequest):
        directory = Path(body.path).expanduser().resolve()
        if not directory.is_dir():
            raise HTTPException(status_code=400, detail="请选择已存在的导出文件夹")
        try:
            target = ProjectService._unique_path(directory, "woosh-studio-skill.zip")
            target.write_bytes(workbench.workflow_zip())
            return {"path": str(target)}
        except OSError as error:
            raise HTTPException(
                status_code=400, detail=f"无法导出 Skill 包：{error}"
            ) from error

    @app.get("/api/v1/freesound/status")
    async def freesound_status(request: Request):
        return studio(request).freesound.status()

    @app.post("/api/v1/freesound/search")
    async def freesound_search(body: FreesoundSearchRequest, request: Request):
        try:
            return await asyncio.to_thread(
                studio(request).freesound.search,
                body.query,
                body.page,
                body.page_size,
                body.filter,
            )
        except PermissionError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/api/v1/freesound/import")
    async def freesound_import(body: FreesoundImportRequest, request: Request):
        try:
            return await asyncio.to_thread(
                studio(request).freesound.import_preview,
                body,
                Path(body.project_path).expanduser().resolve(),
            )
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/api/v1/projects/resources/resolve")
    async def resolve_resources(body: ResourceResolveRequest, request: Request):
        root = Path(body.project_path).expanduser().resolve()
        try:
            studio(request).projects.open(root)
            result = []
            for value in body.paths:
                path = Path(value).expanduser()
                # Existing absolute references remain usable; new imports are project relative.
                resolved = (
                    path.resolve()
                    if path.is_absolute()
                    else ProjectService.resolve_project_file(root, value)
                )
                result.append(
                    {
                        "path": value,
                        "absolute_path": str(resolved),
                        "exists": resolved.is_file(),
                    }
                )
            return result
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/projects/resources/import")
    async def import_resource_paths(body: ResourceImportRequest, request: Request):
        try:
            files, warnings = await asyncio.to_thread(
                workbench.collect_paths, body.paths
            )
            return await asyncio.to_thread(
                workbench.import_resources,
                studio(request).projects,
                Path(body.project_path),
                files,
                warnings,
            )
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/projects/resources/upload")
    async def upload_resources(
        request: Request,
        project_path: str = Form(...),
        files: list[UploadFile] = File(...),
    ):
        try:
            if len(files) > workbench.MAX_FILES:
                raise ValueError("一次最多导入 200 个文件")
            total = 0
            warnings = []
            with tempfile.TemporaryDirectory(prefix="woosh-import-") as temporary:
                collected = []
                for index, upload in enumerate(files):
                    name = upload.filename or "unnamed"
                    suffix = Path(name).suffix.lower()
                    if (
                        suffix
                        not in workbench.AUDIO_EXTENSIONS
                        | workbench.DOCUMENT_EXTENSIONS
                    ):
                        warnings.append(f"不支持的文件类型：{name}")
                        continue
                    destination = Path(temporary) / f"{index}{suffix}"
                    size = 0
                    limit = (
                        workbench.MAX_AUDIO_BYTES
                        if suffix in workbench.AUDIO_EXTENSIONS
                        else workbench.MAX_DOCUMENT_BYTES
                    )
                    with destination.open("wb") as output:
                        while chunk := await upload.read(1024 * 1024):
                            size += len(chunk)
                            total += len(chunk)
                            if size > limit or total > workbench.MAX_BATCH_BYTES:
                                raise ValueError(
                                    "文件超过导入上限：音频 200 MB、模板 2 MB、合计 1 GB"
                                )
                            output.write(chunk)
                    collected.append((destination, name))
                return await asyncio.to_thread(
                    workbench.import_resources,
                    studio(request).projects,
                    Path(project_path),
                    collected,
                    warnings,
                )
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        finally:
            for upload in files:
                await upload.close()

    @app.get("/api/v1/projects/audio")
    async def project_audio(
        request: Request,
        project_path: str = Query(...),
        relative_path: str = Query(...),
    ):
        try:
            path = studio(request).projects.resolve_project_file(
                Path(project_path), relative_path
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not path.is_file():
            raise HTTPException(status_code=404, detail="音频文件不存在")
        return FileResponse(path)

    @app.get("/api/v1/models")
    async def models(request: Request):
        return studio(request).models.list_models()

    @app.post("/api/v1/models/license")
    async def accept_license(body: LicenseRequest, request: Request):
        studio(request).database.accept_license(body.model_id, body.release)
        return {"accepted": True, "model_id": body.model_id, "release": body.release}

    @app.post("/api/v1/models/register")
    async def register_model(body: CustomModelRequest, request: Request):
        try:
            return studio(request).models.register_custom(
                body.model_id, Path(body.path)
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/models/{model_id}/download")
    async def download_model(model_id: str, request: Request):
        container = studio(request)
        existing = next(
            (
                job
                for job in container.jobs.list()
                if job.kind == JobKind.MODEL_DOWNLOAD
                and job.payload.get("model_id") == model_id
                and job.status not in TERMINAL_STATUSES
            ),
            None,
        )
        if existing is not None:
            return existing
        try:
            worker = container.models.download_worker(model_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="未知模型") from error
        return container.jobs.submit(
            JobKind.MODEL_DOWNLOAD, {"model_id": model_id}, worker
        )

    @app.delete("/api/v1/models/{model_id}")
    async def remove_model(model_id: str, request: Request):
        container = studio(request)

        def remove():
            with container.runtime.maintenance():
                container.translation.unload()
                container.dialogue.unload()
                container.models.remove(model_id)

        try:
            await asyncio.to_thread(remove)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"removed": True}

    @app.post("/api/v1/generations")
    async def generate(body: GenerationRequest, request: Request):
        container = studio(request)
        return container.jobs.submit(
            JobKind.GENERATION,
            body.model_dump(mode="json"),
            container.inference.generation_worker(body),
        )

    @app.get("/api/v1/models/runtime")
    async def model_runtime(request: Request):
        return studio(request).runtime.status()

    @app.post("/api/v1/models/runtime/release")
    async def release_models(request: Request):
        try:
            await asyncio.to_thread(studio(request).runtime.release)
            return studio(request).runtime.status()
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/models/{model_id}/preload")
    async def preload_model(model_id: str, request: Request):
        from .models import (
            QWEN_TTS_BASE_MODEL_ID,
            QWEN_TTS_CUSTOM_MODEL_ID,
            WHISPER_MODEL_ID,
        )

        container = studio(request)
        if not container.models.is_installed(model_id):
            raise HTTPException(status_code=400, detail="模型尚未安装")
        mapping = {
            QWEN_TTS_BASE_MODEL_ID: ("speech_worker", "generate"),
            QWEN_TTS_CUSTOM_MODEL_ID: ("speech_worker", "generate"),
            WHISPER_MODEL_ID: ("asr_worker", "transcribe"),
            HEARTMULA_MODEL_ID: ("music_worker", "generate"),
            DEMUCS_MODEL_ID: ("music_worker", "separate"),
        }
        if model_id not in mapping:
            raise HTTPException(status_code=400, detail="该模型会在首次使用时自动加载")
        module, operation = mapping[model_id]

        def worker(job_id, update, control):
            return container.runtime.run(
                "woosh_studio." + module,
                {
                    "command": "load",
                    "operation": operation,
                    "model_id": model_id,
                    "model_path": str(container.models.model_path(model_id)),
                    "device": container.system.capabilities().effective_device,
                    "memory_mode": container.music._memory_mode()
                    if model_id == HEARTMULA_MODEL_ID
                    else "default",
                },
                control,
                lambda event: update(
                    status=JobStatus.LOADING,
                    stage=event.get("stage", "预加载模型"),
                    progress=event.get("progress", 0),
                ),
            )

        return container.jobs.submit(
            JobKind.MODEL_PRELOAD, {"model_id": model_id}, worker
        )

    @app.post("/api/v1/assets/{asset_id}/protect")
    async def protect_audio(
        asset_id: str, body: AudioProtectionRequest, request: Request
    ):
        try:
            return await asyncio.to_thread(
                studio(request).renderer.protect_asset, asset_id, body.project_path
            )
        except (OSError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/projects/audio/analysis")
    async def audio_analysis(body: AudioAnalysisRequest, request: Request):
        from .signal_analysis import analyze_audio

        container = studio(request)
        try:
            root = Path(body.project_path).expanduser().resolve()
            await asyncio.to_thread(container.projects.open, root)
            path = container.projects.resolve_project_file(root, body.relative_path)
            return await asyncio.to_thread(analyze_audio, path)
        except (OSError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/transcriptions")
    async def transcribe_reference(body: TranscriptionRequest, request: Request):
        container = studio(request)
        try:
            await asyncio.to_thread(container.transcription.validate, body)
        except (ValueError, OSError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return container.jobs.submit(
            JobKind.TRANSCRIPTION,
            body.model_dump(mode="json"),
            container.transcription.worker(body),
        )

    @app.post("/api/v1/exports/localization")
    async def export_localization(body: LocalizationExportRequest, request: Request):
        container = studio(request)

        def worker(job_id, update, control):
            control.checkpoint()
            return container.exports.export_localization(body)

        return container.jobs.submit(
            JobKind.EXPORT, body.model_dump(mode="json"), worker
        )

    @app.get("/api/v1/jobs/{job_id}/items")
    async def job_items(job_id: str, request: Request):
        return studio(request).database.speech_items(job_id=job_id)

    @app.post("/api/v1/jobs/{job_id}/retry")
    async def retry_job(job_id: str, request: Request):
        container = studio(request)
        try:
            old = container.jobs.get(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error
        if old.status not in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="任务仍在执行")
        if old.kind != JobKind.SPEECH_GENERATION:
            raise HTTPException(
                status_code=400, detail="请从对应页面重新提交该类型任务"
            )
        body = SpeechGenerationRequest.model_validate({**old.payload, "force": False})
        return container.jobs.submit(
            JobKind.SPEECH_GENERATION,
            body.model_dump(mode="json"),
            container.speech.generation_worker(body),
        )

    @app.post("/api/v1/generations/speech")
    async def generate_speech(body: SpeechGenerationRequest, request: Request):
        container = studio(request)
        try:
            container.speech.validate_request(body)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return container.jobs.submit(
            JobKind.SPEECH_GENERATION,
            body.model_dump(mode="json"),
            container.speech.generation_worker(body),
        )

    @app.post("/api/v1/generations/music")
    async def generate_music(body: MusicGenerationRequest, request: Request):
        container = studio(request)
        return container.jobs.submit(
            JobKind.MUSIC_GENERATION,
            body.model_dump(mode="json"),
            container.music.generation_worker(body),
        )

    @app.post("/api/v1/assets/{asset_id}/separate")
    async def separate_music_asset(
        asset_id: str, body: SeparateAssetRequest, request: Request
    ):
        container = studio(request)
        return container.jobs.submit(
            JobKind.STEM_SEPARATION,
            {"asset_id": asset_id, **body.model_dump(mode="json")},
            container.music.separation_worker(asset_id, body),
        )

    @app.post("/api/v1/assets/{asset_id}/trim")
    async def trim_audio_asset(asset_id: str, body: AssetTrimRequest, request: Request):
        try:
            manifest, asset, details = await asyncio.to_thread(
                studio(request).renderer.trim_asset,
                asset_id,
                body,
            )
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"manifest": manifest, "asset": asset, "details": details}

    @app.post("/api/v1/translate")
    async def translate(body: TranslationRequest, request: Request):
        try:
            result = await asyncio.to_thread(
                studio(request).dialogue.translate,
                body.text,
                body.source_language,
                body.target_language,
            )
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "original": body.text,
            "translated": result["text"],
            "translation": result,
        }

    @app.post("/api/v1/renders/preview")
    async def render_preview(body: RenderRequest, request: Request):
        path = await asyncio.to_thread(studio(request).renderer.preview, body)
        return {"path": str(path)}

    @app.post("/api/v1/renders")
    async def render(body: RenderRequest, request: Request):
        container = studio(request)

        def worker(job_id, update, control):
            control.checkpoint()
            update(status=JobStatus.RENDERING, stage="混合轨道", progress=0.2)
            path = container.renderer.render(body)
            return {"path": str(path)}

        return container.jobs.submit(
            JobKind.RENDER, body.model_dump(mode="json"), worker
        )

    @app.post("/api/v1/exports")
    async def export(body: ExportRequest, request: Request):
        container = studio(request)

        def worker(job_id, update, control):
            control.checkpoint()
            update(status=JobStatus.RENDERING, stage="整理导出资源", progress=0.15)
            result = container.exports.export(body)
            update(progress=0.9, stage="写入导出清单")
            return result

        return container.jobs.submit(
            JobKind.EXPORT, body.model_dump(mode="json"), worker
        )

    @app.get("/api/v1/jobs")
    async def list_jobs(request: Request):
        return studio(request).jobs.list()

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        try:
            return studio(request).jobs.get(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error

    @app.post("/api/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, request: Request):
        try:
            return studio(request).jobs.cancel(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error

    @app.post("/api/v1/jobs/{job_id}/pause")
    async def pause_job(job_id: str, request: Request):
        try:
            return studio(request).jobs.pause(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error

    @app.post("/api/v1/jobs/{job_id}/resume")
    async def resume_job(job_id: str, request: Request):
        try:
            return studio(request).jobs.resume(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error

    @app.get("/api/v1/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request):
        container = studio(request)

        async def event_stream():
            previous = None
            while True:
                if await request.is_disconnected():
                    break
                try:
                    job = container.jobs.get(job_id)
                except KeyError:
                    yield 'event: error\ndata: {"detail":"任务不存在"}\n\n'
                    break
                payload = job.model_dump_json()
                if payload != previous:
                    yield f"event: job\ndata: {payload}\n\n"
                    previous = payload
                if job.status in TERMINAL_STATUSES:
                    break
                await asyncio.sleep(0.35)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


app = create_app()


def run() -> None:
    uvicorn.run(
        "woosh_studio.main:app",
        host="127.0.0.1",
        port=int(os.environ.get("WOOSH_STUDIO_PORT", "8765")),
        log_level=os.environ.get("WOOSH_STUDIO_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    run()
