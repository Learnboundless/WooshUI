import { BookOpen, Check, Copy, Download, FileJson, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api, downloadWorkflow } from "../api";
import type { AgentTemplate } from "../types";
import { downloadBlob } from "../workbench";
import { WorkbenchDialog } from "./WorkbenchDialog";

export function AgentKitDialog({ initialTab = "script", onClose, onUseTemplate }: { initialTab?: string; onClose: () => void; onUseTemplate?: (text: string) => void }) {
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [active, setActive] = useState(initialTab);
  const [contentTab, setContentTab] = useState<"prompt" | "template">("prompt");
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  useEffect(() => { void api.agentTemplates().then(setTemplates).catch((reason) => setError(String(reason.message || reason))); }, []);
  const selected = templates.find((item) => item.id === active) ?? templates[0];
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setFeedback("已复制，可以粘贴给其他 AI 模型"); setError(""); }
    catch { setError("剪贴板不可用，请在下方文本框中全选并复制"); }
  }
  async function exportKit() {
    try {
      setExporting(true); setError("");
      if ("__TAURI_INTERNALS__" in window) {
        const { open } = await import("@tauri-apps/plugin-dialog");
        const directory = await open({ directory: true, title: "选择 Skill 包导出位置" });
        if (typeof directory !== "string") return;
        const result = await api.exportWorkflow(directory);
        setFeedback(`Skill 包已导出：${result.path}`);
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("reveal_in_explorer", { path: result.path });
      } else {
        downloadBlob(await downloadWorkflow(), "woosh-studio-skill.zip");
        setFeedback("Skill 包已下载。解压后将 woosh-studio 文件夹放入 AI 工具的 skills 目录。");
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setExporting(false); }
  }
  return <WorkbenchDialog title="AI 协作 · 模板与工作流" subtitle="复制提示词交给 AI，再把生成的剧本或角色 JSON 导回工作台。" onClose={onClose} wide>
    <div className="agent-kit-layout"><nav aria-label="AI 模板分类">{templates.map((item) => <button className={selected?.id === item.id ? "active" : ""} key={item.id} onClick={() => { setActive(item.id); setContentTab("prompt"); setFeedback(""); }}><FileJson size={17} /><span>{item.title}</span></button>)}<div className="agent-kit-portable"><BookOpen size={19} /><strong>带到另一台电脑</strong><p>一个 Skill 覆盖音效、音乐、配音、剪辑、模型与导出。包含模板、操作指南和 API 助手。</p><button className="secondary-button" disabled={exporting} onClick={() => void exportKit()}><Download size={15} />{exporting ? "导出中…" : "导出 Skill 包"}</button></div></nav>
      <section className="agent-kit-content">{selected ? <><div className="agent-kit-heading"><div><span className="eyebrow">AI HANDOFF</span><h3>{selected.title}</h3><p>{selected.description}</p></div><Sparkles size={26} /></div><div className="workbench-tabs"><button className={contentTab === "prompt" ? "active" : ""} onClick={() => setContentTab("prompt")}>生成提示词</button><button className={contentTab === "template" ? "active" : ""} onClick={() => setContentTab("template")}>输出模板</button></div><textarea aria-label={contentTab === "prompt" ? "AI 生成提示词" : "AI 输出模板"} className="code-editor" readOnly value={selected[contentTab]} /><div className="agent-kit-actions"><button className="primary-button" onClick={() => void copy(selected[contentTab])}><Copy size={15} />复制{contentTab === "prompt" ? "提示词" : "模板"}</button>{onUseTemplate && ["script", "voices", "multilingual"].includes(selected.id) && <button className="secondary-button" onClick={() => onUseTemplate(selected.template)}>使用此示例</button>}</div></> : <p className="muted">正在读取随应用提供的模板…</p>}{feedback && <p className="workbench-notice" role="status"><Check size={15} />{feedback}</p>}{error && <p className="workbench-error" role="alert">{error}</p>}</section></div>
  </WorkbenchDialog>;
}
