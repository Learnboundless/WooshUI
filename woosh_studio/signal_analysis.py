"""Sample-derived waveform/spectrogram and non-clipping output gain."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import numpy as np
import soundfile as sf


def protect_peak(audio, ceiling=0.98):
    samples = np.asarray(audio, dtype=np.float32)
    if not np.isfinite(samples).all():
        raise ValueError("模型音频包含无效数值，请重新生成")
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    gain = min(1.0, ceiling / max(peak, 1e-12))
    return samples * gain, {
        "source_peak": peak,
        "gain": gain,
        "gain_db": float(20 * np.log10(max(gain, 1e-12))),
        "output_peak": peak * gain,
    }


def analyze_audio(path: Path):
    path = path.resolve()
    stat = path.stat()
    return _analyze(str(path), stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=128)
def _analyze(filename, size, modified):
    del size, modified
    info = sf.info(filename)
    if info.frames <= 0 or info.duration > 900 or info.channels > 16:
        raise ValueError("音频为空或超出分析范围（最长15分钟、最多16声道）")
    audio, sr = sf.read(filename, always_2d=True, dtype="float32")
    if not np.isfinite(audio).all():
        raise ValueError("音频包含无效采样值")
    bins = min(256, len(audio))
    edges = np.linspace(0, len(audio), bins + 1, dtype=int)
    peaks = [
        [
            float(np.min(audio[edges[i] : edges[i + 1]])),
            float(np.max(audio[edges[i] : edges[i + 1]])),
        ]
        for i in range(bins)
    ]
    nfft = 2048
    padded = np.pad(audio, ((0, max(0, nfft - len(audio))), (0, 0)))
    starts = np.linspace(
        0, max(0, len(padded) - nfft), min(192, max(1, len(audio) // 256)), dtype=int
    )
    window = np.hanning(nfft).astype(np.float32)
    frames = padded[starts[:, None] + np.arange(nfft)[None, :]] * window[None, :, None]
    magnitude = (
        np.sqrt(np.mean(np.abs(np.fft.rfft(frames, axis=1)) ** 2, axis=2))
        * 2
        / max(float(window.sum()), 1)
    )
    frequencies = np.fft.rfftfreq(nfft, 1 / sr)
    frequency_edges = np.geomspace(20, sr / 2, 65)
    spectrogram = []
    for row in magnitude:
        bands = []
        for low, high in zip(frequency_edges[:-1], frequency_edges[1:]):
            indices = np.flatnonzero((frequencies >= low) & (frequencies < high))
            amplitude = (
                float(np.max(row[indices]))
                if len(indices)
                else float(
                    row[
                        min(
                            len(row) - 1,
                            max(1, int(round((low + high) / 2 / (sr / nfft)))),
                        )
                    ]
                )
            )
            bands.append(
                round(float(np.clip(20 * np.log10(max(amplitude, 1e-6)), -90, 6)), 1)
            )
        spectrogram.append(bands)
    power = np.mean(magnitude**2, axis=0)
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    return {
        "sample_rate": sr,
        "channel_count": info.channels,
        "duration_seconds": info.duration,
        "peaks": peaks,
        "spectrogram": spectrogram,
        "frequency_edges_hz": frequency_edges.tolist(),
        "peak": peak,
        "peak_dbfs": round(float(20 * np.log10(max(peak, 1e-12))), 2),
        "rms_dbfs": round(float(20 * np.log10(max(rms, 1e-12))), 2),
        "overload_ratio": float(np.mean(np.abs(audio) > 1)),
        "dominant_frequency_hz": float(frequencies[int(np.argmax(power[1:])) + 1])
        if len(power) > 1
        else 0,
        "high_frequency_ratio": float(
            np.sum(power[frequencies > 10000]) / max(float(np.sum(power)), 1e-12)
        ),
    }
