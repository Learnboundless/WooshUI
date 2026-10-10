export type ViewId = "generate" | "music" | "speech" | "studio" | "models" | "exports" | "settings";
export type JobStatus =
  | "queued"
  | "loading"
  | "running"
  | "rendering"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface RuntimeSettings {
  device: "auto" | "cpu" | "cuda";
  active_model: string;
  active_music_model: string;
  model_root: string | null;
  model_download_source: "auto" | "modelscope" | "huggingface";
  music_memory_mode: "auto" | "bf16" | "int8";
  language: "zh-CN" | "en";
  theme: "system" | "light" | "dark";
  freesound_api_key?: string | null;
  model_residency?: "idle" | "keep" | "release";
  model_idle_seconds?: number;
}

export interface RuntimeStatus {
  offline: boolean;
  source: "bundled" | "managed";
  ready: boolean;
  version: string | null;
  heartmula_ready: boolean;
  heartcodec_ready: boolean;
  demucs_ready: boolean;
}

export interface SystemCapabilities {
  platform: string;
  python_version: string;
  cuda_available: boolean;
  cuda_device_name: string | null;
  cuda_memory_bytes: number | null;
  effective_device: "cpu" | "cuda";
  disk_free_bytes: number;
  model_root: string;
  settings: RuntimeSettings;
  runtime: RuntimeStatus;
}

export interface ModelDependency {
  id: string;
  asset_name: string;
  size_bytes: number;
  required: boolean;
}

export interface ModelDescriptor {
  id: string;
  name: string;
  family: "text" | "video" | "translation" | "music" | "speech" | "separation" | "transcription";
  description: string;
  release: string;
  license: string;
  license_url: string;
  installed: boolean;
  custom: boolean;
  bundled?: boolean;
  path: string | null;
  dependencies: ModelDependency[];
  controls: string[];
  supported: boolean;
  engine: "woosh" | "heartmula" | "demucs" | "qwen_tts" | "transformers" | "ctranslate2";
  model_source: "github" | "modelscope" | "huggingface" | "local";
  memory_mode: "standard" | "auto_low_vram" | "cpu";
}

export interface EffectNode {
  id: string;
  type: "pitch" | "speed" | "eq" | "compressor" | "reverb" | "limiter" | "normalize";
  enabled: boolean;
  parameters: Record<string, number | string | boolean>;
}

export interface Clip {
  id: string;
  asset_id: string;
  name: string;
  source_path: string;
  start_seconds: number;
  trim_start_seconds: number;
  trim_end_seconds: number | null;
  fade_in_seconds: number;
  fade_out_seconds: number;
  gain_db: number;
  pan: number;
  loop_enabled: boolean;
  loop_start_seconds: number | null;
  loop_end_seconds: number | null;
  effects: EffectNode[];
}

export interface Track {
  id: string;
  name: string;
  muted: boolean;
  solo: boolean;
  gain_db: number;
  pan: number;
  role: "generic" | "music" | "vocals" | "drums" | "bass" | "other";
  clips: Clip[];
}

export interface Timeline {
  sample_rate: number;
  duration_seconds: number;
  loop_start_seconds: number | null;
  loop_end_seconds: number | null;
  tracks: Track[];
  master_effects: EffectNode[];
}

export interface GeneratedAsset {
  id: string;
  name: string;
  relative_path: string;
  source: "generated" | "imported" | "rendered";
  kind: "sfx" | "music_mix" | "stem" | "voice_line" | "imported" | "render";
  prompt_original: string | null;
  prompt_conditioned: string | null;
  model_id: string | null;
  seed: number | null;
  sample_rate: number;
  channel_count: number;
  duration_seconds: number;
  generation_group_id: string | null;
  parent_asset_id: string | null;
  stem_role: "vocals" | "drums" | "bass" | "other" | null;
  music_metadata: Record<string, unknown> | null;
  favorite: boolean;
  tags: string[];
  created_at: string;
}

