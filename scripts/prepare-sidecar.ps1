param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$uv = (Get-Command uv -ErrorAction Stop).Source
$destination = Join-Path $PSScriptRoot "..\desktop\src-tauri\binaries\uv-$TargetTriple.exe"
New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
Copy-Item -LiteralPath $uv -Destination $destination -Force
Write-Output "Prepared uv sidecar: $destination"
