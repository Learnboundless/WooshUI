import type {
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
      "Content-Type": "application/json",
      ...(backend.token ? { "X-Woosh-Token": backend.token } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || "请求失败");
  }
  return response.json() as Promise<T>;
}

export const api = {
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
  translate: (text: string) =>
    request<{ original: string; translated: string }>("/translate", {
      method: "POST",
      body: JSON.stringify({ text }),
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
