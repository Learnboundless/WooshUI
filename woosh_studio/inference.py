from __future__ import annotations

import gc
import random
import time
from pathlib import Path
from threading import Lock, RLock
from typing import Any

import numpy as np
import soundfile as sf

from .audio import trim_boundary_silence
from .jobs import JobControl
from .models import ModelService
from .projects import ProjectService, safe_name
from .schemas import GeneratedAsset, GenerationRequest, JobStatus
from .storage import LibraryDatabase
from .system import SystemService


SAMPLE_RATE = 48000
LATENT_CHANNELS = 128
LATENT_FRAMES = 501


class InferenceService:
    def __init__(
        self,
        models: ModelService,
        projects: ProjectService,
        system: SystemService,
        database: LibraryDatabase,
        inference_lock: RLock | None = None,
        runtime=None,
    ):
        self.runtime = runtime
        self._loaded_revision = None
        self.models = models
        self.projects = projects
        self.system = system
        self.database = database
        self._model: Any = None
        self._model_id: str | None = None
        self._device: str | None = None
        self._lock = inference_lock or RLock()

    def unload(self) -> None:
        had_loaded_model = self._model is not None
        self._model = None
        self._model_id = None
        self._device = None
        gc.collect()
        if not had_loaded_model:
            return
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except (ImportError, OSError):
            pass

    def generation_worker(self, request: GenerationRequest):
        def worker(job_id: str, update, control: JobControl) -> dict[str, Any]:
            from .model_runtime import model_revision

            device = self.system.capabilities().effective_device
            revision = (
                model_revision(self.models.model_path(request.settings.model_id))
                + model_revision(self.models.dependency_path("Woosh-AE"))
                + model_revision(self.models.dependency_path("TextConditionerA"))
            )
            lease = (
                self.runtime.lease(
                    (request.settings.model_id, revision, device),
                    request.settings.model_id,
                    control,
                    self.unload,
                )
                if self.runtime
                else self._lock
            )
            with lease:
                root = Path(request.project_path).expanduser().resolve()
                manifest = self.projects.open(root)
                from .sfx import automatic_sound_name, is_sfx_asset

                name = (
                    automatic_sound_name(
                        request.prompt_original or request.prompt_conditioned
                    )
                    if request.name_mode == "auto"
                    else request.name
                )
                original = None
                if request.variant_of_asset_id:
                    by_id = {asset.id: asset for asset in manifest.assets}
                    original = by_id.get(request.variant_of_asset_id)
                    if not original or not is_sfx_asset(original, by_id):
                        raise ValueError("只能为现有音效继续生成变体")
                    seen = set()
                    while original.parent_asset_id in by_id and original.id not in seen:
                        seen.add(original.id)
                        original = by_id[original.parent_asset_id]
                batch_id = (
                    (original.generation_group_id or original.id)
                    if original
                    else job_id
                )
                family_id = original.id if original else None
                reused = (
                    self._model is not None
                    and self._model_id == request.settings.model_id
                    and self._device == device
                    and self._loaded_revision == revision
                )
                if not reused and self._model is not None:
                    self.unload()
                update(
                    status=JobStatus.RUNNING if reused else JobStatus.LOADING,
                    stage="复用已加载模型" if reused else "加载模型",
                    progress=0.03,
                )
                started = time.monotonic()
                device = self.system.capabilities().effective_device
                model = self._load_model(request.settings.model_id, device)
                self._loaded_revision = revision
                if self.runtime and not reused:
                    self.runtime.mark_loaded(time.monotonic() - started)
                seeds = self._seeds(request)
                assets: list[GeneratedAsset] = []
                for index, seed in enumerate(seeds):
                    control.checkpoint()
                    update(
                        status=JobStatus.RUNNING,
                        stage=f"生成变体 {index + 1}/{len(seeds)}",
                        progress=0.08 + (index / len(seeds)) * 0.78,
                    )
                    if self.runtime:
                        self.runtime.mark_running()
                    audio = self._generate_one(
                        model=model,
                        model_id=request.settings.model_id,
                        prompt=request.prompt_conditioned,
                        cfg=request.settings.cfg,
                        seed=seed,
                        solver=request.settings.solver,
                        atol=request.settings.atol,
                        rtol=request.settings.rtol,
                        device=device,
                    )
                    trimmed = False
                    if request.postprocess_mode == "trim_silence":
                        processed, start_sample, end_sample = trim_boundary_silence(
                            audio,
                            SAMPLE_RATE,
                        )
                        trimmed = start_sample > 0 or end_sample < len(audio)
                        if trimmed:
                            audio = processed
                    filename = self._unique_generated_name(
                        root,
                        request.category,
                        name,
                        index + 1,
                    )
                    relative_path = Path("Generated") / filename
                    sf.write(
                        root / relative_path,
                        audio,
                        SAMPLE_RATE,
                        subtype="PCM_24",
                    )
                    asset = GeneratedAsset(
                        name=Path(filename).stem,
                        relative_path=relative_path.as_posix(),
                        prompt_original=request.prompt_original,
                        prompt_conditioned=request.prompt_conditioned,
                        model_id=request.settings.model_id,
                        seed=seed,
                        generation_group_id=batch_id,
                        parent_asset_id=family_id,
                        music_metadata={
                            "source_job_id": job_id,
                            "sound_name": name,
                            "variant_index": index + 1,
                            "name_mode": request.name_mode,
                            "settings": request.settings.model_dump(mode="json"),
                        },
                        duration_seconds=len(audio) / SAMPLE_RATE,
                        tags=["已去首尾静音"] if trimmed else [],
                    )
                    if family_id is None:
                        family_id = asset.id
                    assets.append(asset)
                    self.projects.mutate(
                        root, lambda manifest: manifest.assets.append(asset)
                    )
                update(status=JobStatus.RENDERING, stage="写入项目", progress=0.94)
                return {
                    "project_path": str(root),
                    "asset_ids": [asset.id for asset in assets],
                    "generation_group_id": batch_id,
                }

        return worker

    def _load_model(self, model_id: str, device: str):
        if not self.models.is_installed(model_id):
            raise RuntimeError(f"模型尚未安装: {model_id}")
        if (
            self._model is not None
            and self._model_id == model_id
            and self._device == device
        ):
            return self._model
        self.unload()
        from woosh.components.base import LoadConfig

        generator_path = self.models.model_path(model_id)
        autoencoder_path = self.models.dependency_path("Woosh-AE")
        conditioner_path = self.models.dependency_path("TextConditionerA")
        if model_id == "Woosh-DFlow":
            from woosh.model.flowmap_from_pretrained import FlowMapFromPretrained

            config = LoadConfig(
                path=str(generator_path),
                ldm={
                    "conditioners": {"text": {"path": str(conditioner_path)}},
                    "autoencoder": {"path": str(autoencoder_path)},
                },
            )
            model = FlowMapFromPretrained(config)
        else:
            from woosh.model.ldm import LatentDiffusionModel

            config = LoadConfig(
                path=str(generator_path),
                conditioners={"text": {"path": str(conditioner_path)}},
                autoencoder={"path": str(autoencoder_path)},
            )
            model = LatentDiffusionModel(config)
        self._model = model.eval().to(device)
        self._model_id = model_id
        self._device = device
        return self._model

    @staticmethod
    def _generate_one(
        model,
        model_id: str,
        prompt: str,
        cfg: float,
        seed: int,
        solver: str,
        atol: float,
        rtol: float,
        device: str,
    ) -> np.ndarray:
        import torch

        generator = torch.Generator(device="cpu").manual_seed(seed)
        noise = torch.randn(1, LATENT_CHANNELS, LATENT_FRAMES, generator=generator).to(
            device
        )
        condition = model.get_cond(
            {"audio": None, "description": [prompt]},
            no_dropout=True,
            device=device,
        )
        with torch.inference_mode():
            if model_id == "Woosh-DFlow":
                from woosh.inference.flowmap_sampler import sample_euler

                latent = sample_euler(
                    model,
                    noise,
                    cond=condition,
                    num_steps=4,
                    renoise=[0, 0.5, 0.5, 0.3],
                    cfg=cfg,
                )
            else:
                from woosh.inference.flowmatching_sampler import flowmatching_integrate

                latent = flowmatching_integrate(
                    model,
                    noise=noise,
                    cond=condition,
                    cfg=cfg,
                    atol=atol,
                    rtol=rtol,
                    method=solver,
                    device=device,
                    dtype=torch.float64,
                )
            audio = model.autoencoder.inverse(latent).cpu().float()[0].squeeze()
        peak = audio.abs().max().clamp(min=1.0)
        return (audio / peak).numpy()

    @staticmethod
    def _seeds(request: GenerationRequest) -> list[int]:
        settings = request.settings
        base = (
            settings.seed
            if settings.seed is not None
            else random.SystemRandom().randint(0, 2**31 - 1)
        )
        if settings.seed_mode == "fixed":
            return [base] * request.count
        if settings.seed_mode == "increment":
            return [base + index for index in range(request.count)]
        return [
            random.SystemRandom().randint(0, 2**31 - 1) for _ in range(request.count)
        ]

    @staticmethod
    def _unique_generated_name(
        root: Path, category: str, name: str, variant: int
    ) -> str:
        stem = f"{safe_name(category)}_{safe_name(name)}_{variant:02}"
        candidate = root / "Generated" / f"{stem}.wav"
        suffix = 2
        while candidate.exists():
            candidate = root / "Generated" / f"{stem}_{suffix}.wav"
            suffix += 1
        return candidate.name


