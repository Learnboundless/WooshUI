"""Build a self-contained app/runtime/Whisper ZIP64 distribution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while data := source.read(8 * 1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--msi", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", default="0.2.2")
    parser.add_argument("--sfx-archives", type=Path)
    parser.add_argument("--skip-archive", action="store_true")
    args = parser.parse_args()
    for source in (args.msi, args.runtime, args.model / "model.safetensors"):
        if not source.is_file():
            raise FileNotFoundError(source)
    label = "Whisper-Flow" if args.sfx_archives else "Whisper"
    directory = args.output / f"Woosh-Studio-{args.version}-{label}-offline-x64"
    directory.mkdir(parents=True, exist_ok=True)
    model_id = "Whisper-large-v3-turbo"
    model_records = []
    model_zip = directory / f"{model_id}.zip"
    with zipfile.ZipFile(
        model_zip.with_suffix(".zip.part"), "w", zipfile.ZIP_STORED, allowZip64=True
    ) as archive:
        for source in sorted(args.model.rglob("*")):
            if (
                not source.is_file()
                or ".cache" in source.parts
                or source.suffix == ".part"
            ):
                continue
            relative = source.relative_to(args.model).as_posix()
            record = {
                "path": relative,
                "size_bytes": source.stat().st_size,
                "sha256": sha256(source),
            }
            model_records.append(record)
            archive.write(source, model_id + "/" + relative)
        archive.writestr(
            model_id + "/payload-manifest.json",
            json.dumps({"files": model_records}, indent=2),
        )
    os.replace(model_zip.with_suffix(".zip.part"), model_zip)
    print(f"Packed Whisper: {model_zip.stat().st_size} bytes", flush=True)
    core = directory / args.msi.name
    shutil.copy2(args.msi, core)
    runtime = directory / "offline-runtime.zip"
    if not runtime.exists():
        try:
            os.link(args.runtime, runtime)
        except OSError:
            shutil.copy2(args.runtime, runtime)
    with zipfile.ZipFile(runtime) as archive:
        runtime_manifest = json.loads(archive.read("runtime/runtime-manifest.json"))
    installer_script = directory / "Install-Woosh-Studio.ps1"
    shutil.copy2(
        Path(__file__).with_name("install-whisper-offline.ps1"), installer_script
    )
    additional_models = []
    additional_files = []
    if args.sfx_archives:
        for identifier in ("Woosh-DFlow", "Woosh-Flow", "Woosh-AE", "TextConditionerA"):
            source = args.sfx_archives / (identifier + ".zip")
            if not source.is_file():
                raise FileNotFoundError(source)
            target = directory / source.name
            if not target.exists():
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copy2(source, target)
            print("Verifying model contents: " + identifier, flush=True)
            content = []
            with zipfile.ZipFile(source) as bundle:
                configs = [
                    name
                    for name in bundle.namelist()
                    if name.endswith("/" + identifier + "/config.yaml")
                ]
                if len(configs) != 1:
                    raise ValueError("Unexpected model archive layout: " + identifier)
                prefix = configs[0][: -len("config.yaml")]
                for member in bundle.infolist():
                    if member.is_dir() or not member.filename.startswith(prefix):
                        continue
                    digest = hashlib.sha256()
                    with bundle.open(member) as file:
                        while block := file.read(8 * 1024 * 1024):
                            digest.update(block)
                    content.append(
                        {
                            "path": member.filename[len(prefix) :],
                            "size_bytes": member.file_size,
                            "sha256": digest.hexdigest(),
                        }
                    )
            additional_models.append(
                {
                    "id": identifier,
                    "archive": target.name,
                    "inner": prefix.rstrip("/"),
                    "files": content,
                }
            )
            additional_files.append(target)
        license_file = directory / "MODEL_LICENSES.md"
        shutil.copy2(
            Path(__file__).resolve().parents[1] / "MODEL_LICENSES.md", license_file
        )
        additional_files.append(license_file)
    records = []
    for source in (core, runtime, model_zip, installer_script, *additional_files):
        print(f"Verifying package file: {source.name}", flush=True)
        records.append(
            {
                "path": source.name,
                "size_bytes": source.stat().st_size,
                "sha256": sha256(source),
            }
        )
    manifest = {
        "version": args.version,
        "installer": core.name,
        "runtime_archive": runtime.name,
        "runtime_version": runtime_manifest["version"],
        "model_archive": model_zip.name,
        "model_id": model_id,
        "files": records,
        "model_files": model_records,
        "additional_models": additional_models,
    }
    (directory / "package-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8-sig"
    )
    (directory / "Install.cmd").write_text(
        '@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Woosh-Studio.ps1"\r\nif errorlevel 1 pause\r\n',
        encoding="ascii",
    )
    (directory / "安装说明.txt").write_text(
        f"Woosh Studio {args.version} — Whisper 离线安装包\n\n"
        "1. 完整解压 ZIP 到非系统盘，不要直接在压缩包中运行。\n"
        "2. 保存当前项目，关闭 Woosh Studio。右键 Install.cmd，选择以管理员身份运行。\n"
        "3. 安装器校验文件，将 Whisper 和 Python/CUDA 环境部署到共享模型目录，然后升级应用。\n"
        "4. 打开剧本配音，选择参考音频克隆；可麦克风录制、试听、保存并自动识别台词。\n"
        "5. 在输出语言中勾选所需语言，生成文本和配音，在导出页选择游戏多语言包。\n\n"
        "包内包含：新版应用（含多语翻译）、Whisper large-v3-turbo 权重、离线 Python/CUDA 环境。\n"
        + (
            "音效包额外包含 DFlow、Flow、Woosh-AE 和 TextConditionerA。\n"
            if args.sfx_archives
            else ""
        )
        + "配音和音乐使用共享模型库中的 Qwen3-TTS、HeartMuLa、Demucs。\n"
        "安装器优先沿用 WOOSH_MODEL_HOME；首次安装会选择空间足够的非系统盘。\n"
        "可用 PowerShell 参数 -ModelRoot 和 -InstallDirectory 指定路径；-VerifyOnly 仅校验安装包。\n",
        encoding="utf-8-sig",
    )
    checksums = [
        f"{sha256(source)}  {source.name}"
        for source in sorted(directory.iterdir())
        if source.is_file() and source.name != "SHA256SUMS.txt"
    ]
    (directory / "SHA256SUMS.txt").write_text(
        "\n".join(checksums) + "\n", encoding="utf-8"
    )
    if not args.skip_archive:
        output = args.output / (directory.name + ".zip")
        temporary = output.with_suffix(".zip.part")
        with zipfile.ZipFile(
            temporary, "w", zipfile.ZIP_STORED, allowZip64=True
        ) as archive:
            for source in sorted(directory.iterdir()):
                if source.is_file():
                    archive.write(source, directory.name + "/" + source.name)
        os.replace(temporary, output)
        digest = sha256(output)
        output.with_suffix(".zip.sha256").write_text(
            digest + "  " + output.name + "\n", encoding="ascii"
        )
        print(
            json.dumps(
                {
                    "archive": str(output),
                    "bytes": output.stat().st_size,
                    "sha256": digest,
                }
            ),
            flush=True,
        )
    print(json.dumps({"directory": str(directory)}), flush=True)


if __name__ == "__main__":
    main()
