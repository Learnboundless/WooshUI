import {
  Disc3,
  Download,
  FileUp,
  ListMusic,
  ListPlus,
  Music2,
  Play,
  Scissors,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, audioUrl } from "../api";
import type {
  Clip,
  GeneratedAsset,
  ModelDescriptor,
  ProjectManifest,
  Track,
} from "../types";

interface MusicViewProps {
  projectPath: string;
  project: ProjectManifest;
  models: ModelDescriptor[];
  onProjectChange: (manifest: ProjectManifest) => void;
  onQueued: () => void;
  onError: (message: string) => void;
}

type MusicMode = "instrumental" | "lyrics";
type SeedMode = "random" | "fixed" | "increment";
type StemRole = "vocals" | "drums" | "bass" | "other";

const lyricSections = ["Intro", "Verse", "Prechorus", "Chorus", "Bridge", "Outro"];
const tagPresets = ["cinematic", "electronic", "orchestral", "dark", "uplifting", "120 bpm"];
const roleLabels: Record<StemRole, string> = {
  vocals: "人声",
  drums: "鼓",
  bass: "贝斯",
  other: "其他",
};

export function MusicView({
  projectPath,
  project,
  models,
  onProjectChange,
  onQueued,
  onError,
}: MusicViewProps) {
  const [title, setTitle] = useState("Battle Theme");
  const [mode, setMode] = useState<MusicMode>("instrumental");
  const [tagsText, setTagsText] = useState("cinematic, electronic, tense, 120 bpm");
  const [lyrics, setLyrics] = useState("[Intro]\n\n[Verse]\n\n[Chorus]\n");
  const [duration, setDuration] = useState<30 | 60 | 120 | 240>(60);
  const [count, setCount] = useState(1);
  const [separateStems, setSeparateStems] = useState(true);
  const [temperature, setTemperature] = useState(1);
  const [topK, setTopK] = useState(50);
  const [cfgScale, setCfgScale] = useState(1.5);
  const [seed, setSeed] = useState(4281);
  const [seedMode, setSeedMode] = useState<SeedMode>("increment");
  const lyricsFile = useRef<HTMLInputElement>(null);
  const musicModel = models.find((model) => model.id === "HeartMuLa-3B");
  const demucs = models.find((model) => model.id === "Demucs-htdemucs");

  useEffect(() => {
    const saved = localStorage.getItem(`woosh-music-draft:${project.id}`);
    if (!saved) return;
    try {
      const draft = JSON.parse(saved) as { lyrics?: string; tags?: string; title?: string };
      if (draft.lyrics) setLyrics(draft.lyrics);
      if (draft.tags) setTagsText(draft.tags);
      if (draft.title) setTitle(draft.title);
    } catch {
      localStorage.removeItem(`woosh-music-draft:${project.id}`);
    }
  }, [project.id]);

  useEffect(() => {
    localStorage.setItem(
      `woosh-music-draft:${project.id}`,
      JSON.stringify({ lyrics, tags: tagsText, title }),
    );
  }, [lyrics, project.id, tagsText, title]);

  const groups = useMemo(() => {
    const grouped = new Map<string, GeneratedAsset[]>();
    for (const asset of project.assets) {
      if (!["music_mix", "stem"].includes(asset.kind)) continue;
      const key = asset.generation_group_id || asset.parent_asset_id || asset.id;
      grouped.set(key, [...(grouped.get(key) || []), asset]);
    }
    return [...grouped.entries()].reverse();
  }, [project.assets]);

  function appendSection(section: string) {
    setLyrics((value) => `${value.trimEnd()}\n\n[${section}]\n`);
  }

  function addTag(tag: string) {
    const tags = parseTags(tagsText);
    if (!tags.includes(tag)) setTagsText([...tags, tag].join(", "));
  }

  async function generate() {
    if (!musicModel?.installed) {
      onError("请先在模型页面安装 HeartMuLa 与 HeartCodec");
      return;
    }
    if (separateStems && !demucs?.installed) {
      onError("生成后分轨已开启，请先安装 Demucs 四分轨工具");
      return;
    }
    try {
      await api.generateMusic({
        project_path: projectPath,
        title,
        mode,
        tags: parseTags(tagsText),
        lyrics: mode === "lyrics" ? lyrics : "",
        duration_seconds: duration,
        count,
        separate_stems: separateStems,
        settings: {
          model_id: "HeartMuLa-3B",
          temperature,
          top_k: topK,
          cfg_scale: cfgScale,
          seed,
          seed_mode: seedMode,
        },
      });
      onQueued();
    } catch (error) {
      onError(error instanceof Error ? error.message : "音乐任务提交失败");
    }
  }

  async function separate(assetId: string) {
    try {
      await api.separateAsset(assetId, projectPath);
      onQueued();
    } catch (error) {
      onError(error instanceof Error ? error.message : "分轨任务提交失败");
    }
  }

  async function addAssetsToTimeline(assets: GeneratedAsset[]) {
    const sourceAssets = assets.some((asset) => asset.kind === "stem")
      ? assets.filter((asset) => asset.kind === "stem")
      : assets.filter((asset) => asset.kind === "music_mix");
    let tracks = project.timeline.tracks.map((track) => ({ ...track, clips: [...track.clips] }));
    for (const asset of sourceAssets) {
      const role = asset.stem_role || (asset.kind === "music_mix" ? "music" : "generic");
      let track = tracks.find((candidate) => candidate.role === role);
      if (!track) {
        track = createTrack(
          asset.stem_role ? roleLabels[asset.stem_role] : "音乐",
          role,
        );
        tracks.push(track);
      }
      track.clips.push(createClip(asset));
    }
    const durationSeconds = Math.max(
      project.timeline.duration_seconds,
      ...sourceAssets.map((asset) => asset.duration_seconds),
    );
    try {
      const saved = await api.saveProject(projectPath, {
        ...project,
        timeline: { ...project.timeline, tracks, duration_seconds: durationSeconds },
      });
      onProjectChange(saved);
    } catch (error) {
      onError(error instanceof Error ? error.message : "加入工作台失败");
    }
  }

  async function importLyrics(file: File | undefined) {
    if (!file) return;
    try {
      setLyrics(await file.text());
    } catch {
      onError("歌词文件读取失败");
    } finally {
      if (lyricsFile.current) lyricsFile.current.value = "";
    }
  }

  return (
    <div className="workspace music-view three-column-view">
      <section className="content-pane music-pane">
        <header className="view-header">
          <div><span className="eyebrow">TEXT TO MUSIC</span><h1>生成音乐</h1></div>
          <button className="primary-button" onClick={generate} disabled={!title.trim()}>
            <Sparkles size={17} />生成 {count} 个变体
          </button>
        </header>

        <div className="music-mode-row">
          <div className="segmented music-mode">
            <button className={mode === "instrumental" ? "active" : ""} onClick={() => setMode("instrumental")}><Disc3 size={15} />纯音乐 BGM</button>
            <button className={mode === "lyrics" ? "active" : ""} onClick={() => setMode("lyrics")}><Music2 size={15} />带歌词歌曲</button>
          </div>
          <label className="title-input"><span>标题</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
        </div>

        <div className="music-editor">
          <div className="tag-editor">
            <label><span>风格标签</span><input value={tagsText} onChange={(event) => setTagsText(event.target.value)} placeholder="风格, 情绪, 速度, 乐器" /></label>
            <div className="tag-presets">{tagPresets.map((tag) => <button key={tag} onClick={() => addTag(tag)}>+ {tag}</button>)}</div>
          </div>
          {mode === "lyrics" && (
            <div className="lyrics-editor">
              <div className="lyrics-toolbar">
                <span>歌词</span>
                <div>
                  <input ref={lyricsFile} hidden type="file" accept=".txt,.lrc,text/plain" onChange={(event) => void importLyrics(event.target.files?.[0])} />
                  <button title="导入 TXT 或 LRC 歌词" onClick={() => lyricsFile.current?.click()}><FileUp size={13} />导入</button>
                  {lyricSections.map((section) => <button key={section} title={`插入 ${section}`} onClick={() => appendSection(section)}>[{section}]</button>)}
                </div>
              </div>
              <textarea aria-label="歌曲歌词" value={lyrics} onChange={(event) => setLyrics(event.target.value)} />
            </div>
          )}
        </div>

        <div className="section-heading"><div><h2>音乐素材组</h2><span>{groups.length} 组</span></div></div>
        <div className="music-results">
          {groups.length === 0 ? (
            <div className="empty-state music-empty"><ListMusic size={28} /><strong>还没有音乐</strong><span>音乐混音与后处理分轨会成组显示。</span></div>
          ) : groups.map(([groupId, assets]) => {
            const mix = assets.find((asset) => asset.kind === "music_mix");
            const stems = assets.filter((asset) => asset.kind === "stem");
            return <article className="music-group" key={groupId}>
              <header><div><strong>{mix?.name || "音乐素材"}</strong><span>{formatDuration(mix?.duration_seconds || 0)} · {mix?.seed ?? "—"}</span></div><button className="secondary-button compact-button" onClick={() => void addAssetsToTimeline(assets)}><ListPlus size={15} />{stems.length ? "加入四轨" : "加入混音"}</button></header>
              {mix && <MusicAssetRow asset={mix} projectPath={projectPath} onAdd={() => void addAssetsToTimeline([mix])} />}
              {stems.length > 0 ? <div className="stem-grid">{stems.map((asset) => <MusicAssetRow asset={asset} projectPath={projectPath} key={asset.id} compact onAdd={() => void addAssetsToTimeline([asset])} />)}</div> : mix && <button className="text-button separate-button" onClick={() => void separate(mix.id)}><Scissors size={15} />生成后分离人声、鼓、贝斯、其他</button>}
            </article>;
          })}
        </div>
      </section>

      <aside className="inspector-pane">
        <div className="inspector-header"><h2>音乐参数</h2><span className={musicModel?.installed ? "status-dot ready" : "status-dot"}>{musicModel?.installed ? "可用" : "未安装"}</span></div>
        <fieldset className="field"><legend>最大时长</legend><div className="segmented duration-segment">{([30, 60, 120, 240] as const).map((value) => <button className={duration === value ? "active" : ""} key={value} onClick={() => setDuration(value)}>{value < 60 ? `${value}s` : `${value / 60}m`}</button>)}</div></fieldset>
        <label className="field"><span>变体数量 <output>{count}</output></span><input type="range" min="1" max="4" value={count} onChange={(event) => setCount(Number(event.target.value))} /></label>
        <label className="toggle-row stem-toggle"><span><strong>生成后分轨</strong><small>Demucs 后处理 · 4 stems</small></span><input type="checkbox" checked={separateStems} onChange={(event) => setSeparateStems(event.target.checked)} /></label>
        <div className="inspector-divider" />
        <label className="field"><span>Temperature <output>{temperature.toFixed(2)}</output></span><input type="range" min="0.1" max="2" step="0.05" value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} /></label>
        <label className="field"><span>Top K <output>{topK}</output></span><input type="range" min="1" max="200" value={topK} onChange={(event) => setTopK(Number(event.target.value))} /></label>
        <label className="field"><span>CFG <output>{cfgScale.toFixed(2)}</output></span><input type="range" min="1" max="5" step="0.05" value={cfgScale} onChange={(event) => setCfgScale(Number(event.target.value))} /></label>
        <fieldset className="field"><legend>种子策略</legend><div className="segmented"><button className={seedMode === "random" ? "active" : ""} onClick={() => setSeedMode("random")}>随机</button><button className={seedMode === "fixed" ? "active" : ""} onClick={() => setSeedMode("fixed")}>固定</button><button className={seedMode === "increment" ? "active" : ""} onClick={() => setSeedMode("increment")}>递增</button></div></fieldset>
        <label className="field"><span>起始种子</span><input type="number" value={seed} disabled={seedMode === "random"} onChange={(event) => setSeed(Number(event.target.value))} /></label>
      </aside>
    </div>
  );
}

