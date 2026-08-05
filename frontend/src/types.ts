export type ViewId = "generate" | "music" | "studio" | "models" | "exports" | "settings";
export type JobStatus =
  | "queued"
  | "loading"
  | "running"
  | "rendering"
  | "completed"
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
  family: "text" | "video" | "translation" | "music" | "separation";
  description: string;
  release: string;
  license: string;
  license_url: string;
  installed: boolean;
  custom: boolean;
  path: string | null;
  dependencies: ModelDependency[];
  controls: string[];
  supported: boolean;
  engine: "woosh" | "heartmula" | "demucs" | "transformers" | "ctranslate2";
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
  kind: "sfx" | "music_mix" | "stem" | "imported" | "render";
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

export interface ProjectManifest {
  schema_version: 2;
  id: string;
  name: string;
  description: string;
  sample_rate: number;
  created_at: string;
  updated_at: string;
  assets: GeneratedAsset[];
  timeline: Timeline;
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
