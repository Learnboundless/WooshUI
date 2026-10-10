import { api } from "./api";
import type { ModelDescriptor, ResourceMapping, ScriptDocument, ScriptPreview, VoiceProfile } from "./types";

export const languages = ["Chinese", "English", "Japanese", "Korean", "Auto", "German", "French", "Russian", "Portuguese", "Spanish", "Italian"];
export const speakers = ["Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ryan", "Aiden", "Ono_Anna", "Sohee"];
export const blankVoice = (name = "新角色"): VoiceProfile => ({ id: crypto.randomUUID(), name, mode: "custom_voice", language: "Chinese", speaker: "Vivian", instruct: "自然、清晰地说话", reference_audio: null, reference_text: "" });
export const emptyScript = (): ScriptDocument => ({ title: "项目剧本", voices: [], lines: [] });

export function mergeScript(current: ScriptDocument, preview: ScriptPreview, replace: boolean): ScriptDocument {
  const incoming = structuredClone(preview.script);
  incoming.lines = incoming.lines.map(line => ({...line, asset_id:null, localizations:Object.fromEntries(Object.entries(line.localizations || {}).map(([locale,value])=>[locale,{...value,asset_id:null,input_fingerprint:null}]))}));
  if (replace && preview.kind === "woosh.script") return incoming;
  const next = structuredClone(current);
  const idMap = new Map<string, string>();
  const changed = new Set<string>();
  for (const voice of incoming.voices) {
    // A role-only import updates matching roles. Appending a script preserves existing voices.
    const match = preview.kind === "woosh.voices" ? next.voices.find((item) => item.id === voice.id || item.name === voice.name) : undefined;
    const id = match?.id ?? (next.voices.some((item) => item.id === voice.id) ? crypto.randomUUID() : voice.id);
    idMap.set(voice.id, id);
    if (match) {
      next.voices = next.voices.map((item) => item.id === id ? { ...voice, id } : item);
      changed.add(id);
    } else {
      let name = voice.name;
      let suffix = 2;
      while (next.voices.some((item) => item.name === name)) name = `${voice.name} ${suffix++}`;
      next.voices.push({ ...voice, id, name });
    }
  }
  next.lines = next.lines.map((line) => changed.has(line.voice_id || "") ? { ...line, character: next.voices.find((voice) => voice.id === line.voice_id)!.name, asset_id: null, localizations:Object.fromEntries(Object.entries(line.localizations || {}).map(([locale,value])=>[locale,{...value,asset_id:null,input_fingerprint:null}])) } : line);
  for (const line of incoming.lines) {
    const voiceId = line.voice_id ? idMap.get(line.voice_id) ?? null : null;
    let gameKey = line.key || ""; let keySuffix = 2;
    while (gameKey && next.lines.some(item => item.key === gameKey)) gameKey = line.key + "." + keySuffix++;
    next.lines.push({ ...line, key:gameKey, id: next.lines.some((item) => item.id === line.id) ? crypto.randomUUID() : line.id, voice_id: voiceId, character: next.voices.find((voice) => voice.id === voiceId)?.name ?? line.character, asset_id: null });
  }
  if (preview.kind === "woosh.script") {
    next.target_locales = [...new Set([...(current.target_locales || []),...(incoming.target_locales || [])])];
    if (!current.lines.length) { next.title = incoming.title; next.source_locale = incoming.source_locale || current.source_locale; }
    next.glossary = [...(current.glossary || []), ...(incoming.glossary || []).filter(term => !(current.glossary || []).some(old => old.source === term.source))];
  }
  return next;
}

export function bindImportedReferences(preview: ScriptPreview, mappings: ResourceMapping[], documentPath?: string): ScriptPreview {
  const normalize = (path: string) => path.replaceAll("\\", "/").replace(/^\.\//, "");
  const script = structuredClone(preview.script);
  for (const profile of script.voices) {
    for (const voice of [profile, ...Object.values(profile.locale_overrides || {})]) {
    if (!voice.reference_audio) continue;
    const reference = normalize(voice.reference_audio);
    const doc = mappings.find((item) => item.relative_path === documentPath);
    const sibling = doc ? `${normalize(doc.source).split("/").slice(0, -1).join("/")}/${reference}`.replace(/^\//, "") : reference;
    const exact = mappings.filter((item) => [normalize(item.source), normalize(item.original_path), item.relative_path].some((value) => value === reference || value === sibling));
    const matches = exact.length ? exact : mappings.filter((item) => normalize(item.source).split("/").pop() === reference.split("/").pop());
    if (matches.length === 1) voice.reference_audio = matches[0].relative_path;
    }
  }
  return { ...preview, script };
}

export function lineIssue(script: ScriptDocument, lineId: string, models: ModelDescriptor[]): string | null {
  const line = script.lines.find((item) => item.id === lineId);
  if (!line) return "台词不存在";
  if (!line.text.trim()) return "请填写台词";
  const voice = script.voices.find((item) => item.id === line.voice_id);
  if (!voice) return "请选择角色音色";
  for (const locale of script.target_locales?.length ? script.target_locales : [""]) {
    const settings = {...voice,...voice.locale_overrides?.[locale]};
    const prefix = locale ? locale + "：" : "";
    if (settings.mode === "clone" && (!settings.reference_audio || !settings.reference_text.trim())) return prefix + "角色缺少参考音频或参考文本";
    const modelId = settings.mode === "clone" ? "Qwen3-TTS-Base-1.7B" : "Qwen3-TTS-CustomVoice-1.7B";
    if (!models.some(model=>model.id===modelId && model.installed)) return prefix + (settings.mode === "clone" ? "请安装克隆音色模型" : "请安装内置音色模型");
  }
  return null;
}

export async function revealResource(projectPath: string, path: string): Promise<void> {
  const [resource] = await api.resolveResources(projectPath, [path]);
  if (!resource?.exists) throw new Error(`文件不存在：${path}`);
  if (!("__TAURI_INTERNALS__" in window)) throw new Error(`请在文件管理器中打开：${resource.absolute_path}`);
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("reveal_in_explorer", { path: resource.absolute_path });
}

export async function copyResourcePath(projectPath: string, path: string): Promise<void> {
  const [resource] = await api.resolveResources(projectPath, [path]);
  await navigator.clipboard.writeText(resource.absolute_path);
}

export function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = name;
  document.body.append(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Browser folder drops require reading every chunk returned by the directory reader.
export async function droppedFiles(transfer: DataTransfer): Promise<File[]> {
  const result: File[] = [];
  async function visit(entry: FileSystemEntry, parent = ""): Promise<void> {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject));
      Object.defineProperty(file, "webkitRelativePath", { value: parent + file.name });
      result.push(file);
      if (result.length > 200) throw new Error("一次最多导入 200 个文件");
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      for (;;) {
        const entries = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
        if (!entries.length) break;
        for (const child of entries) await visit(child, parent + entry.name + "/");
      }
    }
  }
  const entries = Array.from(transfer.items || []).filter((item) => item.kind === "file").map((item) => item.webkitGetAsEntry?.());
  if (entries.some(Boolean)) {
    for (const entry of entries) if (entry) await visit(entry);
    return result;
  }
  return Array.from(transfer.files);
}

export function detectDialogueLanguage(text: string): string {
  if (/[\u3040-\u30ff]/.test(text)) return "Japanese";
  if (/[\uac00-\ud7af]/.test(text)) return "Korean";
  if (/[\u4e00-\u9fff]/.test(text)) return "Chinese";
  if (/[\u0400-\u04ff]/.test(text)) return "Russian";
  return "English";
}
