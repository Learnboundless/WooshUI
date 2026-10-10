param(
    [string]$Version = "0.2.0"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtime = Join-Path $root "desktop\src-tauri\runtime"
$artifacts = Join-Path $root ".artifacts\installers"
$distribution = Join-Path $artifacts "Woosh-Studio-$Version-full-offline"
New-Item -ItemType Directory -Force -Path $distribution | Out-Null
$msi = Join-Path $root ("desktop\src-tauri\target\release\bundle\msi\Woosh Studio_{0}_x64_zh-CN.msi" -f $Version)
if (-not (Test-Path -LiteralPath $msi)) { throw "请先运行 npm --prefix desktop run build" }
Copy-Item -LiteralPath $msi -Destination $distribution -Force
& (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $root "scripts\archive_distribution.py") $runtime (Join-Path $distribution "Woosh-Studio-$Version-offline-runtime.zip")
if ($LASTEXITCODE -ne 0) { throw "runtime ZIP 打包失败" }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install-full-offline.ps1") -Destination $distribution -Force
@"
Woosh Studio $Version 完整离线安装包

1. 确保用户环境变量 WOOSH_MODEL_HOME 指向已有模型目录（例如 E:\AIModels\WooshStudio）。
2. 运行 install-full-offline.ps1。
3. 脚本会安装核心 MSI，并将 Python/CUDA runtime 解压到 WOOSH_MODEL_HOME\.runtime。
4. 多语种翻译权重已内置在核心 MSI，首次启动自动部署，无需下载。
5. HeartMuLa、Qwen3-TTS 和 Demucs 权重已在模型目录中时，应用可直接离线启动。
"@ | Set-Content -LiteralPath (Join-Path $distribution "安装说明.txt") -Encoding utf8
Write-Output "Created $distribution"
