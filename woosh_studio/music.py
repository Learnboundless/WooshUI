from __future__ import annotations

import random
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

import soundfile as sf

from .jobs import JobControl
from .models import DEMUCS_MODEL_ID, HEARTMULA_MODEL_ID, ModelService
from .projects import ProjectService, safe_name
from .runtime import runtime_status
from .schemas import (
    GeneratedAsset,
    JobStatus,
    MusicGenerationRequest,
    SeparateAssetRequest,
)
from .system import SystemService


STEM_ROLES = ("vocals", "drums", "bass", "other")


class InferenceCoordinator:
    def __init__(self) -> None:
        self.lock = RLock()


class MusicService:
    def __init__(
        self,
        models: ModelService,
        projects: ProjectService,
        system: SystemService,
        coordinator: InferenceCoordinator,
        unload_woosh: Callable[[], None],
        runtime=None,
    ):
        self.models = models
        self.projects = projects
        self.system = system
        self.coordinator = coordinator
        self.unload_woosh = unload_woosh
        self.runtime = runtime

    def generation_worker(self, request: MusicGenerationRequest):
        def worker(job_id: str, update, control: JobControl) -> dict[str, Any]:
            if not self.models.is_installed(HEARTMULA_MODEL_ID):
                raise RuntimeError("模型尚未安装: HeartMuLa-3B")
            if request.separate_stems and not self.models.is_installed(DEMUCS_MODEL_ID):
                raise RuntimeError("生成后分轨需要先安装 Demucs-htdemucs")
            root = Path(request.project_path).expanduser().resolve()
            seeds = self._seeds(request)
            created_ids: list[str] = []
            mixes = []
            with self.runtime.sequence(control):
                for index, seed in enumerate(seeds):
                    control.checkpoint()
                    group_id = str(uuid4())
                    directory = root / "Generated" / "Music" / group_id
                    output = directory / "mix.wav"
                    base = index / len(seeds)
                    scale = 1 / len(seeds)
                    update(
                        status=JobStatus.LOADING,
                        stage=f"准备音乐变体 {index + 1}/{len(seeds)}",
                        progress=base + 0.01 * scale,
                    )
                    worker_result = self._run_worker(
                        {
                            "command": "generate",
                            "model_path": str(self.models.music_path()),
                            "output_path": str(output),
                            "mode": request.mode,
                            "lyrics": request.lyrics
                            if request.mode == "lyrics"
                            else "",
                            "tags": request.tags,
                            "duration_seconds": request.duration_seconds,
                            "performance_mode": request.settings.performance_mode,
                            "temperature": request.settings.temperature,
                            "top_k": request.settings.top_k,
                            "cfg_scale": request.settings.cfg_scale,
                            "seed": seed,
                            "device": self.system.capabilities().effective_device,
                            "memory_mode": self._memory_mode(),
                            "runtime_version": runtime_status().version,
                        },
                        control,
                        lambda event: update(
                            status=JobStatus.RUNNING,
                            stage=event.get("stage", "生成音乐"),
                            message=event.get("message", ""),
                            progress=(base + float(event.get("progress", 0)) * scale)
                            * (0.75 if request.separate_stems else 0.98),
                        ),
                    )
                    control.checkpoint()
                    if not output.is_file():
                        raise RuntimeError(f"音乐进程未在目标位置写入音频：{output}")
                    mix_asset = self._register_mix(
                        root, output, request, group_id, seed
                    )
                    if request.settings.performance_mode == "preview":
                        mix_asset.tags.append("快速预览")
                    mix_asset.music_metadata = {
                        **(mix_asset.music_metadata or {}),
                        "diagnostics": worker_result.get("diagnostics", {}),
                        "memory_mode": self._memory_mode(),
                        "performance_mode": request.settings.performance_mode,
                    }
                    self.projects.mutate(
                        root, lambda manifest: manifest.assets.append(mix_asset)
                    )
                    created_ids.append(mix_asset.id)
                    mixes.append(mix_asset)
                    self.projects.mutate(
                        root,
                        lambda manifest: setattr(
                            manifest.timeline,
                            "duration_seconds",
                            max(
                                manifest.timeline.duration_seconds,
                                mix_asset.duration_seconds,
                            ),
                        ),
                    )
                if request.separate_stems:
                    for index, mix_asset in enumerate(mixes):
                        control.checkpoint()
                        stem_assets = self._separate(
                            root,
                            mix_asset,
                            control,
                            lambda event: update(
                                status=JobStatus.RENDERING,
                                stage=event.get("stage", "分离四轨"),
                                progress=0.75
                                + (index + float(event.get("progress", 0)))
                                / len(mixes)
                                * 0.23,
                            ),
                        )
                        self.projects.mutate(
                            root, lambda manifest: manifest.assets.extend(stem_assets)
                        )
                        created_ids.extend(asset.id for asset in stem_assets)
            update(status=JobStatus.RENDERING, stage="写入项目", progress=0.99)
            return {
                "project_path": str(root),
                "asset_ids": created_ids,
            }

        return worker

    def _memory_mode(self) -> str:
        settings = self.models.database.get_settings()
        capabilities = self.system.capabilities()
        if capabilities.effective_device == "cpu":
            return "cpu"
        if settings.music_memory_mode != "auto":
            return settings.music_memory_mode
        memory = capabilities.cuda_memory_bytes or 0
        return "int8" if memory < 12 * 1024**3 else "bf16"

    def separation_worker(self, asset_id: str, request: SeparateAssetRequest):
        def worker(job_id: str, update, control: JobControl) -> dict[str, Any]:
            if not self.models.is_installed(DEMUCS_MODEL_ID):
                raise RuntimeError("模型尚未安装: Demucs-htdemucs")
            root = Path(request.project_path).expanduser().resolve()
            manifest = self.projects.open(root)
            asset = next(
                (item for item in manifest.assets if item.id == asset_id), None
            )
            if asset is None:
                raise RuntimeError("项目中不存在该音乐素材")
            if asset.kind != "music_mix":
                raise RuntimeError("只能对完整音乐混音执行分轨")
            with self.runtime.sequence(control):
                stems = self._separate(
                    root,
                    asset,
                    control,
                    lambda event: update(
                        status=JobStatus.RENDERING,
                        stage=event.get("stage", "分离四轨"),
                        message=event.get("message", ""),
                        progress=float(event.get("progress", 0)) * 0.96,
                    ),
                )
            new_stems = []

            def attach(latest):
                if not any(item.id == asset_id for item in latest.assets):
                    raise RuntimeError(
                        "原音乐素材在分轨过程中已被移除；生成文件保留在磁盘"
                    )
                existing_roles = {
                    item.stem_role
                    for item in latest.assets
                    if item.parent_asset_id == asset.id
                }
                new_stems.extend(
                    item for item in stems if item.stem_role not in existing_roles
                )
                latest.assets.extend(new_stems)

            self.projects.mutate(root, attach)
            return {
                "project_path": str(root),
                "asset_ids": [item.id for item in new_stems],
            }

        return worker

    def _register_mix(
        self,
        root: Path,
        output: Path,
        request: MusicGenerationRequest,
        group_id: str,
        seed: int,
    ) -> GeneratedAsset:
        info = sf.info(output)
        return GeneratedAsset(
            name=f"{safe_name(request.title)}_mix",
            relative_path=output.relative_to(root).as_posix(),
            kind="music_mix",
            prompt_original=",".join(request.tags),
            prompt_conditioned=",".join(request.tags),
            model_id=HEARTMULA_MODEL_ID,
            seed=seed,
            sample_rate=info.samplerate,
            channel_count=info.channels,
            duration_seconds=info.duration,
            generation_group_id=group_id,
            music_metadata={
                "mode": request.mode,
                "tags": request.tags,
                "lyrics": request.lyrics if request.mode == "lyrics" else "",
                "requested_duration_seconds": request.duration_seconds,
                "temperature": request.settings.temperature,
                "top_k": request.settings.top_k,
                "cfg_scale": request.settings.cfg_scale,
                "stems_are_post_processed": request.separate_stems,
                "runtime_version": runtime_status().version,
                "offline": runtime_status().offline,
            },
        )

    def _separate(
        self,
        root: Path,
        mix: GeneratedAsset,
        control: JobControl,
        on_progress: Callable[[dict[str, Any]], None],
    ) -> list[GeneratedAsset]:
        source = self.projects.resolve_project_file(root, mix.relative_path)
        output = source.parent / "Stems"
        self._run_worker(
            {
                "command": "separate",
                "source_path": str(source),
                "output_directory": str(output),
                "model_path": str(self.models.demucs_path()),
                "device": self.system.capabilities().effective_device,
            },
            control,
            on_progress,
        )
        assets = []
        for role in STEM_ROLES:
            target = output / f"{role}.wav"
            info = sf.info(target)
            assets.append(
                GeneratedAsset(
                    name=f"{mix.name}_{role}",
                    relative_path=target.relative_to(root).as_posix(),
                    kind="stem",
                    model_id=DEMUCS_MODEL_ID,
                    seed=mix.seed,
                    sample_rate=info.samplerate,
                    channel_count=info.channels,
                    duration_seconds=info.duration,
                    generation_group_id=mix.generation_group_id,
                    parent_asset_id=mix.id,
                    stem_role=role,
                    music_metadata={"derived_from": mix.id, "native_stem": False},
                )
            )
        return assets

    def _run_worker(
        self,
        payload: dict[str, Any],
        control: JobControl,
        on_progress: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        return self.runtime.run(
            "woosh_studio.music_worker", payload, control, on_progress
        )

    @staticmethod
    def _seeds(request: MusicGenerationRequest) -> list[int]:
        settings = request.settings
        random_source = random.SystemRandom()
        base = (
            settings.seed
            if settings.seed is not None
            else random_source.randint(0, 2**31 - 1)
        )
        if settings.seed_mode == "fixed":
            return [base] * request.count
        if settings.seed_mode == "increment":
            return [base + index for index in range(request.count)]
        return [random_source.randint(0, 2**31 - 1) for _ in range(request.count)]
