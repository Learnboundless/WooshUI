from __future__ import annotations

import re
import shutil
from pathlib import Path
from threading import RLock
from typing import Callable

import soundfile as sf

from .schemas import GeneratedAsset, ProjectManifestV3, utc_now
from .storage import AtomicJsonStore, LibraryDatabase


MANIFEST_NAME = "project.woosh.json"
PROJECT_DIRECTORIES = ("Sources", "Generated", "Renders", "Exports", ".cache")


def safe_name(value: str) -> str:
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value.strip())
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    return normalized or "Untitled"


class ProjectService:
    def __init__(self, database: LibraryDatabase):
        self.database = database
        self._mutation_lock = RLock()

    def create(
        self, parent: Path, name: str, description: str = ""
    ) -> tuple[Path, ProjectManifestV3]:
        parent = parent.expanduser().resolve()
        parent.mkdir(parents=True, exist_ok=True)
        root = parent / f"{safe_name(name)}.woosh"
        if root.exists():
            raise FileExistsError(f"项目目录已存在: {root}")
        root.mkdir()
        for directory in PROJECT_DIRECTORIES:
            (root / directory).mkdir()
        manifest = ProjectManifestV3(name=safe_name(name), description=description)
        manifest.script.target_locales = ["zh-CN"]
        self._write(root, manifest)
        self.database.remember_project(root, manifest.name)
        return root, manifest

    def open(self, root: Path) -> ProjectManifestV3:
        with self._mutation_lock:
            root = root.expanduser().resolve()
            manifest_path = root / MANIFEST_NAME
            data = AtomicJsonStore.read(manifest_path)
            if data.get("schema_version", 1) == 1:
                backup = manifest_path.with_suffix(".v1.bak")
                if not backup.exists():
                    shutil.copy2(manifest_path, backup)
                data = self._migrate_v1(data)
                AtomicJsonStore.write(manifest_path, data)
            if data.get("schema_version") == 2:
                from .localization import migrate_project

                backup = manifest_path.with_suffix(".v2.bak")
                if not backup.exists():
                    shutil.copy2(manifest_path, backup)
                data = migrate_project(data)
                AtomicJsonStore.write(manifest_path, data)
            manifest = ProjectManifestV3.model_validate(data)
            if any(
                asset.kind == "sfx" and not asset.generation_group_id
                for asset in manifest.assets
            ):
                assets = {asset.id: asset for asset in manifest.assets}
                changed = False
                for batch_id, ids in self.database.sfx_batches(root):
                    family = [
                        assets[id]
                        for id in ids
                        if id in assets and assets[id].kind == "sfx"
                    ]
                    for index, asset in enumerate(family):
                        if not asset.generation_group_id:
                            asset.generation_group_id = batch_id
                            if index and not asset.parent_asset_id:
                                asset.parent_asset_id = family[0].id
                            changed = True
                if changed:
                    self._write(root, manifest)
            self.database.remember_project(root, manifest.name)
            return manifest

    def save(self, root: Path, manifest: ProjectManifestV3) -> ProjectManifestV3:
        root = root.expanduser().resolve()
        if not (root / MANIFEST_NAME).exists():
            raise FileNotFoundError(f"不是 Woosh Studio 项目: {root}")
        if manifest.schema_version == 2:
            from .localization import migrate_project

            manifest = ProjectManifestV3.model_validate(
                migrate_project(manifest.model_dump(mode="json"))
            )
        updated = manifest.model_copy(update={"updated_at": utc_now()})
        self._write(root, updated)
        self.database.remember_project(root, updated.name)
        return updated

    def mutate(
        self, root: Path, update: Callable[[ProjectManifestV3], None]
    ) -> ProjectManifestV3:
        """Apply a partial update to the latest manifest, shared by asynchronous workflows."""
        with self._mutation_lock:
            manifest = self.open(root)
            update(manifest)
            return self.save(root, manifest)

    def import_asset(
        self, root: Path, source: Path
    ) -> tuple[ProjectManifestV3, GeneratedAsset]:
        root = root.expanduser().resolve()
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        manifest = self.open(root)
        destination = self._unique_path(root / "Sources", safe_name(source.name))
        shutil.copy2(source, destination)
        sample_rate = manifest.sample_rate
        channel_count = 1
        duration_seconds = 0.0
        try:
            info = sf.info(destination)
            sample_rate = info.samplerate
            channel_count = info.channels
            duration_seconds = info.duration
        except RuntimeError:
            pass
        asset = GeneratedAsset(
            name=destination.stem,
            relative_path=destination.relative_to(root).as_posix(),
            source="imported",
            kind="imported",
            sample_rate=sample_rate,
            channel_count=channel_count,
            duration_seconds=duration_seconds,
        )
        manifest.assets.append(asset)
        manifest = self.save(root, manifest)
        return manifest, asset

    def asset_health(self, root: Path) -> dict:
        manifest = self.open(root)

        def inspect(value: str) -> dict:
            try:
                path = self.resolve_project_file(root, value)
                exists = path.is_file()
                return {
                    "path": value,
                    "exists": exists,
                    "absolute_path": str(path),
                    "reason": "" if exists else "文件不存在或已移动",
                }
            except (OSError, ValueError) as error:
                return {
                    "path": value,
                    "exists": False,
                    "absolute_path": None,
                    "reason": str(error),
                }

        paths = {asset.relative_path for asset in manifest.assets}
        paths.update(
            clip.source_path
            for track in manifest.timeline.tracks
            for clip in track.clips
        )
        files = {value: inspect(value) for value in paths}
        return {
            "assets": [
                {"asset_id": asset.id, **files[asset.relative_path]}
                for asset in manifest.assets
            ],
            "files": list(files.values()),
        }

    def remove_assets(self, root: Path, asset_ids: list[str]) -> ProjectManifestV3:
        selected = set(asset_ids)

        def remove(manifest):
            paths = {
                asset.relative_path for asset in manifest.assets if asset.id in selected
            }
            manifest.assets = [
                asset for asset in manifest.assets if asset.id not in selected
            ]
            for track in manifest.timeline.tracks:
                track.clips = [
                    clip for clip in track.clips if clip.asset_id not in selected
                ]
            for line in manifest.script.lines:
                for localized in line.localizations.values():
                    if localized.asset_id in selected:
                        localized.asset_id = None
                        localized.input_fingerprint = None
                if line.asset_id in selected:
                    line.asset_id = None
            remaining = {asset.relative_path for asset in manifest.assets}
            for voice in manifest.script.voices:
                for settings in (voice, *voice.locale_overrides.values()):
                    if settings.reference_audio in paths - remaining:
                        settings.reference_audio = None

        # Remove project entries and bindings; source files stay on disk.
        return self.mutate(root, remove)

    def relink_asset(
        self, root: Path, asset_id: str, source: Path
    ) -> ProjectManifestV3:
        root = root.expanduser().resolve()
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"替换音频不存在：{source}")
        info = sf.info(source)
        if info.frames <= 0:
            raise ValueError("音频为空")

        def relink(manifest):
            asset = next(
                (item for item in manifest.assets if item.id == asset_id), None
            )
            if asset is None:
                raise ValueError("素材已被移除")
            old_path = asset.relative_path
            if root in source.parents:
                destination = source
            else:
                destination = self._unique_path(
                    root / "Sources", safe_name(source.name)
                )
                shutil.copy2(source, destination)
            asset.relative_path = destination.relative_to(root).as_posix()
            asset.sample_rate = info.samplerate
            asset.channel_count = info.channels
            asset.duration_seconds = info.duration
            for track in manifest.timeline.tracks:
                for clip in track.clips:
                    if clip.asset_id == asset_id:
                        clip.source_path = asset.relative_path
                        clip.trim_start_seconds = min(
                            clip.trim_start_seconds, max(0, info.duration - 0.01)
                        )
                        if clip.trim_end_seconds is not None:
                            clip.trim_end_seconds = min(
                                clip.trim_end_seconds, info.duration
                            )
            for voice in manifest.script.voices:
                for settings in (voice, *voice.locale_overrides.values()):
                    if settings.reference_audio == old_path:
                        settings.reference_audio = asset.relative_path

        return self.mutate(root, relink)

    @staticmethod
    def resolve_project_file(root: Path, relative_path: str) -> Path:
        root = root.expanduser().resolve()
        candidate = (root / relative_path).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("项目文件路径越界")
        return candidate

    @staticmethod
    def _unique_path(directory: Path, filename: str) -> Path:
        candidate = directory / filename
        counter = 2
        while candidate.exists():
            candidate = (
                directory / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
            )
            counter += 1
        return candidate

    @staticmethod
    def _write(root: Path, manifest: ProjectManifestV3) -> None:
        AtomicJsonStore.write(
            root / MANIFEST_NAME,
            manifest.model_dump(mode="json"),
        )

    @staticmethod
    def _migrate_v1(data: dict) -> dict:
        migrated = dict(data)
        migrated["schema_version"] = 2
        migrated.pop("generation_mode", None)
        assets = []
        for raw_asset in migrated.get("assets", []):
            asset = dict(raw_asset)
            if "kind" not in asset:
                asset["kind"] = (
                    "imported" if asset.get("source") == "imported" else "sfx"
                )
            asset.setdefault("channel_count", 1)
            assets.append(asset)
        migrated["assets"] = assets
        tracks = migrated.get("timeline", {}).get("tracks", [])
        for track in tracks:
            track.setdefault("role", "generic")
        return migrated
