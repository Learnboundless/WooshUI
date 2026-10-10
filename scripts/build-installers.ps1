param(
    [switch]$SkipModelDownload,
    [switch]$SkipArchive,
    [switch]$ReuseAppBuild,
    [switch]$SkipModelVerification
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktop = Join-Path $root "desktop"
$tauri = Join-Path $desktop "src-tauri"
$tauriConfig = Get-Content -LiteralPath (Join-Path $tauri "tauri.conf.json") -Raw | ConvertFrom-Json
$version = $tauriConfig.version
$artifacts = Join-Path $root ".artifacts\installers"
$modelArchives = Join-Path $root ".artifacts\model-archives"
$distribution = Join-Path $artifacts "Woosh-Studio-$version-with-models-x64"
$temporary = Join-Path $root ".artifacts\tmp"
$payloadFiles = @(
    "Woosh-DFlow.zip",
    "Woosh-Flow.zip",
    "Woosh-AE.zip",
    "TextConditionerA.zip"
)

New-Item -ItemType Directory -Force -Path $artifacts, $distribution, $temporary | Out-Null
$env:TEMP = $temporary
$env:TMP = $temporary

& (Join-Path $PSScriptRoot "prepare-bundled-translation.ps1")
if ($LASTEXITCODE -ne 0) { throw "Bundled translation preparation failed" }

$wixDirectory = Join-Path $tauri "target\release\wix\x64"
$coreOutput = Join-Path $artifacts "Woosh-Studio-$version-no-models-x64.msi"
& (Join-Path $PSScriptRoot "build-offline-runtime.ps1") -Version $version
if ($LASTEXITCODE -ne 0) {
    throw "Offline runtime build failed"
}
if ($ReuseAppBuild) {
    $savedWxs = Join-Path $wixDirectory "main.wxs"
    if (-not (Test-Path -LiteralPath $savedWxs) -or -not (Select-String -LiteralPath $savedWxs -SimpleMatch "M2M100-418M-int8.zip" -Quiet)) {
        throw "Saved MSI build has no bundled translation; rerun without -ReuseAppBuild."
    }
    & (Join-Path $PSScriptRoot "relink-core-msi.ps1") `
        -SourceWxs (Join-Path $wixDirectory "main.wxs") `
        -LocaleWxl (Join-Path $wixDirectory "locale.wxl") `
        -OutputMsi $coreOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Core MSI relink failed"
    }
}
else {
    Push-Location $desktop
    try {
        & npx tauri build --bundles msi
        if ($LASTEXITCODE -ne 0) {
            throw "Core MSI build failed"
        }
    }
    finally {
        Pop-Location
    }
    $bundleDirectory = Join-Path $tauri "target\release\bundle\msi"
    $coreBundle = Get-ChildItem -LiteralPath $bundleDirectory -Filter "*$version*x64*zh-CN.msi" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $coreBundle) {
        throw "The Tauri MSI output was not found in $bundleDirectory"
    }
    Copy-Item -LiteralPath $coreBundle.FullName -Destination $coreOutput -Force
}

if ($SkipModelDownload) {
    Get-Item -LiteralPath $coreOutput | Select-Object FullName, Length, LastWriteTime
    return
}

if (-not $SkipModelVerification) {
    & (Join-Path $PSScriptRoot "prepare-offline-models.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Offline models are not ready"
    }
}
else {
    foreach ($name in $payloadFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $modelArchives $name) -PathType Leaf)) {
            throw "Previously verified model payload is missing: $name"
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $root ".artifacts\offline-models\model-manifest.json") -PathType Leaf)) {
        throw "Previously verified model manifest is missing"
    }
}

$modelMsi = Join-Path $distribution "Woosh-Studio-$version-with-models-x64.msi"
foreach ($name in $payloadFiles) {
    $stalePayload = Join-Path $distribution $name
    if (Test-Path -LiteralPath $stalePayload) {
        Remove-Item -LiteralPath $stalePayload -Force
    }
}
& (Join-Path $PSScriptRoot "build-model-msi.ps1") `
    -SourceWxs (Join-Path $wixDirectory "main.wxs") `
    -LocaleWxl (Join-Path $wixDirectory "locale.wxl") `
    -ModelArchiveDirectory $modelArchives `
    -LicenseFile (Join-Path $root "MODEL_LICENSES.md") `
    -OutputMsi $modelMsi
if ($LASTEXITCODE -ne 0) {
    throw "Selectable-model MSI build failed"
}

foreach ($name in $payloadFiles) {
    $source = Join-Path $modelArchives $name
    $target = Join-Path $distribution $name
    # WiX normally emits external files beside the MSI. Keep this fallback for
    # tool versions that leave the original source path in place.
    if (-not (Test-Path -LiteralPath $target)) {
        New-Item -ItemType HardLink -Path $target -Target $source | Out-Null
    }
}
Copy-Item -LiteralPath (Join-Path $root "MODEL_LICENSES.md") -Destination $distribution -Force
Copy-Item `
    -LiteralPath (Join-Path $root ".artifacts\offline-models\model-manifest.json") `
    -Destination $distribution `
    -Force

$instructions = @"
Woosh Studio $version 模型可选安装包

1. 请完整解压本目录，不要只从压缩包内直接运行 MSI。
2. 双击 Woosh-Studio-$version-with-models-x64.msi。
3. 在“选择离线模型”页面勾选 DFlow、Flow、两者或都不安装。
4. 任一模型会自动包含 Woosh-AE 与 TextConditionerA，共享文件只安装一次。
5. 模型权重仅限 CC BY-NC 4.0 允许的研究和非商业用途。
"@
Set-Content -LiteralPath (Join-Path $distribution "安装说明.txt") -Value $instructions -Encoding utf8

if (-not $SkipArchive) {
    & (Join-Path $root ".venv\Scripts\python.exe") `
        (Join-Path $PSScriptRoot "archive_distribution.py") `
        $distribution `
        (Join-Path $artifacts "Woosh-Studio-$version-with-models-x64.zip")
    if ($LASTEXITCODE -ne 0) {
        throw "MSI model distribution archive failed"
    }
}

Get-Item -LiteralPath $coreOutput, $modelMsi | Select-Object FullName, Length, LastWriteTime
if (-not $SkipArchive) {
    Get-Item -LiteralPath (Join-Path $artifacts "Woosh-Studio-$version-with-models-x64.zip") |
        Select-Object FullName, Length, LastWriteTime
}
