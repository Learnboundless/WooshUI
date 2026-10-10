import { useState } from "react";
import { localeName, blankLocalization, currentText, sourceLanguage } from "../localization";
import type { LocalizedLine, ProjectManifest, ScriptDocument, ScriptLine } from "../types";
import { AudioPreview } from "./AudioPreview";
import { AssetActions } from "./AssetActions";

interface Props {
  script: ScriptDocument; line: ScriptLine; index: number; project: ProjectManifest; projectPath: string;
  disabled: boolean; missingIds: Set<string>; onChange: (values: Record<string,LocalizedLine>) => void;
  onGenerate: (locale: string, force: boolean) => void; onProjectChange: (value: ProjectManifest) => void; onError: (value: string) => void;
}
export function LocalizedLineEditor(props: Props) {
  const [selected, setSelected] = useState(props.script.target_locales?.[0] || "zh-CN");
  const targets = props.script.target_locales || [];
  const locale = targets.includes(selected) ? selected : targets[0];
  if (!locale) return null;
  const local = props.line.localizations?.[locale] || blankLocalization(props.script, props.line);
  const current = currentText(props.script, props.line, local);
  const versions = props.project.assets.filter(asset => asset.kind === "voice_line" && asset.music_metadata?.script_line_id === props.line.id && asset.music_metadata?.locale === locale);
  const asset = versions.find(item => item.id === local.asset_id);
  function edit(changes: Partial<LocalizedLine>) {
    const next = {...local, ...changes};
    if ("text" in changes || "spoken_text" in changes) {
      if (!current) { next.source_text = props.line.text.trim(); next.source_language = sourceLanguage(props.script, props.line); }
      next.source_revision = props.line.source_revision || 1;
      next.model_id = "manual"; next.review_status = "draft";
      if ((next.spoken_text || next.text) !== (local.spoken_text || local.text)) { next.asset_id = null; next.input_fingerprint = null; }
    }
    props.onChange({...props.line.localizations, [locale]: next});
  }
  return <section className="localized-line-editor" aria-label={"第 " + props.index + " 句多语言版本"}>
    <div className="locale-tabs" role="tablist" aria-label="台词语言版本">{targets.map(code => <button role="tab" aria-selected={code === locale} className={code === locale ? "active" : ""} key={code} onClick={() => setSelected(code)}>{localeName(code)}<span>{props.line.localizations?.[code]?.asset_id ? "●" : "○"}</span></button>)}</div>
    <div className="localized-line-heading"><strong>{localeName(locale)}文本与配音</strong><span className={current ? "muted" : "line-issue"}>{!local.text ? "等待翻译" : !current ? "源文已变更 · 需核对" : asset ? "已有配音" : "等待配音"}</span></div>
    <label className="field"><span>显示文本 / 字幕</span><textarea aria-label={"第 " + props.index + " 句 " + localeName(locale) + " 文本"} value={local.text} onChange={event => edit({text: event.target.value})} placeholder="准备文本后可编辑译文"/></label>
    <label className="field"><span>实际朗读文本（留空时使用显示文本）</span><textarea aria-label={"第 " + props.index + " 句 " + localeName(locale) + " 朗读文本"} rows={2} value={local.spoken_text} onChange={event => edit({spoken_text: event.target.value})} placeholder="为变量、数字或专有名词填写实际读法"/></label>
    <div className="localized-line-controls"><label><input type="checkbox" checked={local.locked} onChange={event => edit({locked: event.target.checked})}/>锁定译文</label><label><input type="checkbox" checked={local.review_status === "approved" && current} disabled={!local.text.trim()} onChange={event => edit({review_status: event.target.checked ? "approved" : "draft", source_text: props.line.text.trim(), source_language: sourceLanguage(props.script, props.line), source_revision: props.line.source_revision || 1})}/>已核对当前原文</label><button className="secondary-button" disabled={props.disabled || !props.line.enabled} onClick={() => props.onGenerate(locale, Boolean(asset))}>{asset ? "重新生成" : "生成"}{localeName(locale)}配音</button></div>
    {props.script.glossary?.filter(term => props.line.text.includes(term.source)).map(term => <p className="muted" key={term.source}>术语提示：{term.source} → {term.translations[locale] || "待补充"}{term.note ? " · " + term.note : ""}</p>)}
    {asset && <div className="line-audio-result"><header><strong>{localeName(locale)}配音 · {asset.duration_seconds.toFixed(1)} 秒</strong><AssetActions asset={asset} projectPath={props.projectPath} missing={props.missingIds.has(asset.id)} onProjectChange={props.onProjectChange} onError={props.onError}/></header><AudioPreview projectPath={props.projectPath} path={asset.relative_path} label={"第 " + props.index + " 句 " + localeName(locale) + " 配音试听"} missing={props.missingIds.has(asset.id)} onError={props.onError}/></div>}
    {versions.filter(item => item.id !== asset?.id).length > 0 && <details><summary>{localeName(locale)}历史配音</summary>{versions.filter(item => item.id !== asset?.id).map(item => <AudioPreview key={item.id} projectPath={props.projectPath} path={item.relative_path} label={item.name} missing={props.missingIds.has(item.id)} onError={props.onError}/>)}</details>}
  </section>;
}
