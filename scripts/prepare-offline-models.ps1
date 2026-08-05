param(
    [string]$ArtifactRoot = (Join-Path $PSScriptRoot "..\.artifacts"),
    [string]$ReleaseBase = "https://github.com/SonyResearch/Woosh/releases/download/v1.0.0"
)

$ErrorActionPreference = "Stop"
$archiveDirectory = Join-Path $ArtifactRoot "model-archives"
$outputDirectory = Join-Path $ArtifactRoot "offline-models"
$downloader = Join-Path $PSScriptRoot "ranged_download.py"
$release = $ReleaseBase
$assets = @(
    @{ Name = "Woosh-DFlow.zip"; Size = 1281505601 },
    @{ Name = "Woosh-Flow.zip"; Size = 1253883744 },
    @{ Name = "Woosh-AE.zip"; Size = 822991075 },
    @{ Name = "TextConditionerA.zip"; Size = 1297121262 }
)

New-Item -ItemType Directory -Force -Path $archiveDirectory | Out-Null
foreach ($asset in $assets) {
    $destination = Join-Path $archiveDirectory $asset.Name
    if (-not (Test-Path -LiteralPath $destination) -or (Get-Item -LiteralPath $destination).Length -ne $asset.Size) {
        & uv run --no-sync python $downloader "$release/$($asset.Name)" $destination $asset.Size --segments 24 --connections 8
        if ($LASTEXITCODE -ne 0) {
            throw "Download failed: $($asset.Name)"
        }
    }
    if ((Get-Item -LiteralPath $destination).Length -ne $asset.Size) {
        throw "Downloaded file size is invalid: $($asset.Name)"
    }
}

& uv run --no-default-groups --group studio --extra cuda python -m woosh_studio.offline_bundle $archiveDirectory $outputDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Offline model verification failed"
}

Write-Output "Offline models prepared: $outputDirectory"
