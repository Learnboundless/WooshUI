from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .audio import AudioRenderService
from .config import StudioPaths
from .exports import ExportService
from .inference import InferenceService, TranslationService
from .jobs import JobManager, TERMINAL_STATUSES
from .models import ModelService
from .music import InferenceCoordinator, MusicService
from .projects import ProjectService
from .schemas import (
    AssetTrimRequest,
    CreateProjectRequest,
    CustomModelRequest,
    ExportRequest,
    GenerationRequest,
    ImportAssetRequest,
    JobKind,
    JobStatus,
    LicenseRequest,
    MusicGenerationRequest,
    PathRequest,
    RenderRequest,
    RuntimeSettings,
    SaveProjectRequest,
    SeparateAssetRequest,
    TranslationRequest,
)
from .storage import LibraryDatabase
from .system import SystemService


class StudioContainer:
    def __init__(self, paths: StudioPaths):
        self.paths = paths.ensure()
        self.database = LibraryDatabase(paths.database)
        self.projects = ProjectService(self.database)
        self.system = SystemService(paths, self.database)
        self.models = ModelService(paths, self.database)
        offline_models = os.environ.get("WOOSH_STUDIO_OFFLINE_MODELS")
        if offline_models:
            self.models.install_offline_archives(Path(offline_models))
        self.jobs = JobManager(self.database)
        self.coordinator = InferenceCoordinator()
        self.inference = InferenceService(
            self.models,
            self.projects,
            self.system,
            self.database,
            self.coordinator.lock,
        )
        self.music = MusicService(
            self.models,
            self.projects,
            self.system,
            self.coordinator,
            self.inference.unload,
        )
        self.translation = TranslationService(self.models)
        self.renderer = AudioRenderService(self.projects)
        self.exports = ExportService(self.projects, self.renderer)


def create_app(paths: StudioPaths | None = None) -> FastAPI:
    paths = (paths or StudioPaths.from_environment()).ensure()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.studio = StudioContainer(paths)
        yield
        application.state.studio.inference.unload()

    app = FastAPI(
        title="Woosh Studio API",
        version="0.2.0",
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
            provided = request.headers.get("X-Woosh-Token") or request.query_params.get("token")
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
        return studio(request).system.capabilities()

    @app.patch("/api/v1/system/settings")
    async def update_system_settings(settings: RuntimeSettings, request: Request):
        container = studio(request)
        previous = container.database.get_settings()
        try:
            updated = container.system.update_settings(settings)
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if previous.device != updated.device or previous.active_model != updated.active_model:
            container.inference.unload()
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

    @app.post("/api/v1/projects/import")
    async def import_asset(body: ImportAssetRequest, request: Request):
        try:
            manifest, asset = studio(request).projects.import_asset(
                Path(body.project_path), Path(body.source_path)
            )
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"manifest": manifest, "asset": asset}

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
            return studio(request).models.register_custom(body.model_id, Path(body.path))
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
        if container.database.get_settings().active_model == model_id:
            container.inference.unload()
        try:
            container.models.remove(model_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"removed": True}

    @app.post("/api/v1/generations")
    async def generate(body: GenerationRequest, request: Request):
        container = studio(request)
        return container.jobs.submit(
            JobKind.GENERATION,
            body.model_dump(mode="json"),
            container.inference.generation_worker(body),
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
    async def trim_audio_asset(
        asset_id: str, body: AssetTrimRequest, request: Request
    ):
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
            translated = await asyncio.to_thread(
                studio(request).translation.translate, body.text
            )
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"original": body.text, "translated": translated}

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

        return container.jobs.submit(JobKind.RENDER, body.model_dump(mode="json"), worker)

    @app.post("/api/v1/exports")
    async def export(body: ExportRequest, request: Request):
        container = studio(request)

        def worker(job_id, update, control):
            control.checkpoint()
            update(status=JobStatus.RENDERING, stage="整理导出资源", progress=0.15)
            result = container.exports.export(body)
            update(progress=0.9, stage="写入导出清单")
            return result

        return container.jobs.submit(JobKind.EXPORT, body.model_dump(mode="json"), worker)

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
