from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DevicePreference(str, Enum):
    AUTO = "auto"
    CPU = "cpu"
    CUDA = "cuda"


class JobStatus(str, Enum):
    QUEUED = "queued"
    LOADING = "loading"
    RUNNING = "running"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobKind(str, Enum):
    GENERATION = "generation"
    MUSIC_GENERATION = "music_generation"
    STEM_SEPARATION = "stem_separation"
    MODEL_DOWNLOAD = "model_download"
    RENDER = "render"
    EXPORT = "export"
    TRANSLATION = "translation"


class ErrorCode(str, Enum):
    DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"
    MODEL_NOT_INSTALLED = "MODEL_NOT_INSTALLED"
    LICENSE_NOT_ACCEPTED = "LICENSE_NOT_ACCEPTED"
    DISK_SPACE_LOW = "DISK_SPACE_LOW"
    GPU_OOM = "GPU_OOM"
    PROJECT_CONFLICT = "PROJECT_CONFLICT"
    DOWNLOAD_CORRUPT = "DOWNLOAD_CORRUPT"
    JOB_CANCELLED = "JOB_CANCELLED"
    INVALID_REQUEST = "INVALID_REQUEST"


class StudioError(StrictModel):
    code: ErrorCode
    message: str
    detail: str | None = None


class JobEvent(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: JobKind
    status: JobStatus = JobStatus.QUEUED
    progress: Annotated[float, Field(ge=0, le=1)] = 0
    stage: str = "等待中"
    message: str = ""
    speed_bytes_per_second: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: StudioError | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ModelDependency(StrictModel):
    id: str
    asset_name: str
    size_bytes: int = 0
    required: bool = True


class ModelDescriptor(StrictModel):
    id: str
    name: str
    family: Literal["text", "video", "translation", "music", "separation"]
    description: str
    release: str = "v1.0.0"
    license: str
    license_url: str
    installed: bool = False
    custom: bool = False
    path: str | None = None
    dependencies: list[ModelDependency] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    supported: bool = True
    engine: Literal[
        "woosh", "heartmula", "demucs", "transformers", "ctranslate2"
    ] = "woosh"
    model_source: Literal["github", "modelscope", "huggingface", "local"] = "github"
    memory_mode: Literal["standard", "auto_low_vram", "cpu"] = "standard"


class LicenseAcceptance(StrictModel):
    model_id: str
    release: str
    accepted: bool
    accepted_at: datetime | None = None


class RuntimeSettings(StrictModel):
    device: DevicePreference = DevicePreference.AUTO
    active_model: str = "Woosh-DFlow"
    active_music_model: str = "HeartMuLa-3B"
    model_root: str | None = None
    model_download_source: Literal["auto", "modelscope", "huggingface"] = "auto"
    music_memory_mode: Literal["auto", "bf16", "int8"] = "auto"
    language: Literal["zh-CN", "en"] = "zh-CN"
    theme: Literal["system", "light", "dark"] = "system"


class PathRequest(StrictModel):
    path: str


class LicenseRequest(StrictModel):
    model_id: str
    release: str = "v1.0.0"
    accepted: Literal[True]


class CustomModelRequest(StrictModel):
    model_id: str
    path: str


class TranslationRequest(StrictModel):
    text: str


class SystemCapabilities(StrictModel):
    platform: str
    python_version: str
    cuda_available: bool
    cuda_device_name: str | None = None
    cuda_memory_bytes: int | None = None
    effective_device: Literal["cpu", "cuda"]
    disk_free_bytes: int
    model_root: str
    settings: RuntimeSettings


class EffectType(str, Enum):
    PITCH = "pitch"
    SPEED = "speed"
    EQ = "eq"
    COMPRESSOR = "compressor"
    REVERB = "reverb"
    LIMITER = "limiter"
    NORMALIZE = "normalize"


class EffectNode(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: EffectType
    enabled: bool = True
    parameters: dict[str, float | int | bool | str] = Field(default_factory=dict)


class Clip(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    asset_id: str
    name: str
    source_path: str
    start_seconds: Annotated[float, Field(ge=0)] = 0
    trim_start_seconds: Annotated[float, Field(ge=0)] = 0
    trim_end_seconds: float | None = None
    fade_in_seconds: Annotated[float, Field(ge=0)] = 0
    fade_out_seconds: Annotated[float, Field(ge=0)] = 0
    gain_db: Annotated[float, Field(ge=-60, le=24)] = 0
    pan: Annotated[float, Field(ge=-1, le=1)] = 0
    loop_enabled: bool = False
    loop_start_seconds: float | None = None
    loop_end_seconds: float | None = None
    effects: list[EffectNode] = Field(default_factory=list)


class Track(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = "新轨道"
    muted: bool = False
    solo: bool = False
    gain_db: Annotated[float, Field(ge=-60, le=24)] = 0
    pan: Annotated[float, Field(ge=-1, le=1)] = 0
    role: Literal["generic", "music", "vocals", "drums", "bass", "other"] = "generic"
    clips: list[Clip] = Field(default_factory=list)


class Timeline(StrictModel):
    sample_rate: int = 48000
    duration_seconds: Annotated[float, Field(ge=0)] = 8
    loop_start_seconds: float | None = None
    loop_end_seconds: float | None = None
    tracks: list[Track] = Field(default_factory=list)
    master_effects: list[EffectNode] = Field(default_factory=list)


class GenerationSettings(StrictModel):
    model_id: Literal["Woosh-DFlow", "Woosh-Flow"] = "Woosh-DFlow"
    cfg: Annotated[float, Field(ge=0, le=15)] = 4.5
    seed: int | None = None
    seed_mode: Literal["random", "fixed", "increment"] = "random"
    solver: Literal["dopri5", "dopri8", "bosh3", "adaptive_heun"] = "dopri5"
    atol: Annotated[float, Field(gt=0, le=1)] = 0.001
    rtol: Annotated[float, Field(gt=0, le=1)] = 0.001


class GenerationRequest(StrictModel):
    project_path: str
    prompt_original: str
    prompt_conditioned: str
    count: Annotated[int, Field(ge=1, le=8)] = 1
    category: str = "SFX"
    name: str = "generated"
    postprocess_mode: Literal["none", "trim_silence"] = "none"
    settings: GenerationSettings = Field(default_factory=GenerationSettings)

    @field_validator("prompt_conditioned")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("生成提示词不能为空")
        return value

    @field_validator("category", "name")
    @classmethod
    def validate_generation_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("音效名称不能为空")
        return value


class GeneratedAsset(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    relative_path: str
    source: Literal["generated", "imported", "rendered"] = "generated"
    kind: Literal["sfx", "music_mix", "stem", "imported", "render"] = "sfx"
    prompt_original: str | None = None
    prompt_conditioned: str | None = None
    model_id: str | None = None
    seed: int | None = None
    sample_rate: int = 48000
    channel_count: Annotated[int, Field(ge=1, le=16)] = 1
    duration_seconds: float = 0
    generation_group_id: str | None = None
    parent_asset_id: str | None = None
    stem_role: Literal["vocals", "drums", "bass", "other"] | None = None
    music_metadata: dict[str, Any] | None = None
    favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class ExportPreset(StrictModel):
    format: Literal["wav24", "wav16", "flac", "ogg"] = "wav24"
    package: Literal["files", "wwise_fmod"] = "files"
    naming_template: str = "{category}_{name}_{variant:02}"
    category: str = "SFX"


class ProjectManifestV1(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    sample_rate: int = 48000
    generation_mode: Literal["text", "video"] = "text"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    assets: list[GeneratedAsset] = Field(default_factory=list)
    timeline: Timeline = Field(default_factory=Timeline)
    export_preset: ExportPreset = Field(default_factory=ExportPreset)


class ProjectManifestV2(StrictModel):
    schema_version: Literal[2] = 2
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    sample_rate: int = 48000
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    assets: list[GeneratedAsset] = Field(default_factory=list)
    timeline: Timeline = Field(default_factory=Timeline)
    export_preset: ExportPreset = Field(default_factory=ExportPreset)


class CreateProjectRequest(StrictModel):
    parent_directory: str
    name: str
    description: str = ""


class SaveProjectRequest(StrictModel):
    project_path: str
    manifest: ProjectManifestV2


class ImportAssetRequest(StrictModel):
    project_path: str
    source_path: str


class RenderRequest(StrictModel):
    project_path: str
    timeline: Timeline
    output_name: str = "mixdown"


class ExportRequest(StrictModel):
    project_path: str
    asset_ids: list[str] = Field(default_factory=list)
    timeline: Timeline | None = None
    preset: ExportPreset = Field(default_factory=ExportPreset)


class MusicGenerationSettings(StrictModel):
    model_id: Literal["HeartMuLa-3B"] = "HeartMuLa-3B"
    temperature: Annotated[float, Field(ge=0.1, le=2)] = 1.0
    top_k: Annotated[int, Field(ge=1, le=200)] = 50
    cfg_scale: Annotated[float, Field(ge=1, le=5)] = 1.5
    seed: int | None = None
    seed_mode: Literal["random", "fixed", "increment"] = "random"


class MusicGenerationRequest(StrictModel):
    project_path: str
    title: str = "BGM"
    mode: Literal["instrumental", "lyrics"] = "instrumental"
    tags: list[str] = Field(default_factory=list, max_length=24)
    lyrics: str = ""
    duration_seconds: Literal[30, 60, 120, 240] = 60
    count: Annotated[int, Field(ge=1, le=4)] = 1
    separate_stems: bool = True
    settings: MusicGenerationSettings = Field(default_factory=MusicGenerationSettings)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("音乐标题不能为空")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower().replace(",", "") for value in values]
        return list(dict.fromkeys(value for value in normalized if value))

    @field_validator("lyrics")
    @classmethod
    def validate_lyrics(cls, value: str, info) -> str:
        value = value.strip()
        if info.data.get("mode") == "lyrics" and not value:
            raise ValueError("带歌词模式必须填写歌词")
        return value


class SeparateAssetRequest(StrictModel):
    project_path: str


class AssetTrimRequest(StrictModel):
    project_path: str
    mode: Literal["manual", "trim_silence"] = "trim_silence"
    start_seconds: Annotated[float, Field(ge=0)] = 0
    end_seconds: float | None = None
    threshold_db: Annotated[float, Field(ge=-80, le=-20)] = -45
    padding_seconds: Annotated[float, Field(ge=0, le=0.5)] = 0.04
    output_name: str | None = None

    @model_validator(mode="after")
    def validate_manual_range(self):
        if self.mode == "manual":
            if self.end_seconds is None:
                raise ValueError("手动裁剪必须填写结束时间")
            if self.end_seconds <= self.start_seconds:
                raise ValueError("结束时间必须晚于开始时间")
        return self
