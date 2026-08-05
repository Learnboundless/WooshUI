import { FolderOpen, X } from "lucide-react";
import { useState } from "react";

interface ProjectModalProps {
  open: boolean;
  defaultDirectory: string;
  onClose: () => void;
  onCreate: (directory: string, name: string) => Promise<void>;
  onPickDirectory: () => Promise<string | null>;
}

export function ProjectModal({ open, defaultDirectory, onClose, onCreate, onPickDirectory }: ProjectModalProps) {
  const [directory, setDirectory] = useState(defaultDirectory);
  const [name, setName] = useState("新音效项目");
  const [busy, setBusy] = useState(false);
  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="new-project-title">
        <header><h2 id="new-project-title">新建项目</h2><button className="icon-button" onClick={onClose} title="关闭"><X size={17} /></button></header>
        <label className="field"><span>项目名称</span><input value={name} onChange={(event) => setName(event.target.value)} autoFocus /></label>
        <label className="field"><span>保存位置</span><div className="input-action"><input value={directory} onChange={(event) => setDirectory(event.target.value)} /><button className="icon-button" title="选择文件夹" onClick={async () => { const value = await onPickDirectory(); if (value) setDirectory(value); }}><FolderOpen size={17} /></button></div></label>
        <footer><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" disabled={!directory || !name || busy} onClick={async () => { setBusy(true); try { await onCreate(directory, name); } finally { setBusy(false); } }}>{busy ? "创建中" : "创建项目"}</button></footer>
      </section>
    </div>
  );
}
