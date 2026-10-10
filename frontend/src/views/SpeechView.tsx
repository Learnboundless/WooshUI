import { ArrowDown, ArrowUp, BookOpen, Check, ChevronRight, ClipboardPaste, Copy, FileJson, FolderOpen, Headphones, Loader2, Mic2, Plus, Save, Search, Trash2, Undo2, Upload, Users, WandSparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { api, audioUrl } from "../api";
import { ReferenceAudioTools } from "../components/ReferenceAudioTools";
import { LocalizedLineEditor } from "../components/LocalizedLineEditor";
import { locales, localeName, voiceSettings } from "../localization";
import { AudioPreview } from "../components/AudioPreview";
import { AssetActions } from "../components/AssetActions";
import { useAssetHealth } from "../hooks/useAssetHealth";
import { AgentKitDialog } from "../components/AgentKitDialog";
import { FreesoundDialog } from "../components/FreesoundDialog";
import { ScriptImportDialog } from "../components/ScriptImportDialog";
import type { JobEvent, ModelDescriptor, ProjectManifest, ResourceDocument, ResourceImportResult, ResourceMapping, ScriptDocument, ScriptLine, ScriptPreview, VoiceProfile } from "../types";
import { blankVoice, copyResourcePath, detectDialogueLanguage, droppedFiles, emptyScript, languages, lineIssue, mergeScript, revealResource, speakers } from "../workbench";

interface Props {
  projectPath: string; project: ProjectManifest; models: ModelDescriptor[]; jobs?: JobEvent[]; active?: boolean;
  onProjectChange: (project: ProjectManifest) => void; onQueued: () => void; onError: (message: string) => void;
}
interface ImportState { text?: string; documents?: ResourceDocument[]; mappings?: ResourceMapping[]; }
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const lineContent = (line: ScriptLine) => ({ ...line, localizations: undefined, source_language: line.source_language || "Auto", translation: null, asset_id: null });
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

export function SpeechView({ projectPath, project, models, jobs = [], active = true, onProjectChange, onQueued, onError }: Props) {
  const { missingIds, refresh: refreshHealth } = useAssetHealth(projectPath, project);
  const [translationErrors, setTranslationErrors] = useState<Record<string, string>>({});
  const [translating, setTranslating] = useState<string[]>([]);
  const [translationRetry, setTranslationRetry] = useState(0);
  const attemptedTranslations = useRef(new Set<string>());
  const translationInFlight = useRef(false);
  const [draft, setDraft] = useState<ScriptDocument>(() => project.script ?? emptyScript());
  const draftRef = useRef(draft);
  const savedRef = useRef(draft);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const [saveStatus, setSaveStatus] = useState("已保存");
  const [submitting, setSubmitting] = useState(false);
  const [importing, setImporting] = useState(false);
  const importingRef = useRef(false);
  const [dragging, setDragging] = useState(false);
  const [selectedVoiceId, setSelectedVoiceId] = useState(draft.voices[0]?.id ?? "");
  const [sideTab, setSideTab] = useState<"voices" | "resources">("voices");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [notice, setNotice] = useState("");
  const [resourceWarnings, setResourceWarnings] = useState<string[]>([]);
  const [importState, setImportState] = useState<ImportState | null>(null);
  const [freesoundOpen, setFreesoundOpen] = useState(false);
  const [agentTab, setAgentTab] = useState<string | null>(null);
  const [undo, setUndo] = useState<ScriptDocument | null>(null);
  const [documents, setDocuments] = useState<ResourceDocument[]>([]);
  const [mappings, setMappings] = useState<ResourceMapping[]>([]);
  const [referenceExists, setReferenceExists] = useState<boolean | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const pickerBinding = useRef<string | undefined>(undefined);
  const dragDepth = useRef(0);
  const [voiceLocale, setVoiceLocale] = useState("");
  const selectedProfile = draft.voices.find((voice) => voice.id === selectedVoiceId) ?? draft.voices[0];
  const selectedVoice = selectedProfile && voiceLocale ? {...selectedProfile, ...selectedProfile.locale_overrides?.[voiceLocale]} : selectedProfile;
  const targets = draft.target_locales || [];
  const multilingual = targets.length > 0;
  useEffect(() => { if (voiceLocale && !targets.includes(voiceLocale)) setVoiceLocale(""); }, [voiceLocale, targets]);
  const busyJob = jobs.some((job) => job.kind === "speech_generation" && job.payload.project_path === projectPath && !["completed", "partial", "failed", "cancelled", "interrupted"].includes(job.status));
  const enabled = draft.lines.filter((line) => line.enabled);
  const problems = enabled.filter((line) => lineIssue(draft, line.id, models));
  const generated = draft.lines.filter((line) => line.asset_id && project.assets.some((asset) => asset.id === line.asset_id));
  const audioAssets = project.assets.filter((asset) => /\.(wav|flac|mp3|ogg|aif|aiff)$/i.test(asset.relative_path));
  const visibleLines = draft.lines.filter((line) => (!search || `${line.character} ${line.text}`.toLowerCase().includes(search.toLowerCase())) && (filter === "all" || (filter === "issues" ? line.enabled && lineIssue(draft, line.id, models) : line.voice_id === filter)));

  const update = useCallback((next: ScriptDocument, remember = false) => {
    if (remember) setUndo(draftRef.current);
    draftRef.current = next;
    setDraft(next);
    setSaveStatus("待保存");
  }, []);

  const persist = useCallback(async (snapshot: ScriptDocument) => {
    const operation = saveQueue.current.catch(() => undefined).then(async () => {
      if (same(snapshot, savedRef.current)) return;
      setSaveStatus("保存中…");
      const saved = await api.saveScript(projectPath, snapshot);
      savedRef.current = saved.script ?? snapshot;
      const wasCurrent = same(snapshot, draftRef.current);
      if (wasCurrent) { draftRef.current = saved.script ?? snapshot; setDraft(draftRef.current); }
      onProjectChange(saved);
      setSaveStatus(wasCurrent ? "已保存" : "待保存");
    });
    saveQueue.current = operation;
    try { await operation; }
    catch (reason) { setSaveStatus("保存失败 · 点击重试"); throw reason; }
  }, [onProjectChange, projectPath]);

  useEffect(() => () => { void persist(draftRef.current).catch((reason) => onError(errorText(reason))); }, [persist, onError]);

  useEffect(() => {
    const incoming = project.script ?? emptyScript();
    if (same(incoming, savedRef.current)) return;
    if (same(draftRef.current, savedRef.current)) {
      draftRef.current = incoming; setDraft(incoming);
    } else {
      // Refresh finished audio without replacing text the user is currently editing.
      const next = { ...draftRef.current, lines: draftRef.current.lines.map((line) => {
        const fresh = incoming.lines.find((item) => item.id === line.id);
        const voice = draftRef.current.voices.find((item) => item.id === line.voice_id);
        const freshVoice = incoming.voices.find((item) => item.id === line.voice_id);
        if (!fresh || !same(lineContent(fresh), lineContent(line)) || !same(voice, freshVoice)) return line;
        const before = savedRef.current.lines.find(item => item.id === line.id);
        const merged = {...line.localizations};
        for (const [locale, localized] of Object.entries(fresh.localizations || {})) {
          if (same(line.localizations?.[locale], before?.localizations?.[locale])) merged[locale] = localized;
        }
        return {...line, asset_id:fresh.asset_id, translation:fresh.translation || line.translation, localizations:merged};
      }) };
      draftRef.current = next; setDraft(next);
    }
    savedRef.current = incoming;
  }, [project.script]);

  useEffect(() => {
    if (same(draft, savedRef.current)) return;
    const timer = window.setTimeout(() => { void persist(draft).catch((reason) => onError(errorText(reason))); }, 900);
    return () => window.clearTimeout(timer);
  }, [draft, persist, onError]);

  useEffect(() => {
    if (!active) return;
    function key(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault(); void persist(draftRef.current).catch((reason) => onError(errorText(reason)));
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [active, persist, onError]);

  useEffect(() => {
    let cancelled = false;
    setReferenceExists(null);
    if (selectedVoice?.reference_audio) void api.resolveResources(projectPath, [selectedVoice.reference_audio]).then(([resource]) => { if (!cancelled) setReferenceExists(resource?.exists ?? false); }).catch(() => { if (!cancelled) setReferenceExists(false); });
    return () => { cancelled = true; };
  }, [projectPath, selectedVoice?.reference_audio]);

  useEffect(() => {
    if (!active || draft.target_locales?.length || translationInFlight.current) return;
    const timer = window.setTimeout(async () => {
      const candidates = draftRef.current.lines.filter((line) => {
        if (!line.text.trim() || !line.enabled || line.language === "Auto") return false;
        const source = line.source_language && line.source_language !== "Auto" ? line.source_language : detectDialogueLanguage(line.text);
        if (source === line.language) return false;
        const translated = line.translation;
        if (translated?.source_text === line.text.trim() && translated.target_language === line.language && translated.text.trim()) return false;
        return !attemptedTranslations.current.has(JSON.stringify([line.id, line.text, line.source_language || "Auto", line.language]));
      });
      if (!candidates.length) return;
      translationInFlight.current = true;
      for (const line of candidates) {
        const key = JSON.stringify([line.id, line.text, line.source_language || "Auto", line.language]);
        attemptedTranslations.current.add(key);
        setTranslating((items) => [...items, line.id]);
        try {
          const result = await api.translate(line.text, line.source_language || "Auto", line.language);
          const current = draftRef.current.lines.find((item) => item.id === line.id);
          if (current && current.text === line.text && current.language === line.language && current.source_language === line.source_language) {
            update({ ...draftRef.current, lines: draftRef.current.lines.map((item) => item.id === line.id ? { ...item, translation: result.translation, asset_id: null } : item) });
            setTranslationErrors((errors) => { const next = { ...errors }; delete next[line.id]; return next; });
          }
        } catch (reason) { setTranslationErrors((errors) => ({ ...errors, [line.id]: errorText(reason) })); }
        finally { setTranslating((items) => items.filter((id) => id !== line.id)); }
      }
      translationInFlight.current = false;
      setTranslationRetry((value) => value + 1);
    }, 650);
    return () => window.clearTimeout(timer);
  }, [draft, active, translationRetry, update]);

  function retryTranslations() {
    attemptedTranslations.current.clear(); setTranslationErrors({}); setTranslationRetry((value) => value + 1);
  }

  const translationReady = models.some((model) => model.id === "m2m100-418M-int8" && model.installed);
  useEffect(() => { attemptedTranslations.current.clear(); setTranslationRetry((value) => value + 1); }, [translationReady]);

  function updateVoice(id: string, changes: Partial<VoiceProfile>) {
    const current = draftRef.current;
    if (voiceLocale && !("name" in changes)) {
      const profile = current.voices.find(voice => voice.id === id);
      if (!profile) return;
      const effective = profile.locale_overrides?.[voiceLocale] || voiceSettings(profile);
      const override = voiceSettings({...profile, ...effective, ...changes});
      update({...current, voices: current.voices.map(voice => voice.id === id ? {...voice, locale_overrides: {...voice.locale_overrides, [voiceLocale]: override}} : voice),
        lines: current.lines.map(line => line.voice_id === id && line.localizations?.[voiceLocale] ? {...line, localizations: {...line.localizations, [voiceLocale]: {...line.localizations[voiceLocale], asset_id: null, input_fingerprint: null}}} : line)});
      return;
    }
    update({ ...current, voices: current.voices.map((voice) => voice.id === id ? { ...voice, ...changes } : voice), lines: current.lines.map((line) => line.voice_id === id ? { ...line, character: changes.name ?? line.character, language: changes.language ?? line.language, translation: changes.language ? null : line.translation, asset_id: null, localizations:Object.fromEntries(Object.entries(line.localizations || {}).map(([locale,value])=>[locale, current.voices.find(voice=>voice.id===id)?.locale_overrides?.[locale] ? value : {...value,asset_id:null,input_fingerprint:null}])) } : line) });
  }
  function updateLine(id: string, changes: Partial<ScriptLine>) {
    const current = draftRef.current;
    update({ ...current, lines: current.lines.map((line) => line.id === id ? { ...line, ...changes, ...(("text" in changes || "language" in changes || "source_language" in changes || "instruct" in changes || "voice_id" in changes) ? { localizations:Object.fromEntries(Object.entries(line.localizations || {}).map(([locale,value])=>[locale,{...value,asset_id:null,input_fingerprint:null}])) } : {}), ...(("text" in changes || "language" in changes || "source_language" in changes) ? { translation: null } : {}), ...(!("enabled" in changes) ? { asset_id: null } : {}) } : line) });
  }
  function addVoice() {
    const current = draftRef.current;
    let name = "新角色"; let number = 2;
    while (current.voices.some((voice) => voice.name === name)) name = `新角色 ${number++}`;
    const voice = blankVoice(name);
    update({ ...current, voices: [...current.voices, voice] });
    setSelectedVoiceId(voice.id); setSideTab("voices");
  }
  function addLine() {
    const current = draftRef.current;
    const voice = current.voices.find((item) => item.id === selectedVoiceId) ?? current.voices[0];
    update({ ...current, lines: [...current.lines, { id: crypto.randomUUID(), character: voice?.name || "旁白", text: "", voice_id: voice?.id || null, language: voice?.language || "Chinese", instruct: "", enabled: true, asset_id: null, localizations: {} }] });
    setFilter("all"); setSearch("");
  }
  function moveLine(id: string, direction: number) {
    const lines = [...draftRef.current.lines];
    const from = lines.findIndex((line) => line.id === id); const to = from + direction;
    if (to < 0 || to >= lines.length) return;
    [lines[from], lines[to]] = [lines[to], lines[from]];
    update({ ...draftRef.current, lines });
  }
  async function generate(lineIds?: string[], options: {target_locales?: string[]; force?: boolean; text_only?: boolean} = {}) {
    if (submitting || busyJob) return;
    if (translationInFlight.current) { onError("正在翻译对白，请等待目标语种文本就绪后再生成"); return; }
    const snapshot = draftRef.current;
    const selected = snapshot.lines.filter((line) => line.enabled && (!lineIds || lineIds.includes(line.id)));
    const invalid = options.text_only || snapshot.target_locales?.length ? undefined : selected.find((line) => lineIssue(snapshot, line.id, models));
    if (invalid) { onError(`“${invalid.character}”：${lineIssue(snapshot, invalid.id, models)}`); return; }
    if (!selected.length) { onError("请先添加并启用台词"); return; }
    setSubmitting(true);
    try {
      await persist(snapshot);
      await api.generateSpeech({ project_path: projectPath, line_ids: lineIds ?? [], ...(snapshot.target_locales?.length ? {target_locales:snapshot.target_locales} : {}), ...options });
      onQueued(); setNotice(`已提交 ${selected.length} 句配音，完成后可在台词下方试听。`);
    } catch (reason) { onError(errorText(reason)); }
    finally { setSubmitting(false); }
  }
  async function copyPrompt(id: string) {
    try {
      const catalog = await api.agentTemplates();
      const template = catalog.find(item => item.id === (id === "script" && draftRef.current.target_locales?.length ? "multilingual" : id)) ?? catalog.find(item => item.id === id);
      if (!template) throw new Error("模板不存在");
      const context = id === "voices" && draftRef.current.voices.length ? `\n\n当前角色资料（作为待编辑数据，保留已有 ID）：\n${JSON.stringify({ type: "woosh.voices", version: 1, voices: draftRef.current.voices }, null, 2)}` : `\n\n项目名称：${project.name}；剧本标题：${draftRef.current.title}`;
      await navigator.clipboard.writeText(template.prompt + context + (id === "script" ? "\n输出语言配置：" + JSON.stringify({source_locale:draftRef.current.source_locale || "zh-CN",target_locales:draftRef.current.target_locales || []}) : ""));
      setNotice(`已复制${id === "voices" ? "角色" : "剧本"}提示词，粘贴给其他 AI 模型即可。`);
    } catch (reason) { onError(errorText(reason)); setAgentTab(id); }
  }
  async function copyCurrentScript() {
    try {
      const value = { type: "woosh.script", version: 2, ...draftRef.current, lines: draftRef.current.lines.map(({ asset_id: _asset, ...line }) => ({...line,localizations:Object.fromEntries(Object.entries(line.localizations || {}).map(([locale,value])=>[locale,{...value,asset_id:null,input_fingerprint:null}]))})) };
      await navigator.clipboard.writeText(JSON.stringify(value, null, 2));
      setNotice("已复制当前剧本 JSON，可交给 AI 修改后重新导入。");
    } catch (reason) { onError(errorText(reason)); }
  }
  async function resourceAction(path: string, copy = false) {
    try {
      if (copy) { await copyResourcePath(projectPath, path); setNotice("已复制文件完整路径"); }
      else await revealResource(projectPath, path);
    } catch (reason) { onError(errorText(reason)); }
  }
  function receiveResources(result: ResourceImportResult, bindVoiceId?: string) {
    onProjectChange(result.manifest);
    const allDocuments = [...documents, ...result.documents];
    const allMappings = [...mappings, ...result.mappings];
    setDocuments(allDocuments); setMappings(allMappings); setResourceWarnings(result.warnings);
    if (bindVoiceId && result.assets.length === 1) updateVoice(bindVoiceId, { mode: "clone", reference_audio: result.assets[0].relative_path });
    setNotice(`已导入 ${result.assets.length} 个音频、${result.documents.length} 份模板${result.warnings.length ? `，${result.warnings.length} 项需查看` : ""}。`);
    if (result.documents.length) setImportState({ documents: result.documents, mappings: allMappings });
    else if (!bindVoiceId) setSideTab("resources");
  }
  async function ingest(source: string[] | File[], bindVoiceId?: string) {
    if (importingRef.current || !source.length) return;
    importingRef.current = true; setImporting(true);
    try {
      const result = typeof source[0] === "string" ? await api.importResources(projectPath, source as string[]) : await api.uploadResources(projectPath, source as File[]);
      receiveResources(result, bindVoiceId);
    } catch (reason) { onError(errorText(reason)); }
    finally { importingRef.current = false; setImporting(false); setDragging(false); }
  }
  const ingestRef = useRef(ingest);
  ingestRef.current = ingest;
  useEffect(() => {
    if (!active || !("__TAURI_INTERNALS__" in window)) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void import("@tauri-apps/api/webviewWindow").then(async ({ getCurrentWebviewWindow }) => {
      const off = await getCurrentWebviewWindow().onDragDropEvent((event) => {
        if (disposed) return;
        if (event.payload.type === "drop") {
          setDragging(false);
          const position = event.payload.position;
          const target = document.elementFromPoint(position.x / window.devicePixelRatio, position.y / window.devicePixelRatio)?.closest<HTMLElement>("[data-reference-voice]");
          void ingestRef.current(event.payload.paths, target?.dataset.referenceVoice);
        } else setDragging(event.payload.type !== "leave");
      });
      if (disposed) off(); else unlisten = off;
    }).catch((reason) => onError(`拖拽监听失败：${errorText(reason)}`));
    return () => { disposed = true; unlisten?.(); };
  }, [active, onError]);

  async function pick(directory = false, bindVoiceId?: string) {
    if ("__TAURI_INTERNALS__" in window) {
      try {
        const { open } = await import("@tauri-apps/plugin-dialog");
        const paths = await open({ directory, multiple: !directory, title: directory ? "导入素材文件夹" : "导入模板或参考音频", ...(!directory ? { filters: [{ name: "模板与音频", extensions: ["json", "txt", "md", "wav", "flac", "mp3", "ogg", "aiff", "aif"] }] } : {}) });
        if (paths) await ingest(Array.isArray(paths) ? paths : [paths], bindVoiceId);
      } catch (reason) { onError(errorText(reason)); }
    } else {
      pickerBinding.current = bindVoiceId;
      (directory ? folderInput : fileInput).current?.click();
    }
  }
  async function drop(event: DragEvent<HTMLElement>) {
    event.preventDefault(); dragDepth.current = 0; setDragging(false);
    if ("__TAURI_INTERNALS__" in window) return;
    const target = (event.target as HTMLElement).closest<HTMLElement>("[data-reference-voice]");
    try { await ingest(await droppedFiles(event.dataTransfer), target?.dataset.referenceVoice); }
    catch (reason) { onError(errorText(reason)); }
  }
  function applyImport(preview: ScriptPreview, replace: boolean) {
    const next = mergeScript(draftRef.current, preview, replace);
    update(next, true); setSelectedVoiceId(next.voices[0]?.id || ""); setFilter("all"); setSearch(""); setSideTab("voices"); setImportState(null);
    setNotice(`已导入 ${preview.script.voices.length} 个角色、${preview.script.lines.length} 句台词，正在自动保存。`);
  }

  return <div className={`workspace speech-view ${dragging ? "is-dragging" : ""}`} onDragEnter={(event) => { if (event.dataTransfer.types.includes("Files")) { event.preventDefault(); dragDepth.current++; setDragging(true); } }} onDragLeave={() => { dragDepth.current--; if (dragDepth.current <= 0) setDragging(false); }} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }} onDrop={(event) => void drop(event)}>
    <input hidden ref={fileInput} type="file" multiple accept=".json,.txt,.md,.wav,.flac,.mp3,.ogg,.aiff,.aif" aria-label="选择导入文件" onChange={(event) => { void ingest(Array.from(event.target.files || []), pickerBinding.current); event.target.value = ""; }} />
    <input hidden ref={(element) => { folderInput.current = element; element?.setAttribute("webkitdirectory", ""); }} type="file" multiple aria-label="选择导入文件夹" onChange={(event) => { void ingest(Array.from(event.target.files || [])); event.target.value = ""; }} />
    <section className="speech-main">
      <header className="speech-header"><div><span className="eyebrow">SCRIPT WORKSPACE</span><h1>剧本工作台</h1><p>从 AI 剧本到角色配音，在这里完成。</p></div><div className="speech-header-actions"><button className="speech-save" onClick={() => void persist(draftRef.current).catch((reason) => onError(errorText(reason)))} title="保存剧本 · Ctrl+S"><Save size={14} />{saveStatus}</button><button className="primary-button" onClick={() => void generate()} disabled={submitting || busyJob || translating.length > 0 || !enabled.length}>{submitting || busyJob ? <Loader2 className="spin" size={16} /> : <WandSparkles size={16} />}{busyJob ? "配音生成中" : `生成 ${enabled.length} 句${multilingual ? " × " + targets.length + " 语言" : ""}配音`}</button></div></header>
      <div className="speech-ai-strip"><div><span className="ai-strip-icon"><WandSparkles size={19} /></span><span><strong>让 AI 帮你准备剧本</strong><small>复制提示词 → 交给 AI → 导入生成结果</small></span></div><div><button onClick={() => void copyPrompt("script")}><Copy size={14} />剧本提示词</button><button onClick={() => void copyPrompt("voices")}><Copy size={14} />角色提示词</button><button title="打开所有模板与 Skill 工作流" onClick={() => setAgentTab("script")}><BookOpen size={14} />模板中心</button></div></div>
      <div className="speech-project-row"><input aria-label="剧本标题" value={draft.title} onChange={(event) => update({ ...draftRef.current, title: event.target.value })} /><span>{draft.voices.length} 角色 · {draft.lines.length} 台词 · {generated.length} 已生成</span><button className="icon-button small" title="复制当前剧本 JSON" onClick={() => void copyCurrentScript()}><Copy size={15} /></button></div>
      <section className="localization-settings" aria-label="游戏多语言设置"><div><strong>输出语言</strong><label>原文语言<select aria-label="剧本原文语言" value={draft.source_locale || "zh-CN"} onChange={event => update({...draftRef.current, source_locale: event.target.value})}>{locales.map(([code,name]) => <option key={code} value={code}>{name}</option>)}</select></label></div><div className="locale-checkboxes">{locales.map(([code,name]) => <label key={code}><input type="checkbox" checked={targets.includes(code)} onChange={event => { const next = event.target.checked ? [...targets,code] : targets.filter(item => item !== code); if (!next.length) { onError("请至少保留一种输出语言"); return; } update({...draftRef.current,target_locales:next}); }}/>{name}</label>)}</div><div className="reference-tool-actions"><span className="muted">{enabled.length} 句 × {targets.length || 1} 语言 · 自动复用有效结果</span><button className="secondary-button" disabled={busyJob || submitting || !enabled.length} onClick={() => void generate(undefined, {text_only: true})}>准备多语言文本</button></div><details><summary>游戏术语表（提示与人工核对）</summary>{(draft.glossary || []).map((term,index) => <div className="glossary-row" key={index}><input aria-label={"术语原文 " + (index+1)} value={term.source} onChange={event => update({...draftRef.current, glossary: draftRef.current.glossary!.map((item,i) => i===index ? {...item,source:event.target.value} : item)})}/>{targets.map(locale => <input key={locale} aria-label={"术语 " + (index+1) + " " + localeName(locale)} placeholder={localeName(locale)} value={term.translations[locale] || ""} onChange={event => update({...draftRef.current, glossary: draftRef.current.glossary!.map((item,i) => i===index ? {...item,translations:{...item.translations,[locale]:event.target.value}} : item)})}/>)}<button className="text-button" onClick={() => update({...draftRef.current,glossary:draftRef.current.glossary!.filter((_,i)=>i!==index)})}>删除</button></div>)}<button className="text-button" onClick={() => update({...draftRef.current,glossary:[...(draftRef.current.glossary || []),{source:"新术语",translations:{},note:""}]})}>添加术语</button></details></section>
      <div className="speech-import-bar"><button className="secondary-button" disabled={importing} onClick={() => void pick()}><Upload size={15} />导入文件</button><button className="secondary-button" disabled={importing} onClick={() => void pick(true)}><FolderOpen size={15} />导入文件夹</button><button className="secondary-button" onClick={() => setImportState({})}><ClipboardPaste size={15} />粘贴 JSON</button><span>{importing ? "正在复制到项目…" : "也可拖入文件 / 文件夹"}</span>{undo && <button className="text-button" onClick={() => { update(undo); setUndo(null); setNotice("已撤销上一步操作"); }}><Undo2 size={14} />撤销</button>}</div>
      {notice && <div className="workbench-notice" role="status"><Check size={15} /><span>{notice}</span><button className="icon-button small" title="关闭提示" onClick={() => setNotice("")}><X size={13} /></button></div>}
      {resourceWarnings.length > 0 && <details className="workbench-warning"><summary>导入报告：{resourceWarnings.length} 项未导入或需要处理</summary>{resourceWarnings.map((warning, index) => <p key={index}>{warning}</p>)}</details>}
      {draft.lines.length > 0 ? <><div className="speech-list-toolbar"><label className="speech-search"><Search size={15} /><input aria-label="搜索台词" placeholder="搜索角色或台词…" value={search} onChange={(event) => setSearch(event.target.value)} /></label><select aria-label="筛选台词" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">全部台词</option><option value="issues">需要处理 ({problems.length})</option>{draft.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name}</option>)}</select><button className="text-button" onClick={addLine}><Plus size={15} />添加台词</button></div>
        {problems.length > 0 && <button className="speech-issues" onClick={() => setFilter("issues")}>{problems.length} 句台词需要处理角色、文本或模型配置<ChevronRight size={15} /></button>}
        <div className="script-lines">{visibleLines.map((line) => {
          const index = draft.lines.indexOf(line);
          const issue = line.enabled ? lineIssue(draft, line.id, models) : null;
          const versions = project.assets.filter((item) => item.kind === "voice_line" && (item.id === line.asset_id || item.music_metadata?.script_line_id === line.id));
          const asset = multilingual ? undefined : versions.find((item) => item.id === line.asset_id) ?? versions.at(-1);
          const stale = asset && asset.id !== line.asset_id;
          const sourceLanguage = line.source_language && line.source_language !== "Auto" ? line.source_language : detectDialogueLanguage(line.text);
          const needsTranslation = !multilingual && line.language !== "Auto" && sourceLanguage !== line.language;
          const translation = line.translation?.source_text === line.text.trim() && line.translation.target_language === line.language ? line.translation : null;
          return <article className={`script-line ${!line.enabled ? "disabled" : ""}`} key={line.id} aria-label={`台词 ${index + 1}`}>
            <div className="script-line-head"><span className="line-number">{String(index + 1).padStart(2, "0")}</span><select aria-label={`第 ${index + 1} 句角色`} value={line.voice_id || ""} onChange={(event) => { const voice = draft.voices.find((item) => item.id === event.target.value); updateLine(line.id, { voice_id: voice?.id || null, character: voice?.name || line.character, language: voice?.language || line.language }); }}><option value="">{line.character || "未绑定角色"} · 选择音色</option>{draft.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name}</option>)}</select><label className="line-enable"><input type="checkbox" checked={line.enabled} onChange={(event) => updateLine(line.id, { enabled: event.target.checked })} />启用</label><div className="line-tools"><button className="icon-button small" disabled={index === 0} title={`上移第 ${index + 1} 句`} onClick={() => moveLine(line.id, -1)}><ArrowUp size={14} /></button><button className="icon-button small" disabled={index === draft.lines.length - 1} title={`下移第 ${index + 1} 句`} onClick={() => moveLine(line.id, 1)}><ArrowDown size={14} /></button><button className="icon-button small" title={`删除第 ${index + 1} 句`} onClick={() => update({ ...draftRef.current, lines: draftRef.current.lines.filter((item) => item.id !== line.id) }, true)}><Trash2 size={14} /></button></div></div>
            <textarea aria-label={`第 ${index + 1} 句台词`} rows={2} placeholder="写下角色要说的话…" value={line.text} onChange={(event) => updateLine(line.id, { text: event.target.value })} />
            <div className="dialogue-language-row"><label>原文语言<select aria-label={`第 ${index + 1} 句原文语言`} value={line.source_language || "Auto"} onChange={(event) => updateLine(line.id, { source_language: event.target.value })}>{["Auto", ...languages.filter((language) => language !== "Auto")].map((language) => <option key={language} value={language}>{language === "Auto" ? "自动（汉字/假名/韩文/英文）" : language}</option>)}</select></label><span>{multilingual ? "输出：" + targets.map(localeName).join(" / ") : "配音：" + line.language + (needsTranslation ? " · 内置模型自动翻译" : " · 使用原文")}</span></div>
            {needsTranslation && <div className="dialogue-translation"><div><strong>{line.language} 配音文本</strong><button className="text-button" disabled={translating.includes(line.id)} onClick={retryTranslations}>{translating.includes(line.id) ? "正在翻译…" : "重新翻译"}</button></div>{translation ? <textarea aria-label={`第 ${index + 1} 句译文`} value={translation.text} onChange={(event) => updateLine(line.id, { translation: { ...translation, text: event.target.value, model_id: "manual" } })} /> : <p>{translating.includes(line.id) ? "正在使用内置模型生成对应语种文本…" : "等待本地翻译，原文保持不变"}</p>}{translationErrors[line.id] && <><p className="line-issue" role="alert">{translationErrors[line.id]}</p></>}</div>}
            <div className="script-line-foot"><input aria-label={`第 ${index + 1} 句情绪`} placeholder="本句情绪 / 表演指导（可选）" value={line.instruct} onChange={(event) => updateLine(line.id, { instruct: event.target.value })} />{!multilingual && <select aria-label={`第 ${index + 1} 句语言`} value={line.language} onChange={(event) => updateLine(line.id, { language: event.target.value })}>{languages.map((language) => <option key={language}>{language}</option>)}</select>}<button className="text-button" disabled={!line.enabled || submitting || busyJob} title="保存并生成这一句" onClick={() => void generate([line.id])}><Mic2 size={14} />{asset ? "重新生成" : "生成"}</button></div>
            {multilingual && <><div className="dialogue-game-keys"><input aria-label={"第 " + (index+1) + " 句游戏 key"} placeholder="游戏台词 key（可选）" value={line.key || ""} onChange={event => updateLine(line.id,{key:event.target.value})}/><input aria-label={"第 " + (index+1) + " 句场景"} placeholder="场景 ID（可选）" value={line.scene_id || ""} onChange={event => updateLine(line.id,{scene_id:event.target.value})}/></div><LocalizedLineEditor script={draft} line={line} index={index+1} project={project} projectPath={projectPath} disabled={busyJob || submitting} missingIds={missingIds} onChange={localizations => updateLine(line.id,{localizations})} onGenerate={(locale,force) => void generate([line.id],{target_locales:[locale],force})} onProjectChange={onProjectChange} onError={onError}/></>}
            {!multilingual && issue && <p className="line-issue">{issue}</p>}{asset && <div className="line-audio-result"><header><strong>{stale ? "上次配音 · 内容已修改" : "配音结果"}</strong><span>{asset.duration_seconds.toFixed(1)} 秒</span><AssetActions asset={asset} projectPath={projectPath} missing={missingIds.has(asset.id)} onProjectChange={onProjectChange} onError={onError} /></header><AudioPreview projectPath={projectPath} path={asset.relative_path} label={`第 ${index + 1} 句配音试听`} missing={missingIds.has(asset.id)} onError={onError} onMissing={() => void refreshHealth()} />{versions.length > 1 && <details><summary>历史配音（{versions.length - 1}）</summary>{versions.filter((item) => item.id !== asset.id).map((item) => <div key={item.id}><AudioPreview projectPath={projectPath} path={item.relative_path} label={item.name} missing={missingIds.has(item.id)} onError={onError} /><AssetActions asset={item} projectPath={projectPath} missing={missingIds.has(item.id)} onProjectChange={onProjectChange} onError={onError} /></div>)}</details>}</div>}

          </article>;
        })}</div>{!visibleLines.length && <p className="speech-no-results">没有匹配的台词，试试其他关键词或筛选条件。</p>}<button className="speech-add-line" onClick={addLine}><Plus size={16} />添加下一句台词</button>
      </> : <div className="speech-empty"><div className="speech-empty-art"><FileJson size={36} /><span><Mic2 size={19} /></span></div><h2>从一份剧本开始</h2><p>导入 AI 生成的剧本和角色，<br />或直接拖入素材文件夹，开始你的配音创作。</p><div><button className="primary-button" onClick={() => setImportState({})}><ClipboardPaste size={16} />导入 AI 剧本</button><button className="secondary-button" onClick={addLine}><Plus size={16} />手动写第一句</button></div><button className="text-button" onClick={() => setAgentTab("script")}>查看剧本示例与格式<ChevronRight size={14} /></button></div>}
    </section>
    <aside className="speech-inspector"><div className="speech-inspector-title"><Users size={18} /><h2>角色与素材</h2><button className="icon-button small" title="添加角色" onClick={addVoice}><Plus size={17} /></button></div><div className="workbench-tabs"><button className={sideTab === "voices" ? "active" : ""} onClick={() => setSideTab("voices")}>角色 {draft.voices.length}</button><button className={sideTab === "resources" ? "active" : ""} onClick={() => setSideTab("resources")}>素材 {audioAssets.length}</button></div>
      {sideTab === "voices" ? <><div className="voice-selector">{draft.voices.map((voice, index) => <button className={selectedVoice?.id === voice.id ? "active" : ""} key={voice.id} onClick={() => setSelectedVoiceId(voice.id)}><span className={`voice-avatar tone-${index % 4}`}>{voice.name.slice(0, 1) || "?"}</span><span><strong>{voice.name || "未命名角色"}</strong><small>{voice.mode === "clone" ? "参考音频克隆" : voice.speaker} · {draft.lines.filter((line) => line.voice_id === voice.id).length} 句</small></span><ChevronRight size={14} /></button>)}</div><button className="speech-add-role" onClick={addVoice}><Plus size={15} />添加角色</button>
      {selectedVoice ? <section className="voice-editor" key={selectedVoice.id}><div className="voice-editor-heading"><strong>角色设置</strong><button className="icon-button small" title="删除选中角色" onClick={() => { update({ ...draftRef.current, voices: draftRef.current.voices.filter((voice) => voice.id !== selectedVoice.id), lines: draftRef.current.lines.map((line) => line.voice_id === selectedVoice.id ? { ...line, voice_id: null, asset_id: null } : line) }, true); setNotice("已删除角色，相关台词已解除绑定。可撤销恢复。"); }}><Trash2 size={14} /></button></div><label className="field"><span>角色名称</span><input value={selectedVoice.name} onChange={(event) => updateVoice(selectedVoice.id, { name: event.target.value })} /></label>{multilingual && <><label className="field"><span>音色适用语言</span><select aria-label="编辑角色语言音色" value={voiceLocale} onChange={event => setVoiceLocale(event.target.value)}><option value="">默认音色（各语言共用）</option>{targets.map(locale => <option key={locale} value={locale}>{localeName(locale)}音色</option>)}</select></label>{voiceLocale && <div className="muted">{selectedProfile?.locale_overrides?.[voiceLocale] ? "该语言使用独立音色" : "继承默认音色，编辑后单独保存"}<button className="text-button" onClick={() => { const overrides = {...selectedProfile.locale_overrides}; delete overrides[voiceLocale]; update({...draftRef.current, voices: draftRef.current.voices.map(voice => voice.id === selectedProfile.id ? {...voice,locale_overrides:overrides} : voice)}); }}>恢复默认音色</button></div>}</> }<label className="field"><span>音色来源</span><select value={selectedVoice.mode} onChange={(event) => updateVoice(selectedVoice.id, { mode: event.target.value as VoiceProfile["mode"] })}><option value="custom_voice">内置固定音色</option><option value="clone">参考音频克隆</option></select></label>
        {selectedVoice.mode === "custom_voice" ? <label className="field"><span>内置音色</span><select value={selectedVoice.speaker || "Vivian"} onChange={(event) => updateVoice(selectedVoice.id, { speaker: event.target.value })}>{speakers.map((speaker) => <option key={speaker}>{speaker}</option>)}</select></label> : <div className="reference-editor" data-reference-voice={selectedVoice.id}><div className="reference-title"><Headphones size={16} /><strong>参考音频</strong><button className="text-button" disabled={importing} onClick={() => void pick(false, selectedVoice.id)}>选择文件</button><button className="text-button" disabled={importing} onClick={() => setFreesoundOpen(true)}>Freesound</button></div><p>建议使用 5–15 秒清晰人声。超过 15 秒时，使用前 10 秒提取声线，避免长上下文续说；短参考录音可同时参考语气。</p><select aria-label="从项目选择参考音频" value={audioAssets.some((asset) => asset.relative_path === selectedVoice.reference_audio) ? selectedVoice.reference_audio! : ""} onChange={(event) => updateVoice(selectedVoice.id, { reference_audio: event.target.value || null })}><option value="">选择已导入的音频…</option>{audioAssets.map((asset) => <option key={asset.id} value={asset.relative_path} disabled={missingIds.has(asset.id)}>{asset.name}{missingIds.has(asset.id) ? "（文件缺失）" : ""}</option>)}</select>{selectedVoice.reference_audio && <><div className="reference-path"><span title={selectedVoice.reference_audio}>{selectedVoice.reference_audio}</span><button className="icon-button small" title="定位参考音频" onClick={() => void resourceAction(selectedVoice.reference_audio!)}><FolderOpen size={15} /></button><button className="icon-button small" title="复制参考音频路径" onClick={() => void resourceAction(selectedVoice.reference_audio!, true)}><Copy size={14} /></button></div>{referenceExists === false ? <p className="line-issue">文件不存在，请重新选择参考音频</p> : !/^(?:[A-Za-z]:|[\\/])/.test(selectedVoice.reference_audio) && <audio controls preload="none" src={audioUrl(projectPath, selectedVoice.reference_audio)} aria-label="参考音频试听" />}</>}
        <ReferenceAudioTools active={active} key={selectedVoice.id + ":" + voiceLocale} projectPath={projectPath} referenceAudio={selectedVoice.reference_audio} referenceText={selectedVoice.reference_text} asrReady={models.some(model => model.id === "Whisper-large-v3-turbo" && model.installed)} onReference={path => updateVoice(selectedVoice.id,{reference_audio:path,reference_text:""})} onText={text => updateVoice(selectedVoice.id,{reference_text:text})} onProjectChange={onProjectChange} onError={onError}/><details><summary>手动填写路径</summary><input aria-label="参考音频路径" placeholder="项目相对路径或完整路径" value={selectedVoice.reference_audio || ""} onChange={(event) => updateVoice(selectedVoice.id, { reference_audio: event.target.value || null })} /></details><label className="field"><span>参考音频中的准确台词</span><textarea rows={3} placeholder="填写这段参考音频实际说出的内容" value={selectedVoice.reference_text} onChange={(event) => updateVoice(selectedVoice.id, { reference_text: event.target.value })} /></label></div>}
        {!multilingual && <label className="field"><span>角色语言（同步台词并自动翻译）</span><select value={selectedVoice.language} onChange={(event) => updateVoice(selectedVoice.id, { language: event.target.value })}>{languages.map((language) => <option key={language}>{language}</option>)}</select></label>}<label className="field"><span>角色语气 / 表演指导</span><textarea rows={3} placeholder="例如：低沉、克制，语速略慢" value={selectedVoice.instruct} onChange={(event) => updateVoice(selectedVoice.id, { instruct: event.target.value })} /></label><button className="text-button" onClick={() => void copyPrompt("voices")}><Copy size={14} />复制角色 Prompt 模板</button>
      </section> : <div className="voice-empty"><Users size={25} /><strong>先认识故事里的角色</strong><p>手动添加角色，或导入 AI 生成的角色音色模板。</p><button className="text-button" onClick={() => setImportState({})}>导入角色模板<ChevronRight size={14} /></button></div>}</> : <section className="speech-resources"><p>素材已保存在项目中，可用于角色参考音频。</p><button className="secondary-button" disabled={importing} onClick={() => void pick()}><Plus size={15} />导入素材</button><button className="secondary-button" disabled={importing} onClick={() => setFreesoundOpen(true)}><Headphones size={15} />Freesound 资源</button>{audioAssets.map((asset) => <article className="speech-resource" key={asset.id}><div><Headphones size={15} /><strong>{asset.name}</strong><span>{asset.duration_seconds.toFixed(1)}s</span></div><small title={asset.relative_path}>{asset.relative_path}</small><AudioPreview projectPath={projectPath} path={asset.relative_path} label={asset.name} missing={missingIds.has(asset.id)} onError={onError} onMissing={() => void refreshHealth()} /><AssetActions asset={asset} projectPath={projectPath} missing={missingIds.has(asset.id)} onProjectChange={onProjectChange} onError={onError} /><div>{selectedVoice && <button className="text-button" onClick={() => { updateVoice(selectedVoice.id, { mode: "clone", reference_audio: asset.relative_path }); setSideTab("voices"); }}>用作「{selectedVoice.name}」参考</button>}<button className="icon-button small" title={`定位 ${asset.name}`} onClick={() => void resourceAction(asset.relative_path)}><FolderOpen size={15} /></button><button className="icon-button small" title={`复制 ${asset.name} 路径`} onClick={() => void resourceAction(asset.relative_path, true)}><Copy size={14} /></button></div></article>)}{documents.length > 0 && <div className="speech-documents"><h3>本次导入的模板</h3>{documents.map((doc) => <div key={doc.relative_path}><button className="text-button" onClick={() => setImportState({ documents: [doc], mappings })}><FileJson size={14} />{doc.name}</button><button className="icon-button small" title={`定位 ${doc.name}`} onClick={() => void resourceAction(doc.relative_path)}><FolderOpen size={14} /></button></div>)}</div>}{!audioAssets.length && <div className="voice-empty"><Upload size={25} /><p>拖入音频或文件夹，<br />为角色准备参考素材。</p></div>}</section>}
      <button className="text-button" onClick={() => void api.openProject(projectPath).then(onProjectChange).then(refreshHealth).catch((reason) => onError(errorText(reason)))}>刷新配音与文件状态</button><div className="speech-model-state"><span className={models.some((model) => model.family === "speech" && model.installed) ? "ready-dot" : "pending-dot"} /><span>{models.some((model) => model.family === "speech" && model.installed) ? "本地语音模型已安装" : "前往「模型」安装语音模型"}</span></div>
    </aside>
    {dragging && <div className="speech-drop-overlay"><Upload size={34} /><strong>松开以导入文件或文件夹</strong><span>音频复制到项目 · 剧本 / 角色模板先预览</span></div>}
    {importState && <ScriptImportDialog initialText={importState.text} documents={importState.documents} mappings={importState.mappings} hasScript={draft.lines.length > 0 || draft.voices.length > 0} onClose={() => setImportState(null)} onImport={applyImport} />}
    {freesoundOpen && <FreesoundDialog projectPath={projectPath} onClose={() => setFreesoundOpen(false)} onImported={(manifest, relativePath) => { onProjectChange(manifest); if (selectedVoice) updateVoice(selectedVoice.id, { mode: "clone", reference_audio: relativePath }); setFreesoundOpen(false); setSideTab("voices"); setNotice("Freesound 参考音频已导入并绑定到当前角色。"); }} onError={onError} />}
    {agentTab && <AgentKitDialog initialTab={agentTab} onClose={() => setAgentTab(null)} onUseTemplate={(text) => { setAgentTab(null); setImportState({ text }); }} />}
  </div>;
}
