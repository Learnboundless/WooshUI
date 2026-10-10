from __future__ import annotations

import hashlib
import io
import os
import time
from contextlib import contextmanager
from threading import Event, Thread
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .worker_protocol import emit, progress, release_memory, serve
from .speech_options import speech_segments, token_budget
from .signal_analysis import protect_peak

_model = None
_key = None
_prompts: OrderedDict = OrderedDict()


def unload():
    global _model, _key
    _prompts.clear()
    _model = _key = None
    release_memory()


def load(payload):
    global _model, _key
    key = (
        payload.get("model_path"),
        payload.get("model_revision"),
        payload.get("device"),
    )
    if _model is not None and key == _key:
        progress("复用 Qwen3-TTS", 0.18)
        return {"reused": True}
    unload()
    started = time.monotonic()
    progress("加载 Qwen3-TTS", 0.05)
    if os.environ.get("WOOSH_SPEECH_WORKER_FAKE") == "1":
        _model = object()
    else:
        import torch
        from qwen_tts import Qwen3TTSModel

        device = payload.get("device", "cpu")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA 设备不可用")
        _model = Qwen3TTSModel.from_pretrained(
            payload["model_path"],
            device_map="cuda:0" if device == "cuda" else "cpu",
            dtype=torch.bfloat16 if device == "cuda" else torch.float32,
            local_files_only=True,
        )
    _key = key
    emit("loaded", seconds=time.monotonic() - started)
    progress("Qwen3-TTS 已加载", 0.18)
    return {"reused": False}


def write_wav(path: Path, audio, sample_rate: int) -> None:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_24")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())


