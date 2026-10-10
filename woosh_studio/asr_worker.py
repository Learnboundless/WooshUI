from __future__ import annotations

import os
import time

from .worker_protocol import emit, progress, release_memory, serve

_pipeline = None
_key = None


def unload():
    global _pipeline, _key
    _pipeline = _key = None
    release_memory()


def load(payload):
    global _pipeline, _key
    key = (payload.get("model_path"), payload.get("model_revision"), payload.get("device"))
    if _pipeline is not None and key == _key:
        progress("复用语音识别模型", 0.15)
        return {"reused": True}
    unload()
    started = time.monotonic()
    progress("加载 Whisper large-v3-turbo", 0.04)
    if os.environ.get("WOOSH_ASR_WORKER_FAKE") == "1":
        _pipeline = object()
    else:
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
        device = payload.get("device", "cpu")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA 设备不可用")
        dtype = torch.float16 if device == "cuda" else torch.float32
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            payload["model_path"], torch_dtype=dtype, local_files_only=True,
            use_safetensors=True,
        ).to(device)
        processor = AutoProcessor.from_pretrained(payload["model_path"], local_files_only=True)
        _pipeline = pipeline("automatic-speech-recognition", model=model,
                             tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor,
                             torch_dtype=dtype, device=device)
    _key = key
    emit("loaded", seconds=time.monotonic() - started)
    return {"reused": False}


def transcribe(payload):
    load(payload)
    import numpy as np
    import soundfile as sf
    audio, sr = sf.read(payload["source_path"], always_2d=True, dtype="float32")
    if not len(audio) or len(audio) / sr > 300:
        raise ValueError("参考录音需在 0 到 300 秒之间")
    mono = audio.mean(axis=1)
    if not np.isfinite(mono).all() or float(np.max(np.abs(mono))) < 0.0001:
        raise ValueError("录音没有可识别的声音，请检查麦克风后重新录制")
    if os.environ.get("WOOSH_ASR_WORKER_FAKE") == "1":
        return {"text": "这是一段测试录音。", "language": payload.get("language", "Auto"), "duration_seconds": len(audio) / sr}
    # Input arrays avoid invoking an external ffmpeg executable for browser WAV recordings.
    if sr != 16000:
        import torch
        import torchaudio
        mono = torchaudio.functional.resample(torch.from_numpy(mono), sr, 16000).numpy()
    kwargs = {"task": "transcribe"}
    if payload.get("language") and payload["language"] != "Auto":
        kwargs["language"] = payload["language"].lower()
    progress("识别参考音频", 0.2)
    result = _pipeline({"array": mono, "sampling_rate": 16000}, chunk_length_s=30,
                       stride_length_s=5, return_timestamps=True, generate_kwargs=kwargs)
    text = result["text"].strip()
    if not text:
        raise RuntimeError("未识别到台词，请试听录音或手动填写")
    progress("识别完成，请核对台词", 0.98)
    return {"text": text, "language": payload.get("language", "Auto"), "duration_seconds": len(audio) / sr}


if __name__ == "__main__":
    serve({"load": load, "transcribe": transcribe}, unload)
