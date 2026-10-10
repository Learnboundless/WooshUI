from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from .runtime import sha256


def prepare_runtime(python_root: Path, cache_root: Path, output: Path, version: str) -> dict:
    python_root = python_root.resolve()
    cache_root = cache_root.resolve()
    output = output.resolve()
    if not (python_root / "Scripts" / "python.exe").is_file() and not list(python_root.rglob("python.exe")):
        raise FileNotFoundError("Python 3.12 runtime not found")
    if not cache_root.is_dir():
        raise FileNotFoundError(f"uv cache not found: {cache_root}")
    staging = output.parent / f".{output.name}.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        shutil.copytree(python_root, staging / "python")
        shutil.copytree(cache_root, staging / "uv-cache")
        critical = []
        interpreter = next((path for path in (staging / "python").rglob("python.exe")), None)
        if interpreter:
            critical.append(interpreter)
        for candidate in (staging / "python" / "pyvenv.cfg", staging / "uv-cache"):
            if candidate.is_file():
                critical.append(candidate)
        files = []
        root = staging
        for path in critical:
            if path.is_file():
                files.append({"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256(path)})
        manifest = {"version": version, "format": 1, "files": files}
        (staging / "runtime-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if output.exists():
            shutil.rmtree(output)
        staging.replace(output)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Woosh offline Python runtime")
    parser.add_argument("python_root", type=Path)
    parser.add_argument("cache_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--version", default="0.2.0")
    args = parser.parse_args()
    print(json.dumps(prepare_runtime(args.python_root, args.cache_root, args.output, args.version), ensure_ascii=False))


if __name__ == "__main__":
    main()