export interface VoiceSettings { mode: "custom_voice" | "clone"; speaker: string | null; instruct: string; reference_audio: string | null; reference_text: string; }
export interface VoiceProfile {
  locale_overrides?: Record<string, VoiceSettings>;
  id: string; name: string; mode: "custom_voice" | "clone"; language: string; speaker: string | null; instruct: string; reference_audio: string | null; reference_text: string;
}
export interface LocalizedLine { text: string; spoken_text: string; source_text: string; source_language: string; source_revision: number; model_id: string; locked: boolean; review_status: "draft" | "approved" | "stale"; asset_id: string | null; input_fingerprint: string | null; }
export interface ScriptLine {
  key?: string; scene_id?: string; context?: string; source_revision?: number; localizations?: Record<string, LocalizedLine>;
  id: string; character: string; text: string; source_language?: string; translation?: DialogueTranslation | null; voice_id: string | null; language: string; instruct: string; enabled: boolean; asset_id: string | null;
}
export interface ScriptDocument { title: string; source_locale?: string; target_locales?: string[]; glossary?: Array<{source: string; translations: Record<string,string>; note: string}>; voices: VoiceProfile[]; lines: ScriptLine[]; }

export interface ProjectManifest {
  schema_version: 2 | 3;
  id: string;
  name: string;
  description: string;
  sample_rate: number;
  created_at: string;
  updated_at: string;
  assets: GeneratedAsset[];
  timeline: Timeline;
  script?: ScriptDocument;
  export_preset: {
    format: "wav24" | "wav16" | "flac" | "ogg";
    package: "files" | "wwise_fmod";
    naming_template: string;
    category: string;
  };
}

export interface JobEvent {
  id: string;
  kind:
    | "generation"
    | "music_generation"
  | "speech_generation"
    | "transcription"
    | "model_preload"
    | "stem_separation"
    | "model_download"
    | "render"
    | "export"
    | "translation";
  status: JobStatus;
  progress: number;
  stage: string;
  message: string;
  speed_bytes_per_second: number | null;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: { code: string; message: string; detail: string | null } | null;
  created_at: string;
  updated_at: string;
}

export interface ScriptPreview { kind: "woosh.script" | "woosh.voices"; script: ScriptDocument; warnings: string[]; }
export interface AgentTemplate { id: string; title: string; description: string; prompt: string; template: string; }
export interface ResourceDocument { name: string; relative_path: string; text: string; }
export interface ResourceMapping { source: string; original_path: string; relative_path: string; }
export interface ResourceImportResult { manifest: ProjectManifest; assets: GeneratedAsset[]; documents: ResourceDocument[]; mappings: ResourceMapping[]; warnings: string[]; }
export interface ResolvedResource { path: string; absolute_path: string; exists: boolean; }

export interface DialogueTranslation { source_text: string; source_language: string; target_language: string; text: string; model_id: string; }
export interface AssetFileStatus { asset_id?: string; path: string; exists: boolean; absolute_path: string | null; reason: string; }
export interface AssetHealth { assets: AssetFileStatus[]; files: AssetFileStatus[]; }


export interface FreesoundResult { id: number; name: string; description: string; tags: string[]; username: string; license: string; duration: number; preview_url: string; download_url?: string; sound_url: string; filesize: number; samplerate: number; channels: number; }
export interface FreesoundSearchResponse { count: number; page: number; page_size: number; results: FreesoundResult[]; next: boolean; previous: boolean; }

export interface ModelRuntime { state: "unloaded" | "loading" | "ready" | "running" | "failed"; model_id: string | null; load_count: number; cache_hits: number; load_seconds: number; generation_seconds: number; idle_seconds: number; pid: number | null; }

export interface AudioAnalysis {sample_rate:number;channel_count:number;duration_seconds:number;peaks:number[][];spectrogram:number[][];frequency_edges_hz:number[];peak:number;peak_dbfs:number;rms_dbfs:number;overload_ratio:number;dominant_frequency_hz:number;high_frequency_ratio:number;}
