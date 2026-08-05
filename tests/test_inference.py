import builtins
from pathlib import Path

import pytest

from woosh_studio.inference import InferenceService
from woosh_studio.schemas import GenerationRequest


def test_unload_does_not_import_torch_without_a_loaded_model(monkeypatch) -> None:
    service = InferenceService.__new__(InferenceService)
    service._model = None
    service._model_id = None
    service._device = None
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "torch":
            raise AssertionError("torch must not be imported for an idle service")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    service.unload()


def test_generation_request_normalizes_and_requires_sound_name() -> None:
    request = GenerationRequest(
        project_path="E:/test.woosh",
        prompt_original="激光枪",
        prompt_conditioned="a laser blaster",
        name="  玩家激光枪  ",
    )

    assert request.name == "玩家激光枪"
    with pytest.raises(ValueError, match="音效名称不能为空"):
        GenerationRequest(
            project_path="E:/test.woosh",
            prompt_original="激光枪",
            prompt_conditioned="a laser blaster",
            name="   ",
        )


def test_generated_filename_uses_requested_sound_name_and_avoids_conflicts(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "Generated"
    generated.mkdir()
    first = InferenceService._unique_generated_name(
        tmp_path, "SFX", "玩家激光枪", 1
    )
    (generated / first).write_bytes(b"existing")

    second = InferenceService._unique_generated_name(
        tmp_path, "SFX", "玩家激光枪", 1
    )

    assert first == "SFX_玩家激光枪_01.wav"
    assert second == "SFX_玩家激光枪_01_2.wav"
