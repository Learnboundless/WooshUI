from __future__ import annotations

import math
import os
import random
import time
from pathlib import Path
from typing import Any


from .worker_protocol import emit, progress, release_memory, serve
from .signal_analysis import protect_peak

_pipeline = None
_separator = None
_key = None


def unload():
    global _pipeline, _separator, _key
    _pipeline = _separator = _key = None
    release_memory()


def _identity(payload):
    return (
        payload.get("operation", payload.get("command", "generate")),
        payload.get("model_path"),
        payload.get("model_revision"),
        payload.get("device"),
        payload.get("memory_mode"),
    )


def fake_generate(payload: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    import soundfile as sf

    output = Path(payload["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = min(float(payload.get("duration_seconds", 30)), 2.0)
    sample_rate = 48_000
    for step in range(1, 6):
        progress("生成测试音乐", step / 7, f"{step}/5")
    samples = np.arange(int(duration * sample_rate), dtype=np.float32)
    frequency = 110 + int(payload.get("seed", 0)) % 220
    left = np.sin(2 * math.pi * frequency * samples / sample_rate) * 0.12
    right = np.sin(2 * math.pi * (frequency * 1.005) * samples / sample_rate) * 0.12
    sf.write(output, np.stack([left, right], axis=1), sample_rate, subtype="PCM_24")
    progress("写入音乐", 0.98)
    return {"path": str(output), "sample_rate": sample_rate, "channel_count": 2}


def generate(payload: dict[str, Any]) -> dict[str, Any]:
    global _pipeline, _key
    key = _identity(payload)
    reused = _pipeline is not None and _key == key
    if not reused:
        unload()
    started = time.monotonic()
    if os.environ.get("WOOSH_MUSIC_WORKER_FAKE") == "1":
        if not reused:
            _pipeline, _key = object(), key
            emit("loaded", seconds=0)
        return fake_generate(payload)

    progress("加载 HeartMuLa", 0.02, payload.get("memory_mode", "auto"))
    from .runtime import validate_music_bundle

    validate_music_bundle(Path(payload["model_path"]))
    import torch
    from heartlib.pipelines import music_generation
    from heartlib.pipelines.music_generation import HeartMuLaGenPipeline

    if torch.cuda.is_available():
        torch.set_float32_matmul_precision("high")
        torch.backends.cudnn.allow_tf32 = True
    seed = int(payload["seed"])
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    duration_seconds = int(payload["duration_seconds"])
    original_tqdm = music_generation.tqdm

    def progress_tqdm(iterable, *args, **kwargs):
        total = len(iterable) if hasattr(iterable, "__len__") else duration_seconds * 12
        for index, item in enumerate(iterable):
            if index % 12 == 0:
                generated = min(duration_seconds, int(index * 0.08))
                progress(
                    "生成音乐",
                    0.12 + 0.7 * index / max(total, 1),
                    f"{generated}s/{duration_seconds}s",
                )
            yield item

    music_generation.tqdm = progress_tqdm
    try:
        requested_device = payload.get("device", "cuda")
        if requested_device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA 设备不可用")
        device = torch.device(requested_device)
        low_vram = (
            device.type == "cuda"
            and payload.get("memory_mode") in {"auto", "int8"}
            and torch.cuda.get_device_properties(0).total_memory < 12 * 1024**3
        )
        dtype = {
            "mula": torch.bfloat16 if device.type == "cuda" else torch.float32,
            "codec": torch.float32,
        }
        memory_mode = payload.get("memory_mode", "bf16")
        if reused:
            pipeline = _pipeline
        elif device.type == "cuda" and memory_mode == "int8":
            progress("配置 mmgp INT8", 0.05, "低显存换入换出")
            from .heartmula_mmgp import create_pipeline

            try:
                pipeline = create_pipeline(
                    Path(payload["model_path"]),
                    device,
                    use_int8=True,
                )
            except Exception as error:
                raise RuntimeError(f"mmgp INT8 初始化失败: {error}") from error
        else:
            pipeline = HeartMuLaGenPipeline.from_pretrained(
                pretrained_path=str(Path(payload["model_path"])),
                device=device,
                dtype=dtype,
                version="3B-happy-new-year",
                lazy_load=low_vram,
            )
        if not reused:
            _pipeline, _key = pipeline, key
            emit("loaded", seconds=time.monotonic() - started)
        progress(
            "复用 HeartMuLa" if reused else "HeartMuLa 已加载",
            0.1,
            "mmgp INT8 低显存模式"
            if memory_mode == "int8"
            else ("低显存换入换出" if low_vram else str(dtype["mula"])),
        )
        if payload.get("preload"):
            return {"reused": reused}
        lyrics = payload.get("lyrics", "").strip() or "[Instrumental]"
        output = Path(payload["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        preview = payload.get("performance_mode") == "preview"
        cfg_scale = float(payload.get("cfg_scale", 1.5))
        inputs = {"lyrics": lyrics, "tags": ",".join(payload.get("tags", []))}
        preprocess, forward, _ = pipeline._sanitize_parameters(
            max_audio_length_ms=duration_seconds * 1000,
            temperature=float(payload.get("temperature", 1.0)),
            topk=int(payload.get("top_k", 50)),
            cfg_scale=cfg_scale,
            save_path=str(output),
        )
        model_inputs = pipeline.preprocess(inputs, **preprocess)
        required = (
            int(model_inputs["tokens"].shape[1]) + int(duration_seconds * 12.5) + 8
        )
        cache_frames = max(256, math.ceil(required / 128) * 128)
        pipeline.mula._woosh_cache_frames = cache_frames
        progress(
            "生成音乐",
            0.12,
            f"缓存长度 {cache_frames} · {'快速预览' if preview else '标准质量'}",
        )
        generate_started = time.monotonic()
        generated = pipeline._forward(model_inputs, **forward)
        generation_seconds = time.monotonic() - generate_started
        progress("解码音乐", 0.84, "解码后执行峰值保护")
        decode_started = time.monotonic()
        frames = generated["frames"].to(pipeline.codec_device)
        waveform = pipeline.codec.detokenize(
            frames, duration=14.88 if preview else 29.76, num_steps=8 if preview else 10
        )
        pipeline._unload()
        samples = waveform.detach().float().cpu().numpy().T
        samples, protection = protect_peak(samples)
        import soundfile as sf

        sf.write(output, samples, 48000, subtype="PCM_24")
        diagnostics = {
            "cache_frames": cache_frames,
            "memory_budget_mb": getattr(pipeline, "_woosh_memory_budget_mb", None),
            "generation_seconds": generation_seconds,
            "decode_seconds": time.monotonic() - decode_started,
            "performance_mode": "preview" if preview else "standard",
            "cfg_scale": cfg_scale,
            "peak_protection": protection,
        }

    finally:
        music_generation.tqdm = original_tqdm
    progress("解码完成", 0.98)
    return {"path": str(output), "sample_rate": 48_000, "diagnostics": diagnostics}


def fake_separate(payload: dict[str, Any]) -> dict[str, Any]:
    import soundfile as sf

    source, sample_rate = sf.read(
        payload["source_path"], always_2d=True, dtype="float32"
    )
    output = Path(payload.get("output_directory", "."))
    output.mkdir(parents=True, exist_ok=True)
    paths = {}
    gains = {"vocals": 0.55, "drums": 0.75, "bass": 0.45, "other": 0.65}
    for index, (role, gain) in enumerate(gains.items(), start=1):
        target = output / f"{role}.wav"
        sf.write(target, source * gain, sample_rate, subtype="PCM_24")
        paths[role] = str(target)
        progress("分离测试音轨", index / 5, role)
    return {"paths": paths, "sample_rate": sample_rate}


def separate(payload: dict[str, Any]) -> dict[str, Any]:
    global _separator, _key
    key = ("separate", *_identity(payload)[1:])
    reused = _separator is not None and _key == key
    if not reused:
        unload()
    started = time.monotonic()
    if os.environ.get("WOOSH_MUSIC_WORKER_FAKE") == "1":
        if not reused:
            _separator, _key = object(), key
            emit("loaded", seconds=0)
        return fake_separate(payload)

    import torch
    import torchaudio
    from demucs.api import Separator

    output = Path(payload.get("output_directory", "."))
    output.mkdir(parents=True, exist_ok=True)
    device = payload.get("device", "cuda")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA 设备不可用")

    def callback(state: dict[str, Any]) -> None:
        length = max(int(state.get("audio_length", 1)), 1)
        offset = int(state.get("segment_offset", 0))
        progress(
            "分离四轨", 0.08 + 0.78 * min(offset / length, 1), state.get("state", "")
        )

    progress("加载 Demucs", 0.02)
    separator = (
        _separator
        if reused
        else Separator(
            model="htdemucs",
            repo=Path(payload["model_path"]),
            device=device,
            shifts=1,
            split=True,
            overlap=0.25,
            callback=callback,
        )
    )
    if not reused:
        _separator, _key = separator, key
        emit("loaded", seconds=time.monotonic() - started)
    if payload.get("preload"):
        return {"reused": reused}
    _, stems = separator.separate_audio_file(Path(payload["source_path"]))
    result = {}
    for index, role in enumerate(("vocals", "drums", "bass", "other"), start=1):
        waveform = stems[role]
        if separator.samplerate != 48_000:
            waveform = torchaudio.functional.resample(
                waveform, separator.samplerate, 48_000
            )
        target = output / f"{role}.wav"
        torchaudio.save(str(target), waveform.cpu().float(), 48_000, bits_per_sample=24)
        result[role] = str(target)
        progress("写入分轨", 0.86 + index * 0.03, role)
    return {"paths": result, "sample_rate": 48_000}


def load(payload):
    payload = {**payload, "preload": True, "seed": 0, "duration_seconds": 30}
    if os.environ.get("WOOSH_MUSIC_WORKER_FAKE") == "1":
        global _pipeline, _separator, _key
        key = _identity(payload)
        if key != _key:
            unload()
            _key = key
            if payload.get("operation") == "separate":
                _separator = object()
            else:
                _pipeline = object()
            emit("loaded", seconds=0)
        return {"ready": True}
    return (
        separate(payload)
        if payload.get("operation") == "separate"
        else generate(payload)
    )


def main():
    serve({"load": load, "generate": generate, "separate": separate}, unload)


if __name__ == "__main__":
    main()
