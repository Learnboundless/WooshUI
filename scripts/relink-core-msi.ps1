param(
    [Parameter(Mandatory = $true)]
    [string]$SourceWxs,
    [Parameter(Mandatory = $true)]
    [string]$LocaleWxl,
    [Parameter(Mandatory = $true)]
    [string]$OutputMsi,
    [string]$WixTools = (Join-Path $env:LOCALAPPDATA "tauri\WixTools314")
)

$ErrorActionPreference = "Stop"
$candle = Join-Path $WixTools "candle.exe"
$light = Join-Path $WixTools "light.exe"
foreach ($path in @($SourceWxs, $LocaleWxl, $candle, $light)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required MSI relink input is missing: $path"
    }
}

$workDirectory = Join-Path (Split-Path -Parent (Split-Path -Parent $OutputMsi)) ".wix-core"
New-Item -ItemType Directory -Force -Path $workDirectory | Out-Null
$wixObject = Join-Path $workDirectory "main-core.wixobj"

& $candle -nologo -arch x64 -ext WixUIExtension -out $wixObject $SourceWxs
if ($LASTEXITCODE -ne 0) {
    throw "WiX candle failed for the core installer."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputMsi) | Out-Null
& $light `
    -nologo `
    -ext WixUIExtension `
    -cultures:zh-cn `
    -loc $LocaleWxl `
    -pdbout (Join-Path $workDirectory "main-core.wixpdb") `
    -out $OutputMsi `
    $wixObject
if ($LASTEXITCODE -ne 0) {
    throw "WiX light failed for the core installer."
}

Get-Item -LiteralPath $OutputMsi | Select-Object FullName, Length, LastWriteTime
