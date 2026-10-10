import { Link2, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { GeneratedAsset, ProjectManifest } from "../types";
import { WorkbenchDialog } from "./WorkbenchDialog";

export function AssetActions({ asset, projectPath, missing, onProjectChange, onError }: { asset: GeneratedAsset; projectPath: string; missing?: boolean; onProjectChange: (project: ProjectManifest) => void; onError: (message: string) => void }) {
  const [dialog, setDialog] = useState<"remove" | "relink" | null>(null);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  async function choose() {
    try {
      if (!("__TAURI_INTERNALS__" in window)) { setDialog("relink"); return; }
      const { open } = await import("@tauri-apps/plugin-dialog");
      const result = await open({ directory: false, multiple: false, filters: [{ name: "音频", extensions: ["wav", "mp3", "flac", "ogg", "aif", "aiff"] }] });
      if (typeof result === "string") { setPath(result); setDialog("relink"); }
    } catch (reason) { onError(reason instanceof Error ? reason.message : String(reason)); }
  }
  async function apply() {
    setBusy(true);
    try { onProjectChange(dialog === "remove" ? await api.removeAssets(projectPath, [asset.id]) : await api.relinkAsset(projectPath, asset.id, path)); setDialog(null); }
    catch (reason) { onError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  }
  return <span className="asset-actions" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
    {missing && <button className="icon-button small" title={`重新关联 ${asset.name}`} onClick={() => void choose()}><Link2 size={14} /></button>}
    <button className="icon-button small" title={`删除素材 ${asset.name}`} onClick={() => setDialog("remove")}><Trash2 size={14} /></button>
    {dialog && <WorkbenchDialog title={dialog === "remove" ? "从项目移除素材" : "重新关联音频"} onClose={() => !busy && setDialog(null)}><div className="asset-action-body"><strong>{asset.name}</strong><p>{asset.relative_path}</p>{dialog === "remove" ? <p>将移除素材记录和使用它的时间线片段，并解除配音/参考关联。磁盘上的音频文件保留。</p> : <><p>选择实际音频文件，外部音频会复制到项目中，保留现有素材 ID 和时间线关联。</p><input aria-label="重新关联音频路径" placeholder="音频文件的完整路径" value={path} onChange={(event) => setPath(event.target.value)} /><button className="text-button" onClick={() => void choose()}><RefreshCw size={14} />选择文件</button></>}</div><footer><button className="secondary-button" disabled={busy} onClick={() => setDialog(null)}>取消</button><button className="primary-button" disabled={busy || (dialog === "relink" && !path.trim())} onClick={() => void apply()}>{busy ? "处理中…" : dialog === "remove" ? "确认移除" : "确认关联"}</button></footer></WorkbenchDialog>}
  </span>;
}
