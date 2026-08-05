from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

from .models import install_checkpoint_archive


OFFLINE_ASSETS = (
    "Woosh-DFlow.zip",
    "Woosh-Flow.zip",
    "Woosh-AE.zip",
    "TextConditionerA.zip",
)
RELEASE_URL = "https://github.com/SonyResearch/Woosh/releases/tag/v1.0.0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def prepare_offline_models(archive_directory: Path, output: Path) -> None:
    output = output.resolve()
    staging = output.parent / f".{output.name}-{uuid4().hex}.tmp"
    staging.mkdir(parents=True)
    try:
        assets = []
        for asset in OFFLINE_ASSETS:
            archive = archive_directory / asset
            if not archive.is_file():
                raise FileNotFoundError(archive)
            install_checkpoint_archive(archive, staging / Path(asset).stem)
            assets.append(
                {
                    "asset": asset,
                    "size_bytes": archive.stat().st_size,
                    "sha256": sha256(archive),
                }
            )
        (staging / "model-manifest.json").write_text(
            json.dumps(
                {
                    "release": "v1.0.0",
                    "source": RELEASE_URL,
                    "license": "CC BY-NC 4.0",
                    "assets": assets,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if output.exists():
            shutil.rmtree(output)
        staging.replace(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare verified Woosh offline model resources")
    parser.add_argument("archive_directory", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    prepare_offline_models(arguments.archive_directory, arguments.output)


if __name__ == "__main__":
    main()