def fake_generate(payload: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    output = Path(payload["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.25, min(12.0, len(payload.get("text", "")) * 0.06))
    sr = 24000
    t = np.arange(int(duration * sr), dtype=np.float32)
    wave = 0.08 * np.sin(2 * np.pi * (180 + len(payload.get("text", "")) * 2) * t / sr)
    write_wav(output, wave, sr)
    progress("写入测试配音", 0.98)
    return {
        "path": str(output),
        "sample_rate": sr,
        "channel_count": 1,
        "duration_seconds": duration,
    }


@contextmanager
def synthesis_progress(model, index, total, budget):
    from transformers import StoppingCriteria, StoppingCriteriaList

    started = time.monotonic()
    stop = Event()
    state = {"frames": 0, "limit": False}
    last = [0.0]
    base = 0.25 + 0.65 * index / total
    scale = 0.65 / total

    class Monitor(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            frames = int(input_ids.shape[-1])
            state["frames"] = frames
            elapsed = time.monotonic() - started
            if elapsed - last[0] >= 1:
                progress(
                    f"合成语音 {index + 1}/{total}",
                    base + scale * min(frames / budget, 0.95),
                    f"已生成 {frames} 帧 · {elapsed:.0f} 秒",
                )
                last[0] = elapsed
            if frames >= budget:
                state["limit"] = True
                return True
            if elapsed > 180:
                raise RuntimeError("本段合成超过 3 分钟，请缩短台词或改用清晰参考录音")
            return False

    talker = getattr(getattr(model, "model", None), "talker", None)
    original = getattr(talker, "generate", None)
    if original:

        def monitored(*args, **kwargs):
            kwargs["stopping_criteria"] = StoppingCriteriaList(
                [*kwargs.get("stopping_criteria", []), Monitor()]
            )
            return original(*args, **kwargs)

        talker.generate = monitored

    def heartbeat():
        while not stop.wait(3):
            elapsed = time.monotonic() - started
            progress(
                f"合成语音 {index + 1}/{total}",
                base + scale * min(state["frames"] / budget, 0.95),
                f"已生成 {state['frames']} 帧 · {elapsed:.0f} 秒",
            )

    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield state
        if state["limit"]:
            raise RuntimeError(
                "模型没有正常结束本段语音，已停止以避免长时间重复；请重试或换用清晰的短参考音频"
            )
    finally:
        stop.set()
        thread.join(timeout=1)
        if original:
            talker.generate = original


def generate(payload: dict[str, Any]) -> dict[str, Any]:
    load(payload)
    if os.environ.get("WOOSH_SPEECH_WORKER_FAKE") == "1":
        return fake_generate(payload)
    import numpy as np
    import soundfile as sf

    language = payload.get("language", "Chinese")
    segments = speech_segments(payload["text"], language)
    reference_mode = "custom_voice"
    if payload.get("mode") == "clone":
        reference = Path(payload["reference_audio"])
        digest = hashlib.sha256(reference.read_bytes()).hexdigest()
        info = sf.info(reference)
        long_reference = info.duration > 15
        reference_mode = "voice_only_short_reference" if long_reference else "context"
        key = (digest, payload.get("reference_text", ""), reference_mode)
        if key not in _prompts:
            progress(
                "提取角色声线",
                0.2,
                "长参考录音使用前 10 秒提取声线，避免长上下文续说"
                if long_reference
                else "分析参考音频与准确台词",
            )
            if long_reference:
                audio, sample_rate = sf.read(
                    reference,
                    frames=int(info.samplerate * 10),
                    always_2d=True,
                    dtype="float32",
                )
                _prompts[key] = _model.create_voice_clone_prompt(
                    ref_audio=(audio.mean(axis=1), sample_rate),
                    ref_text=None,
                    x_vector_only_mode=True,
                )
            else:
                _prompts[key] = _model.create_voice_clone_prompt(
                    ref_audio=str(reference), ref_text=payload.get("reference_text", "")
                )
            while len(_prompts) > 16:
                _prompts.popitem(last=False)
        else:
            progress("复用角色声线", 0.22)
        _prompts.move_to_end(key)
    audio_parts = []
    details = []
    for index, text in enumerate(segments):
        budget = token_budget(text, language)
        progress(
            f"合成语音 {index + 1}/{len(segments)}",
            0.25 + 0.65 * index / len(segments),
            "完整文本模式",
        )
        with synthesis_progress(_model, index, len(segments), budget) as state:
            kwargs = {
                "text": text,
                "language": language,
                "max_new_tokens": budget,
                "non_streaming_mode": True,
            }
            if payload.get("mode") == "clone":
                wavs, sr = _model.generate_voice_clone(
                    **kwargs, voice_clone_prompt=_prompts[key]
                )
            else:
                wavs, sr = _model.generate_custom_voice(
                    **kwargs,
                    speaker=payload.get("speaker") or "Vivian",
                    instruct=payload.get("instruct", "") or None,
                )
        audio = np.asarray(wavs[0], dtype=np.float32)
        if len(audio) / sr > budget / 12.5 * 1.1:
            raise RuntimeError("配音时长异常，请重试本句")
        fade = min(len(audio) // 2, int(sr * 0.005))
        if len(segments) > 1 and fade:
            audio = audio.copy()
            audio[:fade] *= np.linspace(0, 1, fade)
            audio[-fade:] *= np.linspace(1, 0, fade)
        if audio_parts:
            audio_parts.append(np.zeros(int(sr * 0.12), dtype=np.float32))
        audio_parts.append(audio)
        details.append({"frames": state["frames"], "token_budget": budget})
    audio, protection = protect_peak(np.concatenate(audio_parts))
    output = Path(payload["output_path"])
    write_wav(output, audio, sr)
    progress("写入配音", 0.98)
    return {
        "path": str(output),
        "sample_rate": sr,
        "channel_count": 1,
        "duration_seconds": len(audio) / sr,
        "diagnostics": {
            "reference_mode": reference_mode,
            "segments": details,
            "peak_protection": protection,
        },
    }


def main():
    serve({"load": load, "generate": generate}, unload)


if __name__ == "__main__":
    main()
