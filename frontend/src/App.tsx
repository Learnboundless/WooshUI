import { BookOpen, CircleAlert, FolderOpen, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, getBackendStatus, type BackendStatus } from "./api";
import { AgentKitDialog } from "./components/AgentKitDialog";
import { JobBar } from "./components/JobBar";
import { ProjectModal } from "./components/ProjectModal";
import { Sidebar } from "./components/Sidebar";
import type { JobEvent, ModelDescriptor, ProjectManifest, RuntimeSettings, SystemCapabilities, ViewId } from "./types";
import { ExportsView } from "./views/ExportsView";
import { GenerateView } from "./views/GenerateView";
import { MusicView } from "./views/MusicView";
import { ModelsView } from "./views/ModelsView";
import { SettingsView } from "./views/SettingsView";
import { SpeechView } from "./views/SpeechView";
import { StudioView } from "./views/StudioView";

export function App() {
  const [agentKit, setAgentKit] = useState(false);
  const [view, setView] = useState<ViewId>("generate");
  const [capabilities, setCapabilities] = useState<SystemCapabilities | null>(null);
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [jobs, setJobs] = useState<JobEvent[]>([]);
  const [recent, setRecent] = useState<Array<{ path: string; name: string; opened_at: string }>>([]);
  const [projectPath, setProjectPath] = useState("");
  const [project, setProject] = useState<ProjectManifest | null>(null);
  const [projectModal, setProjectModal] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>({ phase: "starting", message: "正在启动本地音频服务", detail: "正在检查运行环境", progress: 0.02, first_setup: false, elapsed_seconds: 0 });
  const handledJobs = useRef(new Set<string>());

  const updateSpeechProject = useCallback((updated: ProjectManifest) => setProject((current) => current?.id === updated.id ? updated : current), []);

  const refreshModels = useCallback(async () => setModels(await api.models()), []);
  const refreshRecent = useCallback(async () => setRecent(await api.recentProjects()), []);
  const refreshProject = useCallback(async () => {
    if (projectPath) setProject(await api.openProject(projectPath));
  }, [projectPath]);

  useEffect(() => {
    let cancelled = false;
    async function connect() {
      const desktop = "__TAURI_INTERNALS__" in window;
      const maxAttempts = desktop ? 1800 : 120;
      for (let attempt = 0; attempt < maxAttempts && !cancelled; attempt += 1) {
        try {
          const [system, modelList, jobList, recentList] = await Promise.all([api.capabilities(), api.models(), api.jobs(), api.recentProjects()]);
          if (cancelled) return;
          setCapabilities(system);
          setModels(modelList);
          setJobs(jobList);
          setRecent(recentList);
          setLoading(false);
          return;
        } catch (reason) {
          const status = await getBackendStatus().catch(() => null);
          if (cancelled) return;
          if (status) setBackendStatus(status);
          if (status?.phase === "failed" || attempt === maxAttempts - 1) {
            setError(status ? `${status.message}：${status.detail}` : (reason instanceof Error ? reason.message : "本地服务连接失败"));
            setLoading(false);
            return;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
        }
      }
    }
    void connect();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void api.jobs().then((jobList) => {
        setJobs(jobList);
        for (const job of jobList) {
          if (!["completed", "partial", "failed", "cancelled", "interrupted"].includes(job.status) || handledJobs.current.has(job.id)) continue;
          handledJobs.current.add(job.id);
          if (["generation", "music_generation", "speech_generation", "stem_separation"].includes(job.kind)) void refreshProject();
          if (job.kind === "model_download") void refreshModels();
        }
      }).catch(() => undefined);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [refreshModels, refreshProject]);

  useEffect(() => {
    const theme = capabilities?.settings.theme ?? "system";
    document.documentElement.dataset.theme = theme;
  }, [capabilities?.settings.theme]);

  async function pickDirectory(): Promise<string | null> {
    if ("__TAURI_INTERNALS__" in window) {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({ directory: true, multiple: false });
      return typeof selected === "string" ? selected : null;
    }
    return window.prompt("请输入本地文件夹的完整路径") || null;
  }

  async function openProject(path?: string) {
    try {
      const target = path || await pickDirectory();
      if (!target) return;
      const manifest = await api.openProject(target);
      setProjectPath(target);
      setProject(manifest);
      setView("generate");
      await refreshRecent();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "项目打开失败");
    }
  }

  async function createProject(directory: string, name: string) {
    try {
      const created = await api.createProject(directory, name);
      setProjectPath(created.path);
      setProject(created.manifest);
      setProjectModal(false);
      setView("generate");
      await refreshRecent();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "项目创建失败");
    }
  }

  function closeProject() {
    setProject(null);
    setProjectPath("");
    setView("generate");
  }

  async function removeRecentProject(path: string) {
    try {
      await api.removeRecentProject(path);
      setRecent((items) => items.filter((item) => item.path !== path));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "最近项目移除失败");
    }
  }

  async function revealProject(path: string) {
    if (!("__TAURI_INTERNALS__" in window)) {
      setError("资源管理器操作仅在桌面版可用");
      return;
    }
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("reveal_in_explorer", { path });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function updateSettings(settings: RuntimeSettings) {
    try {
      await api.updateSettings(settings);
      const [system, modelList] = await Promise.all([api.capabilities(), api.models()]);
      setCapabilities(system);
      setModels(modelList);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "设置保存失败");
    }
  }

  if (loading) return <div className="app-loading"><div className="brand-mark large"><Sparkles size={22} /></div><div className="loading-copy"><strong>启动 Woosh Studio</strong><span>{backendStatus.message}</span><small>{backendStatus.detail}</small></div><div className="loading-progress"><div className="loading-track" aria-hidden="true"><span style={{ width: `${Math.round(backendStatus.progress * 100)}%` }} /></div><b>{Math.round(backendStatus.progress * 100)}%</b></div></div>;

  if (!capabilities) return <div className="app-loading"><div className="brand-mark large"><CircleAlert size={22} /></div><div className="loading-copy"><strong>本地服务启动失败</strong><span>{error || "无法连接到音频服务"}</span></div><button className="secondary-button" onClick={() => window.location.reload()}>重新检查</button></div>;

  return <div className="app-shell">
    <Sidebar
      activeView={view}
      project={project}
      projectPath={projectPath}
      recent={recent}
      onView={setView}
      onOpenProject={(path) => void openProject(path)}
      onNewProject={() => setProjectModal(true)}
      onCloseProject={closeProject}
      onRemoveRecent={(path) => void removeRecentProject(path)}
      onRevealProject={(path) => void revealProject(path)}
      onError={setError}
    />
    <main className="main-shell">
      <div className="app-toolbar"><div className="breadcrumb"><span>Woosh Studio</span><i>/</i><strong>{project?.name || "项目"}</strong></div><div className="toolbar-right"><button className="text-button" onClick={() => setAgentKit(true)}><BookOpen size={14} />AI 工作流</button><div className="runtime-pill"><span className={capabilities?.effective_device === "cuda" ? "runtime-indicator cuda" : "runtime-indicator"} />{capabilities?.effective_device.toUpperCase()}<small>{capabilities?.cuda_device_name || "本地运行"}</small></div></div></div>
      {!project && ["generate", "music", "speech", "studio", "exports"].includes(view) ? <ProjectWelcome onNew={() => setProjectModal(true)} onOpen={() => void openProject()} /> : project && capabilities ? <>
        {view === "generate" && <GenerateView projectPath={projectPath} project={project} models={models} activeModel={capabilities.settings.active_model} onModelChange={(id) => void updateSettings({ ...capabilities.settings, active_model: id })} onProjectChange={setProject} onQueued={() => void api.jobs().then(setJobs)} onError={setError} />}
        {view === "music" && <MusicView projectPath={projectPath} project={project} models={models} onProjectChange={setProject} onQueued={() => void api.jobs().then(setJobs)} onError={setError} />}
        <div className="speech-host" hidden={view !== "speech"}><SpeechView key={projectPath} active={view === "speech"} projectPath={projectPath} project={project} models={models} jobs={jobs} onProjectChange={updateSpeechProject} onQueued={() => void api.jobs().then(setJobs)} onError={setError} /></div>
        {view === "studio" && <StudioView projectPath={projectPath} project={project} onProjectChange={setProject} onError={setError} />}
        {view === "exports" && <ExportsView projectPath={projectPath} project={project} onQueued={() => void api.jobs().then(setJobs)} onError={setError} />}
      </> : null}
      {view === "models" && <ModelsView models={models} jobs={jobs} modelRoot={capabilities.model_root} onRefresh={() => { void refreshModels(); void api.jobs().then(setJobs); }} onError={setError} />}
      {view === "settings" && capabilities && <SettingsView capabilities={capabilities} onChange={(settings) => void updateSettings(settings)} />}
      <JobBar jobs={jobs} onCancel={(id) => void api.cancelJob(id).then(() => api.jobs()).then(setJobs).catch((reason) => setError(reason.message))} />
    </main>
    {agentKit && <AgentKitDialog onClose={() => setAgentKit(false)} />}
    <ProjectModal open={projectModal} defaultDirectory={recent[0]?.path.replace(/[\\/][^\\/]+$/, "") || "C:\\Users\\Public\\Documents"} onClose={() => setProjectModal(false)} onCreate={createProject} onPickDirectory={pickDirectory} />
    {error && <div className="toast error" role="alert"><CircleAlert size={17} /><span>{error}</span><button className="icon-button small" title="关闭" onClick={() => setError("")}><X size={15} /></button></div>}
  </div>;
}

function ProjectWelcome({ onNew, onOpen }: { onNew: () => void; onOpen: () => void }) {
  return <section className="project-welcome"><div className="welcome-wave" aria-hidden="true">{Array.from({ length: 17 }, (_, index) => <span key={index} style={{ height: `${18 + Math.abs(8 - index) * 4 + (index % 3) * 8}px` }} />)}</div><h1>选择一个音效项目</h1><div><button className="primary-button" onClick={onNew}><Sparkles size={17} />新建项目</button><button className="secondary-button" onClick={onOpen}><FolderOpen size={17} />打开项目</button></div></section>;
}
