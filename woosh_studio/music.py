from __future__ import annotations

import json
import os
import queue
import random
import subprocess
import sys
from collections import deque
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Callable
from uuid import uuid4

import soundfile as sf

from .jobs import JobControl
from .models import DEMUCS_MODEL_ID, HEARTMULA_MODEL_ID, ModelService
from .projects import ProjectService, safe_name
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
    ):
        self.models = models
        self.projects = projects
        self.system = system
        self.coordinator = coordinator
        self.unload_woosh = unload_woosh

    def generation_worker(self, request: MusicGenerationRequest):
        def worker(job_id: str, update, control: JobControl) -> dict[str, Any]:
            if not self.models.is_installed(HEARTMULA_MODEL_ID):
                raise RuntimeError("模型尚未安装: HeartMuLa-3B")
            if request.separate_stems and not self.models.is_installed(DEMUCS_MODEL_ID):
                raise RuntimeError("生成后分轨需要先安装 Demucs-htdemucs")
            root = Path(request.project_path).expanduser().resolve()
            seeds = self._seeds(request)
            created_ids: list[str] = []
            with self.coordinator.lock:
                self.unload_woosh()
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
                    self._run_worker(
                        {
                            "command": "generate",
                            "model_path": str(self.models.music_path()),
                            "output_path": str(output),
                            "mode": request.mode,
                            "lyrics": request.lyrics if request.mode == "lyrics" else "",
                            "tags": request.tags,
                            "duration_seconds": request.duration_seconds,
                            "temperature": request.settings.temperature,
                            "top_k": request.settings.top_k,
                            "cfg_scale": request.settings.cfg_scale,
                            "seed": seed,
                            "device": self.system.capabilities().effective_device,
                            "memory_mode": self._memory_mode(),
                        },
                        control,
                        lambda event: update(
                            status=JobStatus.RUNNING,
                            stage=event.get("stage", "生成音乐"),
                            message=event.get("message", ""),
                            progress=base + float(event.get("progress", 0)) * 0.75 * scale,
                        ),
                    )
                    control.checkpoint()
                    manifest = self.projects.open(root)
                    mix_asset = self._register_mix(
                        root, output, request, group_id, seed
                    )
                    manifest.assets.append(mix_asset)
                    created_ids.append(mix_asset.id)
                    if request.separate_stems:
                        stem_assets = self._separate(
                            root,
                            mix_asset,
                            control,
                            lambda event: update(
                                status=JobStatus.RENDERING,
                                stage=event.get("stage", "分离四轨"),
                                message=event.get("message", ""),
                                progress=base
                                + (0.76 + float(event.get("progress", 0)) * 0.21)
                                * scale,
                            ),
                        )
                        manifest.assets.extend(stem_assets)
                        created_ids.extend(asset.id for asset in stem_assets)
                    manifest.timeline.duration_seconds = max(
                        manifest.timeline.duration_seconds,
                        mix_asset.duration_seconds,
                    )
                    self.projects.save(root, manifest)
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
            asset = next((item for item in manifest.assets if item.id == asset_id), None)
            if asset is None:
                raise RuntimeError("项目中不存在该音乐素材")
            if asset.kind != "music_mix":
                raise RuntimeError("只能对完整音乐混音执行分轨")
            with self.coordinator.lock:
                self.unload_woosh()
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
            existing_roles = {
                item.stem_role
                for item in manifest.assets
                if item.parent_asset_id == asset.id
            }
            new_stems = [item for item in stems if item.stem_role not in existing_roles]
            manifest.assets.extend(new_stems)
            self.projects.save(root, manifest)
            return {"asset_ids": [item.id for item in new_stems]}

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
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONUNBUFFERED": "1",
                "HEARTMULA_MODEL_DIR": str(self.models.music_path()),
                "TORCH_HOME": str(self.models.models_root / ".torch"),
                "HF_HOME": str(self.models.models_root / ".huggingface"),
                "MODELSCOPE_CACHE": str(self.models.models_root / ".modelscope"),
            }
        )
        process = subprocess.Popen(
            [sys.executable, "-m", "woosh_studio.music_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        assert process.stdin is not None
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.close()
        messages: queue.Queue[str | None] = queue.Queue()
        stderr_tail: deque[str] = deque(maxlen=12)

        def read_stdout() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                messages.put(line)
            messages.put(None)

        def read_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                stderr_tail.append(line.strip())

        Thread(target=read_stdout, daemon=True).start()
        Thread(target=read_stderr, daemon=True).start()
        result: dict[str, Any] | None = None
        error: str | None = None
        try:
            stream_closed = False
            while process.poll() is None or not stream_closed:
                control.checkpoint()
                try:
                    line = messages.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line is None:
                    stream_closed = True
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    stderr_tail.append(line.strip())
                    continue
                if event.get("event") == "progress":
                    on_progress(event)
                elif event.get("event") == "result":
                    result = event.get("result", {})
                elif event.get("event") == "error":
                    error = event.get("message", "音乐工作进程失败")
            exit_code = process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        if error:
            raise RuntimeError(error)
        if exit_code != 0 or result is None:
            detail = " · ".join(item for item in stderr_tail if item)
            raise RuntimeError(detail or f"音乐工作进程退出码 {exit_code}")
        return result

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
