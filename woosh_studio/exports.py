from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import soundfile as sf

from .audio import AudioRenderService
from .projects import ProjectService, safe_name
from .schemas import ExportRequest, GeneratedAsset


FORMAT_SETTINGS = {
    "wav24": ("WAV", "PCM_24", ".wav"),
    "wav16": ("WAV", "PCM_16", ".wav"),
    "flac": ("FLAC", "PCM_24", ".flac"),
    "ogg": ("OGG", "VORBIS", ".ogg"),
}


class ExportService:
    def __init__(self, projects: ProjectService, renderer: AudioRenderService, models=None):
        self.projects = projects
        self.renderer = renderer
        self.models = models

    def export(self, request: ExportRequest) -> dict[str, Any]:
        root = Path(request.project_path).expanduser().resolve()
        manifest = self.projects.open(root)
        assets = [asset for asset in manifest.assets if asset.id in request.asset_ids]
        export_name = safe_name(f"{manifest.name}_export")
        export_root = root / "Exports" / export_name
        counter = 2
        while export_root.exists():
            export_root = root / "Exports" / f"{export_name}_{counter}"
            counter += 1
        audio_root = export_root / "Audio"
        audio_root.mkdir(parents=True)
        records: list[dict[str, Any]] = []
        for index, asset in enumerate(assets, start=1):
            records.append(
                self._export_asset(root, audio_root, asset, request, index)
            )
        if request.timeline is not None:
            audio = self.renderer.render_timeline(root, request.timeline)
            timeline_asset_ids = {
                clip.asset_id
                for track in request.timeline.tracks
                for clip in track.clips
            }
            timeline_models = sorted(
                {
                    asset.model_id
                    for asset in manifest.assets
                    if asset.id in timeline_asset_ids and asset.model_id
                }
            )
            filename = self._format_name(
                request.preset.naming_template,
                request.preset.category,
                "mixdown",
                len(records) + 1,
            )
            output_path = self._write_audio(
                audio_root / filename, audio.T, request.preset.format, request.timeline.sample_rate
            )
            records.append(
                {
                    "id": "timeline-mixdown",
                    "name": output_path.stem,
                    "path": output_path.relative_to(export_root).as_posix(),
                    "source": "timeline",
                    "sample_rate": request.timeline.sample_rate,
                    "model_ids": timeline_models,
                    "loop": {
                        "start_seconds": request.timeline.loop_start_seconds,
                        "end_seconds": request.timeline.loop_end_seconds,
                    },
                }
            )
        package_manifest = {
            "schema_version": 2,
            "project": manifest.name,
            "generator": "Woosh Studio",
            "licenses": self._licenses(records),
            "assets": records,
        }
        (export_root / "manifest.json").write_text(
            json.dumps(package_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        license_lines = [
            f"{item['component']}: {item['license']}\n{item['url']}"
            for item in package_manifest["licenses"]
        ]
        (export_root / "LICENSES.txt").write_text(
            "\n\n".join(license_lines) + "\n", encoding="utf-8"
        )
        if request.preset.package == "wwise_fmod":
            self._write_wwise(export_root, records)
            self._write_fmod(export_root, records)
            archive = shutil.make_archive(str(export_root), "zip", export_root)
            return {"directory": str(export_root), "archive": archive, "assets": records}
        return {"directory": str(export_root), "assets": records}

    def export_localization(self, request):
        from .localization import effective_voice, file_digest, speech_fingerprint, text_current, digest
        from .model_runtime import model_revision
        root = Path(request.project_path).expanduser().resolve()
        manifest = self.projects.open(root)
        locales = request.target_locales or manifest.script.target_locales
        if not locales:
            raise ValueError("请先选择剧本输出语言")
        voices = {voice.id: voice for voice in manifest.script.voices}
        assets = {asset.id: asset for asset in manifest.assets}
        records, errors = [], []
        for line in manifest.script.lines:
            if not line.enabled:
                continue
            for locale in locales:
                localized = line.localizations.get(locale)
                valid_text = text_current(manifest.script, line, localized)
                asset = assets.get(localized.asset_id) if localized else None
                audio = None
                status = "missing_text" if localized is None or not localized.text.strip() else "stale_text" if not valid_text else "missing_audio"
                if valid_text and asset and line.voice_id in voices:
                    metadata = asset.music_metadata or {}
                    voice = effective_voice(voices[line.voice_id], locale)
                    reference = Path(voice.reference_audio).expanduser() if voice.reference_audio else None
                    if reference and not reference.is_absolute():
                        reference = self.projects.resolve_project_file(root, voice.reference_audio)
                    reference_hash = file_digest(reference) if reference and reference.is_file() else ""
                    version = model_revision(self.models.model_path(asset.model_id)) if self.models and asset.model_id and self.models.is_installed(asset.model_id) else metadata.get("model_revision", "")
                    fingerprint = speech_fingerprint(manifest.script, line, locale, localized, voice, version, reference_hash)
                    source = self.projects.resolve_project_file(root, asset.relative_path)
                    if localized.input_fingerprint == fingerprint and metadata.get("input_fingerprint") == fingerprint and source.is_file() and metadata.get("audio_sha256") == file_digest(source):
                        audio, status = source, "ready"
                    else:
                        status = "stale_audio"
                if request.require_approved and localized and localized.review_status != "approved":
                    status = "needs_review"
                if request.mode == "complete" and status != "ready":
                    errors.append(f"{line.key or line.id} · {locale}: {status}")
                if request.mode == "text" and (not valid_text or request.require_approved and localized.review_status != "approved"):
                    errors.append(f"{line.key or line.id} · {locale}: 文本未就绪或未审核")
                records.append({"line_id": line.id, "key": line.key, "scene_id": line.scene_id,
                    "character_id": line.voice_id or "", "locale": locale,
                    "text": localized.text if localized else "", "spoken_text": (localized.spoken_text or localized.text) if localized else "",
                    "audio_path": "", "duration_ms": 0, "status": status,
                    "source_revision": line.source_revision, "_source": audio, "_asset": asset})
        if not records:
            raise ValueError("剧本中没有启用台词")
        if errors:
            raise ValueError("多语言交付检查未通过：" + "；".join(errors[:12]))
        export_root = root / "Exports" / (safe_name(manifest.name) + "_localization")
        counter = 2
        while export_root.exists():
            export_root = root / "Exports" / f"{safe_name(manifest.name)}_localization_{counter}"
            counter += 1
        export_root.mkdir(parents=True)
        licenses = []
        for record in records:
            source, asset = record.pop("_source"), record.pop("_asset")
            if request.mode == "complete" and source:
                audio, sr = sf.read(source, always_2d=True, dtype="float32")
                directory = export_root / "audio" / record["locale"]
                directory.mkdir(parents=True, exist_ok=True)
                filename = safe_name(record["line_id"]).replace(".", "_")[:100] + "_" + digest(record["line_id"])[:10]
                target = self._write_audio(directory / filename, audio, request.format, sr)
                record.update(audio_path=target.relative_to(export_root).as_posix(), duration_ms=round(len(audio) / sr * 1000), sample_rate=sr)
                licenses.append({"model_id": asset.model_id})
        text_root = export_root / "text"
        text_root.mkdir()
        for locale in locales:
            localized_records = {record["line_id"]: record for record in records if record["locale"] == locale}
            (text_root / f"{locale}.json").write_text(json.dumps(localized_records, ensure_ascii=False, indent=2), encoding="utf-8")
        fields = ["line_id", "key", "scene_id", "character_id", "locale", "text", "spoken_text", "audio_path", "duration_ms", "status", "source_revision"]
        with (export_root / "dialogue.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        package = {"schema_version": 1, "project_id": manifest.id, "locales": locales, "fallback_locale": None,
                   "mode": request.mode, "lines": records, "licenses": self._licenses(licenses)}
        (export_root / "manifest.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"directory": str(export_root), "line_count": len(records), "locales": locales}

    def _export_asset(
        self,
        root: Path,
        audio_root: Path,
        asset: GeneratedAsset,
        request: ExportRequest,
        variant: int,
    ) -> dict[str, Any]:
        source = self.projects.resolve_project_file(root, asset.relative_path)
        audio, sample_rate = sf.read(source, always_2d=True, dtype="float32")
        filename = self._format_name(
            request.preset.naming_template,
            request.preset.category,
            asset.name,
            variant,
        )
        output = self._write_audio(
            audio_root / filename, audio, request.preset.format, sample_rate
        )
        return {
            "id": asset.id,
            "name": output.stem,
            "path": output.relative_to(audio_root.parent).as_posix(),
            "source": asset.source,
            "model_id": asset.model_id,
            "seed": asset.seed,
            "prompt_original": asset.prompt_original,
            "prompt_conditioned": asset.prompt_conditioned,
            "sample_rate": sample_rate,
            "kind": asset.kind,
            "stem_role": asset.stem_role,
            "generation_group_id": asset.generation_group_id,
            "parent_asset_id": asset.parent_asset_id,
            "music_metadata": asset.music_metadata,
        }

    @staticmethod
    def _licenses(records: list[dict[str, Any]]) -> list[dict[str, str]]:
        models = {record.get("model_id") for record in records}
        models.update(
            model
            for record in records
            for model in record.get("model_ids", [])
        )
        licenses: list[dict[str, str]] = []
        if any(model and str(model).startswith("Woosh") for model in models):
            licenses.append(
                {
                    "component": "Sony Woosh model weights",
                    "license": "CC BY-NC 4.0",
                    "usage": "Research and non-commercial use only",
                    "url": "https://creativecommons.org/licenses/by-nc/4.0/",
                }
            )
        if "HeartMuLa-3B" in models:
            licenses.append(
                {
                    "component": "HeartMuLa and HeartCodec",
                    "license": "Apache 2.0",
                    "usage": "See license terms",
                    "url": "https://www.apache.org/licenses/LICENSE-2.0",
                }
            )
        if any(model and str(model).startswith("Qwen3-TTS") for model in models):
            licenses.append(
                {
                    "component": "Qwen3-TTS speech models",
                    "license": "Apache 2.0",
                    "usage": "See license terms",
                    "url": "https://www.apache.org/licenses/LICENSE-2.0",
                }
            )
        if "Demucs-htdemucs" in models:
            licenses.append(
                {
                    "component": "Demucs htdemucs",
                    "license": "MIT",
                    "usage": "Post-processed source separation",
                    "url": "https://github.com/facebookresearch/demucs/blob/main/LICENSE",
                }
            )
        return licenses

    @staticmethod
    def _write_audio(
        path_without_suffix: Path,
        audio,
        format_key: str,
        sample_rate: int,
    ) -> Path:
        format_name, subtype, suffix = FORMAT_SETTINGS[format_key]
        target = path_without_suffix.with_suffix(suffix)
        sf.write(target, audio, sample_rate, format=format_name, subtype=subtype)
        return target

    @staticmethod
    def _format_name(template: str, category: str, name: str, variant: int) -> str:
        try:
            rendered = template.format(
                category=safe_name(category), name=safe_name(name), variant=variant
            )
        except (KeyError, ValueError) as error:
            raise ValueError("导出命名模板只能使用 category、name 和 variant") from error
        return safe_name(rendered)

    @staticmethod
    def _write_wwise(root: Path, records: list[dict[str, Any]]) -> None:
        directory = root / "Wwise"
        directory.mkdir()
        with (directory / "wwise_import.tsv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["Audio File", "Object Path", "Object Type", "Notes"])
            for record in records:
                is_music = record.get("kind") in {"music_mix", "stem"}
                hierarchy = (
                    "\\Interactive Music Hierarchy\\Default Work Unit\\Music"
                    if is_music
                    else "\\Actor-Mixer Hierarchy\\Default Work Unit\\SFX"
                )
                writer.writerow(
                    [
                        f"../{record['path']}",
                        f"{hierarchy}\\{record['name']}",
                        "Music Track" if is_music else "Sound SFX",
                        record.get("prompt_conditioned") or "",
                    ]
                )

    @staticmethod
    def _write_fmod(root: Path, records: list[dict[str, Any]]) -> None:
        directory = root / "FMOD"
        directory.mkdir()
        (directory / "fmod_manifest.json").write_text(
            json.dumps({"assets": records}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (directory / "README.txt").write_text(
            "Copy Audio into the FMOD Studio project's Assets folder, then use "
            "fmod_manifest.json to preserve names, prompts, seeds, and model metadata.\n"
            "Woosh Studio does not build .bank files.\n",
            encoding="utf-8",
        )
