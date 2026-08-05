from __future__ import annotations

import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Any


def emit(event: str, **payload: Any) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def progress(stage: str, value: float, message: str = "") -> None:
    emit("progress", stage=stage, progress=max(0.0, min(1.0, value)), message=message)


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
    if os.environ.get("WOOSH_MUSIC_WORKER_FAKE") == "1":
        return fake_generate(payload)

    progress("加载 HeartMuLa", 0.02, payload.get("memory_mode", "auto"))
    import torch
    from heartlib.pipelines import music_generation
    from heartlib.pipelines.music_generation import HeartMuLaGenPipeline

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
        if device.type == "cuda" and memory_mode == "int8":
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
        progress(
            "HeartMuLa 已加载",
            0.1,
            "mmgp INT8 低显存模式"
            if memory_mode == "int8"
            else ("低显存换入换出" if low_vram else str(dtype["mula"])),
        )
        lyrics = payload.get("lyrics", "").strip() or "[Instrumental]"
        output = Path(payload["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        pipeline(
            {"lyrics": lyrics, "tags": ",".join(payload.get("tags", []))},
            max_audio_length_ms=duration_seconds * 1000,
            temperature=float(payload.get("temperature", 1.0)),
            topk=int(payload.get("top_k", 50)),
            cfg_scale=float(payload.get("cfg_scale", 1.5)),
            save_path=str(output),
        )
    finally:
        music_generation.tqdm = original_tqdm
    progress("解码完成", 0.98)
    return {"path": str(output), "sample_rate": 48_000}


def fake_separate(payload: dict[str, Any]) -> dict[str, Any]:
    import soundfile as sf

    source, sample_rate = sf.read(payload["source_path"], always_2d=True, dtype="float32")
    output = Path(payload["output_directory"])
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
    if os.environ.get("WOOSH_MUSIC_WORKER_FAKE") == "1":
        return fake_separate(payload)

    import torch
    import torchaudio
    from demucs.api import Separator

    output = Path(payload["output_directory"])
    output.mkdir(parents=True, exist_ok=True)
    device = payload.get("device", "cuda")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA 设备不可用")

    def callback(state: dict[str, Any]) -> None:
        length = max(int(state.get("audio_length", 1)), 1)
        offset = int(state.get("segment_offset", 0))
        progress("分离四轨", 0.08 + 0.78 * min(offset / length, 1), state.get("state", ""))

    progress("加载 Demucs", 0.02)
    separator = Separator(
        model="htdemucs",
        repo=Path(payload["model_path"]),
        device=device,
        shifts=1,
        split=True,
        overlap=0.25,
        callback=callback,
    )
    _, stems = separator.separate_audio_file(Path(payload["source_path"]))
    result = {}
    for index, role in enumerate(("vocals", "drums", "bass", "other"), start=1):
        waveform = stems[role]
        if separator.samplerate != 48_000:
            waveform = torchaudio.functional.resample(
                waveform, separator.samplerate, 48_000
            )
        target = output / f"{role}.wav"
        torchaudio.save(
            str(target), waveform.cpu().float(), 48_000, bits_per_sample=24
        )
        result[role] = str(target)
        progress("写入分轨", 0.86 + index * 0.03, role)
    return {"paths": result, "sample_rate": 48_000}


def main() -> None:
    try:
        request = json.loads(sys.stdin.readline())
        command = request.pop("command")
        if command == "generate":
            result = generate(request)
        elif command == "separate":
            result = separate(request)
        else:
            raise ValueError(f"未知音乐工作命令: {command}")
        emit("result", result=result)
    except Exception as error:
        emit("error", message=str(error), detail=type(error).__name__)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
