from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "Woosh Studio"


def default_home() -> Path:
    configured = os.environ.get("WOOSH_STUDIO_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    return Path.home() / ".woosh-studio"


def default_model_home(app_home: Path) -> Path:
    configured = (
        os.environ.get("WOOSH_MODEL_HOME")
        or os.environ.get("AI_MODELS_HOME")
        or os.environ.get("HF_HOME")
    )
    if configured:
        root = Path(configured).expanduser().resolve()
        if os.environ.get("WOOSH_MODEL_HOME"):
            return root
        return root / "WooshStudio"
    return app_home / "models"


@dataclass(frozen=True)
class StudioPaths:
    home: Path
    model_home: Path | None = None

    @classmethod
    def from_environment(cls) -> "StudioPaths":
        home = default_home()
        return cls(home, default_model_home(home))

    @property
    def database(self) -> Path:
        return self.home / "library.sqlite3"

    @property
    def models(self) -> Path:
        return self.model_home or self.home / "models"

    @property
    def downloads(self) -> Path:
        return self.models / ".downloads"

    @property
    def runtime(self) -> Path:
        return self.home / "runtime"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    def ensure(self) -> "StudioPaths":
        for path in (
            self.home,
            self.models,
            self.downloads,
            self.runtime,
            self.logs,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self
