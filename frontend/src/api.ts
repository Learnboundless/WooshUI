import type {
  AgentTemplate,
  AssetHealth,
  FreesoundSearchResponse,
  FreesoundResult,
  DialogueTranslation,
  ScriptPreview,
  ScriptDocument,
  ResourceImportResult,
  ResolvedResource,
  JobEvent,
  ModelDescriptor,
  GeneratedAsset,
  ProjectManifest,
  RuntimeSettings,
  SystemCapabilities,
  Timeline,
} from "./types";

interface BackendInfo {
  url: string;
  token: string;
}

export interface BackendStatus {
  phase: "installing" | "starting" | "ready" | "failed";
  message: string;
  detail: string;
  progress: number;
  first_setup: boolean;
  elapsed_seconds: number;
}

let backend: BackendInfo = {
  url: import.meta.env.VITE_API_URL || "http://127.0.0.1:8765",
  token: "",
};

export async function initializeBackend(): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) return;
  const { invoke } = await import("@tauri-apps/api/core");
  backend = await invoke<BackendInfo>("backend_info");
}

export async function getBackendStatus(): Promise<BackendStatus | null> {
  if (!("__TAURI_INTERNALS__" in window)) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<BackendStatus>("backend_status");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${backend.url}/api/v1${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(backend.token ? { "X-Woosh-Token": backend.token } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((item: { msg: string }) => item.msg).join("；") : "请求失败");
  }
  return response.json() as Promise<T>;
}

