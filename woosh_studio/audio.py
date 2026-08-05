from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard import (
    Compressor,
    HighShelfFilter,
    Limiter,
    LowShelfFilter,
    PeakFilter,
    Pedalboard,
    PitchShift,
    Reverb,
)

from .projects import ProjectService, safe_name
from .schemas import (
    AssetTrimRequest,
    Clip,
    EffectNode,
    EffectType,
    GeneratedAsset,
    ProjectManifestV2,
    RenderRequest,
    Timeline,
    Track,
)


def db_to_gain(value: float) -> float:
    return 10 ** (value / 20)


def ensure_stereo(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return np.stack([audio, audio], axis=0)
    audio = audio.T if audio.shape[0] > audio.shape[1] else audio
    if audio.shape[0] == 1:
        return np.repeat(audio, 2, axis=0)
    return audio[:2]


def apply_pan(audio: np.ndarray, pan: float) -> np.ndarray:
    pan = float(np.clip(pan, -1, 1))
    angle = (pan + 1) * math.pi / 4
    result = audio.copy()
    result[0] *= math.cos(angle) * math.sqrt(2)
    result[1] *= math.sin(angle) * math.sqrt(2)
    return result


def apply_fades(
    audio: np.ndarray, sample_rate: int, fade_in: float, fade_out: float
) -> np.ndarray:
    result = audio.copy()
    in_samples = min(int(fade_in * sample_rate), result.shape[1])
    out_samples = min(int(fade_out * sample_rate), result.shape[1])
    if in_samples:
        result[:, :in_samples] *= np.linspace(0, 1, in_samples, dtype=np.float32)
    if out_samples:
        result[:, -out_samples:] *= np.linspace(1, 0, out_samples, dtype=np.float32)
    return result


def detect_content_bounds(
    audio: np.ndarray,
    sample_rate: int,
    threshold_db: float = -45,
    padding_seconds: float = 0.04,
    frame_seconds: float = 0.01,
) -> tuple[int, int]:
    """Find the first and last non-silent frames without removing internal pauses."""
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 1:
        samples = samples[:, None]
    if samples.ndim != 2:
        raise ValueError("音频数据必须是一维或二维数组")
    if samples.shape[0] == 0:
        return 0, 0

    frame_length = max(1, int(round(sample_rate * frame_seconds)))
    squared = np.mean(np.square(samples, dtype=np.float64), axis=1)
    frame_starts = np.arange(0, samples.shape[0], frame_length)
    frame_counts = np.minimum(frame_length, samples.shape[0] - frame_starts)
    frame_rms = np.sqrt(np.add.reduceat(squared, frame_starts) / frame_counts)
    active = np.flatnonzero(frame_rms >= db_to_gain(threshold_db))
    if active.size == 0:
        return 0, samples.shape[0]

    padding = int(round(sample_rate * padding_seconds))
    start = max(0, int(active[0]) * frame_length - padding)
    end = min(
        samples.shape[0],
        (int(active[-1]) + 1) * frame_length + padding,
    )
    return start, end


def trim_boundary_silence(
    audio: np.ndarray,
    sample_rate: int,
    threshold_db: float = -45,
    padding_seconds: float = 0.04,
) -> tuple[np.ndarray, int, int]:
    start, end = detect_content_bounds(
        audio,
        sample_rate,
        threshold_db=threshold_db,
        padding_seconds=padding_seconds,
    )
    return audio[start:end], start, end


def time_stretch(audio: np.ndarray, rate: float) -> np.ndarray:
    if abs(rate - 1) < 1e-4:
        return audio
    if rate <= 0:
        raise ValueError("变速倍率必须大于 0")
    try:
        import torch
        import torchaudio

        waveform = torch.from_numpy(audio)
        n_fft = 2048
        hop_length = 512
        window = torch.hann_window(n_fft)
        spectrogram = torch.stft(
            waveform,
            n_fft=n_fft,
            hop_length=hop_length,
            window=window,
            return_complex=True,
        )
        phase_advance = torch.linspace(
            0, math.pi * hop_length, spectrogram.shape[-2]
        )[..., None]
        stretched = torchaudio.functional.phase_vocoder(
            spectrogram, rate=rate, phase_advance=phase_advance
        )
        target_length = max(1, int(audio.shape[1] / rate))
        return torch.istft(
            stretched,
            n_fft=n_fft,
            hop_length=hop_length,
            window=window,
            length=target_length,
        ).numpy()
    except (ImportError, RuntimeError):
        target_length = max(1, int(audio.shape[1] / rate))
        source = np.linspace(0, 1, audio.shape[1], endpoint=False)
        target = np.linspace(0, 1, target_length, endpoint=False)
        return np.vstack([np.interp(target, source, channel) for channel in audio])


def effect_board(effects: list[EffectNode]) -> tuple[Pedalboard, bool, float]:
    plugins = []
    normalize = False
    speed = 1.0
    for effect in effects:
        if not effect.enabled:
            continue
        parameters = effect.parameters
        if effect.type == EffectType.PITCH:
            plugins.append(PitchShift(semitones=float(parameters.get("semitones", 0))))
        elif effect.type == EffectType.SPEED:
            speed = float(parameters.get("rate", 1))
        elif effect.type == EffectType.EQ:
            plugins.extend(
                [
                    LowShelfFilter(
                        cutoff_frequency_hz=float(parameters.get("low_hz", 180)),
                        gain_db=float(parameters.get("low_db", 0)),
                    ),
                    PeakFilter(
                        cutoff_frequency_hz=float(parameters.get("mid_hz", 1200)),
                        gain_db=float(parameters.get("mid_db", 0)),
                        q=float(parameters.get("mid_q", 0.8)),
                    ),
                    HighShelfFilter(
                        cutoff_frequency_hz=float(parameters.get("high_hz", 6500)),
                        gain_db=float(parameters.get("high_db", 0)),
                    ),
                ]
            )
        elif effect.type == EffectType.COMPRESSOR:
            plugins.append(
                Compressor(
                    threshold_db=float(parameters.get("threshold_db", -18)),
                    ratio=float(parameters.get("ratio", 3)),
                    attack_ms=float(parameters.get("attack_ms", 10)),
                    release_ms=float(parameters.get("release_ms", 100)),
                )
            )
        elif effect.type == EffectType.REVERB:
            plugins.append(
                Reverb(
                    room_size=float(parameters.get("room_size", 0.25)),
                    damping=float(parameters.get("damping", 0.5)),
                    wet_level=float(parameters.get("wet_level", 0.15)),
                    dry_level=float(parameters.get("dry_level", 0.85)),
                    width=float(parameters.get("width", 1)),
                )
            )
        elif effect.type == EffectType.LIMITER:
            plugins.append(
                Limiter(
                    threshold_db=float(parameters.get("threshold_db", -1)),
                    release_ms=float(parameters.get("release_ms", 100)),
                )
            )
        elif effect.type == EffectType.NORMALIZE:
            normalize = True
    return Pedalboard(plugins), normalize, speed


def process_audio(
    audio: np.ndarray, sample_rate: int, effects: list[EffectNode]
) -> np.ndarray:
    board, normalize, speed = effect_board(effects)
    result = time_stretch(audio.astype(np.float32, copy=False), speed)
    if len(board):
        result = board(result, sample_rate=sample_rate)
    if normalize:
        peak = float(np.max(np.abs(result)))
        if peak > 1e-8:
            result = result / peak * db_to_gain(-1)
    return np.asarray(result, dtype=np.float32)


class AudioRenderService:
    def __init__(self, projects: ProjectService):
        self.projects = projects

    def render_timeline(self, root: Path, timeline: Timeline) -> np.ndarray:
        root = root.expanduser().resolve()
        sample_rate = timeline.sample_rate
        length = max(1, int(timeline.duration_seconds * sample_rate))
        master = np.zeros((2, length), dtype=np.float32)
        soloed = any(track.solo for track in timeline.tracks)
        for track in timeline.tracks:
            if track.muted or (soloed and not track.solo):
                continue
            track_audio = self._render_track(root, track, sample_rate, length)
            track_audio *= db_to_gain(track.gain_db)
            track_audio = apply_pan(track_audio, track.pan)
            master += track_audio
        master = process_audio(master, sample_rate, timeline.master_effects)
        peak = float(np.max(np.abs(master)))
        if peak > 1:
            master /= peak
        return master

    def preview(self, request: RenderRequest) -> Path:
        root = Path(request.project_path).expanduser().resolve()
        cache_key = hashlib.sha256(
            json.dumps(request.timeline.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()[:20]
        target = root / ".cache" / f"preview-{cache_key}.wav"
        if not target.exists():
            audio = self.render_timeline(root, request.timeline)
            sf.write(target, audio.T, request.timeline.sample_rate, subtype="PCM_24")
        return target

    def render(self, request: RenderRequest) -> Path:
        root = Path(request.project_path).expanduser().resolve()
        target = root / "Renders" / f"{safe_name(request.output_name)}.wav"
        audio = self.render_timeline(root, request.timeline)
        sf.write(target, audio.T, request.timeline.sample_rate, subtype="PCM_24")
        return target

    def trim_asset(
        self, asset_id: str, request: AssetTrimRequest
    ) -> tuple[ProjectManifestV2, GeneratedAsset, dict[str, float | str]]:
        root = Path(request.project_path).expanduser().resolve()
        manifest = self.projects.open(root)
        source_asset = next(
            (asset for asset in manifest.assets if asset.id == asset_id),
            None,
        )
        if source_asset is None:
            raise FileNotFoundError("项目中不存在该音频素材")

        source = self.projects.resolve_project_file(root, source_asset.relative_path)
        if not source.is_file():
            raise FileNotFoundError("音频文件不存在")
        audio, sample_rate = sf.read(source, always_2d=True, dtype="float32")
        if audio.shape[0] == 0:
            raise ValueError("音频文件为空，无法裁剪")

        if request.mode == "trim_silence":
            processed, start_sample, end_sample = trim_boundary_silence(
                audio,
                sample_rate,
                threshold_db=request.threshold_db,
                padding_seconds=request.padding_seconds,
            )
            if start_sample == 0 and end_sample == audio.shape[0]:
                raise ValueError("未检测到可裁剪的首尾静音，原始素材未修改")
        else:
            start_sample = int(round(request.start_seconds * sample_rate))
            end_sample = int(round((request.end_seconds or 0) * sample_rate))
            if start_sample >= audio.shape[0]:
                raise ValueError("裁剪起点超出素材时长")
            if end_sample > audio.shape[0]:
                raise ValueError("裁剪终点超出素材时长")
            if end_sample <= start_sample:
                raise ValueError("裁剪范围必须包含有效时长")
            processed = audio[start_sample:end_sample]

        output_name = safe_name(request.output_name or f"{source_asset.name}_裁剪")
        directory = root / "Generated" / "Processed"
        directory.mkdir(parents=True, exist_ok=True)
        target = self.projects._unique_path(directory, f"{output_name}.wav")
        sf.write(target, processed, sample_rate, subtype="PCM_24")

        tags = list(dict.fromkeys([*source_asset.tags, "已裁剪"]))
        asset = GeneratedAsset(
            name=target.stem,
            relative_path=target.relative_to(root).as_posix(),
            source="rendered",
            kind="render",
            prompt_original=source_asset.prompt_original,
            prompt_conditioned=source_asset.prompt_conditioned,
            model_id=source_asset.model_id,
            seed=source_asset.seed,
            sample_rate=sample_rate,
            channel_count=processed.shape[1],
            duration_seconds=processed.shape[0] / sample_rate,
            generation_group_id=source_asset.generation_group_id,
            parent_asset_id=source_asset.id,
            tags=tags,
        )
        manifest.assets.append(asset)
        manifest = self.projects.save(root, manifest)
        details: dict[str, float | str] = {
            "mode": request.mode,
            "start_seconds": start_sample / sample_rate,
            "end_seconds": end_sample / sample_rate,
            "removed_seconds": (audio.shape[0] - processed.shape[0]) / sample_rate,
        }
        return manifest, asset, details

    def _render_track(
        self, root: Path, track: Track, sample_rate: int, length: int
    ) -> np.ndarray:
        output = np.zeros((2, length), dtype=np.float32)
        for clip in track.clips:
            clip_audio = self._render_clip(root, clip, sample_rate)
            start = int(clip.start_seconds * sample_rate)
            if start >= length:
                continue
            available = min(clip_audio.shape[1], length - start)
            output[:, start : start + available] += clip_audio[:, :available]
        return output

    def _render_clip(self, root: Path, clip: Clip, sample_rate: int) -> np.ndarray:
        source = self.projects.resolve_project_file(root, clip.source_path)
        audio, source_rate = sf.read(source, always_2d=True, dtype="float32")
        audio = ensure_stereo(audio)
        if source_rate != sample_rate:
            rate = source_rate / sample_rate
            audio = time_stretch(audio, rate)
        trim_start = min(
            max(0, int(clip.trim_start_seconds * sample_rate)),
            max(0, audio.shape[1] - 1),
        )
        trim_end = (
            int(clip.trim_end_seconds * sample_rate)
            if clip.trim_end_seconds is not None
            else audio.shape[1]
        )
        trim_end = min(audio.shape[1], max(trim_start + 1, trim_end))
        audio = audio[:, trim_start:trim_end]
        audio = apply_fades(
            audio, sample_rate, clip.fade_in_seconds, clip.fade_out_seconds
        )
        audio = process_audio(audio, sample_rate, clip.effects)
        audio *= db_to_gain(clip.gain_db)
        audio = apply_pan(audio, clip.pan)
        return audio
