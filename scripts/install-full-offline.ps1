param(
    [string]$PackageRoot = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$package = (Resolve-Path $PackageRoot).Path
$msi = Join-Path $package "Woosh Studio_0.2.0_x64_zh-CN.msi"
$runtimeZip = Join-Path $package "Woosh-Studio-0.2.0-offline-runtime.zip"
if (-not (Test-Path -LiteralPath $msi)) { throw "核心 MSI 不存在: $msi" }
if (-not (Test-Path -LiteralPath $runtimeZip)) { throw "离线 runtime ZIP 不存在: $runtimeZip" }
Get-Process "woosh-studio" -ErrorAction SilentlyContinue | Stop-Process -Force
$installer = Start-Process -FilePath "msiexec.exe" -ArgumentList @("/i", "`"$msi`"", "/passive", "/norestart") -Wait -PassThru
if ($installer.ExitCode -ne 0) { throw "MSI 安装失败，退出码 $($installer.ExitCode)" }
$modelRoot = $env:WOOSH_MODEL_HOME
if ([string]::IsNullOrWhiteSpace($modelRoot)) { $modelRoot = [Environment]::GetEnvironmentVariable("WOOSH_MODEL_HOME", "User") }
if ([string]::IsNullOrWhiteSpace($modelRoot)) { throw "请先设置 WOOSH_MODEL_HOME" }
$modelRoot = [System.IO.Path]::GetFullPath($modelRoot)
if ([System.IO.Path]::GetPathRoot($modelRoot) -ieq "C:\") { throw "模型目录不能位于 C 盘" }
$runtimeTarget = Join-Path $modelRoot ".runtime"
New-Item -ItemType Directory -Force -Path $runtimeTarget | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
$temp = Join-Path $modelRoot ".runtime-installing"
if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
New-Item -ItemType Directory -Force -Path $temp | Out-Null
[System.IO.Compression.ZipFile]::ExtractToDirectory($runtimeZip, $temp, $true)
$source = Join-Path $temp "runtime"
if (-not (Test-Path -LiteralPath $source)) { throw "runtime ZIP 目录结构无效" }
if (Test-Path -LiteralPath $runtimeTarget) { Remove-Item -LiteralPath $runtimeTarget -Recurse -Force }
Move-Item -LiteralPath $source -Destination $runtimeTarget
Remove-Item -LiteralPath $temp -Recurse -Force
Write-Output "Woosh Studio 已安装。模型目录: $modelRoot"
