import type { LocalizedLine, ScriptDocument, ScriptLine, VoiceProfile, VoiceSettings } from "./types";

export const locales = [
  ["zh-CN", "中文", "Chinese"], ["en", "英语", "English"], ["ja", "日语", "Japanese"],
  ["ko", "韩语", "Korean"], ["de", "德语", "German"], ["fr", "法语", "French"],
  ["ru", "俄语", "Russian"], ["pt", "葡萄牙语", "Portuguese"], ["es", "西班牙语", "Spanish"], ["it", "意大利语", "Italian"],
] as const;
export const localeName = (code: string) => locales.find(([key]) => key === code)?.[1] || code;
export const engineLanguage = (code: string) => locales.find(([key]) => key === code)?.[2] || "Chinese";
export function sourceLanguage(script: ScriptDocument, line: ScriptLine) { return line.source_language && line.source_language !== "Auto" ? line.source_language : engineLanguage(script.source_locale || "zh-CN"); }
export function currentText(script: ScriptDocument, line: ScriptLine, localized?: LocalizedLine) { return Boolean(localized?.text.trim() && localized.source_text === line.text.trim() && localized.source_language === sourceLanguage(script, line) && localized.review_status !== "stale"); }
export function voiceSettings(voice: VoiceProfile): VoiceSettings { return {mode: voice.mode, speaker: voice.speaker, instruct: voice.instruct, reference_audio: voice.reference_audio, reference_text: voice.reference_text}; }
export const blankLocalization = (script: ScriptDocument, line: ScriptLine): LocalizedLine => ({text: "", spoken_text: "", source_text: line.text.trim(), source_language: sourceLanguage(script,line), source_revision: line.source_revision || 1, model_id: "manual", locked: false, review_status: "draft", asset_id: null, input_fingerprint: null});
