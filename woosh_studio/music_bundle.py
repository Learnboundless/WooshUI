from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .models import DEMUCS_FILE, HEARTMULA_FILES


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def prepare_payload(model_root: Path, output: Path) -> dict[str, Any]:
    model_root = model_root.expanduser().resolve()
    if model_root.drive.lower() == "c:":
        raise RuntimeError(f"模型目录不能位于 C 盘: {model_root}")
    payload = output / "Payload"
    records: list[dict[str, Any]] = []
    for definition in HEARTMULA_FILES:
        relative = Path("HeartMuLa") / str(definition["path"])
        source = model_root / relative
        if not source.is_file() or source.stat().st_size != int(definition["size"]):
            raise RuntimeError(f"HeartMuLa 模型文件缺失或大小无效: {source}")
        actual_digest = digest(source)
        expected = definition.get("sha256")
        if expected and actual_digest != expected:
            raise RuntimeError(f"HeartMuLa 模型文件哈希无效: {source}")
        link_or_copy(source, payload / relative)
        records.append(
            {
                "component": "music",
                "path": relative.as_posix(),
                "size": source.stat().st_size,
                "sha256": expected or actual_digest,
            }
        )

    demucs_relative = Path("Demucs-htdemucs") / str(DEMUCS_FILE["name"])
    demucs_source = model_root / demucs_relative
    if (
        not demucs_source.is_file()
        or demucs_source.stat().st_size != int(DEMUCS_FILE["size"])
    ):
        raise RuntimeError(f"Demucs 模型文件缺失或大小无效: {demucs_source}")
    demucs_digest = digest(demucs_source)
    if demucs_digest != str(DEMUCS_FILE["sha256"]):
        raise RuntimeError(f"Demucs 模型文件哈希无效: {demucs_source}")
    link_or_copy(demucs_source, payload / demucs_relative)
    records.append(
        {
            "component": "demucs",
            "path": demucs_relative.as_posix(),
            "size": demucs_source.stat().st_size,
            "sha256": demucs_digest,
        }
    )
    manifest = {
        "schema_version": 1,
        "product": "Woosh Studio HeartMuLa Models",
        "model_root_environment": "WOOSH_MODEL_HOME",
        "files": records,
    }
    (output / "model-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_root", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    manifest = prepare_payload(arguments.model_root, arguments.output)
    print(f"Prepared {len(manifest['files'])} files in {arguments.output}")


if __name__ == "__main__":
    main()
