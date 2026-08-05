from pathlib import Path
from types import SimpleNamespace

import ctranslate2
import ctranslate2.converters
import sentencepiece

from woosh_studio.config import StudioPaths
from woosh_studio.inference import TranslationService
from woosh_studio.jobs import JobControl
from woosh_studio.models import (
    ModelService,
    TRANSLATION_DOWNLOAD_SIZE,
    TRANSLATION_MODEL_ID,
    TRANSLATION_SOURCE_FILES,
)
from woosh_studio.storage import LibraryDatabase


def model_service(tmp_path: Path) -> ModelService:
    paths = StudioPaths(tmp_path / "app")
    return ModelService(paths, LibraryDatabase(paths.database))


def create_fake_translation_model(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for filename in (
        "model.bin",
        "config.json",
        "shared_vocabulary.json",
        "source.spm",
        "target.spm",
    ):
        (path / filename).write_bytes(b"test")


def test_translation_catalog_reports_source_download_size(tmp_path: Path) -> None:
    descriptor = next(
        model
        for model in model_service(tmp_path).list_models()
        if model.id == TRANSLATION_MODEL_ID
    )

    assert TRANSLATION_DOWNLOAD_SIZE == sum(
        size for _, size in TRANSLATION_SOURCE_FILES
    )
    assert descriptor.dependencies[0].size_bytes == TRANSLATION_DOWNLOAD_SIZE


def test_translation_download_converts_official_weights_to_int8(
    tmp_path: Path, monkeypatch
) -> None:
    models = model_service(tmp_path)
    updates: list[dict] = []

    def record_update(**changes):
        updates.append(changes)

    def fake_download(_url, destination, _control, on_progress, expected_size=None):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"source")
        on_progress(1, expected_size or 0)

    class FakeConverter:
        def __init__(self, source: str):
            assert Path(source).is_dir()

        def convert(self, destination: str, quantization: str, force: bool):
            assert quantization == "int8"
            assert force is True
            create_fake_translation_model(Path(destination))

    monkeypatch.setattr(models, "_download_file", fake_download)
    monkeypatch.setattr(ctranslate2.converters, "TransformersConverter", FakeConverter)

    result = models._translation_download_worker(
        "job-1", record_update, JobControl()
    )

    destination = models.translation_path()
    assert result == {"model_id": TRANSLATION_MODEL_ID, "path": str(destination)}
    assert models._translation_valid(destination)
    assert any(update.get("stage") == "转换 INT8 翻译模型" for update in updates)


def test_translation_service_uses_ctranslate2_int8(
    tmp_path: Path, monkeypatch
) -> None:
    models = model_service(tmp_path)
    create_fake_translation_model(models.translation_path())

    class FakeTranslator:
        def __init__(self, path: str, device: str, compute_type: str):
            assert Path(path) == models.translation_path()
            assert device == "cpu"
            assert compute_type == "int8"

        def translate_batch(self, tokens, beam_size: int, max_decoding_length: int):
            assert tokens == [["heavy", "mech", "</s>"]]
            assert beam_size == 4
            assert max_decoding_length == 128
            return [SimpleNamespace(hypotheses=[["a", "heavy", "mech"]])]

    class FakeSentencePiece:
        def __init__(self, model_file: str):
            self.target = model_file.endswith("target.spm")

        def encode(self, text: str, out_type):
            assert text == "重型机甲"
            assert out_type is str
            return ["heavy", "mech"]

        def decode(self, tokens):
            assert self.target
            assert tokens == ["a", "heavy", "mech"]
            return "a heavy mech"

    monkeypatch.setattr(ctranslate2, "Translator", FakeTranslator)
    monkeypatch.setattr(sentencepiece, "SentencePieceProcessor", FakeSentencePiece)

    assert TranslationService(models).translate("重型机甲") == "a heavy mech"
