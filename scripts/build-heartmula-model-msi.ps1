param(
    [string]$ModelRoot = $(if ($env:WOOSH_MODEL_HOME) {
        $env:WOOSH_MODEL_HOME
    }
    else {
        [Environment]::GetEnvironmentVariable("WOOSH_MODEL_HOME", "User")
    }),
    [string]$Version = "0.2.0",
    [switch]$SkipArchive,
    [string]$WixTools = (Join-Path $env:LOCALAPPDATA "tauri\WixTools314")
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    throw "WOOSH_MODEL_HOME is not set. HeartMuLa model packaging requires a shared non-C drive."
}
$modelRootPath = [System.IO.Path]::GetFullPath($ModelRoot)
if ([System.IO.Path]::GetPathRoot($modelRootPath) -ieq "C:\") {
    throw "ModelRoot must not be on C drive: $modelRootPath"
}

$artifacts = Join-Path $root ".artifacts\installers"
$distribution = Join-Path $artifacts "Woosh-Studio-$Version-HeartMuLa-models-x64"
$work = Join-Path $root ".artifacts\heartmula-msi"
$markers = Join-Path $work "markers"
New-Item -ItemType Directory -Force -Path $artifacts, $distribution, $work, $markers | Out-Null

$env:WOOSH_MODEL_HOME = $modelRootPath
& uv run --no-sync python -m woosh_studio.music_bundle $modelRootPath $distribution
if ($LASTEXITCODE -ne 0) {
    throw "HeartMuLa payload preparation failed"
}

Copy-Item `
    -LiteralPath (Join-Path $PSScriptRoot "model-pack\Install-HeartMuLa-Models.ps1") `
    -Destination $distribution `
    -Force
Set-Content -LiteralPath (Join-Path $markers "core.txt") -Value "Woosh Studio HeartMuLa Models $Version" -Encoding ascii
Set-Content -LiteralPath (Join-Path $markers "heartmula.txt") -Value "HeartMuLa + HeartCodec" -Encoding ascii
Set-Content -LiteralPath (Join-Path $markers "demucs.txt") -Value "Demucs htdemucs" -Encoding ascii

$licenseRtf = Join-Path $work "licenses.rtf"
Set-Content -LiteralPath $licenseRtf -Encoding ascii -Value @"
{\rtf1\ansi\deff0
{\fonttbl{\f0 Segoe UI;}}
\f0\fs20
HeartMuLa and HeartCodec: Apache License 2.0\par
Demucs htdemucs: MIT License\par
\par
The Sony Woosh CC BY-NC license does not apply to HeartMuLa model weights.
}
"@

$candle = Join-Path $WixTools "candle.exe"
$light = Join-Path $WixTools "light.exe"
if (-not (Test-Path -LiteralPath $candle) -or -not (Test-Path -LiteralPath $light)) {
    throw "WiX 3.14 tools were not found. Run a Tauri MSI build first."
}
$wixObject = Join-Path $work "heartmula-models.wixobj"
$msi = Join-Path $distribution "Woosh-Studio-$Version-HeartMuLa-models-x64.msi"
& $candle `
    -nologo `
    -arch x64 `
    -ext WixUIExtension `
    "-dVersion=$Version" `
    "-dMarkerRoot=$markers" `
    "-dInstallerScript=$(Join-Path $PSScriptRoot 'model-pack\Install-HeartMuLa-Models.ps1')" `
    "-dLicenseRtf=$licenseRtf" `
    -out $wixObject `
    (Join-Path $PSScriptRoot "model-pack\heartmula-models.wxs")
if ($LASTEXITCODE -ne 0) {
    throw "WiX candle failed for the HeartMuLa model MSI."
}
& $light `
    -nologo `
    -ext WixUIExtension `
    -cultures:zh-cn `
    -out $msi `
    $wixObject
if ($LASTEXITCODE -ne 0) {
    throw "WiX light failed for the HeartMuLa model MSI."
}

$instructions = @"
Woosh Studio $Version HeartMuLa 模型安装包

1. 完整解压本目录，再运行 MSI。
2. MSI 从用户环境变量 WOOSH_MODEL_HOME 读取共享模型目录。
3. 可分别选择 HeartMuLa + HeartCodec 和 Demucs 四分轨。
4. 模型不会安装到 C 盘，也不会复制到 Woosh Studio 应用目录。
"@
Set-Content -LiteralPath (Join-Path $distribution "安装说明.txt") -Value $instructions -Encoding utf8

if (-not $SkipArchive) {
    & (Join-Path $root ".venv\Scripts\python.exe") `
        (Join-Path $PSScriptRoot "archive_distribution.py") `
        $distribution `
        (Join-Path $artifacts "Woosh-Studio-$Version-HeartMuLa-models-x64.zip")
    if ($LASTEXITCODE -ne 0) {
        throw "HeartMuLa model distribution archive failed"
    }
}

Get-Item -LiteralPath $msi | Select-Object FullName, Length, LastWriteTime
