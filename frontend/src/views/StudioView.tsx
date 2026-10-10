import {
  AudioWaveform,
  Eye,
  EyeOff,
  GripVertical,
  Headphones,
  ListPlus,
  Plus,
  Scissors,
  SlidersHorizontal,
  Speaker,
  Trash2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { api, audioUrl } from "../api";
import { AudioPreview } from "../components/AudioPreview";
import { AssetActions } from "../components/AssetActions";
import { useAssetHealth } from "../hooks/useAssetHealth";
import { ContextMenu } from "../components/ContextMenu";
import type { Clip, EffectNode, EffectNode as Effect, GeneratedAsset, ProjectManifest, Track } from "../types";

interface StudioViewProps {
  projectPath: string;
  project: ProjectManifest;
  onProjectChange: (manifest: ProjectManifest) => void;
  onError: (message: string) => void;
}

const effectNames: Record<Effect["type"], string> = {
  pitch: "变调",
  speed: "变速",
  eq: "三段均衡",
  compressor: "压缩器",
  reverb: "混响",
  limiter: "限制器",
  normalize: "标准化",
};

export function StudioView({ projectPath, project, onProjectChange, onError }: StudioViewProps) {
  const { missingIds, missingPaths, refresh, error: healthError } = useAssetHealth(projectPath, project);
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [selectedClipId, setSelectedClipId] = useState("");
  const [previewPath, setPreviewPath] = useState("");
  const [rendering, setRendering] = useState(false);
  const [processingAsset, setProcessingAsset] = useState(false);
  const [pixelsPerSecond, setPixelsPerSecond] = useState(36);
  const [contextMenu, setContextMenu] = useState<
    | { kind: "clip"; clipId: string; x: number; y: number }
    | { kind: "asset"; assetId: string; x: number; y: number }
    | null
  >(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const selected = useMemo(() => findClip(project.timeline.tracks, selectedClipId), [project.timeline.tracks, selectedClipId]);
  const selectedAsset = useMemo(
    () => project.assets.find((asset) => asset.id === selected?.clip.asset_id),
    [project.assets, selected?.clip.asset_id],
  );
  const menuClip = contextMenu?.kind === "clip"
    ? findClip(project.timeline.tracks, contextMenu.clipId)
    : null;
  const menuAsset = contextMenu?.kind === "asset"
    ? project.assets.find((asset) => asset.id === contextMenu.assetId)
    : menuClip
      ? project.assets.find((asset) => asset.id === menuClip.clip.asset_id)
      : undefined;
  const previewRelative = previewPath ? `.cache/${previewPath.split(/[\\/]/).at(-1)}` : "";

  async function commit(tracks: Track[], durationSeconds = project.timeline.duration_seconds) {
    const next = { ...project, timeline: { ...project.timeline, tracks, duration_seconds: durationSeconds } };
    onProjectChange(next);
    try {
      const saved = await api.saveProject(projectPath, next);
      onProjectChange(saved);
    } catch (error) {
      onError(error instanceof Error ? error.message : "项目保存失败");
    }
  }

  function addTrack() {
    const track: Track = { id: crypto.randomUUID(), name: `轨道 ${project.timeline.tracks.length + 1}`, muted: false, solo: false, gain_db: 0, pan: 0, role: "generic", clips: [] };
    void commit([...project.timeline.tracks, track]);
  }

  function addAsset(asset: GeneratedAsset, trackId?: string, startSeconds = 0) {
    if (missingIds.has(asset.id)) { onError("文件缺失，请先重新关联素材"); return; }
    const clip: Clip = {
      id: crypto.randomUUID(), asset_id: asset.id, name: asset.name, source_path: asset.relative_path,
      start_seconds: startSeconds, trim_start_seconds: 0, trim_end_seconds: null, fade_in_seconds: 0.02,
      fade_out_seconds: 0.08, gain_db: 0, pan: 0, loop_enabled: false, loop_start_seconds: null,
      loop_end_seconds: null, effects: [],
    };
    let tracks = project.timeline.tracks;
    if (tracks.length === 0) {
      const role = asset.stem_role || (asset.kind === "music_mix" ? "music" : "generic");
      const first: Track = { id: crypto.randomUUID(), name: asset.stem_role ? roleName(asset.stem_role) : "轨道 1", muted: false, solo: false, gain_db: 0, pan: 0, role, clips: [clip] };
      tracks = [first];
    } else {
      const targetId = trackId ?? tracks[0].id;
      tracks = tracks.map((track) => track.id === targetId ? { ...track, clips: [...track.clips, clip] } : track);
    }
    setSelectedClipId(clip.id);
    void commit(tracks, Math.max(project.timeline.duration_seconds, startSeconds + asset.duration_seconds));
  }

  function updateTrack(trackId: string, changes: Partial<Track>) {
    void commit(project.timeline.tracks.map((track) => track.id === trackId ? { ...track, ...changes } : track));
  }

  function updateClip(clipId: string, changes: Partial<Clip>) {
    void commit(project.timeline.tracks.map((track) => ({ ...track, clips: track.clips.map((clip) => clip.id === clipId ? { ...clip, ...changes } : clip) })));
  }

  function removeClip(clipId: string) {
    setSelectedClipId("");
    void commit(project.timeline.tracks.map((track) => ({ ...track, clips: track.clips.filter((clip) => clip.id !== clipId) })));
  }

  function addEffect(type: EffectNode["type"]) {
    if (!selected) return;
    const effect: EffectNode = { id: crypto.randomUUID(), type, enabled: true, parameters: defaultParameters(type) };
    updateClip(selected.clip.id, { effects: [...selected.clip.effects, effect] });
  }

  function updateEffect(effectId: string, changes: Partial<EffectNode>) {
    if (!selected) return;
    updateClip(selected.clip.id, { effects: selected.clip.effects.map((effect) => effect.id === effectId ? { ...effect, ...changes } : effect) });
  }

  async function preview() {
    if (project.timeline.tracks.some((track) => track.clips.some((clip) => missingPaths.has(clip.source_path)))) { onError("时间线中有缺失音频，请重新关联素材或删除缺失片段后再渲染"); return; }
    setRendering(true);
    try {
      const result = await api.renderPreview(projectPath, project.timeline);
      setPreviewPath(result.path);
    } catch (error) {
      onError(error instanceof Error ? error.message : "预览渲染失败");
    } finally {
      setRendering(false);
    }
  }

  async function autoTrimAsset(asset: GeneratedAsset, clipId?: string) {
    setProcessingAsset(true);
    try {
      const result = await api.trimAsset(asset.id, {
        project_path: projectPath,
        mode: "trim_silence",
        threshold_db: -45,
        padding_seconds: 0.04,
      });
      if (!clipId) {
        onProjectChange(result.manifest);
        return;
      }
      const tracks = result.manifest.timeline.tracks.map((track) => ({
        ...track,
        clips: track.clips.map((clip) =>
          clip.id === clipId
            ? {
                ...clip,
                asset_id: result.asset.id,
                source_path: result.asset.relative_path,
                name: result.asset.name,
                trim_start_seconds: 0,
                trim_end_seconds: null,
              }
            : clip,
        ),
      }));
      const next = {
        ...result.manifest,
        timeline: { ...result.manifest.timeline, tracks },
      };
      const saved = await api.saveProject(projectPath, next);
      onProjectChange(saved);
    } catch (error) {
      onError(error instanceof Error ? error.message : "自动去空白失败");
    } finally {
      setProcessingAsset(false);
    }
  }

  function keyboardMenuPosition(target: HTMLElement) {
    const bounds = target.getBoundingClientRect();
    return { x: bounds.left + 20, y: bounds.top + 20 };
  }

  return (
    <div className="workspace studio-view">
      <section className="content-pane studio-pane">
        <header className="view-header">
          <div><span className="eyebrow">MULTITRACK</span><h1>音效工作台</h1></div>
          <div className="header-actions"><div className="timeline-zoom"><ZoomOut size={14} /><input aria-label="时间线缩放" type="range" min="12" max="120" step="4" value={pixelsPerSecond} onChange={(event) => setPixelsPerSecond(Number(event.target.value))} /><ZoomIn size={14} /></div><button className="secondary-button" onClick={addTrack}><Plus size={16} />添加轨道</button><button className="primary-button" onClick={preview} disabled={rendering}><Headphones size={16} />{rendering ? "渲染中" : "预览混音"}</button></div>
        </header>
        <div className="transport-strip">
          <button className="transport-button" title="播放预览" onClick={() => previewRelative && document.querySelector<HTMLAudioElement>("#mix-preview")?.play()}><Speaker size={18} /></button>
          <div className="time-readout">00:00.000</div>
          <div className="transport-line"><span style={{ width: "0%" }} /></div>
          <span>{project.timeline.duration_seconds.toFixed(1)} s</span>
          {previewRelative && <audio id="mix-preview" src={audioUrl(projectPath, previewRelative)} />}
        </div>
        {healthError && <p className="line-issue">文件检查失败：{healthError}</p>}
        {missingIds.size > 0 && <div className="workbench-warning">{missingIds.size} 个素材文件缺失。选择素材后可以重新关联或删除。<button className="text-button" onClick={() => void refresh()}>重新检查</button></div>}
        <div className="timeline-shell">
          <div className="timeline-ruler" style={{ width: 180 + Math.max(720, project.timeline.duration_seconds * pixelsPerSecond) }}><span className="track-label-spacer" />{timelineTicks(project.timeline.duration_seconds, pixelsPerSecond).map((seconds) => <span key={seconds} style={{ left: 180 + seconds * pixelsPerSecond }}>{formatRulerTime(seconds)}</span>)}</div>
          <div className="timeline-scroll" ref={timelineRef}>
            {project.timeline.tracks.length === 0 ? (
              <div className="timeline-empty"><AudioWaveform size={30} /><strong>时间线为空</strong><span>从下方素材栏加入音效，或新建轨道。</span></div>
            ) : project.timeline.tracks.map((track) => (
              <div className="track-row" key={track.id} onDragOver={(event) => event.preventDefault()} onDrop={(event) => {
                const assetId = event.dataTransfer.getData("asset-id");
                const asset = project.assets.find((item) => item.id === assetId);
                if (!asset) return;
                const bounds = event.currentTarget.querySelector(".track-lane")?.getBoundingClientRect();
                addAsset(asset, track.id, bounds ? Math.max(0, (event.clientX - bounds.left) / pixelsPerSecond) : 0);
              }}>
                <div className="track-controls"><GripVertical size={15} className="muted" /><span className={`track-role role-${track.role}`}>{track.role === "generic" ? "AUDIO" : track.role.toUpperCase()}</span><input value={track.name} onChange={(event) => updateTrack(track.id, { name: event.target.value })} /><button className={track.muted ? "track-toggle active" : "track-toggle"} title="静音" onClick={() => updateTrack(track.id, { muted: !track.muted })}>M</button><button className={track.solo ? "track-toggle active solo" : "track-toggle"} title="独奏" onClick={() => updateTrack(track.id, { solo: !track.solo })}>S</button><button className="icon-button small" title={`删除轨道 ${track.name}`} onClick={() => void commit(project.timeline.tracks.filter((item) => item.id !== track.id))}><Trash2 size={13} /></button></div>
                <div className="track-lane" style={{ width: Math.max(720, project.timeline.duration_seconds * pixelsPerSecond), backgroundSize: `${pixelsPerSecond}px 100%` }}>
                  {track.clips.map((clip) => (
                    <button
                      className={`timeline-clip ${selectedClipId === clip.id ? "selected" : ""} ${missingPaths.has(clip.source_path) ? "asset-missing" : ""}`}
                      key={clip.id}
                      style={{ left: clip.start_seconds * pixelsPerSecond, width: Math.max(48, clipDuration(clip, project.assets) * pixelsPerSecond) }}
                      onClick={() => setSelectedClipId(clip.id)}
                      onContextMenu={(event) => {
                        event.preventDefault();
                        setSelectedClipId(clip.id);
                        setContextMenu({ kind: "clip", clipId: clip.id, x: event.clientX, y: event.clientY });
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
                          event.preventDefault();
                          setSelectedClipId(clip.id);
                          setContextMenu({ kind: "clip", clipId: clip.id, ...keyboardMenuPosition(event.currentTarget) });
                        }
                      }}
                    >
                      <span>{missingPaths.has(clip.source_path) ? "⚠ 文件缺失 · " : ""}{clip.name}</span><div className="clip-wave"><i /><i /><i /><i /><i /><i /><i /><i /></div>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="asset-tray">
          <div className="section-heading compact"><div><h2>项目素材</h2><span>拖入轨道</span></div></div>
          <div className="asset-tray__items">{project.assets.map((asset) => <button
            draggable={!missingIds.has(asset.id)}
            className={missingIds.has(asset.id) ? "asset-missing" : ""}
            onClick={() => setSelectedAssetId(asset.id)}
            key={asset.id}
            onDragStart={(event) => event.dataTransfer.setData("asset-id", asset.id)}
            onDoubleClick={() => addAsset(asset)}
            onContextMenu={(event) => {
              event.preventDefault();
              setContextMenu({ kind: "asset", assetId: asset.id, x: event.clientX, y: event.clientY });
            }}
            onKeyDown={(event) => {
              if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
                event.preventDefault();
                setContextMenu({ kind: "asset", assetId: asset.id, ...keyboardMenuPosition(event.currentTarget) });
              }
            }}
          ><ListPlus size={15} /><span>{asset.name}</span><small>{missingIds.has(asset.id) ? "文件缺失" : asset.model_id || "导入"}</small></button>)}</div>
        </div>
        {(() => { const asset = project.assets.find((item) => item.id === selectedAssetId); return asset && <div className="studio-asset-preview"><header><strong>{asset.name}</strong><AssetActions asset={asset} projectPath={projectPath} missing={missingIds.has(asset.id)} onProjectChange={onProjectChange} onError={onError} /></header><AudioPreview projectPath={projectPath} path={asset.relative_path} label={asset.name} missing={missingIds.has(asset.id)} onError={onError} onMissing={() => void refresh()} /></div>; })()}
      </section>
      <aside className="inspector-pane clip-inspector">
        <div className="inspector-header"><h2>片段检查器</h2>{selected && <button className="icon-button small" title="删除片段" onClick={() => removeClip(selected.clip.id)}><Trash2 size={15} /></button>}</div>
        {selected && missingPaths.has(selected.clip.source_path) && <p className="workbench-warning">此片段的音频文件缺失</p>}
        {selectedAsset && <><AssetActions asset={selectedAsset} projectPath={projectPath} missing={missingIds.has(selectedAsset.id)} onProjectChange={onProjectChange} onError={onError} /><AudioPreview projectPath={projectPath} path={selectedAsset.relative_path} label={selectedAsset.name} missing={missingIds.has(selectedAsset.id)} onError={onError} onMissing={() => void refresh()} /></>}
        {!selected ? <div className="inspector-empty"><SlidersHorizontal size={24} /><span>选择时间线片段</span></div> : <>
          <label className="field"><span>名称</span><input value={selected.clip.name} onChange={(event) => updateClip(selected.clip.id, { name: event.target.value })} /></label>
          <div className="two-fields"><label className="field"><span>开始</span><input type="number" min="0" step="0.1" value={selected.clip.start_seconds} onChange={(event) => updateClip(selected.clip.id, { start_seconds: Number(event.target.value) })} /></label><label className="field"><span>增益 dB</span><input type="number" min="-60" max="24" step="0.5" value={selected.clip.gain_db} onChange={(event) => updateClip(selected.clip.id, { gain_db: Number(event.target.value) })} /></label></div>
          <div className="two-fields"><label className="field"><span>素材入点</span><input aria-label="素材入点" type="number" min="0" max={selected.clip.trim_end_seconds ?? selectedAsset?.duration_seconds} step="0.01" value={selected.clip.trim_start_seconds} onChange={(event) => { const end = selected.clip.trim_end_seconds ?? selectedAsset?.duration_seconds ?? 0; updateClip(selected.clip.id, { trim_start_seconds: Math.max(0, Math.min(Number(event.target.value), Math.max(0, end - 0.01))) }); }} /></label><label className="field"><span>素材出点</span><input aria-label="素材出点" type="number" min={selected.clip.trim_start_seconds} max={selectedAsset?.duration_seconds} step="0.01" value={selected.clip.trim_end_seconds ?? selectedAsset?.duration_seconds ?? 0} onChange={(event) => { const duration = selectedAsset?.duration_seconds ?? Number(event.target.value); updateClip(selected.clip.id, { trim_end_seconds: Math.max(selected.clip.trim_start_seconds + 0.01, Math.min(Number(event.target.value), duration)) }); }} /></label></div>
          <small className="field-hint trim-hint">入点和出点只影响时间线片段，不修改原素材。</small>
          <button className="secondary-button full-width-button" onClick={() => selected && selectedAsset && void autoTrimAsset(selectedAsset, selected.clip.id)} disabled={processingAsset || !selectedAsset || missingIds.has(selectedAsset.id)}><Scissors size={15} />{processingAsset ? "处理中" : "自动去首尾空白"}</button>
          <small className="field-hint block-hint">创建派生素材并替换当前片段，原 WAV 保留。</small>
          <label className="field"><span>声像 <output>{selected.clip.pan.toFixed(2)}</output></span><input type="range" min="-1" max="1" step="0.01" value={selected.clip.pan} onChange={(event) => updateClip(selected.clip.id, { pan: Number(event.target.value) })} /></label>
          <div className="two-fields"><label className="field"><span>淡入</span><input type="number" min="0" step="0.01" value={selected.clip.fade_in_seconds} onChange={(event) => updateClip(selected.clip.id, { fade_in_seconds: Number(event.target.value) })} /></label><label className="field"><span>淡出</span><input type="number" min="0" step="0.01" value={selected.clip.fade_out_seconds} onChange={(event) => updateClip(selected.clip.id, { fade_out_seconds: Number(event.target.value) })} /></label></div>
          <label className="toggle-row"><span>循环片段</span><input type="checkbox" checked={selected.clip.loop_enabled} onChange={(event) => updateClip(selected.clip.id, { loop_enabled: event.target.checked })} /></label>
          <div className="inspector-divider" />
          <div className="effects-heading"><span>效果链</span><select value="" onChange={(event) => { if (event.target.value) addEffect(event.target.value as EffectNode["type"]); }}><option value="">添加效果</option>{Object.entries(effectNames).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></div>
          <div className="effect-stack">{selected.clip.effects.map((effect) => <EffectEditor key={effect.id} effect={effect} onChange={(changes) => updateEffect(effect.id, changes)} onRemove={() => updateClip(selected.clip.id, { effects: selected.clip.effects.filter((item) => item.id !== effect.id) })} />)}</div>
        </>}
      </aside>
      {contextMenu && menuAsset && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          label={`${menuAsset.name} ${contextMenu.kind === "clip" ? "片段" : "素材"}操作`}
          onClose={() => setContextMenu(null)}
          items={contextMenu.kind === "asset"
            ? [
                {
                  id: "add",
                  label: "加入时间线",
                  disabled: missingIds.has(menuAsset.id),
                  icon: <ListPlus size={15} />,
                  onSelect: () => addAsset(menuAsset),
                },
                {
                  id: "auto-trim",
                  label: "自动去首尾空白",
                  icon: <Scissors size={15} />,
                  disabled: processingAsset || missingIds.has(menuAsset.id),
                  onSelect: () => autoTrimAsset(menuAsset),
                },
              ]
            : [
                {
                  id: "inspect",
                  label: "在检查器中手动裁剪",
                  icon: <SlidersHorizontal size={15} />,
                  onSelect: () => {
                    if (menuClip) setSelectedClipId(menuClip.clip.id);
                  },
                },
                {
                  id: "auto-trim",
                  label: "自动去首尾空白",
                  icon: <Scissors size={15} />,
                  disabled: processingAsset || missingIds.has(menuAsset.id),
                  onSelect: () => {
                    if (menuClip) return autoTrimAsset(menuAsset, menuClip.clip.id);
                  },
                },
                {
                  id: "remove",
                  label: "删除片段",
                  icon: <Trash2 size={15} />,
                  destructive: true,
                  separatorBefore: true,
                  onSelect: () => {
                    if (menuClip) removeClip(menuClip.clip.id);
                  },
                },
              ]}
        />
      )}
    </div>
  );
}

function findClip(tracks: Track[], clipId: string): { track: Track; clip: Clip } | null {
  for (const track of tracks) {
    const clip = track.clips.find((item) => item.id === clipId);
    if (clip) return { track, clip };
  }
  return null;
}

function defaultParameters(type: EffectNode["type"]): Record<string, number | boolean | string> {
  if (type === "pitch") return { semitones: 0 };
  if (type === "speed") return { rate: 1 };
  if (type === "eq") return { low_db: 0, mid_db: 0, high_db: 0, low_hz: 180, mid_hz: 1200, high_hz: 6500, mid_q: 0.8 };
  if (type === "compressor") return { threshold_db: -18, ratio: 3, attack_ms: 10, release_ms: 100 };
  if (type === "reverb") return { room_size: 0.25, damping: 0.5, wet_level: 0.15, dry_level: 0.85, width: 1 };
  if (type === "limiter") return { threshold_db: -1, release_ms: 100 };
  return {};
}

function EffectEditor({ effect, onChange, onRemove }: { effect: EffectNode; onChange: (changes: Partial<EffectNode>) => void; onRemove: () => void }) {
  const entries = Object.entries(effect.parameters).filter(([, value]) => typeof value === "number");
  return <div className="effect-item"><header><GripVertical size={14} /><strong>{effectNames[effect.type]}</strong><button className="icon-button small" title={effect.enabled ? "旁路效果" : "启用效果"} onClick={() => onChange({ enabled: !effect.enabled })}>{effect.enabled ? <Eye size={14} /> : <EyeOff size={14} />}</button><button className="icon-button small" title="删除效果" onClick={onRemove}><Trash2 size={14} /></button></header>{entries.map(([key, value]) => <label key={key}><span>{parameterLabel(key)} <output>{Number(value).toFixed(2)}</output></span><input type="range" min={rangeFor(key)[0]} max={rangeFor(key)[1]} step={rangeFor(key)[2]} value={Number(value)} onChange={(event) => onChange({ parameters: { ...effect.parameters, [key]: Number(event.target.value) } })} /></label>)}</div>;
}

function parameterLabel(key: string) { return ({ semitones: "半音", rate: "倍率", low_db: "低频", mid_db: "中频", high_db: "高频", threshold_db: "阈值", ratio: "比率", attack_ms: "启动", release_ms: "释放", room_size: "空间", damping: "阻尼", wet_level: "湿声", dry_level: "干声", width: "宽度" } as Record<string, string>)[key] || key; }
function rangeFor(key: string): [number, number, number] { if (key === "semitones") return [-12, 12, 1]; if (key === "rate") return [0.5, 2, 0.05]; if (key.endsWith("_db")) return [-24, 12, 0.5]; if (key === "ratio") return [1, 10, 0.1]; if (key.endsWith("_ms")) return [1, 500, 1]; return [0, 1, 0.01]; }

function clipDuration(clip: Clip, assets: GeneratedAsset[]) {
  const asset = assets.find((item) => item.id === clip.asset_id);
  const end = clip.trim_end_seconds ?? asset?.duration_seconds ?? 5;
  return Math.max(0.1, end - clip.trim_start_seconds);
}

function timelineTicks(duration: number, pixelsPerSecond: number) {
  const interval = pixelsPerSecond < 20 ? 10 : pixelsPerSecond < 40 ? 5 : 1;
  return Array.from({ length: Math.floor(duration / interval) + 1 }, (_, index) => index * interval);
}

function formatRulerTime(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function roleName(role: NonNullable<GeneratedAsset["stem_role"]>) {
  return ({ vocals: "人声", drums: "鼓", bass: "贝斯", other: "其他" })[role];
}
