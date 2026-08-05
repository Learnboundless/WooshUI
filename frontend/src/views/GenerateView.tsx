import {
  Copy,
  Heart,
  Languages,
  ListPlus,
  Play,
  RotateCcw,
  Scissors,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, audioUrl } from "../api";
import { ContextMenu } from "../components/ContextMenu";
import { Waveform, type WaveformHandle } from "../components/Waveform";
import type { GeneratedAsset, ModelDescriptor, ProjectManifest } from "../types";

interface GenerateViewProps {
  projectPath: string;
  project: ProjectManifest;
  models: ModelDescriptor[];
  activeModel: string;
  onModelChange: (id: string) => void;
  onProjectChange: (manifest: ProjectManifest) => void;
  onQueued: () => void;
  onError: (message: string) => void;
}

export function GenerateView({
  projectPath,
  project,
  models,
  activeModel,
  onModelChange,
  onProjectChange,
  onQueued,
  onError,
}: GenerateViewProps) {
  const [soundName, setSoundName] = useState("机甲落地");
  const [promptOriginal, setPromptOriginal] = useState("重型机甲落地，金属冲击与短促液压声");
  const [promptConditioned, setPromptConditioned] = useState("a heavy mech landing with a metallic impact and a short hydraulic burst");
  const [count, setCount] = useState(4);
  const [cfg, setCfg] = useState(4.5);
  const [seedMode, setSeedMode] = useState<"random" | "fixed" | "increment">("increment");
  const [seed, setSeed] = useState(4281);
  const [postprocessMode, setPostprocessMode] = useState<"none" | "trim_silence">("trim_silence");
  const [assetTrimMode, setAssetTrimMode] = useState<"manual" | "trim_silence">("trim_silence");
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(0);
  const [processingAsset, setProcessingAsset] = useState(false);
  const [translationStage, setTranslationStage] = useState<"idle" | "preparing" | "translating">("idle");
  const [selectedAssetId, setSelectedAssetId] = useState(project.assets.at(-1)?.id ?? "");
  const [contextMenu, setContextMenu] = useState<{ assetId: string; x: number; y: number } | null>(null);
  const waveformRef = useRef<WaveformHandle>(null);
  const soundAssets = useMemo(
    () => project.assets.filter((asset) => !["music_mix", "stem"].includes(asset.kind)),
    [project.assets],
  );
  const selectedAsset = useMemo(
    () => soundAssets.find((asset) => asset.id === selectedAssetId) ?? soundAssets.at(-1),
    [selectedAssetId, soundAssets],
  );
  const menuAsset = contextMenu
    ? soundAssets.find((asset) => asset.id === contextMenu.assetId)
    : undefined;
  const textModels = models.filter((model) => model.family === "text" && model.supported);
  const activeDescriptor = textModels.find((model) => model.id === activeModel);
  const translationModel = models.find((model) => model.family === "translation");

  useEffect(() => {
    setTrimStart(0);
    setTrimEnd(selectedAsset?.duration_seconds ?? 0);
  }, [selectedAsset?.id, selectedAsset?.duration_seconds]);

  async function translate() {
    setTranslationStage(translationModel?.installed ? "translating" : "preparing");
    try {
      if (!translationModel?.installed) {
        const job = await api.downloadModel(translationModel?.id || "opus-mt-zh-en");
        onQueued();
        await waitForJob(job.id);
        setTranslationStage("translating");
      }
      const result = await api.translate(promptOriginal);
      setPromptConditioned(result.translated);
    } catch (error) {
      onError(error instanceof Error ? error.message : "翻译失败");
    } finally {
      setTranslationStage("idle");
    }
  }

  async function waitForJob(jobId: string) {
    while (true) {
      const job = await api.job(jobId);
      if (job.status === "completed") return;
      if (["failed", "cancelled", "interrupted"].includes(job.status)) {
        throw new Error(job.error?.message || "翻译模型准备失败");
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
  }

  async function generate() {
    const normalizedName = soundName.trim();
    if (!normalizedName) {
      onError("请先填写音效名称");
      return;
    }
    if (!activeDescriptor?.installed) {
      onError("请先在模型页面安装当前模型");
      return;
    }
    try {
      await api.generate({
        project_path: projectPath,
        prompt_original: promptOriginal,
        prompt_conditioned: promptConditioned,
        count,
        category: "SFX",
        name: normalizedName,
        postprocess_mode: postprocessMode,
        settings: {
          model_id: activeModel,
          cfg,
          seed,
          seed_mode: seedMode,
          solver: "dopri5",
          atol: 0.001,
          rtol: 0.001,
        },
      });
      onQueued();
    } catch (error) {
      onError(error instanceof Error ? error.message : "生成任务提交失败");
    }
  }

  async function toggleFavorite(assetId: string) {
    const assets = project.assets.map((asset) =>
      asset.id === assetId ? { ...asset, favorite: !asset.favorite } : asset,
    );
    const saved = await api.saveProject(projectPath, { ...project, assets });
    onProjectChange(saved);
  }

  async function createTrimmedVersion(
    targetAsset = selectedAsset,
    mode: "manual" | "trim_silence" = assetTrimMode,
  ) {
    if (!targetAsset) return;
    if (mode === "manual" && trimEnd <= trimStart) {
      onError("裁剪终点必须晚于起点");
      return;
    }
    setProcessingAsset(true);
    try {
      const result = await api.trimAsset(targetAsset.id, {
        project_path: projectPath,
        mode,
        start_seconds: trimStart,
        end_seconds: mode === "manual" ? trimEnd : undefined,
        threshold_db: -45,
        padding_seconds: 0.04,
      });
      onProjectChange(result.manifest);
      setSelectedAssetId(result.asset.id);
    } catch (error) {
      onError(error instanceof Error ? error.message : "音频裁剪失败");
    } finally {
      setProcessingAsset(false);
    }
  }

  function openContextMenu(asset: GeneratedAsset, x: number, y: number) {
    setSelectedAssetId(asset.id);
    setContextMenu({ assetId: asset.id, x, y });
  }

  function openKeyboardContextMenu(asset: GeneratedAsset, target: HTMLElement) {
    const bounds = target.getBoundingClientRect();
    openContextMenu(asset, bounds.left + 20, bounds.top + 20);
  }

  function auditionAsset(asset: GeneratedAsset) {
    setSelectedAssetId(asset.id);
    window.setTimeout(() => waveformRef.current?.togglePlayback(), 0);
  }

  return (
    <div className="workspace three-column-view">
      <section className="content-pane generate-pane">
        <header className="view-header">
          <div><span className="eyebrow">TEXT TO AUDIO</span><h1>生成音效</h1></div>
          <button className="primary-button" onClick={generate} disabled={!soundName.trim() || !promptConditioned.trim()}>
            <Sparkles size={17} />生成 {count} 个变体
          </button>
        </header>

        <div className="sfx-name-row">
          <label className="title-input">
            <span>名称</span>
            <input
              aria-label="音效名称"
              maxLength={80}
              placeholder="例如：玩家激光枪"
              value={soundName}
              onChange={(event) => setSoundName(event.target.value)}
            />
          </label>
          <span className="sfx-name-preview">SFX_{safePreviewName(soundName)}_01.wav</span>
        </div>

        <div className="prompt-editor">
          <div className="prompt-toolbar">
            <span>提示词</span>
            <button className="text-button" onClick={translate} disabled={translationStage !== "idle" || !promptOriginal.trim()}>
              <Languages size={15} />{translationStage === "preparing" ? "准备本地翻译" : translationStage === "translating" ? "翻译中" : "转为英文"}
            </button>
          </div>
          <textarea value={promptOriginal} onChange={(event) => setPromptOriginal(event.target.value)} aria-label="中文提示词" />
          <div className="conditioned-prompt">
            <span>模型输入</span>
            <textarea value={promptConditioned} onChange={(event) => setPromptConditioned(event.target.value)} aria-label="英文模型提示词" />
          </div>
        </div>

        <div className="section-heading"><div><h2>生成版本</h2><span>{soundAssets.length} 个素材</span></div><button className="icon-button" title="刷新项目"><RotateCcw size={16} /></button></div>
        <div className="asset-grid">
          {soundAssets.length === 0 ? (
            <div className="empty-state"><AudioEmptyIcon /><strong>还没有音效</strong><span>提交提示词后，生成版本会出现在这里。</span></div>
          ) : soundAssets.slice().reverse().map((asset) => (
            <article
              className={selectedAsset?.id === asset.id ? "asset-card selected" : "asset-card"}
              key={asset.id}
              tabIndex={0}
              aria-label={`素材 ${asset.name}`}
              onClick={() => setSelectedAssetId(asset.id)}
              onContextMenu={(event) => {
                event.preventDefault();
                openContextMenu(asset, event.clientX, event.clientY);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setSelectedAssetId(asset.id);
                } else if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
                  event.preventDefault();
                  openKeyboardContextMenu(asset, event.currentTarget);
                }
              }}
            >
              <div className="asset-card__top"><span className="asset-index">{asset.source === "generated" ? "AI" : "SRC"}</span><button className={asset.favorite ? "icon-button small favorite" : "icon-button small"} title="收藏" onClick={(event) => { event.stopPropagation(); void toggleFavorite(asset.id); }}><Heart size={15} fill={asset.favorite ? "currentColor" : "none"} /></button></div>
              <strong>{asset.name}</strong>
              <span className="asset-meta">{asset.model_id || "导入素材"} · {asset.seed ?? "—"}</span>
              <div className="mini-wave"><span /><span /><span /><span /><span /><span /><span /></div>
            </article>
          ))}
        </div>

        {selectedAsset && (
          <div className="audition-strip">
            <button className="transport-button" title="播放或暂停" onClick={() => waveformRef.current?.togglePlayback()}><Play size={18} fill="currentColor" /></button>
            <div className="audition-wave"><Waveform ref={waveformRef} url={audioUrl(projectPath, selectedAsset.relative_path)} height={54} /></div>
            <div className="audition-actions"><button className="icon-button" title="复制参数"><Copy size={16} /></button><button className="icon-button" title="加入工作台"><ListPlus size={16} /></button></div>
          </div>
        )}
      </section>

      <aside className="inspector-pane">
        <div className="inspector-header"><h2>生成参数</h2><span className={activeDescriptor?.installed ? "status-dot ready" : "status-dot"}>{activeDescriptor?.installed ? "可用" : "未安装"}</span></div>
        <label className="field"><span>模型</span><select value={activeModel} onChange={(event) => onModelChange(event.target.value)}>{textModels.map((model) => <option value={model.id} key={model.id}>{model.name}</option>)}</select></label>
        <label className="field"><span>变体数量 <output>{count}</output></span><input type="range" min="1" max="8" value={count} onChange={(event) => setCount(Number(event.target.value))} /></label>
        <label className="field"><span>引导强度 <output>{cfg.toFixed(1)}</output></span><input type="range" min="0" max="15" step="0.1" value={cfg} onChange={(event) => setCfg(Number(event.target.value))} /></label>
        <fieldset className="field"><legend>生成后处理</legend><div className="segmented two-line"><button className={postprocessMode === "none" ? "active" : ""} onClick={() => setPostprocessMode("none")}>保留完整</button><button className={postprocessMode === "trim_silence" ? "active" : ""} onClick={() => setPostprocessMode("trim_silence")}>自动去空白</button></div><small className="field-hint">只裁首尾静音，不处理声音中间的停顿。</small></fieldset>
        <fieldset className="field"><legend>种子策略</legend><div className="segmented"><button className={seedMode === "random" ? "active" : ""} onClick={() => setSeedMode("random")}>随机</button><button className={seedMode === "fixed" ? "active" : ""} onClick={() => setSeedMode("fixed")}>固定</button><button className={seedMode === "increment" ? "active" : ""} onClick={() => setSeedMode("increment")}>递增</button></div></fieldset>
        <label className="field"><span>起始种子</span><input type="number" value={seed} disabled={seedMode === "random"} onChange={(event) => setSeed(Number(event.target.value))} /></label>
        {selectedAsset && <>
          <div className="inspector-divider" />
          <div className="subsection-heading"><span>素材裁剪</span><small>{selectedAsset.duration_seconds.toFixed(2)} 秒</small></div>
          <fieldset className="field"><legend>处理方式</legend><div className="segmented two-line"><button className={assetTrimMode === "trim_silence" ? "active" : ""} onClick={() => setAssetTrimMode("trim_silence")}>自动去空白</button><button className={assetTrimMode === "manual" ? "active" : ""} onClick={() => setAssetTrimMode("manual")}>手动范围</button></div></fieldset>
          {assetTrimMode === "manual" && <div className="two-fields"><label className="field"><span>起点（秒）</span><input aria-label="裁剪起点" type="number" min="0" max={selectedAsset.duration_seconds} step="0.01" value={trimStart} onChange={(event) => setTrimStart(Number(event.target.value))} /></label><label className="field"><span>终点（秒）</span><input aria-label="裁剪终点" type="number" min="0" max={selectedAsset.duration_seconds} step="0.01" value={trimEnd} onChange={(event) => setTrimEnd(Number(event.target.value))} /></label></div>}
          <button className="secondary-button full-width-button" onClick={() => void createTrimmedVersion()} disabled={processingAsset || (assetTrimMode === "manual" && trimEnd <= trimStart)}><Scissors size={15} />{processingAsset ? "处理中" : "创建裁剪版本"}</button>
          <small className="field-hint block-hint">创建新素材，不覆盖当前 WAV。</small>
        </>}
        <div className="inspector-divider" />
        <div className="metric-row"><span>格式</span><strong>48 kHz · Mono</strong></div><div className="metric-row"><span>时长</span><strong>约 5 秒</strong></div><div className="metric-row"><span>设备</span><strong>跟随全局设置</strong></div>
      </aside>
      {contextMenu && menuAsset && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          label={`${menuAsset.name} 素材操作`}
          onClose={() => setContextMenu(null)}
          items={[
            {
              id: "audition",
              label: "试听",
              icon: <Play size={15} />,
              onSelect: () => auditionAsset(menuAsset),
            },
            {
              id: "auto-trim",
              label: "自动去首尾空白",
              icon: <Scissors size={15} />,
              disabled: processingAsset,
              onSelect: () => createTrimmedVersion(menuAsset, "trim_silence"),
            },
            {
              id: "manual-trim",
              label: "在检查器中手动裁剪",
              icon: <SlidersHorizontal size={15} />,
              onSelect: () => {
                setSelectedAssetId(menuAsset.id);
                setAssetTrimMode("manual");
              },
            },
            {
              id: "favorite",
              label: menuAsset.favorite ? "取消收藏" : "收藏",
              icon: <Heart size={15} fill={menuAsset.favorite ? "currentColor" : "none"} />,
              separatorBefore: true,
              onSelect: () => toggleFavorite(menuAsset.id),
            },
          ]}
        />
      )}
    </div>
  );
}

function AudioEmptyIcon() {
  return <div className="empty-wave" aria-hidden="true"><span /><span /><span /><span /><span /></div>;
}

function safePreviewName(value: string) {
  return value
    .trim()
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "-")
    .replace(/\s+/g, " ")
    .replace(/^[ .]+|[ .]+$/g, "") || "未命名";
}
