import { Archive, CheckSquare, Download, FileAudio, PackageOpen, Square } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { ProjectManifest } from "../types";

interface ExportsViewProps {
  projectPath: string;
  project: ProjectManifest;
  onQueued: () => void;
  onError: (message: string) => void;
}

export function ExportsView({ projectPath, project, onQueued, onError }: ExportsViewProps) {
  const [selected, setSelected] = useState<string[]>(project.assets.map((asset) => asset.id));
  const [format, setFormat] = useState<"wav24" | "wav16" | "flac" | "ogg">("wav24");
  const [packageType, setPackageType] = useState<"files" | "wwise_fmod">("wwise_fmod");
  const [includeMix, setIncludeMix] = useState(project.timeline.tracks.length > 0);
  const [naming, setNaming] = useState("{category}_{name}_{variant:02}");

  async function runExport() {
    try {
      await api.export({ project_path: projectPath, asset_ids: selected, timeline: includeMix ? project.timeline : null, preset: { format, package: packageType, naming_template: naming, category: "SFX" } });
      onQueued();
    } catch (error) { onError(error instanceof Error ? error.message : "导出任务提交失败"); }
  }

  const toggle = (id: string) => setSelected((value) => value.includes(id) ? value.filter((item) => item !== id) : [...value, id]);
  return <div className="workspace export-view"><section className="content-pane export-assets"><header className="view-header"><div><span className="eyebrow">DELIVERY</span><h1>批量导出</h1></div><button className="primary-button" onClick={runExport} disabled={selected.length === 0 && !includeMix}><Download size={16} />开始导出</button></header><div className="export-select-all"><button className="text-button" onClick={() => setSelected(selected.length === project.assets.length ? [] : project.assets.map((asset) => asset.id))}>{selected.length === project.assets.length ? <CheckSquare size={16} /> : <Square size={16} />}全选</button><span>已选择 {selected.length} 个素材</span></div><div className="export-asset-list">{project.assets.map((asset) => <button className={selected.includes(asset.id) ? "export-asset selected" : "export-asset"} key={asset.id} onClick={() => toggle(asset.id)}>{selected.includes(asset.id) ? <CheckSquare size={17} /> : <Square size={17} />}<FileAudio size={18} /><span><strong>{asset.name}</strong><small>{asset.model_id || "导入素材"} · {asset.sample_rate / 1000} kHz</small></span></button>)}</div></section><aside className="inspector-pane export-inspector"><div className="inspector-header"><h2>导出设置</h2></div><fieldset className="field"><legend>格式</legend><div className="segmented two-line">{([['wav24','WAV 24-bit'],['wav16','WAV 16-bit'],['flac','FLAC'],['ogg','OGG']] as const).map(([value,label]) => <button key={value} className={format === value ? "active" : ""} onClick={() => setFormat(value)}>{label}</button>)}</div></fieldset><fieldset className="field"><legend>交付包</legend><button className={packageType === "files" ? "package-option active" : "package-option"} onClick={() => setPackageType("files")}><FileAudio size={19} /><span><strong>普通文件</strong><small>音频与许可清单</small></span></button><button className={packageType === "wwise_fmod" ? "package-option active" : "package-option"} onClick={() => setPackageType("wwise_fmod")}><Archive size={19} /><span><strong>Wwise / FMOD ZIP</strong><small>音频、导入表与元数据</small></span></button></fieldset><label className="toggle-row"><span>包含时间线混音</span><input type="checkbox" checked={includeMix} onChange={(event) => setIncludeMix(event.target.checked)} /></label><label className="field"><span>命名模板</span><input value={naming} onChange={(event) => setNaming(event.target.value)} /><small className="field-hint">category · name · variant</small></label><div className="package-preview"><PackageOpen size={21} /><span><strong>{project.name}_export.zip</strong><small>{selected.length + (includeMix ? 1 : 0)} 个音频条目</small></span></div></aside></div>;
}
