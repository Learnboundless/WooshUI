from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from uuid import uuid4

import soundfile as sf
from pydantic import ValidationError

from .projects import ProjectService, safe_name
from .schemas import GeneratedAsset, ScriptDocument

WORKFLOW_ROOT = Path(__file__).parent / "agent_workflow" / "woosh-studio"
AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg", ".aiff", ".aif"}
DOCUMENT_EXTENSIONS = {".json", ".md", ".txt"}
MAX_FILES = 200
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_AUDIO_BYTES = 200 * 1024 * 1024
MAX_BATCH_BYTES = 1024 * 1024 * 1024
SPEAKERS = {
    "Vivian",
    "Serena",
    "Uncle_Fu",
    "Dylan",
    "Eric",
    "Ryan",
    "Aiden",
    "Ono_Anna",
    "Sohee",
}
LANGUAGES = {
    "Auto",
    "Chinese",
    "English",
    "Japanese",
    "Korean",
    "German",
    "French",
    "Russian",
    "Portuguese",
    "Spanish",
    "Italian",
}


def parse_script(text: str) -> dict:
    """Validate AI output as data. Never execute embedded instructions or paths."""
    if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError("模板不能超过 2 MB")
    text = text.strip().lstrip("\ufeff")
    fence = re.fullmatch(
        r"```(?:json)?\s*\n?(.*?)\n?```", text, flags=re.DOTALL | re.IGNORECASE
    )
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"JSON 格式错误：第 {error.lineno} 行，第 {error.colno} 列。请粘贴完整 JSON 或 JSON 代码块。"
        ) from error
    if not isinstance(data, dict):
        raise ValueError("模板必须是一个 JSON 对象")
    data = dict(data)
    kind = data.pop("type", "woosh.script")
    version = data.pop("version", 1)
    if (
        kind not in {"woosh.script", "woosh.voices"}
        or type(version) is not int
        or version not in {1, 2}
    ):
        raise ValueError("仅支持 version: 1 或 2 的 woosh.script / woosh.voices 模板")
    if kind == "woosh.voices" and data.get("lines"):
        raise ValueError("角色模板不能包含台词，请使用 woosh.script")
    if not isinstance(data.get("voices", []), list) or not isinstance(
        data.get("lines", []), list
    ):
        raise ValueError("voices 和 lines 必须是数组")
    if len(data.get("voices", [])) > 100 or len(data.get("lines", [])) > 2000:
        raise ValueError("单次最多导入 100 个角色、2000 句台词")
    # AI templates do not carry generated asset references across projects.
    for line in data.get("lines", []):
        if isinstance(line, dict):
            line["asset_id"] = None
            if not isinstance(line.get("localizations", {}), dict):
                raise ValueError("localizations 必须是按语言索引的对象")
            for localized in line.get("localizations", {}).values():
                if isinstance(localized, dict):
                    localized["asset_id"] = None
                    localized["input_fingerprint"] = None
    try:
        script = ScriptDocument.model_validate(data)
    except ValidationError as error:
        issues = [
            f"{'.'.join(map(str, item['loc']))}：{item['msg']}"
            for item in error.errors()[:5]
        ]
        raise ValueError("模板字段有误：" + "；".join(issues)) from error
    if not script.voices and not script.lines:
        raise ValueError("模板中没有角色或台词")
    if not script.title.strip():
        script.title = "导入剧本"
    voice_ids: set[str] = set()
    names: dict[str, str] = {}
    for voice in script.voices:
        voice.name = voice.name.strip()
        if not voice.name or not voice.id.strip():
            raise ValueError("角色名称和 ID 不能为空")
        if voice.id in voice_ids or voice.name in names:
            raise ValueError(f"角色 ID 或名称重复：{voice.name}")
        if voice.language not in LANGUAGES:
            raise ValueError(f"角色“{voice.name}”的语言不受支持：{voice.language}")
        if voice.mode == "custom_voice" and voice.speaker not in SPEAKERS:
            raise ValueError(f"角色“{voice.name}”需要有效的内置音色 speaker")
        voice_ids.add(voice.id)
        names[voice.name] = voice.id
    line_ids: set[str] = set()
    warnings: list[str] = []
    for index, line in enumerate(script.lines, start=1):
        if not line.id.strip() or line.id in line_ids:
            raise ValueError(f"第 {index} 句的 ID 为空或重复")
        line_ids.add(line.id)
        if not line.text.strip() or not line.character.strip():
            raise ValueError(f"第 {index} 句的角色或台词为空")
        if line.language not in LANGUAGES:
            raise ValueError(f"第 {index} 句的语言不受支持：{line.language}")
        if not line.voice_id:
            line.voice_id = names.get(line.character)
        if line.voice_id and line.voice_id not in voice_ids:
            raise ValueError(f"第 {index} 句引用了不存在的角色 ID：{line.voice_id}")
        if not line.voice_id:
            warnings.append(f"第 {index} 句“{line.character}”尚未绑定角色")
    return {
        "kind": kind,
        "script": script.model_dump(mode="json"),
        "warnings": warnings,
    }


