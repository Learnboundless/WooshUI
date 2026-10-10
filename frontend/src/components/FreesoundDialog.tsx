import { ExternalLink, Headphones, Info, Loader2, Search, Upload, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { FreesoundResult, ProjectManifest } from "../types";
import { WorkbenchDialog } from "./WorkbenchDialog";

export function FreesoundDialog({ projectPath, onClose, onImported, onError }: { projectPath: string; onClose: () => void; onImported: (manifest: ProjectManifest, path: string) => void; onError: (message: string) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<FreesoundResult[]>([]);
  const [selected, setSelected] = useState<FreesoundResult | null>(null);
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [quality, setQuality] = useState<"preview" | "original">("preview");
  const [importing, setImporting] = useState<number | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { void api.freesoundStatus().then((status) => setConfigured(status.configured)).catch(() => setConfigured(false)); }, []);
  async function search(nextPage = 1) {
    if (!query.trim()) return;
    setBusy(true); setError("");
    try { const response = await api.freesoundSearch(query.trim(), nextPage); setResults(response.results); setCount(response.count); setPage(nextPage); setSelected(response.results[0] || null); }
    catch (reason) { const message = reason instanceof Error ? reason.message : String(reason); setError(message); onError(message); }
    finally { setBusy(false); }
  }
  async function importSound(sound: FreesoundResult) {
    setImporting(sound.id); setError("");
    try { const result = await api.freesoundImport({ project_path: projectPath, sound_id: sound.id, preview_url: quality === "original" && sound.download_url ? sound.download_url : sound.preview_url, name: sound.name, username: sound.username, license: sound.license, sound_url: sound.sound_url, duration: sound.duration }); onImported(result.manifest, result.asset.relative_path); }
    catch (reason) { const message = reason instanceof Error ? reason.message : String(reason); setError(message); onError(message); }
    finally { setImporting(null); }
  }
  return <WorkbenchDialog title="Freesound 参考音频" subtitle="搜索官方资源、试听并复制到当前项目。导入后会保留作者、许可证和原始链接。" onClose={onClose} wide>
    <div className="freesound-layout"><section className="freesound-main"><form className="freesound-search" onSubmit={(event) => { event.preventDefault(); void search(1); }}><Search size={17} /><input aria-label="搜索 Freesound" placeholder="例如：female whisper, old radio, footsteps…" value={query} onChange={(event) => setQuery(event.target.value)} /><button className="primary-button" disabled={busy || !query.trim()}>{busy ? <Loader2 className="spin" size={15} /> : <Search size={15} />}搜索</button></form>{configured === false && <div className="workbench-warning"><Info size={15} />尚未配置 Freesound API key。请先在「设置 → 在线资源」填写；也可以直接打开网站浏览。</div>}{error && <p className="workbench-error" role="alert">{error}</p>}<div className="freesound-results">{results.map((sound) => <button className={selected?.id === sound.id ? "freesound-result active" : "freesound-result"} key={sound.id} onClick={() => setSelected(sound)}><span className="freesound-result-icon"><Headphones size={17} /></span><span><strong>{sound.name}</strong><small>{sound.username} · {sound.duration.toFixed(1)}s · {sound.license || "许可证未返回"}</small><em>{sound.tags.slice(0, 5).join(" · ")}</em></span></button>)}{!results.length && <div className="freesound-empty"><Headphones size={28} /><strong>搜索可用的参考音频</strong><p>建议用英文描述声音，结果会显示作者与许可证。</p></div>}</div><div className="freesound-pagination"><button className="secondary-button" disabled={busy || page <= 1} onClick={() => void search(page - 1)}>上一页</button><span>{count ? `${(page - 1) * 20 + 1}–${Math.min(page * 20, count)} / ${count}` : ""}</span><button className="secondary-button" disabled={busy || page * 20 >= count} onClick={() => void search(page + 1)}>下一页</button></div></section><aside className="freesound-detail">{selected ? <><header><div><span className="eyebrow">FREESOUND</span><h3>{selected.name}</h3></div><button className="icon-button" title="关闭详情" onClick={() => setSelected(null)}><X size={16} /></button></header><audio controls autoPlay preload="metadata" src={selected.preview_url} aria-label={`试听 ${selected.name}`} /><dl><div><dt>作者</dt><dd>{selected.username || "—"}</dd></div><div><dt>许可证</dt><dd>{selected.license || "—"}</dd></div><div><dt>时长</dt><dd>{selected.duration.toFixed(2)} 秒</dd></div><div><dt>格式</dt><dd>{selected.channels || "—"} ch · {selected.samplerate || "—"} Hz</dd></div></dl><p className="freesound-description">{selected.description || "没有描述"}</p><div className="freesound-detail-actions"><label className="freesound-quality"><input type="radio" checked={quality === "preview"} onChange={() => setQuality("preview")} />快速预览（MP3/OGG） <input type="radio" checked={quality === "original"} disabled={!selected.download_url} onChange={() => setQuality("original")} />原始下载（适合参考音色）{!selected.download_url && "（需重新搜索详情）"}</label><button className="primary-button" disabled={importing === selected.id || configured === false} onClick={() => void importSound(selected)}>{importing === selected.id ? <Loader2 className="spin" size={15} /> : <Upload size={15} />}导入到当前项目</button><a className="secondary-button" href={selected.sound_url} target="_blank" rel="noreferrer"><ExternalLink size={14} />在 Freesound 打开</a></div><small className="freesound-attribution">导入后保留归属：{selected.name} · {selected.username} · {selected.license || "请在原页面确认许可证"}</small></> : <div className="freesound-empty detail"><Headphones size={30} /><p>选择一个搜索结果查看试听和许可证。</p></div>}</aside></div>
  </WorkbenchDialog>;
}
