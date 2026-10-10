import numpy as np
import soundfile as sf
from woosh_studio.config import StudioPaths
from woosh_studio.storage import LibraryDatabase
from woosh_studio.projects import ProjectService
from woosh_studio.schemas import (
    GeneratedAsset,
    JobEvent,
    JobKind,
    JobStatus,
    GenerationRequest,
)
from woosh_studio.sfx import automatic_sound_name


def test_existing_job_results_backfill_batch_and_variant_links(tmp_path):
    paths = StudioPaths(tmp_path / "app").ensure()
    db = LibraryDatabase(paths.database)
    projects = ProjectService(db)
    root, manifest = projects.create(tmp_path, "legacy")
    manifest.assets = [
        GeneratedAsset(id="a", name="sound", relative_path="Generated/a.wav"),
        GeneratedAsset(id="b", name="sound2", relative_path="Generated/b.wav"),
        GeneratedAsset(
            id="voice", name="voice", relative_path="Voice.wav", kind="voice_line"
        ),
    ]
    projects.save(root, manifest)
    db.save_job(
        JobEvent(
            id="batch",
            kind=JobKind.GENERATION,
            status=JobStatus.COMPLETED,
            payload={"project_path": str(root)},
            result={"asset_ids": ["a", "b"]},
        )
    )
    opened = projects.open(root)
    assert [asset.generation_group_id for asset in opened.assets] == [
        "batch",
        "batch",
        None,
    ]
    assert opened.assets[1].parent_asset_id == "a"
    assert projects.open(root).assets[1].parent_asset_id == "a"


def test_auto_name_does_not_require_a_manual_title():
    request = GenerationRequest(
        project_path="test",
        prompt_original="请生成一个重型机甲落地，金属冲击",
        prompt_conditioned="heavy mech landing",
        name_mode="auto",
        name="",
    )
    assert automatic_sound_name(request.prompt_original) == "重型机甲落地"


def test_peak_protection_keeps_original_file_and_registers_new_music(tmp_path):
    from woosh_studio.audio import AudioRenderService

    paths = StudioPaths(tmp_path / "app").ensure()
    projects = ProjectService(LibraryDatabase(paths.database))
    root, manifest = projects.create(tmp_path, "protect")
    source = root / "Generated/music.wav"
    samples = np.sin(np.arange(48000) * 0.04) * 1.5
    sf.write(source, samples, 48000, subtype="FLOAT")
    original = source.read_bytes()
    asset = GeneratedAsset(
        name="Music", kind="music_mix", relative_path="Generated/music.wav"
    )
    manifest.assets.append(asset)
    projects.save(root, manifest)
    result = AudioRenderService(projects).protect_asset(asset.id, str(root))
    assert source.read_bytes() == original
    assert result["asset"].parent_asset_id == asset.id
    output, sr = sf.read(root / result["asset"].relative_path)
    assert np.max(np.abs(output)) <= 0.981
    assert len(result["manifest"].assets) == 2
