import json
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

from woosh_studio.audio import AudioRenderService
from woosh_studio.config import StudioPaths
from woosh_studio.exports import ExportService
from woosh_studio.projects import ProjectService
from woosh_studio.schemas import (
    Clip,
    EffectNode,
    EffectType,
    ExportPreset,
    ExportRequest,
    GeneratedAsset,
    Timeline,
    Track,
)
from woosh_studio.storage import LibraryDatabase


def test_timeline_render_and_middleware_package(tmp_path: Path) -> None:
    paths = StudioPaths(tmp_path / "app").ensure()
    projects = ProjectService(LibraryDatabase(paths.database))
    root, manifest = projects.create(tmp_path, "Export Test")
    seconds = 0.25
    samples = int(48000 * seconds)
    waveform = 0.3 * np.sin(2 * np.pi * 440 * np.arange(samples) / 48000)
    source = root / "Generated" / "hit.wav"
    sf.write(source, waveform, 48000, subtype="PCM_24")
    asset = GeneratedAsset(
        name="hit",
        relative_path="Generated/hit.wav",
        model_id="Woosh-DFlow",
        seed=42,
        duration_seconds=seconds,
    )
    manifest.assets.append(asset)
    clip = Clip(
        asset_id=asset.id,
        name="hit",
        source_path=asset.relative_path,
        fade_in_seconds=0.01,
        fade_out_seconds=0.01,
        effects=[EffectNode(type=EffectType.NORMALIZE)],
    )
    manifest.timeline = Timeline(
        duration_seconds=1,
        tracks=[Track(name="Impact", clips=[clip])],
    )
    projects.save(root, manifest)

    renderer = AudioRenderService(projects)
    rendered = renderer.render_timeline(root, manifest.timeline)
    assert rendered.shape == (2, 48000)
    assert 0.8 < float(np.max(np.abs(rendered))) <= 1

    exporter = ExportService(projects, renderer)
    result = exporter.export(
        ExportRequest(
            project_path=str(root),
            asset_ids=[asset.id],
            timeline=manifest.timeline,
            preset=ExportPreset(package="wwise_fmod"),
        )
    )
    archive = Path(result["archive"])
    assert archive.is_file()
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "manifest.json" in names
        assert "Wwise/wwise_import.tsv" in names
        assert "FMOD/fmod_manifest.json" in names
        package_manifest = json.loads(bundle.read("manifest.json"))
    assert {
        item["license"] for item in package_manifest["licenses"]
    } == {"CC BY-NC 4.0"}
    assert len(package_manifest["assets"]) == 2
