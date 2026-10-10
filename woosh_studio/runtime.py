from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .schemas import RuntimeStatus

OFFLINE_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "MODELSCOPE_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
}


def runtime_status() -> RuntimeStatus:
    manifest_value = os.environ.get("WOOSH_STUDIO_RUNTIME_MANIFEST", "").strip()
    manifest = Path(manifest_value) if manifest_value else None
    valid, version = verify_runtime_manifest(manifest) if manifest else (False, None)
    bundled = os.environ.get("WOOSH_STUDIO_BUNDLED_RUNTIME") == "1"
    offline = os.environ.get("WOOSH_STUDIO_OFFLINE") == "1" or bundled
    return RuntimeStatus(
        offline=offline,
        source="bundled" if bundled else "managed",
        ready=valid or not bundled,
        version=version,
    )


def verify_runtime_manifest(path: Path | None) -> tuple[bool, str | None]:
    if path is None or not path.is_file():
        return False, None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        root = path.parent
        for item in data.get("files", []):
            relative = Path(str(item["path"]))
            target = (root / relative).resolve()
            if target != root.resolve() and root.resolve() not in target.parents:
                return False, None
            if not target.is_file() or target.stat().st_size != int(item["size_bytes"]):
                return False, None
            if str(item.get("sha256", "")) and sha256(target) != str(item["sha256"]):
                return False, None
        return True, str(data.get("version")) if data.get("version") else None
    except (OSError, ValueError, KeyError, TypeError):
        return False, None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def validate_music_bundle(root: Path) -> None:
    required = (
        root / "HeartMuLa-oss-3B-happy-new-year" / "config.json",
        root / "HeartCodec-oss" / "config.json",
        root / "tokenizer.json",
        root / "gen_config.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    for directory in (root / "HeartMuLa-oss-3B-happy-new-year", root / "HeartCodec-oss"):
        if not any(directory.glob("model-*.safetensors")) and not (directory / "model.safetensors").is_file():
            missing.append(str(directory / "model-*.safetensors"))
    if missing:
        raise RuntimeError("HeartMuLa 本地模型包不完整: " + ", ".join(missing))


def apply_offline_environment(environment: dict[str, str]) -> None:
    environment.update(OFFLINE_ENVIRONMENT)
    environment.setdefault("HF_HOME", str(Path(environment.get("WOOSH_MODEL_HOME", ".")) / ".huggingface"))
    environment.setdefault("MODELSCOPE_CACHE", str(Path(environment.get("WOOSH_MODEL_HOME", ".")) / ".modelscope"))