export const api = {
  analyzeAudio: (projectPath:string,relativePath:string) => request<import("./types").AudioAnalysis>("/projects/audio/analysis",{method:"POST",body:JSON.stringify({project_path:projectPath,relative_path:relativePath})}),
  protectAudio: (projectPath:string,assetId:string) => request<{manifest:ProjectManifest;asset:GeneratedAsset}>(`/assets/${encodeURIComponent(assetId)}/protect`,{method:"POST",body:JSON.stringify({project_path:projectPath})}),
  modelRuntime: () => request<import("./types").ModelRuntime>("/models/runtime"),
  releaseModels: () => request<import("./types").ModelRuntime>("/models/runtime/release", { method: "POST" }),
  preloadModel: (id: string) => request<JobEvent>(`/models/${id}/preload`, { method: "POST" }),
  transcribe: (projectPath: string, referenceAudio: string, language = "Auto") => request<JobEvent>("/transcriptions", { method: "POST", body: JSON.stringify({project_path: projectPath, reference_audio: referenceAudio, language}) }),
  retryJob: (id: string) => request<JobEvent>(`/jobs/${id}/retry`, { method: "POST" }),
  exportLocalization: (body: Record<string, unknown>) => request<JobEvent>("/exports/localization", { method: "POST", body: JSON.stringify(body) }),

  freesoundStatus: () => request<{ configured: boolean; website: string }>("/freesound/status"),
  freesoundSearch: (query: string, page = 1, filter?: string) => request<FreesoundSearchResponse>("/freesound/search", { method: "POST", body: JSON.stringify({ query, page, page_size: 20, filter: filter || null }) }),
  freesoundImport: (body: { project_path: string; sound_id: number; preview_url: string; download_url?: string; name: string; username: string; license: string; sound_url: string; duration: number }) => request<{ manifest: ProjectManifest; asset: GeneratedAsset }>("/freesound/import", { method: "POST", body: JSON.stringify(body) }),
  assetHealth: (path: string) => request<AssetHealth>("/projects/assets/health", { method: "POST", body: JSON.stringify({ path }) }),
  removeAssets: (projectPath: string, assetIds: string[]) => request<ProjectManifest>("/projects/assets", { method: "DELETE", body: JSON.stringify({ project_path: projectPath, asset_ids: assetIds }) }),
  relinkAsset: (projectPath: string, assetId: string, sourcePath: string) => request<ProjectManifest>(`/assets/${encodeURIComponent(assetId)}/relink`, { method: "POST", body: JSON.stringify({ project_path: projectPath, source_path: sourcePath }) }),
  saveScript: (projectPath: string, script: ScriptDocument) => request<ProjectManifest>("/projects/script", { method: "PUT", body: JSON.stringify({ project_path: projectPath, script }) }),
  agentTemplates: () => request<AgentTemplate[]>("/agent/templates"),
  previewScript: (text: string) => request<ScriptPreview>("/scripts/preview", { method: "POST", body: JSON.stringify({ text }) }),
  importResources: (projectPath: string, paths: string[]) => request<ResourceImportResult>("/projects/resources/import", { method: "POST", body: JSON.stringify({ project_path: projectPath, paths }) }),
  uploadResources: (projectPath: string, files: File[]) => {
    const body = new FormData();
    body.append("project_path", projectPath);
    files.forEach((file) => body.append("files", file, file.webkitRelativePath || file.name));
    return request<ResourceImportResult>("/projects/resources/upload", { method: "POST", body });
  },
  resolveResources: (projectPath: string, paths: string[]) => request<ResolvedResource[]>("/projects/resources/resolve", { method: "POST", body: JSON.stringify({ project_path: projectPath, paths }) }),
  exportWorkflow: (path: string) => request<{ path: string }>("/agent/export", { method: "POST", body: JSON.stringify({ path }) }),
  capabilities: () => request<SystemCapabilities>("/system/capabilities"),
  updateSettings: (settings: RuntimeSettings) =>
    request<RuntimeSettings>("/system/settings", {
      method: "PATCH",
      body: JSON.stringify(settings),
    }),
  models: () => request<ModelDescriptor[]>("/models"),
  acceptLicense: (modelId: string, release = "v1.0.0") =>
    request(`/models/license`, {
      method: "POST",
      body: JSON.stringify({ model_id: modelId, release, accepted: true }),
    }),
  downloadModel: (modelId: string) =>
    request<JobEvent>(`/models/${encodeURIComponent(modelId)}/download`, { method: "POST" }),
  removeModel: (modelId: string) =>
    request(`/models/${encodeURIComponent(modelId)}`, { method: "DELETE" }),
  recentProjects: () => request<Array<{ path: string; name: string; opened_at: string }>>("/projects/recent"),
  removeRecentProject: (path: string) =>
    request<{ removed: boolean }>("/projects/recent", {
      method: "DELETE",
      body: JSON.stringify({ path }),
    }),
  createProject: (parentDirectory: string, name: string, description = "") =>
    request<{ path: string; manifest: ProjectManifest }>("/projects", {
      method: "POST",
      body: JSON.stringify({ parent_directory: parentDirectory, name, description }),
    }),
  openProject: (path: string) =>
    request<ProjectManifest>("/projects/open", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  saveProject: (projectPath: string, manifest: ProjectManifest) =>
    request<ProjectManifest>("/projects", {
      method: "PUT",
      body: JSON.stringify({ project_path: projectPath, manifest }),
    }),
  generate: (body: Record<string, unknown>) =>
    request<JobEvent>("/generations", { method: "POST", body: JSON.stringify(body) }),
  generateMusic: (body: Record<string, unknown>) =>
    request<JobEvent>("/generations/music", { method: "POST", body: JSON.stringify(body) }),
  generateSpeech: (body: Record<string, unknown>) =>
    request<JobEvent>("/generations/speech", { method: "POST", body: JSON.stringify(body) }),
  separateAsset: (assetId: string, projectPath: string) =>
    request<JobEvent>(`/assets/${encodeURIComponent(assetId)}/separate`, {
      method: "POST",
      body: JSON.stringify({ project_path: projectPath }),
    }),
  trimAsset: (
    assetId: string,
    body: {
      project_path: string;
      mode: "manual" | "trim_silence";
      start_seconds?: number;
      end_seconds?: number;
      threshold_db?: number;
      padding_seconds?: number;
      output_name?: string;
    },
  ) =>
    request<{
      manifest: ProjectManifest;
      asset: GeneratedAsset;
      details: {
        mode: string;
        start_seconds: number;
        end_seconds: number;
        removed_seconds: number;
      };
    }>(`/assets/${encodeURIComponent(assetId)}/trim`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  translate: (text: string, sourceLanguage = "Chinese", targetLanguage = "English") =>
    request<{ original: string; translated: string; translation: DialogueTranslation }>("/translate", {
      method: "POST",
      body: JSON.stringify({ text, source_language: sourceLanguage, target_language: targetLanguage }),
    }),
  jobs: () => request<JobEvent[]>("/jobs"),
  job: (jobId: string) => request<JobEvent>(`/jobs/${jobId}`),
  cancelJob: (jobId: string) => request<JobEvent>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  pauseJob: (jobId: string) => request<JobEvent>(`/jobs/${jobId}/pause`, { method: "POST" }),
  resumeJob: (jobId: string) => request<JobEvent>(`/jobs/${jobId}/resume`, { method: "POST" }),
  renderPreview: (projectPath: string, timeline: Timeline) =>
    request<{ path: string }>("/renders/preview", {
      method: "POST",
      body: JSON.stringify({ project_path: projectPath, timeline, output_name: "preview" }),
    }),
  export: (body: Record<string, unknown>) =>
    request<JobEvent>("/exports", { method: "POST", body: JSON.stringify(body) }),
};

export function audioUrl(projectPath: string, relativePath: string): string {
  const query = new URLSearchParams({ project_path: projectPath, relative_path: relativePath });
  const token = backend.token ? `&token=${encodeURIComponent(backend.token)}` : "";
  return `${backend.url}/api/v1/projects/audio?${query.toString()}${token}`;
}

export async function downloadWorkflow(): Promise<Blob> {
  const response = await fetch(`${backend.url}/api/v1/agent/workflow.zip`, { headers: backend.token ? { "X-Woosh-Token": backend.token } : {} });
  if (!response.ok) throw new Error("Skill 包下载失败");
  return response.blob();
}
