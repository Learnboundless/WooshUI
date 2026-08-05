from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from woosh_studio.audio import (
    AudioRenderService,
    detect_content_bounds,
    trim_boundary_silence,
)
from woosh_studio.config import StudioPaths
from woosh_studio.projects import ProjectService
from woosh_studio.schemas import AssetTrimRequest, GeneratedAsset
from woosh_studio.storage import LibraryDatabase


SAMPLE_RATE = 48000


def test_trim_boundary_silence_preserves_internal_pause_and_stereo() -> None:
    audio = np.zeros((SAMPLE_RATE * 2, 2), dtype=np.float32)
    audio[int(0.2 * SAMPLE_RATE) : int(0.5 * SAMPLE_RATE), 0] = 0.3
    audio[int(1.2 * SAMPLE_RATE) : int(1.5 * SAMPLE_RATE), 1] = 0.4

    trimmed, start, end = trim_boundary_silence(audio, SAMPLE_RATE)

    assert start == int(0.16 * SAMPLE_RATE)
    assert end == int(1.54 * SAMPLE_RATE)
    assert trimmed.shape == (end - start, 2)
    internal_pause = trimmed[
        int(0.55 * SAMPLE_RATE) : int(0.95 * SAMPLE_RATE)
    ]
    assert np.count_nonzero(internal_pause) == 0


def test_all_silent_audio_is_left_intact() -> None:
    audio = np.zeros(SAMPLE_RATE, dtype=np.float32)

    start, end = detect_content_bounds(audio, SAMPLE_RATE)
    trimmed, _, _ = trim_boundary_silence(audio, SAMPLE_RATE)

    assert (start, end) == (0, SAMPLE_RATE)
    assert trimmed.shape == audio.shape


def test_short_final_frame_is_not_attenuated_by_detection_padding() -> None:
    audio = np.zeros(SAMPLE_RATE + 24, dtype=np.float32)
    audio[-24:] = 0.01

    start, end = detect_content_bounds(audio, SAMPLE_RATE, padding_seconds=0)

    assert start == SAMPLE_RATE
    assert end == len(audio)


def test_trim_asset_creates_non_destructive_derived_asset(tmp_path: Path) -> None:
    paths = StudioPaths(tmp_path / "app").ensure()
    projects = ProjectService(LibraryDatabase(paths.database))
    root, manifest = projects.create(tmp_path, "Trim Test")
    source_audio = np.zeros((SAMPLE_RATE, 2), dtype=np.float32)
    source_audio[int(0.25 * SAMPLE_RATE) : int(0.75 * SAMPLE_RATE)] = 0.25
    source_path = root / "Generated" / "source.wav"
    sf.write(source_path, source_audio, SAMPLE_RATE, subtype="PCM_24")
    source_asset = GeneratedAsset(
        name="source",
        relative_path="Generated/source.wav",
        duration_seconds=1,
        channel_count=2,
        tags=["impact"],
    )
    manifest.assets.append(source_asset)
    projects.save(root, manifest)
    renderer = AudioRenderService(projects)

    updated, derived, details = renderer.trim_asset(
        source_asset.id,
        AssetTrimRequest(project_path=str(root), mode="trim_silence"),
    )

    assert source_path.is_file()
    assert derived.parent_asset_id == source_asset.id
    assert derived.source == "rendered"
    assert derived.kind == "render"
    assert derived.channel_count == 2
    assert derived.relative_path.startswith("Generated/Processed/")
    assert "impact" in derived.tags
    assert "已裁剪" in derived.tags
    assert details["removed_seconds"] == pytest.approx(0.42, abs=0.02)
    assert {asset.id for asset in updated.assets} == {
        source_asset.id,
        derived.id,
    }
    assert (root / derived.relative_path).is_file()


def test_manual_trim_validates_range_and_uses_unique_names(tmp_path: Path) -> None:
    paths = StudioPaths(tmp_path / "app").ensure()
    projects = ProjectService(LibraryDatabase(paths.database))
    root, manifest = projects.create(tmp_path, "Manual Trim")
    source_path = root / "Sources" / "source.wav"
    sf.write(source_path, np.ones(SAMPLE_RATE), SAMPLE_RATE)
    source_asset = GeneratedAsset(
        name="source",
        relative_path="Sources/source.wav",
        source="imported",
        kind="imported",
        duration_seconds=1,
    )
    manifest.assets.append(source_asset)
    projects.save(root, manifest)
    renderer = AudioRenderService(projects)
    request = AssetTrimRequest(
        project_path=str(root),
        mode="manual",
        start_seconds=0.1,
        end_seconds=0.4,
        output_name="short",
    )

    _, first, _ = renderer.trim_asset(source_asset.id, request)
    _, second, _ = renderer.trim_asset(source_asset.id, request)

    assert first.relative_path.endswith("short.wav")
    assert second.relative_path.endswith("short_2.wav")
    assert first.duration_seconds == pytest.approx(0.3)


def test_auto_trim_rejects_audio_without_boundary_silence(tmp_path: Path) -> None:
    paths = StudioPaths(tmp_path / "app").ensure()
    projects = ProjectService(LibraryDatabase(paths.database))
    root, manifest = projects.create(tmp_path, "No Silence")
    source_path = root / "Generated" / "full.wav"
    sf.write(source_path, np.full(SAMPLE_RATE, 0.2), SAMPLE_RATE)
    source_asset = GeneratedAsset(
        name="full",
        relative_path="Generated/full.wav",
        duration_seconds=1,
    )
    manifest.assets.append(source_asset)
    projects.save(root, manifest)

    with pytest.raises(ValueError, match="未检测到"):
        AudioRenderService(projects).trim_asset(
            source_asset.id,
            AssetTrimRequest(project_path=str(root), mode="trim_silence"),
        )
