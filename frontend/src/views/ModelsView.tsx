import {
  Check,
  CircleAlert,
  Download,
  HardDrive,
  Languages,
  Music2,
  Pause,
  Play,
  Scissors,
  Trash2,
  X,
} from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { JobEvent, ModelDescriptor } from "../types";

interface ModelsViewProps {
  models: ModelDescriptor[];
  jobs: JobEvent[];
  modelRoot: string;
  onRefresh: () => void;
  onError: (message: string) => void;
}

const groups: Array<{
  id: "text" | "music" | "separation" | "translation";
  title: string;
  subtitle: string;
}> = [
  { id: "text", title: "音效模型", subtitle: "Woosh 文本生成音效" },
  { id: "music", title: "音乐模型", subtitle: "HeartMuLa 与 HeartCodec" },
  { id: "separation", title: "分轨工具", subtitle: "音乐后处理模型" },
  { id: "translation", title: "语言工具", subtitle: "本地中文提示词翻译" },
];

export function ModelsView({
  models,
  jobs,
  modelRoot,
  onRefresh,
  onError,
}: ModelsViewProps) {
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});

  async function download(model: ModelDescriptor) {
    try {
      if (model.family !== "translation") {
        if (!accepted[model.id]) {
          onError("请先确认模型权重许可");
          return;
        }
        await api.acceptLicense(model.id, model.release);
      }
      await api.downloadModel(model.id);
      onRefresh();
    } catch (error) {
      onError(error instanceof Error ? error.message : "下载任务提交失败");
    }
  }

  async function controlDownload(job: JobEvent, action: "pause" | "resume" | "cancel") {
    try {
      if (action === "pause") await api.pauseJob(job.id);
      else if (action === "resume") await api.resumeJob(job.id);
      else await api.cancelJob(job.id);
      onRefresh();
    } catch (error) {
      onError(error instanceof Error ? error.message : "下载任务操作失败");
    }
  }

  return (
    <div className="workspace single-pane-view">
      <section className="content-pane models-pane">
        <header className="view-header">
          <div><span className="eyebrow">MODEL LIBRARY</span><h1>模型与权重</h1></div>
          <div className="storage-chip" title={modelRoot}><HardDrive size={15} /><span>共享模型库</span><strong>{modelRoot}</strong></div>
        </header>
        {groups.map((group) => {
          const entries = models.filter((model) => model.family === group.id);
          if (entries.length === 0) return null;
          return <section className="model-group" key={group.id}>
            <header><div><h2>{group.title}</h2><span>{group.subtitle}</span></div><small>{entries.filter((model) => model.installed).length}/{entries.length} 已安装</small></header>
            <div className="model-list">{entries.map((model) => {
              const job = jobs.find((item) => item.kind === "model_download" && item.payload.model_id === model.id && ["queued", "loading", "running"].includes(item.status));
              const size = model.dependencies.reduce((sum, item) => sum + item.size_bytes, 0);
              return <article className="model-row" key={model.id}>
                <ModelIcon model={model} />
                <div className="model-main">
                  <div className="model-title"><strong>{model.name}</strong>{model.installed && <span className="installed-badge"><Check size={13} />已安装</span>}</div>
                  <p>{model.description}</p>
                  <div className="model-meta"><span>{model.release}</span><span>{model.license}</span>{size > 0 && <span>{formatBytes(size)} 下载</span>}<span>{sourceLabel(model.model_source)}</span></div>
                  {model.family !== "translation" && !model.installed && <label className="license-check"><input type="checkbox" checked={Boolean(accepted[model.id])} onChange={(event) => setAccepted((value) => ({ ...value, [model.id]: event.target.checked }))} /><span>我已阅读并接受 {model.license}</span></label>}
                  {job && <div className="model-progress"><div className="progress-track"><span style={{ width: `${job.progress * 100}%` }} /></div><span>{job.stage} · {Math.round(job.progress * 100)}%</span></div>}
                </div>
                <div className="model-actions">
                  {model.installed ? <><span className="model-path" title={model.path || ""}>{model.path}</span><button className="icon-button" title="移除模型" onClick={async () => {
                    try {
                      await api.removeModel(model.id);
                      onRefresh();
                    } catch (error) {
                      onError(error instanceof Error ? error.message : "移除失败");
                    }
                  }}><Trash2 size={16} /></button></> : job ? <>
                    <button className="icon-button" title={job.payload.paused ? "继续下载" : "暂停下载"} onClick={() => void controlDownload(job, job.payload.paused ? "resume" : "pause")}>
                      {job.payload.paused ? <Play size={16} /> : <Pause size={16} />}
                    </button>
                    <button className="icon-button" title="取消下载" onClick={() => void controlDownload(job, "cancel")}><X size={16} /></button>
                  </> : <button className="primary-button" onClick={() => void download(model)}><Download size={16} />下载</button>}
                </div>
              </article>;
            })}</div>
          </section>;
        })}
        <div className="license-notice"><CircleAlert size={17} /><span>Woosh 权重采用 CC BY-NC 4.0；HeartMuLa 与 HeartCodec 采用 Apache 2.0。导出包会分别记录来源与许可。</span></div>
      </section>
    </div>
  );
}

function ModelIcon({ model }: { model: ModelDescriptor }) {
  if (model.family === "translation") return <div className="model-icon translation"><Languages size={20} /></div>;
  if (model.family === "music") return <div className="model-icon music"><Music2 size={20} /></div>;
  if (model.family === "separation") return <div className="model-icon separation"><Scissors size={20} /></div>;
  return <div className="model-icon">{model.id.includes("DFlow") ? "DF" : "FL"}</div>;
}

function sourceLabel(source: ModelDescriptor["model_source"]) {
  return ({ github: "GitHub", modelscope: "ModelScope", huggingface: "Hugging Face", local: "本地" })[source];
}

function formatBytes(bytes: number) {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}
