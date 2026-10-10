param(
    [string]$SourceRoot = (Join-Path $PSScriptRoot ".."),
    [string]$SourceModel = "",
    [switch]$BuildFrontend
)
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Build environment missing: $python. Prepare the repository Python environment before packaging."
}
if ([string]::IsNullOrWhiteSpace($SourceModel)) {
    $sharedModels = $env:WOOSH_MODEL_HOME
    if ([string]::IsNullOrWhiteSpace($sharedModels)) { $sharedModels = [Environment]::GetEnvironmentVariable("WOOSH_MODEL_HOME", "User") }
    $sharedSource = if ($sharedModels) { Join-Path $sharedModels ".downloads\m2m100-418M-source" } else { "" }
    $SourceModel = if ($sharedSource -and (Test-Path -LiteralPath $sharedSource)) { $sharedSource } else { Join-Path $projectRoot ".artifacts\translation-source" }
}
Push-Location $projectRoot
try {
    & $python -X utf8 -m woosh_studio.translation_bundle --source $SourceModel --archive (Join-Path $projectRoot ".artifacts\model-archives\M2M100-418M-int8.zip")
    if ($LASTEXITCODE -ne 0) { throw "Bundled translation preparation failed; refusing to publish an installer without translation weights." }
    if ($BuildFrontend) {
        & npm --prefix (Join-Path $projectRoot "frontend") run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
    }
}
finally { Pop-Location }
