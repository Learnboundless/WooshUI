import { AlertCircle, ArrowRight, Check, ClipboardPaste, FileJson } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { ResourceDocument, ResourceMapping, ScriptPreview } from "../types";
import { bindImportedReferences } from "../workbench";
import { WorkbenchDialog } from "./WorkbenchDialog";

export function ScriptImportDialog({ initialText = "", documents = [], mappings = [], hasScript, onClose, onImport }: { initialText?: string; documents?: ResourceDocument[]; mappings?: ResourceMapping[]; hasScript: boolean; onClose: () => void; onImport: (preview: ScriptPreview, replace: boolean) => void }) {
  const [text, setText] = useState(initialText || documents[0]?.text || "");
  const [documentPath, setDocumentPath] = useState(documents[0]?.relative_path);
  const [preview, setPreview] = useState<ScriptPreview | null>(null);
  const [replace, setReplace] = useState(!hasScript);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function inspect() {
    setBusy(true); setError("");
    try { setPreview(bindImportedReferences(await api.previewScript(text), mappings, documentPath)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setPreview(null); }
    finally { setBusy(false); }
  }
  return <WorkbenchDialog title="导入剧本 / 角色" subtitle="支持 JSON，以及包含 JSON 代码块的 TXT / Markdown。导入前先检查内容。" onClose={onClose} wide>
    <div className="script-import-body">{documents.length > 0 && <label className="field"><span>选择模板文件（共 {documents.length} 份，每次导入一份）</span><select value={documentPath} onChange={(event) => { const doc = documents.find((item) => item.relative_path === event.target.value)!; setText(doc.text); setDocumentPath(doc.relative_path); setPreview(null); setError(""); }}>{documents.map((doc) => <option key={doc.relative_path} value={doc.relative_path}>{doc.name}</option>)}</select></label>}
      <div className="import-columns"><section><div className="import-section-title"><FileJson size={16} /><strong>AI 输出内容</strong><button className="text-button" onClick={async () => { try { setText(await navigator.clipboard.readText()); setPreview(null); } catch { setError("无法读取剪贴板，请直接在下方粘贴"); } }}><ClipboardPaste size={14} />粘贴</button></div><textarea className="code-editor" aria-label="导入 JSON 内容" placeholder={'粘贴 AI 生成的完整 JSON…\n{\n  "type": "woosh.script",\n  "version": 1,\n  "title": "我的剧本",\n  "voices": [],\n  "lines": []\n}'} value={text} onChange={(event) => { setText(event.target.value); setPreview(null); setError(""); }} /><button className="secondary-button" onClick={() => void inspect()} disabled={busy || !text.trim()}>{busy ? "检查中…" : "检查并预览"}<ArrowRight size={15} /></button></section>
      <section className="import-preview">{preview ? <><div className="import-section-title"><Check size={16} /><strong>{preview.kind === "woosh.voices" ? "角色模板" : preview.script.title}</strong></div><div className="import-counts"><span><b>{preview.script.voices.length}</b> 个角色</span><span><b>{preview.script.lines.length}</b> 句台词</span></div><div className="import-voice-tags">{preview.script.voices.map((voice) => <span key={voice.id}>{voice.name}<small>{voice.mode === "clone" ? "参考音频" : voice.speaker}</small></span>)}</div><ol className="import-line-preview">{preview.script.lines.slice(0, 8).map((line) => <li key={line.id}><strong>{line.character}</strong><p>{line.text}</p></li>)}</ol>{preview.script.lines.length > 8 && <p className="muted">另外还有 {preview.script.lines.length - 8} 句台词</p>}{preview.warnings.map((warning) => <p className="workbench-warning" key={warning}><AlertCircle size={14} />{warning}</p>)}{preview.kind === "woosh.voices" ? <p className="muted">同名或同 ID 角色会更新音色设置，其余角色与台词会保留。</p> : hasScript && <fieldset className="import-mode"><legend>导入方式</legend><label><input type="radio" checked={!replace} onChange={() => setReplace(false)} />追加到现有剧本</label><label><input type="radio" checked={replace} onChange={() => setReplace(true)} />替换当前剧本</label>{replace && <p className="workbench-warning">将替换角色和台词。已有音频素材保留，可用「撤销」恢复。</p>}</fieldset>}</> : <div className="import-preview-empty"><FileJson size={32} /><strong>预览会显示在这里</strong><p>检查角色绑定、台词数量和模板格式，确认后再导入。</p></div>}</section></div>{error && <p className="workbench-error" role="alert">{error}</p>}
    </div><footer><span className="muted">文件中的文本作为素材数据处理</span><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" disabled={!preview || busy} onClick={() => preview && onImport(preview, replace)}><Check size={16} />确认导入</button></footer>
  </WorkbenchDialog>;
}