class TranslationService:
    def __init__(self, models: ModelService):
        self.models = models
        self._translator = None
        self._translation_revision = None
        self._source_tokenizer = None
        self._target_tokenizer = None
        self._lock = Lock()

    def unload(self):
        with self._lock:
            self._translator = self._source_tokenizer = self._target_tokenizer = None

    def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        path = self.models.translation_path()
        if not self.models._translation_valid(path):
            raise RuntimeError("本地翻译模型尚未准备完成")
        from .model_runtime import model_revision

        revision = model_revision(path)
        with self._lock:
            if self._translator is None or self._translation_revision != revision:
                import ctranslate2
                import sentencepiece as spm

                self._translator = ctranslate2.Translator(
                    str(path), device="cpu", compute_type="int8"
                )
                self._source_tokenizer = spm.SentencePieceProcessor(
                    model_file=str(path / "source.spm")
                )
                self._target_tokenizer = spm.SentencePieceProcessor(
                    model_file=str(path / "target.spm")
                )
                self._translation_revision = revision
            source_tokens = self._source_tokenizer.encode(text, out_type=str)
            source_tokens.append("</s>")
            result = self._translator.translate_batch(
                [source_tokens], beam_size=4, max_decoding_length=128
            )[0]
            return str(self._target_tokenizer.decode(result.hypotheses[0]))