function MusicAssetRow({ asset, projectPath, compact = false, onAdd }: { asset: GeneratedAsset; projectPath: string; compact?: boolean; onAdd: () => void }) {
  const source = audioUrl(projectPath, asset.relative_path);
  return <div className={compact ? "music-asset compact" : "music-asset"}>
    <span className="music-kind">{asset.stem_role ? roleLabels[asset.stem_role] : "MIX"}</span>
    <button className="icon-button small" title="播放" onClick={(event) => {
      const audio = event.currentTarget.parentElement?.querySelector("audio");
      if (!audio) return;
      if (audio.paused) void audio.play();
      else audio.pause();
    }}><Play size={14} fill="currentColor" /></button>
    <span><strong>{asset.name}</strong><small>{asset.channel_count} ch · 48 kHz</small></span>
    <audio preload="none" src={source} />
    <button className="icon-button small" title="单独加入工作台" onClick={onAdd}><ListPlus size={14} /></button>
    <a className="icon-button small" title="下载 WAV" href={source} download={`${asset.name}.wav`}><Download size={14} /></a>
  </div>;
}

function parseTags(value: string): string[] {
  return [...new Set(value.split(/[,，]/).map((tag) => tag.trim().toLowerCase()).filter(Boolean))];
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${Math.round(seconds % 60).toString().padStart(2, "0")}`;
}

function createTrack(name: string, role: Track["role"]): Track {
  return {
    id: crypto.randomUUID(),
    name,
    muted: false,
    solo: false,
    gain_db: 0,
    pan: 0,
    role,
    clips: [],
  };
}

function createClip(asset: GeneratedAsset): Clip {
  return {
    id: crypto.randomUUID(),
    asset_id: asset.id,
    name: asset.name,
    source_path: asset.relative_path,
    start_seconds: 0,
    trim_start_seconds: 0,
    trim_end_seconds: asset.duration_seconds,
    fade_in_seconds: 0.02,
    fade_out_seconds: 0.08,
    gain_db: 0,
    pan: 0,
    loop_enabled: false,
    loop_start_seconds: null,
    loop_end_seconds: null,
    effects: [],
  };
}
