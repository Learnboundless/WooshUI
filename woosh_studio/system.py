from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

from .config import StudioPaths
from .schemas import DevicePreference, RuntimeSettings, SystemCapabilities
from .storage import LibraryDatabase


def torch_capabilities() -> tuple[bool, str | None, int | None]:
    try:
        import torch

        if not torch.cuda.is_available():
            return False, None, None
        properties = torch.cuda.get_device_properties(0)
        return True, properties.name, properties.total_memory
    except (ImportError, RuntimeError):
        return False, None, None


class SystemService:
    def __init__(self, paths: StudioPaths, database: LibraryDatabase):
        self.paths = paths
        self.database = database

    def capabilities(self) -> SystemCapabilities:
        settings = self.database.get_settings()
        cuda_available, cuda_name, cuda_memory = torch_capabilities()
        effective = self.resolve_device(settings.device, cuda_available)
        model_root = (
            Path(settings.model_root).expanduser().resolve()
            if settings.model_root
            else self.paths.models
        )
        model_root.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(model_root)
        return SystemCapabilities(
            platform=platform.platform(),
            python_version=sys.version.split()[0],
            cuda_available=cuda_available,
            cuda_device_name=cuda_name,
            cuda_memory_bytes=cuda_memory,
            effective_device=effective,
            disk_free_bytes=disk.free,
            model_root=str(model_root),
            settings=settings,
        )

    def update_settings(self, settings: RuntimeSettings) -> RuntimeSettings:
        cuda_available, _, _ = torch_capabilities()
        self.resolve_device(settings.device, cuda_available)
        if settings.model_root:
            model_root = Path(settings.model_root).expanduser().resolve()
            if platform.system() == "Windows" and model_root.drive.lower() == "c:":
                raise RuntimeError("共享模型目录不能位于 C 盘")
            model_root.mkdir(parents=True, exist_ok=True)
            persist_model_home(model_root)
            settings = settings.model_copy(update={"model_root": str(model_root)})
        self.database.save_settings(settings)
        return settings

    @staticmethod
    def resolve_device(
        preference: DevicePreference, cuda_available: bool
    ) -> str:
        if preference == DevicePreference.CUDA and not cuda_available:
            raise RuntimeError("当前运行环境未检测到可用 CUDA 设备")
        if preference == DevicePreference.CUDA:
            return "cuda"
        if preference == DevicePreference.AUTO and cuda_available:
            return "cuda"
        return "cpu"


def persist_model_home(path: Path) -> None:
    os.environ["WOOSH_MODEL_HOME"] = str(path)
    if platform.system() != "Windows":
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        winreg.SetValueEx(
            key,
            "WOOSH_MODEL_HOME",
            0,
            winreg.REG_SZ,
            str(path),
        )