def workflow_catalog() -> list[dict]:
    return json.loads(
        (WORKFLOW_ROOT / "assets" / "templates.json").read_text(encoding="utf-8")
    )


def workflow_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(WORKFLOW_ROOT.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(
                    path,
                    (Path("woosh-studio") / path.relative_to(WORKFLOW_ROOT)).as_posix(),
                )
    return output.getvalue()


def collect_paths(paths: list[str]) -> tuple[list[tuple[Path, str]], list[str]]:
    files: list[tuple[Path, str]] = []
    warnings: list[str] = []
    seen: set[Path] = set()
    skipped = 0
    for raw in paths:
        source = Path(raw).expanduser()
        if source.is_symlink():
            warnings.append(f"跳过符号链接：{source.name}")
            continue
        source = source.resolve()
        if not source.exists():
            warnings.append(f"路径不存在：{source}")
            continue
        candidates = source.rglob("*") if source.is_dir() else [source]
        for item in candidates:
            if item.is_symlink() or not item.is_file() or item.resolve() in seen:
                continue
            seen.add(item.resolve())
            if item.suffix.lower() not in AUDIO_EXTENSIONS | DOCUMENT_EXTENSIONS:
                skipped += 1
                continue
            name = (
                (Path(source.name) / item.relative_to(source)).as_posix()
                if source.is_dir()
                else source.name
            )
            files.append((item, name))
            if len(files) > MAX_FILES:
                raise ValueError("一次最多导入 200 个音频或模板文件，请拆分文件夹")
    if skipped:
        warnings.append(
            f"跳过 {skipped} 个不支持的文件；支持音频和 JSON / TXT / Markdown 模板"
        )
    if not files and not warnings:
        warnings.append("没有找到支持的音频或模板文件")
    return files, warnings


def import_resources(
    projects: ProjectService,
    root: Path,
    files: list[tuple[Path, str]],
    warnings: list[str] | None = None,
) -> dict:
    root = root.expanduser().resolve()
    manifest = projects.open(root)
    warnings = list(warnings or [])
    if (
        len(files) > MAX_FILES
        or sum(source.stat().st_size for source, _ in files) > MAX_BATCH_BYTES
    ):
        raise ValueError("单次导入上限为 200 个文件 / 1 GB")
    batch = root / "Sources" / "Imports" / uuid4().hex[:12]
    assets: list[GeneratedAsset] = []
    documents: list[dict] = []
    mappings: list[dict] = []
    for source, name in files:
        extension = source.suffix.lower()
        if extension not in AUDIO_EXTENSIONS | DOCUMENT_EXTENSIONS:
            warnings.append(f"不支持的文件类型：{name}")
            continue
        limit = MAX_AUDIO_BYTES if extension in AUDIO_EXTENSIONS else MAX_DOCUMENT_BYTES
        if source.stat().st_size > limit:
            warnings.append(f"文件过大，已跳过：{name}")
            continue
        try:
            if extension in AUDIO_EXTENSIONS:
                info = sf.info(source)
                if info.frames <= 0 or not 1 <= info.channels <= 16:
                    raise ValueError("音频为空或声道数不受支持")
                text = None
            else:
                text = source.read_text(encoding="utf-8-sig")
            # Preserve nested folder structure, while preventing traversal from upload names.
            parts = [
                safe_name(part)
                for part in name.replace("\\", "/").split("/")
                if part not in {"", ".", ".."}
            ]
            destination = batch.joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination = projects._unique_path(destination.parent, destination.name)
            shutil.copy2(source, destination)
            relative = destination.relative_to(root).as_posix()
            mappings.append(
                {
                    "source": name.replace("\\", "/"),
                    "original_path": str(source),
                    "relative_path": relative,
                }
            )
            if text is not None:
                documents.append(
                    {"name": name, "relative_path": relative, "text": text}
                )
            else:
                asset = GeneratedAsset(
                    name=destination.stem,
                    relative_path=relative,
                    source="imported",
                    kind="imported",
                    sample_rate=info.samplerate,
                    channel_count=info.channels,
                    duration_seconds=info.duration,
                )
                assets.append(asset)
        except (OSError, RuntimeError, ValueError, UnicodeError) as error:
            warnings.append(f"{name}：{error}")
    if assets:
        manifest = projects.mutate(root, lambda latest: latest.assets.extend(assets))
    else:
        manifest = projects.open(root)
    return {
        "manifest": manifest,
        "assets": assets,
        "documents": documents,
        "mappings": mappings,
        "warnings": warnings,
    }
