from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path


ASSETS = ("Woosh-DFlow.zip", "Woosh-Flow.zip", "Woosh-AE.zip", "TextConditionerA.zip")
PACKAGE_ROOT = "Woosh-Studio-0.2.0-models-offline"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Woosh Studio offline ZIP64 distribution")
    parser.add_argument("--standard-installer", type=Path, required=True)
    parser.add_argument("--archive-directory", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--license", type=Path, required=True)
    parser.add_argument("--install-script", type=Path, required=True)
    parser.add_argument("--install-command", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    files = [
        (arguments.standard_installer, "Woosh-Studio-0.2.0-standard.exe"),
        (arguments.model_manifest, "model-manifest.json"),
        (arguments.license, "MODEL_LICENSES.md"),
        (arguments.install_script, "Install-Woosh-Studio-Offline.ps1"),
        (arguments.install_command, "Install-Woosh-Studio-Offline.cmd"),
        *[
            (arguments.archive_directory / asset, f"model-archives/{asset}")
            for asset in ASSETS
        ],
    ]
    for source, _ in files:
        if not source.is_file():
            raise FileNotFoundError(source)

    checksums = [f"{sha256(source)}  {relative}" for source, relative in files]
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
        for source, relative in files:
            bundle.write(source, f"{PACKAGE_ROOT}/{relative}")
        bundle.writestr(f"{PACKAGE_ROOT}/SHA256SUMS.txt", "\n".join(checksums) + "\n")
    temporary.replace(arguments.output)
    print(f"Offline distribution: {arguments.output} ({arguments.output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
