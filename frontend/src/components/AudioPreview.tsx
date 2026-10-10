import { AlertTriangle, Copy, FolderOpen, Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { audioUrl } from "../api";
import { copyResourcePath, revealResource } from "../workbench";

export function AudioPreview({ projectPath, path, label, missing = false, onError, onMissing, autoPlay = false }: { projectPath: string; path: string; label: string; missing?: boolean; onError: (message: string) => void; onMissing?: () => void; autoPlay?: boolean }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [failure, setFailure] = useState("");
  useEffect(() => { setFailure(""); setPlaying(false); }, [path, missing]);
  async function play() {
    try {
      if (!ref.current) return;
      if (ref.current.paused) { await ref.current.play(); setFailure(""); }
      else ref.current.pause();
    } catch (reason) { setFailure("无法播放：文件可能已移动、损坏或格式不受支持"); onError(reason instanceof Error ? reason.message : String(reason)); onMissing?.(); }
  }
  function fail() { setFailure("音频无法读取，请检查文件或重新关联"); setPlaying(false); onMissing?.(); }
  return <div className={`audio-preview ${missing ? "missing" : ""}`}>
    {missing ? <span className="missing-label"><AlertTriangle size={15} />文件缺失 · 请重新关联或生成</span> : <div className="audio-preview-controls"><button className="icon-button" title={`${playing ? "暂停" : "试听"} ${label}`} onClick={() => void play()}>{playing ? <Pause size={16} /> : <Play size={16} />}</button><audio ref={ref} controls preload="metadata" autoPlay={autoPlay} src={audioUrl(projectPath, path)} aria-label={label} onPlay={() => { setPlaying(true); document.querySelectorAll("audio").forEach((audio) => { if (audio !== ref.current) audio.pause(); }); }} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onError={fail} /></div>}
    <div className="audio-preview-path"><span title={path}>{path}</span><button className="icon-button small" title={`定位 ${label}`} onClick={() => void revealResource(projectPath, path).catch((reason) => onError(String(reason.message || reason)))}><FolderOpen size={14} /></button><button className="icon-button small" title={`复制 ${label} 路径`} onClick={() => void copyResourcePath(projectPath, path).catch((reason) => onError(String(reason.message || reason)))}><Copy size={13} /></button></div>
    {failure && !missing && <p role="alert" className="line-issue">{failure}</p>}
  </div>;
}
