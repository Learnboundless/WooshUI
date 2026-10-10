"""Build and deploy the translation payload shipped inside every desktop installer.

Network access and conversion are build-time work. Runtime installation only reads
our bundled archive, validates it and atomically installs into the shared model root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

MODEL_ID = "m2m100-418M-int8"
MODEL_REPO = "facebook/m2m100_418M"
MODEL_REVISION = "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636"
ARCHIVE_NAME = "M2M100-418M-int8.zip"
MANIFEST_NAME = "bundle-manifest.json"
BUNDLE_VERSION = 1
REQUIRED_FILES = {
    "model.bin",
    "config.json",
    "shared_vocabulary.json",
    "tokenizer/sentencepiece.bpe.model",
    "tokenizer/vocab.json",
    "tokenizer/tokenizer_config.json",
    "tokenizer/special_tokens_map.json",
    "LICENSE",
    "MODEL_CARD.md",
}
MAX_UNPACKED_BYTES = 2_000_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_manifest(data: dict) -> dict:
    if (
        data.get("model_id") != MODEL_ID
        or data.get("revision") != MODEL_REVISION
        or data.get("bundle_version") != BUNDLE_VERSION
    ):
        raise ValueError("内置翻译模型清单的版本不匹配")
    files = data.get("files", [])
    names = set()
    for file in files:
        name = file["path"]
        parts = PurePosixPath(name)
        if (
            parts.is_absolute()
            or ".." in parts.parts
            or "\\" in name
            or ":" in name
            or name in names
        ):
            raise ValueError("内置翻译模型清单包含非法路径")
        if file["size_bytes"] <= 0 or len(file["sha256"]) != 64:
            raise ValueError("内置翻译模型文件清单无效")
        names.add(name)
    if (
        not REQUIRED_FILES <= names
        or sum(file["size_bytes"] for file in files) > MAX_UNPACKED_BYTES
    ):
        raise ValueError("内置翻译模型文件不完整或大小异常")
    return data


def verify_directory(root: Path) -> dict:
    manifest = checked_manifest(
        json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    )
    for entry in manifest["files"]:
        path = root / entry["path"]
        if (
            not path.is_file()
            or path.stat().st_size != entry["size_bytes"]
            or sha256(path) != entry["sha256"]
        ):
            raise ValueError(f"内置翻译模型校验失败：{entry['path']}")
    return manifest


def inspect_archive(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as bundle:
        manifest = checked_manifest(
            json.loads(bundle.read(f"{MODEL_ID}/{MANIFEST_NAME}"))
        )
        expected = {f"{MODEL_ID}/{file['path']}" for file in manifest["files"]} | {
            f"{MODEL_ID}/{MANIFEST_NAME}"
        }
        members = bundle.infolist()
        if (
            len(members) != len(expected)
            or {item.filename for item in members} != expected
        ):
            raise ValueError("内置翻译模型压缩包文件清单不匹配")
        if sum(item.file_size for item in members) > MAX_UNPACKED_BYTES:
            raise ValueError("内置翻译模型压缩包过大")
        return manifest


def install_archive(archive: Path, target: Path) -> Path:
    target = target.expanduser().resolve()
    expected = inspect_archive(archive)
    try:
        if verify_directory(target) == expected:
            return target
    except (OSError, ValueError, KeyError):
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    if (
        shutil.disk_usage(target.parent).free
        < sum(file["size_bytes"] for file in expected["files"]) + 64 * 1024**2
    ):
        raise RuntimeError("准备内置翻译模型的可用空间不足")
    temporary = target.with_name(f".{target.name}-install-{uuid4().hex}")
    previous = target.with_name(f".{target.name}-previous-{uuid4().hex}")
    temporary.mkdir()
    try:
        # inspect_archive limits all entries to known safe paths before extracting.
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(temporary)
        staged = temporary / MODEL_ID
        verify_directory(staged)
        if target.exists():
            os.replace(target, previous)
        try:
            os.replace(staged, target)
        except OSError:
            if previous.exists():
                os.replace(previous, target)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return target


def build_archive(source: Path, archive: Path) -> dict:
    if archive.is_file():
        try:
            inspect_archive(archive)
            with zipfile.ZipFile(archive) as bundle:
                if bundle.testzip() is not None:
                    raise ValueError("ZIP CRC mismatch")
            print(f"Verified bundled translation: {archive}", flush=True)
            return inspect_archive(archive)
        except (ValueError, OSError, KeyError, zipfile.BadZipFile):
            print("Rebuilding incomplete translation bundle", flush=True)
    from huggingface_hub import snapshot_download, hf_hub_url, get_hf_file_metadata
    import httpx
    import ctranslate2
    from ctranslate2.converters import TransformersConverter
    import transformers

    if not (source / "pytorch_model.bin").is_file():
        print(
            "Downloading translation weights for the installer (build machine only)",
            flush=True,
        )
        snapshot_download(
            repo_id=MODEL_REPO,
            revision=MODEL_REVISION,
            local_dir=str(source),
            allow_patterns=["*.json", "pytorch_model.bin", "sentencepiece.bpe.model"],
        )
    metadata = get_hf_file_metadata(
        hf_hub_url(MODEL_REPO, "pytorch_model.bin", revision=MODEL_REVISION)
    )
    source_hash = sha256(source / "pytorch_model.bin")
    if source_hash != metadata.etag:
        raise ValueError("官方翻译源权重 SHA-256 校验失败")
    archive.parent.mkdir(parents=True, exist_ok=True)
    staging = archive.parent / f".translation-build-{uuid4().hex}"
    partial = archive.with_suffix(".zip.tmp")
    try:
        model = staging / MODEL_ID
        print("Converting M2M100 to CPU INT8", flush=True)
        TransformersConverter(str(source)).convert(
            str(model), quantization="int8", force=True
        )
        tokenizer = model / "tokenizer"
        tokenizer.mkdir()
        for name in (
            "config.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "vocab.json",
            "sentencepiece.bpe.model",
        ):
            shutil.copy2(source / name, tokenizer / name)
        for url, name in [
            (
                f"https://huggingface.co/{MODEL_REPO}/raw/{MODEL_REVISION}/README.md",
                "MODEL_CARD.md",
            ),
            (
                "https://raw.githubusercontent.com/facebookresearch/fairseq/main/LICENSE",
                "LICENSE",
            ),
        ]:
            response = httpx.get(url, follow_redirects=True, timeout=30)
            response.raise_for_status()
            (model / name).write_text(response.text, encoding="utf-8")
        # Verify the actual converted artifacts can be opened with the shipping runtime.
        engine = ctranslate2.Translator(str(model), device="cpu", compute_type="int8")
        tokenizer_instance = transformers.M2M100Tokenizer.from_pretrained(
            str(tokenizer), local_files_only=True
        )
        tokenizer_instance.src_lang = "en"
        output = engine.translate_batch(
            [
                tokenizer_instance.convert_ids_to_tokens(
                    tokenizer_instance.encode("Hello, my friend.")
                )
            ],
            target_prefix=[["__zh__"]],
            beam_size=4,
        )[0].hypotheses[0]
        translation = tokenizer_instance.decode(
            tokenizer_instance.convert_tokens_to_ids(output), skip_special_tokens=True
        )
        if not translation.strip():
            raise ValueError("内置模型转换后的翻译测试返回空文本")
        print(f"Converted model smoke test: {translation}", flush=True)
        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "model_id": MODEL_ID,
            "repo": MODEL_REPO,
            "revision": MODEL_REVISION,
            "source_sha256": source_hash,
            "license": "MIT",
            "quantization": "int8",
            "ctranslate2_version": ctranslate2.__version__,
            "transformers_version": transformers.__version__,
            "files": [
                {
                    "path": file.relative_to(model).as_posix(),
                    "size_bytes": file.stat().st_size,
                    "sha256": sha256(file),
                }
                for file in sorted(model.rglob("*"))
                if file.is_file()
            ],
        }
        (model / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        verify_directory(model)
        print("Compressing verified model into the desktop payload", flush=True)
        with zipfile.ZipFile(
            partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as bundle:
            for file in sorted(model.rglob("*")):
                if file.is_file():
                    bundle.write(
                        file, f"{MODEL_ID}/{file.relative_to(model).as_posix()}"
                    )
        inspect_archive(partial)
        os.replace(partial, archive)
        archive.with_suffix(".manifest.json").write_text(
            json.dumps(
                {
                    **manifest,
                    "archive_sha256": sha256(archive),
                    "archive_size_bytes": archive.stat().st_size,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Prepared {archive} ({archive.stat().st_size} bytes)", flush=True)
        return manifest
    finally:
        partial.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    build_archive(args.source.resolve(), args.archive.resolve())


if __name__ == "__main__":
    main()
