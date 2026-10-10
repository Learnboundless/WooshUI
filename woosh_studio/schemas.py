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
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobKind(str, Enum):
    GENERATION = "generation"
    MUSIC_GENERATION = "music_generation"
    SPEECH_GENERATION = "speech_generation"
    TRANSCRIPTION = "transcription"
    MODEL_PRELOAD = "model_preload"
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
    family: Literal[
        "text", "video", "translation", "music", "speech", "separation", "transcription"
    ]
    description: str
    release: str = "v1.0.0"
    license: str
    license_url: str
    installed: bool = False
    custom: bool = False
    bundled: bool = False
    path: str | None = None
    dependencies: list[ModelDependency] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    supported: bool = True
    engine: Literal[
        "woosh", "heartmula", "demucs", "qwen_tts", "transformers", "ctranslate2"
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
    model_residency: Literal["idle", "keep", "release"] = "idle"
    model_idle_seconds: int = Field(default=600, ge=30, le=86400)
    freesound_api_key: str | None = None


class RuntimeStatus(StrictModel):
    offline: bool = False
    source: Literal["bundled", "managed"] = "managed"
    ready: bool = True
    version: str | None = None
    heartmula_ready: bool = False
    heartcodec_ready: bool = False
    demucs_ready: bool = False


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
    source_language: str = "Chinese"
    target_language: str = "English"


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
    runtime: RuntimeStatus = Field(default_factory=RuntimeStatus)


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
    name_mode: Literal["auto", "manual"] = "manual"
    variant_of_asset_id: str | None = None
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
    def validate_generation_name(cls, value: str, info) -> str:
        value = value.strip()
        if (
            not value
            and info.field_name == "name"
            and info.data.get("name_mode") == "auto"
        ):
            return value
        if not value:
            raise ValueError("音效名称不能为空")
        return value


class GeneratedAsset(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    relative_path: str
    source: Literal["generated", "imported", "rendered"] = "generated"
    kind: Literal["sfx", "music_mix", "stem", "voice_line", "imported", "render"] = (
        "sfx"
    )
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


class VoiceSettings(StrictModel):
    mode: Literal["custom_voice", "clone"] = "custom_voice"
    speaker: str | None = "Vivian"
    instruct: str = ""
    reference_audio: str | None = None
    reference_text: str = ""


class VoiceProfile(VoiceSettings):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    language: str = "Chinese"
    locale_overrides: dict[str, VoiceSettings] = Field(default_factory=dict)

    @field_validator("locale_overrides")
    @classmethod
    def validate_overrides(cls, value):
        from .languages import validate_locales

        validate_locales(value)
        return value


class LocalizedLine(StrictModel):
    text: str = ""
    spoken_text: str = ""
    source_text: str = ""
    source_language: str = ""
    source_revision: int = 1
    model_id: str = "manual"
    locked: bool = False
    review_status: Literal["draft", "approved", "stale"] = "draft"
    asset_id: str | None = None
    input_fingerprint: str | None = None


class GlossaryEntry(StrictModel):
    source: str = Field(min_length=1)
    translations: dict[str, str] = Field(default_factory=dict)
    note: str = ""


class DialogueTranslation(StrictModel):
    source_text: str
    source_language: str
    target_language: str
    text: str
    model_id: str


class ScriptLine(StrictModel):
    key: str = ""
    scene_id: str = ""
    context: str = ""
    source_revision: int = 1
    localizations: dict[str, LocalizedLine] = Field(default_factory=dict)

    @field_validator("localizations")
    @classmethod
    def validate_localizations(cls, value):
        from .languages import validate_locales

        validate_locales(value)
        return value

    id: str = Field(default_factory=lambda: str(uuid4()))
    character: str
    text: str
    source_language: str = "Auto"
    translation: DialogueTranslation | None = None
    voice_id: str | None = None
    language: str = "Chinese"
    instruct: str = ""
    enabled: bool = True
    asset_id: str | None = None


class ScriptDocument(StrictModel):
    title: str = "项目剧本"
    source_locale: str = "zh-CN"
    target_locales: list[str] = Field(default_factory=list)
    glossary: list[GlossaryEntry] = Field(default_factory=list)

    @field_validator("target_locales")
    @classmethod
    def validate_targets(cls, value):
        from .languages import validate_locales

        return validate_locales(value)

    @field_validator("source_locale")
    @classmethod
    def validate_source(cls, value):
        from .languages import validate_locales

        return validate_locales([value])[0]

    @model_validator(mode="after")
    def unique_ids(self):
        for values in (
            [line.id for line in self.lines],
            [voice.id for voice in self.voices],
            [line.key for line in self.lines if line.key],
        ):
            if any(not value.strip() for value in values) or len(set(values)) != len(
                values
            ):
                raise ValueError("台词、角色 ID 或台词 key 为空或重复")
        return self

    voices: list[VoiceProfile] = Field(default_factory=list)
    lines: list[ScriptLine] = Field(default_factory=list)


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
    script: ScriptDocument = Field(default_factory=ScriptDocument)


class ProjectManifestV3(ProjectManifestV2):
    schema_version: Literal[3] = 3


class CreateProjectRequest(StrictModel):
    parent_directory: str
    name: str
    description: str = ""


class SaveProjectRequest(StrictModel):
    project_path: str
    manifest: ProjectManifestV3 | ProjectManifestV2


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
    performance_mode: Literal["standard", "preview"] = "standard"
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
    duration_seconds: Literal[10, 15, 30, 60, 120, 240] = 30
    count: Annotated[int, Field(ge=1, le=4)] = 1
    separate_stems: bool = False
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


class SpeechGenerationRequest(StrictModel):
    project_path: str
    line_ids: list[str] = Field(default_factory=list)
    continue_on_error: bool = True
    target_locales: list[str] = Field(default_factory=list)
    force: bool = False
    text_only: bool = False

    @field_validator("target_locales")
    @classmethod
    def validate_targets(cls, value):
        from .languages import validate_locales

        return validate_locales(value)


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


class ScriptPreviewRequest(StrictModel):
    text: str


class ResourceImportRequest(StrictModel):
    project_path: str
    paths: list[str] = Field(min_length=1, max_length=200)


class ResourceResolveRequest(StrictModel):
    project_path: str
    paths: list[str] = Field(max_length=200)


class SaveScriptRequest(StrictModel):
    project_path: str
    script: ScriptDocument


class AssetDeleteRequest(StrictModel):
    project_path: str
    asset_ids: list[str] = Field(min_length=1, max_length=2000)


class AssetRelinkRequest(StrictModel):
    project_path: str
    source_path: str


class FreesoundSearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=120)
    page: int = Field(default=1, ge=1, le=1000)
    page_size: int = Field(default=20, ge=1, le=50)
    filter: str | None = Field(default=None, max_length=300)


class FreesoundImportRequest(StrictModel):
    project_path: str
    sound_id: int = Field(ge=1)
    preview_url: str
    name: str = Field(min_length=1, max_length=160)
    username: str = Field(default="", max_length=80)
    license: str = Field(default="", max_length=120)
    sound_url: str
    duration: float = Field(default=0, ge=0)


class TranscriptionRequest(StrictModel):
    project_path: str
    reference_audio: str
    language: str = "Auto"


class LocalizationExportRequest(StrictModel):
    project_path: str
    target_locales: list[str] = Field(default_factory=list)
    mode: Literal["text", "complete"] = "complete"
    require_approved: bool = False
    format: Literal["wav24", "wav16", "flac", "ogg"] = "wav24"

    @field_validator("target_locales")
    @classmethod
    def validate_targets(cls, value):
        from .languages import validate_locales

        return validate_locales(value)


class AudioAnalysisRequest(StrictModel):
    project_path: str
    relative_path: str


class AudioProtectionRequest(StrictModel):
    project_path: str
