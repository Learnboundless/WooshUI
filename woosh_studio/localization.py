from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from .languages import LOCALES, locale_for
from .schemas import LocalizedLine, VoiceSettings


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def source_language(script, line):
    return line.source_language if line.source_language != "Auto" else LOCALES[script.source_locale][0]


def effective_voice(voice, locale):
    return voice.locale_overrides.get(locale) or VoiceSettings.model_validate(
        voice.model_dump(include=set(VoiceSettings.model_fields))
    )


def text_current(script, line, localized):
    return bool(localized and localized.text.strip() and localized.source_text == line.text.strip()
                and localized.source_language == source_language(script, line)
                and localized.review_status != "stale")


def prepare_text(script, line, locale, translator):
    language = LOCALES[locale][0]
    source = source_language(script, line)
    old = line.localizations.get(locale)
    if text_current(script, line, old):
        return old
    if old and old.locked:
        raise ValueError(f"{line.character} · {locale} 译文已锁定且源文已变更，请核对后确认译文")
    legacy = line.translation
    if legacy and legacy.source_text == line.text.strip() and legacy.target_language == language:
        text, model = legacy.text, legacy.model_id
    elif source == language:
        text, model = line.text.strip(), "identity"
    elif translator:
        result = translator.translate(line.text, source, language)
        text, model = result["text"], result["model_id"]
    else:
        raise ValueError("翻译服务尚未配置")
    if not text.strip():
        raise ValueError("译文不能为空")
    # Placeholders are content, not instructions. Never silently drop runtime variables.
    def placeholders(value):
        return sorted(re.findall(r"\{[^{}]+\}|%\d*\$?[sd]|<[^<>]+>", value))
    if placeholders(text) != placeholders(line.text):
        raise ValueError(f"{locale} 译文的变量或富文本标记不一致，请手动修正")
    return LocalizedLine(text=text, spoken_text="", source_text=line.text.strip(), source_language=source,
                         source_revision=line.source_revision, model_id=model)


def speech_fingerprint(script, line, locale, localized, voice, model_version, reference_hash=""):
    return digest({"source_text": line.text.strip(), "source_language": source_language(script, line),
                   "spoken_text": (localized.spoken_text or localized.text).strip(), "locale": locale,
                   "voice": voice.model_dump(), "instruct": line.instruct or voice.instruct,
                   "reference_hash": reference_hash, "model_revision": model_version})


def edit_signature(line):
    return digest(line.model_dump(exclude={"asset_id", "translation", "localizations"}))


def migrate_project(data):
    data = deepcopy(data)
    data["schema_version"] = 3
    script = data.setdefault("script", {"title": "项目剧本", "voices": [], "lines": []})
    script.setdefault("source_locale", "zh-CN")
    targets = []
    for line in script.get("lines", []):
        language = line.get("language", "Chinese")
        try:
            locale = locale_for(language)
        except ValueError:
            continue
        if locale not in targets:
            targets.append(locale)
        translation = line.get("translation")
        source = line.get("source_language", "Auto")
        # Old Auto detection and unversioned audio are kept, but need review before export.
        source_known = source != "Auto"
        source = source if source_known else LOCALES[script["source_locale"]][0]
        valid_translation = translation and translation.get("source_text") == line.get("text", "").strip() and translation.get("target_language") == language
        text = translation["text"] if valid_translation else line.get("text", "") if source == language else ""
        line.setdefault("localizations", {}).setdefault(locale, {
            "text": text, "source_text": line.get("text", "").strip(), "source_language": source,
            "model_id": translation.get("model_id", "legacy") if valid_translation else "legacy",
            "asset_id": line.get("asset_id"), "review_status": "draft" if source_known and text else "stale",
        })
    script.setdefault("target_locales", targets or ["zh-CN"])
    return data


def normalize_edits(previous, incoming):
    """Invalidate only affected locales; keep manual translations and all historical assets."""
    old_lines = {line.id: line for line in previous.lines}
    old_voices = {voice.id: voice for voice in previous.voices}
    voices = {voice.id: voice for voice in incoming.voices}
    for line in incoming.lines:
        old = old_lines.get(line.id)
        if not old:
            continue
        source_changed = (line.text.strip(), source_language(incoming, line)) != (old.text.strip(), source_language(previous, old))
        line.source_revision = old.source_revision + int(source_changed)
        for locale, localized in line.localizations.items():
            prior = old.localizations.get(locale)
            if localized.source_text != line.text.strip() or localized.source_language != source_language(incoming, line):
                localized.review_status = "stale"
            changed = source_changed or line.instruct != old.instruct or line.voice_id != old.voice_id
            if prior and (localized.spoken_text or localized.text) != (prior.spoken_text or prior.text):
                changed = True
            current_voice, old_voice = voices.get(line.voice_id), old_voices.get(old.voice_id)
            if current_voice and old_voice:
                changed |= effective_voice(current_voice, locale) != effective_voice(old_voice, locale)
            else:
                changed = True
            if changed:
                localized.asset_id = None
                localized.input_fingerprint = None
            elif prior and not localized.asset_id and prior.input_fingerprint and localized.model_dump(exclude={"asset_id", "input_fingerprint"}) == prior.model_dump(exclude={"asset_id", "input_fingerprint"}):
                localized.asset_id, localized.input_fingerprint = prior.asset_id, prior.input_fingerprint
