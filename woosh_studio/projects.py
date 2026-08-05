from __future__ import annotations

import re
import shutil
from pathlib import Path

import soundfile as sf

from .schemas import GeneratedAsset, ProjectManifestV2, utc_now
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

    def create(
        self, parent: Path, name: str, description: str = ""
    ) -> tuple[Path, ProjectManifestV2]:
        parent = parent.expanduser().resolve()
        parent.mkdir(parents=True, exist_ok=True)
        root = parent / f"{safe_name(name)}.woosh"
        if root.exists():
            raise FileExistsError(f"项目目录已存在: {root}")
        root.mkdir()
        for directory in PROJECT_DIRECTORIES:
            (root / directory).mkdir()
        manifest = ProjectManifestV2(name=safe_name(name), description=description)
        self._write(root, manifest)
        self.database.remember_project(root, manifest.name)
        return root, manifest

    def open(self, root: Path) -> ProjectManifestV2:
        root = root.expanduser().resolve()
        manifest_path = root / MANIFEST_NAME
        data = AtomicJsonStore.read(manifest_path)
        if data.get("schema_version", 1) == 1:
            data = self._migrate_v1(data)
            AtomicJsonStore.write(manifest_path, data)
        manifest = ProjectManifestV2.model_validate(data)
        self.database.remember_project(root, manifest.name)
        return manifest

    def save(self, root: Path, manifest: ProjectManifestV2) -> ProjectManifestV2:
        root = root.expanduser().resolve()
        if not (root / MANIFEST_NAME).exists():
            raise FileNotFoundError(f"不是 Woosh Studio 项目: {root}")
        updated = manifest.model_copy(update={"updated_at": utc_now()})
        self._write(root, updated)
        self.database.remember_project(root, updated.name)
        return updated

    def import_asset(
        self, root: Path, source: Path
    ) -> tuple[ProjectManifestV2, GeneratedAsset]:
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
            candidate = directory / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
            counter += 1
        return candidate

    @staticmethod
    def _write(root: Path, manifest: ProjectManifestV2) -> None:
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
