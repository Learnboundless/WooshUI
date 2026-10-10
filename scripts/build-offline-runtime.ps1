param(
    [string]$SourceRoot = (Join-Path $PSScriptRoot ".."),
    [string]$Output = (Join-Path $PSScriptRoot "..\desktop\src-tauri\runtime"),
    [string]$Version = "0.2.0"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path $SourceRoot).Path
$outputPath = [System.IO.Path]::GetFullPath($Output)
$staging = Join-Path $root ".artifacts\offline-runtime-source"
$pythonPath = Join-Path $staging "python"
$cachePath = Join-Path $staging "uv-cache"
New-Item -ItemType Directory -Force -Path $pythonPath, $cachePath | Out-Null
$oldPythonInstall = $env:UV_PYTHON_INSTALL_DIR
$oldLocation = Get-Location
Push-Location $root
$oldCache = $env:UV_CACHE_DIR
try {
    $env:UV_PYTHON_INSTALL_DIR = $pythonPath
    $env:UV_CACHE_DIR = $cachePath
    & uv run --managed-python --python 3.12 --project $root --no-default-groups --group studio --group music --group speech --extra cuda python -c "import heartlib, demucs, qwen_tts, torch"
    if ($LASTEXITCODE -ne 0) { throw "依赖预热失败" }
    & uv run --no-default-groups --group studio python -m woosh_studio.runtime_bundle $pythonPath $cachePath $outputPath --version $Version
    if ($LASTEXITCODE -ne 0) { throw "离线运行时打包失败" }
}
finally {
    $env:UV_PYTHON_INSTALL_DIR = $oldPythonInstall
    $env:UV_CACHE_DIR = $oldCache
    Pop-Location
}
Write-Output "Prepared offline runtime at $outputPath"
