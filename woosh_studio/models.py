from __future__ import annotations

import json

import hashlib
import os
import shutil
import time
import zipfile
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

import httpx

from .config import StudioPaths
from .jobs import JobControl
from .schemas import JobStatus, ModelDependency, ModelDescriptor
from .runtime import runtime_status
from .translation_bundle import ARCHIVE_NAME as MULTILINGUAL_ARCHIVE, MODEL_ID as MULTILINGUAL_MODEL_ID, MODEL_REPO as MULTILINGUAL_REPO, MODEL_REVISION as MULTILINGUAL_REVISION, install_archive
from .storage import LibraryDatabase


RELEASE_API = "https://api.github.com/repos/SonyResearch/Woosh/releases/tags/v1.0.0"
RELEASE_DOWNLOAD = "https://github.com/SonyResearch/Woosh/releases/download/v1.0.0"
WOOSH_LICENSE = "https://creativecommons.org/licenses/by-nc/4.0/"
TRANSLATION_LICENSE = "https://creativecommons.org/licenses/by/4.0/"
TRANSLATION_MODEL_ID = "opus-mt-zh-en"
TRANSLATION_REPO = "Helsinki-NLP/opus-mt-zh-en"
TRANSLATION_INSTALLED_SIZE = 82_500_000
TRANSLATION_SOURCE_FILES = (
    ("config.json", 1_394),
    ("generation_config.json", 293),
    ("pytorch_model.bin", 312_087_009),
    ("source.spm", 804_677),
    ("target.spm", 806_530),
    ("tokenizer_config.json", 44),
    ("vocab.json", 1_617_902),
)
TRANSLATION_DOWNLOAD_SIZE = sum(size for _, size in TRANSLATION_SOURCE_FILES)
HEARTMULA_LICENSE = "https://www.apache.org/licenses/LICENSE-2.0"
DEMUCS_LICENSE = "https://github.com/facebookresearch/demucs/blob/main/LICENSE"
HEARTMULA_RELEASE = "2026-02-13"
HEARTMULA_MODEL_ID = "HeartMuLa-3B"
DEMUCS_MODEL_ID = "Demucs-htdemucs"
QWEN_TTS_CUSTOM_MODEL_ID = "Qwen3-TTS-CustomVoice-1.7B"
QWEN_TTS_BASE_MODEL_ID = "Qwen3-TTS-Base-1.7B"
QWEN_TTS_CUSTOM_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
QWEN_TTS_BASE_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
WHISPER_MODEL_ID = "Whisper-large-v3-turbo"
WHISPER_REPO = "openai/whisper-large-v3-turbo"
HEARTMULA_REQUIRED_SPACE = 30_000_000_000

HEARTMULA_FILES = (
    {
        "repo": "HeartMuLa/HeartMuLa-oss-3B-happy-new-year",
        "path": "HeartMuLa-oss-3B-happy-new-year/config.json",
        "remote": "config.json",
        "size": 308,
        "sha256": None,
    },
    {
        "repo": "HeartMuLa/HeartMuLa-oss-3B-happy-new-year",
        "path": "HeartMuLa-oss-3B-happy-new-year/model-00001-of-00004.safetensors",
        "remote": "model-00001-of-00004.safetensors",
        "size": 4_933_188_000,
        "sha256": "4815367cdbddc0192abe3dbe81e2ae6a6e8978a39ad4dd1d26a20e445b3aeea6",
    },
    {
        "repo": "HeartMuLa/HeartMuLa-oss-3B-happy-new-year",
        "path": "HeartMuLa-oss-3B-happy-new-year/model-00002-of-00004.safetensors",
        "remote": "model-00002-of-00004.safetensors",
        "size": 4_932_808_592,
        "sha256": "f079416ba4c0570231f7a2830a2e95033336a8b3528d1c033a07923a25f4b5d7",
    },
    {
        "repo": "HeartMuLa/HeartMuLa-oss-3B-happy-new-year",
        "path": "HeartMuLa-oss-3B-happy-new-year/model-00003-of-00004.safetensors",
        "remote": "model-00003-of-00004.safetensors",
        "size": 4_935_901_576,
        "sha256": "b43cd60ff50033fa9a5e08c4eb26edff55d5e95e0a313592804ab026ed3b895d",
    },
    {
        "repo": "HeartMuLa/HeartMuLa-oss-3B-happy-new-year",
        "path": "HeartMuLa-oss-3B-happy-new-year/model-00004-of-00004.safetensors",
        "remote": "model-00004-of-00004.safetensors",
        "size": 950_588_000,
        "sha256": "07c5f5820c0c00f0b8ad4544ed8a24ae1888f7d8c8a5d8bb3cdaba418a39cf2f",
    },
    {
        "repo": "HeartMuLa/HeartMuLa-oss-3B-happy-new-year",
        "path": "HeartMuLa-oss-3B-happy-new-year/model.safetensors.index.json",
        "remote": "model.safetensors.index.json",
        "size": 22_579,
        "sha256": None,
    },
    {
        "repo": "HeartMuLa/HeartCodec-oss-20260123",
        "path": "HeartCodec-oss/config.json",
        "remote": "config.json",
        "size": 981,
        "sha256": None,
    },
    {
        "repo": "HeartMuLa/HeartCodec-oss-20260123",
        "path": "HeartCodec-oss/model-00001-of-00002.safetensors",
        "remote": "model-00001-of-00002.safetensors",
        "size": 4_930_472_472,
        "sha256": "50d2c022468a0e127992d99e02117d2efbad2b10fddc8ceaf09550f154e185d4",
    },
    {
        "repo": "HeartMuLa/HeartCodec-oss-20260123",
        "path": "HeartCodec-oss/model-00002-of-00002.safetensors",
        "remote": "model-00002-of-00002.safetensors",
        "size": 1_707_911_436,
        "sha256": "6f319d0f5b31858dfe98bd8fc89d3083cbfff74ac75a0531f1a7b86949197917",
    },
    {
        "repo": "HeartMuLa/HeartCodec-oss-20260123",
        "path": "HeartCodec-oss/model.safetensors.index.json",
        "remote": "model.safetensors.index.json",
        "size": 83_875,
        "sha256": None,
    },
    {
        "repo": "HeartMuLa/HeartMuLaGen",
        "path": "tokenizer.json",
        "remote": "tokenizer.json",
        "size": 9_085_657,
        "sha256": None,
    },
    {
        "repo": "HeartMuLa/HeartMuLaGen",
        "path": "gen_config.json",
        "remote": "gen_config.json",
        "size": 101,
        "sha256": None,
    },
)
HEARTMULA_SIZE = sum(int(item["size"]) for item in HEARTMULA_FILES)
DEMUCS_FILE = {
    "name": "955717e8-8726e21a.th",
    "size": 84_141_911,
    "sha256": "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4",
    "url": "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th",
}

