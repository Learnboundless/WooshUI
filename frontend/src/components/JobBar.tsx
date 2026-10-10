import { Ban, CheckCircle2, CircleAlert, Copy, LoaderCircle, X } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { JobEvent } from "../types";
import { WorkbenchDialog } from "./WorkbenchDialog";

interface JobBarProps { jobs: JobEvent[]; onCancel: (id: string) => void; }
const activeStatuses = new Set(["queued", "loading", "running", "rendering"]);
const kinds: Record<string, string> = { generation: "音效生成", music_generation: "音乐生成", speech_generation: "剧本配音", stem_separation: "音轨分离", model_download: "模型下载", render: "混音渲染", export: "导出", translation: "翻译", transcription: "参考音频识别", model_preload: "模型预加载" };

function suggestion(job: JobEvent) {
  const message = job.error?.message || "";
  if (job.error?.code === "GPU_OOM") return "显存不足：先关闭其他生成任务或占用显存的应用，再选择低显存模式重试。";
  if (job.error?.code === "MODEL_NOT_INSTALLED") return "请到模型页面安装任务所需的模型。";
  if (/System error|不存在|No such file|未在目标位置/.test(message)) return "检查下方文件路径。旧版中文目录可能被写成乱码；可在素材中重新关联文件，更新应用后重新生成。";
  if (/TextEncodeInput/.test(message)) return "检查台词和角色指令是否为有效文本，并更新应用以修复 Windows 中文编码问题。";
  if (job.status === "interrupted") return "应用重启中断了任务。检查是否已有生成文件，再从对应页面重新提交。";
  return "查看失败阶段与详细错误，修正输入、模型或文件后，从对应页面重新提交。";
}

export function JobBar({ jobs, onCancel }: JobBarProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState("");
  const selected = jobs.find((job) => job.id === selectedId);
  const visible = jobs.slice(0, 4);
  return <footer className="job-bar" aria-label="任务队列"><button className="job-bar__label" title="查看全部任务" onClick={() => setSelectedId(jobs[0]?.id || null)}><LoaderCircle size={15} /><span>任务</span><span className="count-badge">{jobs.filter((job) => activeStatuses.has(job.status)).length}</span></button>
    <div className="job-bar__items">{!visible.length ? <span className="muted">队列空闲</span> : visible.map((job) => <div className={`job-item ${job.status === "failed" ? "failed" : ""}`} key={job.id}>
      <button className="job-details-trigger" title={job.error?.message || `${kinds[job.kind]}：${job.stage}，点击查看详情`} onClick={() => { setSelectedId(job.id); setCopyStatus(""); }}>{job.status === "completed" ? <CheckCircle2 className="status-success" size={15} /> : job.status === "failed" || job.status === "interrupted" || job.status === "partial" ? <CircleAlert className="status-danger" size={15} /> : job.status === "cancelled" ? <Ban size={15} /> : <LoaderCircle className="spin status-primary" size={15} />}<span className="job-item__body"><span className="job-item__title"><span>{kinds[job.kind]} · {job.stage}</span><span>{Math.round(job.progress * 100)}%</span></span>{job.error ? <span className="job-error-summary">{job.error.message}</span> : <span className="progress-track"><span style={{ width: `${job.progress * 100}%` }} /></span>}</span></button>
      {activeStatuses.has(job.status) && <button className="icon-button small" title="取消任务" onClick={() => onCancel(job.id)}><X size={14} /></button>}</div>)}</div>
    {selected && <WorkbenchDialog title="任务详情与历史" subtitle="失败记录会保留，重启应用后仍可查看。" onClose={() => setSelectedId(null)} wide><div className="job-detail-layout"><nav aria-label="任务历史">{jobs.map((job) => <button key={job.id} className={job.id === selected.id ? "active" : ""} onClick={() => { setSelectedId(job.id); setCopyStatus(""); }}><strong>{kinds[job.kind]} · {job.stage}</strong><small>{new Date(job.created_at).toLocaleString()}</small></button>)}</nav><section><h3>{kinds[selected.kind]} · {selected.stage}</h3><p className="muted">任务 ID：{selected.id}</p>{selected.error || selected.status === "interrupted" ? <><p className="workbench-error" role="alert">{selected.error?.message || "任务因应用重启中断"}</p><p className="job-suggestion">{suggestion(selected)}</p>{selected.error?.detail && <details><summary>失败阶段与原始错误</summary><pre>{selected.error.detail}</pre></details>}</> : <p>{selected.message || "任务状态正常"}</p>}{selected.kind === "speech_generation" && ["failed","partial","cancelled","interrupted"].includes(selected.status) && <button className="primary-button" onClick={() => void api.retryJob(selected.id).then(() => setCopyStatus("已提交恢复任务，有效配音会自动复用")).catch(error => setCopyStatus(String(error)))}>恢复 / 重试未完成项</button>}<details><summary>任务输入参数</summary><pre>{JSON.stringify(selected.payload, null, 2)}</pre></details>{selected.result && <details open><summary>生成结果</summary><pre>{JSON.stringify(selected.result, null, 2)}</pre></details>}<button className="secondary-button" onClick={async () => { try { await navigator.clipboard.writeText(JSON.stringify(selected, null, 2)); setCopyStatus("已复制任务诊断信息"); } catch { setCopyStatus("复制失败，请选择上方错误文本手动复制"); } }}><Copy size={15} />复制诊断信息</button>{copyStatus && <p role="status">{copyStatus}</p>}</section></div></WorkbenchDialog>}
  </footer>;
}
