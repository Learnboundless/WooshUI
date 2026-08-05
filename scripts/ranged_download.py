from __future__ import annotations

import argparse
import math
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

def download_range(url: str, part: Path, start: int, end: int) -> None:
    expected = end - start + 1
    remainder = part.with_suffix(part.suffix + ".remainder")
    if remainder.exists():
        with part.open("ab") as destination, remainder.open("rb") as source:
            while block := source.read(8 * 1024 * 1024):
                destination.write(block)
        remainder.unlink()
    if part.exists() and part.stat().st_size == expected:
        return
    if part.exists() and part.stat().st_size > expected:
        part.unlink()
    existing = part.stat().st_size if part.exists() else 0
    result = subprocess.run(
        [
            "curl.exe",
            "--ssl-no-revoke",
            "--http1.1",
            "-L",
            "--fail",
            "--retry",
            "10",
            "--retry-all-errors",
            "--connect-timeout",
            "20",
            "--range",
            f"{start + existing}-{end}",
            "--output",
            str(remainder),
            url,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if remainder.exists():
        with part.open("ab") as destination, remainder.open("rb") as source:
            while block := source.read(8 * 1024 * 1024):
                destination.write(block)
        remainder.unlink()
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl exited with {result.returncode}")
    if part.stat().st_size != expected:
        raise RuntimeError(f"Incomplete range {start}-{end}: {part.stat().st_size}/{expected}")


def resolve_download_url(url: str) -> str:
    result = subprocess.run(
        [
            "curl.exe",
            "--ssl-no-revoke",
            "--http1.1",
            "-sSIL",
            "-o",
            "NUL",
            "-w",
            "%{url_effective}",
            url,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    resolved = result.stdout.strip()
    return resolved if result.returncode == 0 and resolved.startswith("https://") else url


def ranged_download(url: str, output: Path, size: int, segments: int, connections: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.stat().st_size == size:
        print(f"Already downloaded: {output}")
        return
    url = resolve_download_url(url)

    chunk_size = math.ceil(size / segments)
    ranges = [
        (index, index * chunk_size, min(size - 1, (index + 1) * chunk_size - 1))
        for index in range(segments)
        if index * chunk_size < size
    ]
    parts = [output.with_name(f"{output.name}.part.{index:02}") for index, _, _ in ranges]
    initial_downloaded = sum(
        part.stat().st_size + part.with_suffix(part.suffix + ".remainder").stat().st_size
        if part.with_suffix(part.suffix + ".remainder").exists()
        else part.stat().st_size
        for part in parts
        if part.exists()
    )
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=connections) as executor:
        futures = {
            executor.submit(download_range, url, part, start, end): index
            for (index, start, end), part in zip(ranges, parts, strict=True)
        }
        while futures:
            done = [future for future in futures if future.done()]
            for future in done:
                future.result()
                futures.pop(future)
            downloaded = sum(
                min(
                    ranges[index][2] - ranges[index][1] + 1,
                    (part.stat().st_size if part.exists() else 0)
                    + (
                        part.with_suffix(part.suffix + ".remainder").stat().st_size
                        if part.with_suffix(part.suffix + ".remainder").exists()
                        else 0
                    ),
                )
                for index, part in enumerate(parts)
            )
            elapsed = max(time.monotonic() - started, 0.001)
            print(
                f"{output.name}: {downloaded / size:.1%} "
                f"({downloaded / 1024**2:.0f}/{size / 1024**2:.0f} MiB, "
                f"{max(downloaded - initial_downloaded, 0) / elapsed / 1024**2:.2f} MiB/s)",
                flush=True,
            )
            if futures:
                time.sleep(2)

    assembled = output.with_suffix(output.suffix + ".assembling")
    with assembled.open("wb") as destination:
        for part in parts:
            with part.open("rb") as source:
                while block := source.read(8 * 1024 * 1024):
                    destination.write(block)
    if assembled.stat().st_size != size:
        raise RuntimeError(f"Assembled file size is invalid: {assembled.stat().st_size}/{size}")
    os.replace(assembled, output)
    for part in parts:
        part.unlink()
    print(f"Completed: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable parallel HTTP range downloader")
    parser.add_argument("url")
    parser.add_argument("output", type=Path)
    parser.add_argument("size", type=int)
    parser.add_argument("--segments", "--workers", dest="segments", type=int, default=24)
    parser.add_argument("--connections", type=int, default=8)
    arguments = parser.parse_args()
    ranged_download(
        arguments.url,
        arguments.output,
        arguments.size,
        arguments.segments,
        arguments.connections,
    )


if __name__ == "__main__":
    main()