MODEL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "Woosh-DFlow": {
        "name": "Woosh DFlow",
        "description": "四步蒸馏模型，适合快速生成和批量探索。",
        "assets": ["Woosh-DFlow.zip", "Woosh-AE.zip", "TextConditionerA.zip"],
        "controls": ["cfg", "seed"],
    },
    "Woosh-Flow": {
        "name": "Woosh Flow",
        "description": "完整流匹配模型，适合最终质量渲染。",
        "assets": ["Woosh-Flow.zip", "Woosh-AE.zip", "TextConditionerA.zip"],
        "controls": ["cfg", "seed", "solver", "atol", "rtol"],
    },
}
WOOSH_OFFLINE_ASSETS = (
    "Woosh-DFlow.zip",
    "Woosh-Flow.zip",
    "Woosh-AE.zip",
    "TextConditionerA.zip",
)
MUSIC_OFFLINE_ASSETS = (
    f"{HEARTMULA_MODEL_ID}.zip",
    f"{DEMUCS_MODEL_ID}.zip",
)
# Kept as the public Woosh bundle list used by the existing installer scripts.
OFFLINE_ASSETS = WOOSH_OFFLINE_ASSETS


def safe_extract_zip(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError(f"下载包校验失败: {archive.name}")
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if target != destination and destination not in target.parents:
                raise RuntimeError(f"下载包包含不安全路径: {member.filename}")
        bundle.extractall(destination)


def install_checkpoint_archive(archive: Path, destination: Path) -> None:
    temporary = destination.parent / f".{destination.name}-{uuid4().hex}.tmp"
    temporary.mkdir(parents=True)
    try:
        safe_extract_zip(archive, temporary)
        candidates = [
            config.parent
            for config in temporary.rglob("config.yaml")
            if ModelService._checkpoint_valid(config.parent)
        ]
        if len(candidates) != 1:
            raise RuntimeError(f"{archive.name} 中没有有效 checkpoint")
        source = candidates[0]
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(source, destination)
        shutil.rmtree(temporary, ignore_errors=True)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


class ModelService:
    def __init__(self, paths: StudioPaths, database: LibraryDatabase):
        self.paths = paths
        self.database = database
        self._asset_locks: dict[str, Lock] = {}

    @property
    def models_root(self) -> Path:
        configured = self.database.get_settings().model_root
        root = (
            Path(configured).expanduser().resolve() if configured else self.paths.models
        )
        root.mkdir(parents=True, exist_ok=True)
        return root

    @property
    def downloads_root(self) -> Path:
        root = self.models_root / ".downloads"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def install_offline_archives(self, archive_directory: Path) -> None:
        selected_models = [
            model_id
            for model_id in MODEL_DEFINITIONS
            if (archive_directory / f"{model_id}.zip").is_file()
        ]
        multilingual_archive = archive_directory / MULTILINGUAL_ARCHIVE
        if multilingual_archive.is_file():
            self.ensure_bundled_translation(multilingual_archive)
        music_archive = archive_directory / f"{HEARTMULA_MODEL_ID}.zip"
        demucs_archive = archive_directory / f"{DEMUCS_MODEL_ID}.zip"
        if music_archive.is_file() and not self._music_valid(self.music_path()):
            print("WOOSH_OFFLINE_PROGRESS 0 1 HeartMuLa-3B", flush=True)
            self._install_music_archive(music_archive)
            self.database.accept_license(HEARTMULA_MODEL_ID, HEARTMULA_RELEASE)
            music_archive.unlink(missing_ok=True)
            print("WOOSH_OFFLINE_PROGRESS 1 1 HeartMuLa-3B", flush=True)
        if demucs_archive.is_file() and not self._demucs_valid(self.demucs_path()):
            print("WOOSH_OFFLINE_PROGRESS 0 1 Demucs-htdemucs", flush=True)
            self._install_demucs_archive(demucs_archive)
            demucs_archive.unlink(missing_ok=True)
            print("WOOSH_OFFLINE_PROGRESS 1 1 Demucs-htdemucs", flush=True)
        if not selected_models:
            if music_archive.exists() or demucs_archive.exists():
                return
            print("WOOSH_OFFLINE_COMPLETE", flush=True)
            return

        selected_assets = list(
            dict.fromkeys(
                asset
                for model_id in selected_models
                for asset in MODEL_DEFINITIONS[model_id]["assets"]
            )
        )
        completed = 0
        total = len(selected_assets)
        for asset in selected_assets:
            model_id = Path(asset).stem
            target = self.dependency_path(model_id)
            archive = archive_directory / asset
            print(f"WOOSH_OFFLINE_PROGRESS {completed} {total} {model_id}", flush=True)
            if not self._checkpoint_valid(target):
                if not archive.is_file():
                    raise RuntimeError(f"离线安装包缺少 {asset}")
                install_checkpoint_archive(archive, target)
            completed += 1
            print(f"WOOSH_OFFLINE_PROGRESS {completed} {total} {model_id}", flush=True)
            archive.unlink(missing_ok=True)
        for model_id in selected_models:
            self.database.accept_license(model_id, "v1.0.0")
        print("WOOSH_OFFLINE_COMPLETE", flush=True)

    def list_models(self) -> list[ModelDescriptor]:
        sizes = self._release_sizes()
        descriptors: list[ModelDescriptor] = []
        for model_id, definition in MODEL_DEFINITIONS.items():
            dependencies = [
                ModelDependency(
                    id=Path(asset).stem,
                    asset_name=asset,
                    size_bytes=sizes.get(asset, 0),
                )
                for asset in definition["assets"]
            ]
            descriptors.append(
                ModelDescriptor(
                    id=model_id,
                    name=definition["name"],
                    family="text",
                    description=definition["description"],
                    license="CC BY-NC 4.0",
                    license_url=WOOSH_LICENSE,
                    installed=self.is_installed(model_id),
                    path=str(self.model_path(model_id))
                    if self.is_installed(model_id)
                    else None,
                    dependencies=dependencies,
                    controls=definition["controls"],
                )
            )
        runtime_ready = runtime_status().ready
        music_path = self.music_path()
        descriptors.append(
            ModelDescriptor(
                id=HEARTMULA_MODEL_ID,
                name="HeartMuLa 3B",
                family="music",
                description="生成纯音乐 BGM 与多语言带歌词歌曲，最长约 4 分钟。",
                release=HEARTMULA_RELEASE,
                license="Apache 2.0",
                license_url=HEARTMULA_LICENSE,
                installed=self._music_valid(music_path),
                path=str(music_path) if self._music_valid(music_path) else None,
                dependencies=[
                    ModelDependency(
                        id="HeartMuLa-oss-3B-happy-new-year",
                        asset_name="HeartMuLa 3B weights",
                        size_bytes=15_752_508_476,
                    ),
                    ModelDependency(
                        id="HeartCodec-oss",
                        asset_name="HeartCodec weights",
                        size_bytes=6_638_468_764,
                    ),
                    ModelDependency(
                        id="HeartMuLaGen",
                        asset_name="Tokenizer and generation config",
                        size_bytes=9_085_758,
                    ),
                ],
                controls=[
                    "tags",
                    "lyrics",
                    "duration",
                    "temperature",
                    "top_k",
                    "cfg_scale",
                    "seed",
                ],
                engine="heartmula",
                model_source="modelscope",
                memory_mode="auto_low_vram",
                supported=runtime_ready,
            )
        )
        demucs_path = self.demucs_path()
        descriptors.append(
            ModelDescriptor(
                id=DEMUCS_MODEL_ID,
                name="Demucs 四分轨",
                family="separation",
                description="将完整音乐后处理为人声、鼓、贝斯和其他四个可编辑音轨。",
                release="htdemucs",
                license="MIT",
                license_url=DEMUCS_LICENSE,
                installed=self._demucs_valid(demucs_path),
                path=str(demucs_path) if self._demucs_valid(demucs_path) else None,
                dependencies=[
                    ModelDependency(
                        id="htdemucs",
                        asset_name=DEMUCS_FILE["name"],
                        size_bytes=int(DEMUCS_FILE["size"]),
                    )
                ],
                controls=["four_stems"],
                engine="demucs",
                model_source="github",
                supported=runtime_ready,
            )
        )
        for model_id, name, description, repo in (
            (
                QWEN_TTS_CUSTOM_MODEL_ID,
                "Qwen3-TTS 固定音色",
                "内置 9 种角色音色，支持语气与情绪指令。",
                QWEN_TTS_CUSTOM_REPO,
            ),
            (
                QWEN_TTS_BASE_MODEL_ID,
                "Qwen3-TTS 参考音色",
                "使用本地参考音频固定角色音色，支持多语言台词。",
                QWEN_TTS_BASE_REPO,
            ),
        ):
            path = self.model_path(model_id)
            descriptors.append(
                ModelDescriptor(
                    id=model_id,
                    name=name,
                    family="speech",
                    description=description,
                    release="12Hz-1.7B",
                    license="Apache 2.0",
                    license_url="https://www.apache.org/licenses/LICENSE-2.0",
                    installed=self._speech_valid(path),
                    path=str(path) if self._speech_valid(path) else None,
                    dependencies=[
                        ModelDependency(id=model_id, asset_name=repo, size_bytes=0)
                    ],
                    controls=["language", "speaker", "instruct"],
                    engine="qwen_tts",
                    model_source="huggingface",
                    memory_mode="auto_low_vram",
                    supported=runtime_ready,
                )
            )
        descriptors.append(ModelDescriptor(
            id=MULTILINGUAL_MODEL_ID, name="多语种对白翻译", family="translation",
            description="M2M100 INT8 本地翻译，随应用安装，首次启动自动准备；支持中、英、日、韩等语言互译，无需下载。",
            bundled=bool(self.bundled_translation_archive()),
            license="MIT", license_url="https://huggingface.co/facebook/m2m100_418M",
            installed=self._multilingual_valid(self.model_path(MULTILINGUAL_MODEL_ID)),
            path=str(self.model_path(MULTILINGUAL_MODEL_ID)) if self._multilingual_valid(self.model_path(MULTILINGUAL_MODEL_ID)) else None,
            dependencies=[] if self.bundled_translation_archive() else [ModelDependency(id=MULTILINGUAL_MODEL_ID, asset_name="M2M100 源权重与分词器", size_bytes=1900000000)],
            controls=[], engine="ctranslate2", model_source="local" if self.bundled_translation_archive() else "huggingface", memory_mode="cpu",
        ))
        asr_path = self.model_path(WHISPER_MODEL_ID)
        descriptors.append(ModelDescriptor(id=WHISPER_MODEL_ID, name="Whisper 参考音频转文字", family="transcription",
            description="本地识别麦克风录音或参考音频，识别后的台词可校对编辑。安装后离线使用。",
            release="large-v3-turbo", license="MIT", license_url="https://huggingface.co/openai/whisper-large-v3-turbo",
            installed=self._asr_valid(asr_path), path=str(asr_path) if self._asr_valid(asr_path) else None,
            dependencies=[ModelDependency(id=WHISPER_MODEL_ID, asset_name=WHISPER_REPO)],
            engine="transformers", model_source="huggingface", controls=["transcribe"], supported=runtime_ready))
        translation_path = self.translation_path()
        if self._translation_valid(translation_path) or not self.bundled_translation_archive():
            descriptors.append(
                ModelDescriptor(
                    id=TRANSLATION_MODEL_ID,
                    name="轻量中文转英文",
                    family="translation",
                    description="约 82 MB 的 INT8 本地翻译模型，首次使用自动准备。",
                    license="CC BY 4.0",
                    license_url=TRANSLATION_LICENSE,
                    installed=self._translation_valid(translation_path),
                    path=(
                        str(translation_path)
                        if self._translation_valid(translation_path)
                        else None
                    ),
                    dependencies=[
                        ModelDependency(
                            id="opus-mt-zh-en-int8",
                            asset_name="CTranslate2 INT8 weights",
                            size_bytes=TRANSLATION_DOWNLOAD_SIZE,
                        )
                    ],
                    controls=[],
                    engine="ctranslate2",
                    model_source="huggingface",
                    memory_mode="cpu",
                )
            )
        for custom in self.database.custom_models():
            descriptors.append(
                ModelDescriptor(
                    id=custom["id"],
                    name=custom["id"],
                    family="text",
                    description="用户注册的本地 checkpoint。",
                    license="用户提供",
                    license_url="",
                    installed=Path(custom["path"]).exists(),
                    custom=True,
                    path=custom["path"],
                    controls=["cfg", "seed"],
                )
            )
        return descriptors

    def model_path(self, model_id: str) -> Path:
        if model_id == HEARTMULA_MODEL_ID:
            return self.music_path()
        if model_id == DEMUCS_MODEL_ID:
            return self.demucs_path()
        if model_id in {QWEN_TTS_CUSTOM_MODEL_ID, QWEN_TTS_BASE_MODEL_ID}:
            return self.models_root / "Qwen3-TTS" / model_id
        custom = next(
            (item for item in self.database.custom_models() if item["id"] == model_id),
            None,
        )
        if custom:
            return Path(custom["path"])
        return self.models_root / model_id

    def dependency_path(self, name: str) -> Path:
        return self.models_root / name

    def translation_path(self) -> Path:
        return self.models_root / "opus-mt-zh-en-int8"

    def music_path(self) -> Path:
        return self.models_root / "HeartMuLa"

    def demucs_path(self) -> Path:
        return self.models_root / DEMUCS_MODEL_ID

    def is_installed(self, model_id: str) -> bool:
        if model_id == WHISPER_MODEL_ID:
            return self._asr_valid(self.model_path(model_id))
        if model_id == MULTILINGUAL_MODEL_ID:
            return self._multilingual_valid(self.model_path(model_id))
        if model_id == TRANSLATION_MODEL_ID:
            return self._translation_valid(self.translation_path())
        if model_id == HEARTMULA_MODEL_ID:
            return self._music_valid(self.music_path())
        if model_id == DEMUCS_MODEL_ID:
            return self._demucs_valid(self.demucs_path())
        if model_id in {QWEN_TTS_CUSTOM_MODEL_ID, QWEN_TTS_BASE_MODEL_ID}:
            return self._speech_valid(self.model_path(model_id))
        definition = MODEL_DEFINITIONS.get(model_id)
        if not definition:
            return self.model_path(model_id).exists()
        return all(
            self._checkpoint_valid(self.dependency_path(Path(asset).stem))
            for asset in definition["assets"]
        )

    def register_custom(self, model_id: str, path: Path) -> ModelDescriptor:
        path = path.expanduser().resolve()
        if not self._checkpoint_valid(path):
            raise ValueError(
                "checkpoint 必须包含 config.yaml 和 weights.safetensors/weights.pt"
            )
        self.database.register_custom_model(model_id, path, "text")
        return next(item for item in self.list_models() if item.id == model_id)

    def remove(self, model_id: str) -> None:
        if model_id == MULTILINGUAL_MODEL_ID and self.bundled_translation_archive():
            raise ValueError("多语种翻译是内置组件，由应用自动维护")
        removable = {
            WHISPER_MODEL_ID,
            *MODEL_DEFINITIONS,
            TRANSLATION_MODEL_ID,
            MULTILINGUAL_MODEL_ID,
            HEARTMULA_MODEL_ID,
            DEMUCS_MODEL_ID,
            QWEN_TTS_CUSTOM_MODEL_ID,
            QWEN_TTS_BASE_MODEL_ID,
        }
        if model_id not in removable:
            raise ValueError("自定义模型只会取消注册，不删除用户文件")
        target = (
            self.translation_path()
            if model_id == TRANSLATION_MODEL_ID
            else self.model_path(model_id)
        )
        if target.exists():
            shutil.rmtree(target)

    def download_worker(self, model_id: str):
        if model_id == WHISPER_MODEL_ID:
            return self._asr_download_worker
        if model_id == MULTILINGUAL_MODEL_ID:
            return self._multilingual_download_worker
        if model_id == TRANSLATION_MODEL_ID:
            return self._translation_download_worker
        if model_id == HEARTMULA_MODEL_ID:
            return self._music_download_worker
        if model_id == DEMUCS_MODEL_ID:
            return self._demucs_download_worker
        if model_id in {QWEN_TTS_CUSTOM_MODEL_ID, QWEN_TTS_BASE_MODEL_ID}:
            return self._speech_download_worker(model_id)
        if model_id not in MODEL_DEFINITIONS:
            raise KeyError(model_id)

        def worker(job_id: str, update, control: JobControl) -> dict[str, Any]:
            if os.environ.get("WOOSH_STUDIO_OFFLINE") == "1":
                raise RuntimeError("当前为离线运行模式，无法在线下载模型")
            if not self.database.license_accepted(model_id, "v1.0.0"):
                raise RuntimeError("下载官方权重前必须确认 CC BY-NC 4.0 许可")
            assets = MODEL_DEFINITIONS[model_id]["assets"]
            sizes = self._release_sizes()
            required = sum(sizes.get(asset, 0) for asset in assets)
            if shutil.disk_usage(self.models_root).free < max(
                required * 2, 1_000_000_000
            ):
                raise RuntimeError("磁盘剩余空间不足以下载并解压模型")
            installed: list[str] = []
            for index, asset in enumerate(assets):
                lock = self._asset_locks.setdefault(asset, Lock())
                with lock:
                    control.checkpoint()
                    target = self.dependency_path(Path(asset).stem)
                    if self._checkpoint_valid(target):
                        installed.append(target.name)
                        continue
                    archive = self.downloads_root / asset
                    base_progress = index / len(assets)
                    self._download_file(
                        f"{RELEASE_DOWNLOAD}/{asset}",
                        archive,
                        control,
                        lambda progress, speed: update(
                            status=JobStatus.RUNNING,
                            stage=f"下载 {Path(asset).stem}",
                            progress=base_progress + progress / len(assets),
                            speed_bytes_per_second=speed,
                        ),
                        expected_size=sizes.get(asset),
                    )
                    update(stage=f"安装 {Path(asset).stem}")
                    self._install_archive(archive, target)
                    installed.append(target.name)
            return {"model_id": model_id, "installed": installed}

        return worker

    def _music_download_worker(
        self, job_id: str, update, control: JobControl
    ) -> dict[str, Any]:
        if os.environ.get("WOOSH_STUDIO_OFFLINE") == "1":
            raise RuntimeError("当前为离线运行模式，无法在线下载 HeartMuLa")
        if not self.database.license_accepted(HEARTMULA_MODEL_ID, HEARTMULA_RELEASE):
            raise RuntimeError("下载 HeartMuLa 权重前必须确认 Apache 2.0 许可")
        root = self.music_path()
        root.mkdir(parents=True, exist_ok=True)
        missing = [
            item
            for item in HEARTMULA_FILES
            if not self._remote_file_valid(root / str(item["path"]), item)
        ]
        required = sum(int(item["size"]) for item in missing)
        if missing and shutil.disk_usage(self.models_root).free < max(
            required + 5_000_000_000, HEARTMULA_REQUIRED_SPACE
        ):
            raise RuntimeError("HeartMuLa 安装至少需要 30 GB 可用空间")
        source = self.database.get_settings().model_download_source
        if source == "auto":
            source = "modelscope"
        total_bytes = max(required, 1)
        completed_bytes = 0
        for index, item in enumerate(missing):
            control.checkpoint()
            target = root / str(item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            url = self._model_file_url(source, str(item["repo"]), str(item["remote"]))
            item_size = int(item["size"])
            self._download_file(
                url,
                target,
                control,
                lambda progress, speed, item=item, item_size=item_size, completed_bytes=completed_bytes: (
                    update(
                        status=JobStatus.RUNNING,
                        stage=f"下载 {Path(str(item['path'])).name}",
                        progress=(completed_bytes + progress * item_size)
                        / total_bytes
                        * 0.92,
                        speed_bytes_per_second=speed,
                    )
                ),
                expected_size=item_size,
            )
            update(
                status=JobStatus.RUNNING,
                stage=f"校验 {Path(str(item['path'])).name}",
                progress=(completed_bytes + item_size) / total_bytes * 0.92,
            )
            if not self._remote_file_valid(target, item, verify_hash=True):
                target.unlink(missing_ok=True)
                raise RuntimeError(f"HeartMuLa 文件校验失败: {target.name}")
            completed_bytes += item_size
        if not self._music_valid(root):
            raise RuntimeError("HeartMuLa 下载完成但目录结构校验失败")
        update(progress=0.98, stage="登记 HeartMuLa")
        return {"model_id": HEARTMULA_MODEL_ID, "path": str(root), "source": source}

    def _demucs_download_worker(
        self, job_id: str, update, control: JobControl
    ) -> dict[str, Any]:
        if os.environ.get("WOOSH_STUDIO_OFFLINE") == "1":
            raise RuntimeError("当前为离线运行模式，无法在线下载 Demucs")
        target = self.demucs_path() / str(DEMUCS_FILE["name"])
        target.parent.mkdir(parents=True, exist_ok=True)
        self._download_file(
            str(DEMUCS_FILE["url"]),
            target,
            control,
            lambda progress, speed: update(
                status=JobStatus.RUNNING,
                stage="下载 Demucs htdemucs",
                progress=progress * 0.95,
                speed_bytes_per_second=speed,
            ),
            expected_size=int(DEMUCS_FILE["size"]),
        )
        if not self._remote_file_valid(target, DEMUCS_FILE, verify_hash=True):
            target.unlink(missing_ok=True)
            raise RuntimeError("Demucs 权重校验失败")
        self._prepare_demucs_repository(target.parent)
        return {"model_id": DEMUCS_MODEL_ID, "path": str(target)}

    @staticmethod
    def _asr_valid(path):
        return all((path / name).is_file() for name in ("config.json", "preprocessor_config.json", "tokenizer.json", "model.safetensors"))

    def _asr_download_worker(self, job_id, update, control):
        if os.environ.get("WOOSH_STUDIO_OFFLINE") == "1":
            raise RuntimeError("当前为离线运行模式，请将 Whisper-large-v3-turbo 本地模型文件夹放入共享模型目录")
        from huggingface_hub import HfApi
        target = self.model_path(WHISPER_MODEL_ID)
        update(status=JobStatus.RUNNING, stage="获取语音识别模型文件清单", progress=0.01)
        info = HfApi().model_info(WHISPER_REPO, files_metadata=True)
        wanted = [item for item in info.siblings if item.rfilename in {"config.json", "generation_config.json", "preprocessor_config.json", "tokenizer.json", "tokenizer_config.json", "normalizer.json", "special_tokens_map.json", "vocab.json", "merges.txt", "added_tokens.json", "model.safetensors"}]
        total = sum(item.size or 0 for item in wanted) or 1
        if shutil.disk_usage(self.models_root).free < total + 500_000_000:
            raise RuntimeError("磁盘空间不足以安装语音识别模型")
        completed = 0
        for item in wanted:
            control.checkpoint()
            self._download_file(f"https://huggingface.co/{WHISPER_REPO}/resolve/{info.sha}/{item.rfilename}", target / item.rfilename,
                control, lambda value, speed: update(status=JobStatus.RUNNING, stage=f"下载语音识别模型 · {item.rfilename}", progress=(completed + value * (item.size or 0)) / total * 0.97,
                speed_bytes_per_second=speed), expected_size=item.size)
            if item.lfs and item.lfs.sha256:
                from .localization import file_digest
                if file_digest(target / item.rfilename) != item.lfs.sha256:
                    raise RuntimeError("语音识别模型权重校验失败")
            completed += item.size or 0
        if not self._asr_valid(target):
            raise RuntimeError("语音识别模型文件不完整")
        (target / "woosh-model-revision.json").write_text(json.dumps({"revision": info.sha}), encoding="utf-8")
        return {"model_id": WHISPER_MODEL_ID, "path": str(target)}

    def _speech_download_worker(self, model_id: str):
        def worker(job_id: str, update, control: JobControl) -> dict[str, Any]:
            if os.environ.get("WOOSH_STUDIO_OFFLINE") == "1":
                raise RuntimeError("当前为离线运行模式，无法在线下载 Qwen3-TTS")
            from huggingface_hub import snapshot_download

            repo = (
                QWEN_TTS_CUSTOM_REPO
                if model_id == QWEN_TTS_CUSTOM_MODEL_ID
                else QWEN_TTS_BASE_REPO
            )
            target = self.model_path(model_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            update(status=JobStatus.RUNNING, stage="下载 Qwen3-TTS", progress=0.1)
            snapshot_download(
                repo_id=repo, local_dir=str(target)
            )
            update(status=JobStatus.RUNNING, stage="验证 Qwen3-TTS", progress=0.98)
            if not self._speech_valid(target):
                raise RuntimeError("Qwen3-TTS 模型目录校验失败")
            return {"model_id": model_id, "path": str(target), "repo": repo}

        return worker

    def bundled_translation_archive(self) -> Path | None:
        standalone = os.environ.get("WOOSH_STUDIO_TRANSLATION_BUNDLE")
        if standalone and Path(standalone).is_file():
            return Path(standalone)
        configured = os.environ.get("WOOSH_STUDIO_OFFLINE_MODELS")
        if configured:
            candidate = Path(configured) / MULTILINGUAL_ARCHIVE
            if candidate.is_file():
                return candidate
        # Installed backend lives in <app>/python/woosh_studio. Development
        # launchers pass an explicit archive directory; tests stay self contained.
        candidate = Path(__file__).resolve().parents[2] / "offline-model-archives" / MULTILINGUAL_ARCHIVE
        return candidate if candidate.is_file() else None

    def ensure_bundled_translation(self, archive: Path | None = None) -> Path:
        target = self.model_path(MULTILINGUAL_MODEL_ID)
        archive = archive or self.bundled_translation_archive()
        if archive is None:
            return target
        with self._asset_locks.setdefault(MULTILINGUAL_MODEL_ID, Lock()):
            print("WOOSH_OFFLINE_PROGRESS 0 1 内置多语种翻译", flush=True)
            try:
                install_archive(archive, target)
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                raise RuntimeError(f"内置多语种翻译准备失败，请修复安装或检查模型目录权限：{error}") from error
            print("WOOSH_OFFLINE_PROGRESS 1 1 内置多语种翻译", flush=True)
        return target

    def _install_multilingual_archive(self, archive: Path) -> None:
        self.ensure_bundled_translation(archive)

    @staticmethod
    def _multilingual_valid(path: Path) -> bool:
        return all((path / filename).is_file() for filename in ("model.bin", "config.json", "shared_vocabulary.json", "tokenizer/sentencepiece.bpe.model", "tokenizer/vocab.json"))

    def _multilingual_download_worker(self, job_id, update, control):
        if self.bundled_translation_archive():
            update(status=JobStatus.RUNNING, stage="准备内置多语种翻译", progress=0.1)
            control.checkpoint()
            target = self.ensure_bundled_translation()
            return {"model_id": MULTILINGUAL_MODEL_ID, "path": str(target), "source": "bundled"}
        target = self.model_path(MULTILINGUAL_MODEL_ID)
        with self._asset_locks.setdefault(MULTILINGUAL_MODEL_ID, Lock()):
            if self._multilingual_valid(target):
                return {"model_id": MULTILINGUAL_MODEL_ID, "path": str(target)}
            if os.environ.get("WOOSH_STUDIO_OFFLINE") == "1":
                raise RuntimeError("多语种翻译模型尚未安装。当前离线，请将完整 m2m100-418M-int8 文件夹复制到模型目录。")
            from huggingface_hub import snapshot_download
            from ctranslate2.converters import TransformersConverter
            if shutil.disk_usage(self.models_root).free < 5_000_000_000:
                raise RuntimeError("安装多语种翻译模型需要至少 5 GB 可用空间")
            source = self.downloads_root / ".m2m100-source"
            staging = target.with_name(f".{target.name}-{uuid4().hex}.tmp")
            try:
                update(status=JobStatus.RUNNING, stage="下载多语种翻译模型（约 1.9 GB）", progress=0.05)
                snapshot_download(repo_id=MULTILINGUAL_REPO, revision=MULTILINGUAL_REVISION, local_dir=str(source), allow_patterns=["*.json", "pytorch_model.bin", "sentencepiece.bpe.model"])
                control.checkpoint()
                update(status=JobStatus.RUNNING, stage="转换多语种 INT8 翻译模型", progress=0.8)
                TransformersConverter(str(source)).convert(str(staging), quantization="int8", force=True)
                tokenizer = staging / "tokenizer"
                tokenizer.mkdir()
                for file in source.iterdir():
                    if file.suffix == ".json" or file.name == "sentencepiece.bpe.model":
                        shutil.copy2(file, tokenizer / file.name)
                control.checkpoint()
                if not self._multilingual_valid(staging):
                    raise RuntimeError("多语种翻译模型转换校验失败")
                if target.exists():
                    shutil.rmtree(target)
                os.replace(staging, target)
                return {"model_id": MULTILINGUAL_MODEL_ID, "path": str(target)}
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    def _translation_download_worker(
        self, job_id: str, update, control: JobControl
    ) -> dict[str, Any]:
        if os.environ.get("WOOSH_STUDIO_OFFLINE") == "1":
            raise RuntimeError("当前为离线运行模式，无法在线下载翻译模型")
        destination = self.translation_path()
        if self._translation_valid(destination):
            return {"model_id": TRANSLATION_MODEL_ID, "path": str(destination)}

        required = sum(size for _, size in TRANSLATION_SOURCE_FILES)
        if shutil.disk_usage(self.models_root).free < required + 500_000_000:
            raise RuntimeError("轻量翻译模型准备需要至少 800 MB 可用空间")

        source = self.downloads_root / f".{TRANSLATION_MODEL_ID}-source"
        converted = destination.with_name(f".{destination.name}-{uuid4().hex}.tmp")
        source.mkdir(parents=True, exist_ok=True)
        try:
            completed = 0
            for filename, size in TRANSLATION_SOURCE_FILES:
                control.checkpoint()
                target = source / filename
                self._download_file(
                    self._translation_file_url(filename),
                    target,
                    control,
                    lambda progress, speed, filename=filename, size=size, completed=completed: (
                        update(
                            status=JobStatus.RUNNING,
                            stage=f"下载轻量翻译模型 · {filename}",
                            progress=(completed + progress * size) / required * 0.72,
                            speed_bytes_per_second=speed,
                        )
                    ),
                    expected_size=size,
                )
                completed += size

            control.checkpoint()
            update(status=JobStatus.RUNNING, stage="转换 INT8 翻译模型", progress=0.76)
            from ctranslate2.converters import TransformersConverter

            TransformersConverter(str(source)).convert(
                str(converted), quantization="int8", force=True
            )
            for filename in ("source.spm", "target.spm"):
                shutil.copy2(source / filename, converted / filename)
            control.checkpoint()
            update(status=JobStatus.RUNNING, stage="验证轻量翻译模型", progress=0.96)
            if not self._translation_valid(converted):
                raise RuntimeError("INT8 翻译模型转换结果校验失败")
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(converted, destination)
            return {"model_id": TRANSLATION_MODEL_ID, "path": str(destination)}
        finally:
            shutil.rmtree(source, ignore_errors=True)
            shutil.rmtree(converted, ignore_errors=True)

    @staticmethod
    def _translation_file_url(filename: str) -> str:
        return (
            f"https://huggingface.co/{TRANSLATION_REPO}/resolve/main/"
            f"{filename}?download=true"
        )

    def _download_file(
        self,
        url: str,
        destination: Path,
        control: JobControl,
        on_progress,
        expected_size: int | None = None,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        existing = partial.stat().st_size if partial.exists() else 0
        if expected_size is not None and existing > expected_size:
            partial.unlink()
            existing = 0
        if expected_size is not None and existing == expected_size:
            os.replace(partial, destination)
            on_progress(1, 0)
            return

        last_error: Exception | None = None
        for attempt in range(5):
            existing = partial.stat().st_size if partial.exists() else 0
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            started = time.monotonic()
            try:
                with httpx.stream(
                    "GET", url, headers=headers, follow_redirects=True, timeout=None
                ) as response:
                    response.raise_for_status()
                    if existing and response.status_code == 200:
                        existing = 0
                        partial.unlink(missing_ok=True)
                    response_size = int(response.headers.get("content-length", "0"))
                    total = expected_size or (existing + response_size)
                    mode = "ab" if existing else "wb"
                    written = existing
                    with partial.open(mode) as handle:
                        for chunk in response.iter_bytes(1024 * 1024):
                            control.checkpoint()
                            handle.write(chunk)
                            written += len(chunk)
                            elapsed = max(time.monotonic() - started, 0.001)
                            progress = min(written / total, 1) if total else 0
                            on_progress(progress, (written - existing) / elapsed)
                if expected_size is None or written == expected_size:
                    os.replace(partial, destination)
                    return
                last_error = RuntimeError(
                    f"下载文件大小校验失败: 预期 {expected_size} 字节，"
                    f"实际 {written} 字节"
                )
            except httpx.HTTPError as error:
                last_error = error

            if attempt < 4:
                control.checkpoint()
                time.sleep(min(2**attempt, 8))

        if isinstance(last_error, RuntimeError):
            raise last_error
        raise RuntimeError(f"模型下载网络错误: {last_error}") from last_error

    def _install_archive(self, archive: Path, destination: Path) -> None:
        install_checkpoint_archive(archive, destination)

    def _install_music_archive(self, archive: Path) -> None:
        destination = self.music_path()
        temporary = destination.parent / f".{destination.name}-{uuid4().hex}.tmp"
        temporary.mkdir(parents=True)
        try:
            safe_extract_zip(archive, temporary)
            candidates = [
                path
                for path in (temporary, *temporary.iterdir())
                if path.is_dir() and self._music_valid(path)
            ]
            if len(candidates) != 1:
                raise RuntimeError("HeartMuLa 离线包目录结构无效")
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(candidates[0], destination)
            shutil.rmtree(temporary, ignore_errors=True)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _install_demucs_archive(self, archive: Path) -> None:
        destination = self.demucs_path()
        temporary = destination.parent / f".{destination.name}-{uuid4().hex}.tmp"
        temporary.mkdir(parents=True)
        try:
            safe_extract_zip(archive, temporary)
            weight = next(temporary.rglob(str(DEMUCS_FILE["name"])), None)
            if weight is None or weight.stat().st_size != int(DEMUCS_FILE["size"]):
                raise RuntimeError("Demucs 离线包目录结构无效")
            destination.mkdir(parents=True, exist_ok=True)
            os.replace(weight, destination / weight.name)
            self._prepare_demucs_repository(destination)
            shutil.rmtree(temporary, ignore_errors=True)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @staticmethod
    def _model_file_url(source: str, repo: str, remote: str) -> str:
        if source == "modelscope":
            return f"https://www.modelscope.cn/models/{repo}/resolve/master/{remote}"
        return f"https://huggingface.co/{repo}/resolve/main/{remote}?download=true"

    @staticmethod
    def _remote_file_valid(
        path: Path, definition: dict[str, Any], verify_hash: bool = False
    ) -> bool:
        if not path.is_file() or path.stat().st_size != int(definition["size"]):
            return False
        expected = definition.get("sha256")
        if not verify_hash or not expected:
            return True
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest() == expected

    @classmethod
    def _music_valid(cls, path: Path) -> bool:
        return all(
            cls._remote_file_valid(path / str(item["path"]), item)
            for item in HEARTMULA_FILES
        )

    @staticmethod
    def _demucs_valid(path: Path) -> bool:
        target = path / str(DEMUCS_FILE["name"])
        return target.is_file() and target.stat().st_size == int(DEMUCS_FILE["size"])

    @staticmethod
    def _speech_valid(path: Path) -> bool:
        return (
            (path / "config.json").is_file()
            and (path / "model.safetensors").is_file()
            and (path / "speech_tokenizer").is_dir()
        )

    @staticmethod
    def _translation_valid(path: Path) -> bool:
        return all(
            (path / filename).is_file()
            for filename in (
                "model.bin",
                "config.json",
                "shared_vocabulary.json",
                "source.spm",
                "target.spm",
            )
        )

    @staticmethod
    def _prepare_demucs_repository(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "htdemucs.yaml").write_text("models: ['955717e8']\n", encoding="utf-8")

    def _release_sizes(self) -> dict[str, int]:
        if os.environ.get("WOOSH_STUDIO_OFFLINE") == "1":
            return {}
        try:
            response = httpx.get(
                RELEASE_API,
                headers={"Accept": "application/vnd.github+json"},
                timeout=4,
            )
            response.raise_for_status()
            return {
                asset["name"]: int(asset["size"])
                for asset in response.json().get("assets", [])
            }
        except (httpx.HTTPError, ValueError, KeyError):
            return {}

    @staticmethod
    def _checkpoint_valid(path: Path) -> bool:
        return (path / "config.yaml").is_file() and any(
            (path / filename).is_file()
            for filename in ("weights.safetensors", "weights.pt")
        )
