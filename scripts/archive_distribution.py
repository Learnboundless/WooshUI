from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()

    source = arguments.source.resolve()
    output = arguments.output.resolve()
    temporary = output.with_suffix(output.suffix + ".part")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary.unlink(missing_ok=True)

    files = sorted(path for path in source.rglob("*") if path.is_file())
    with zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_STORED,
        allowZip64=True,
    ) as archive:
        for path in files:
            relative = Path(source.name) / path.relative_to(source)
            archive.write(path, relative.as_posix())
            print(f"Packed {relative}", flush=True)

    os.replace(temporary, output)
    print(f"Created {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
