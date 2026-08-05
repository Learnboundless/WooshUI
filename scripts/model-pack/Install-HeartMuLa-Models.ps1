param(
    [Parameter(Mandatory = $true)]
    [Alias("S")]
    [string]$SourceDirectory,
    [string]$ModelRoot = [Environment]::GetEnvironmentVariable("WOOSH_MODEL_HOME", "User"),
    [Alias("M")]
    [int]$InstallMusic = 3,
    [Alias("D")]
    [int]$InstallDemucs = 3
)

$ErrorActionPreference = "Stop"
$source = (Resolve-Path -LiteralPath $SourceDirectory).Path
if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    throw "用户环境变量 WOOSH_MODEL_HOME 未设置"
}
$root = [System.IO.Path]::GetFullPath($ModelRoot)
if ([System.IO.Path]::GetPathRoot($root) -ieq "C:\") {
    throw "模型目录不能位于 C 盘: $root"
}

$manifestPath = Join-Path $source "model-manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "模型包缺少 model-manifest.json"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$selected = @()
if ($InstallMusic -eq 3) {
    $selected += "music"
}
if ($InstallDemucs -eq 3) {
    $selected += "demucs"
}
if ($selected.Count -eq 0) {
    exit 0
}

New-Item -ItemType Directory -Force -Path $root | Out-Null
[Environment]::SetEnvironmentVariable("WOOSH_MODEL_HOME", $root, "User")
$records = @($manifest.files | Where-Object { $selected -contains $_.component })
$completed = 0
foreach ($record in $records) {
    $relative = [string]$record.path
    $sourceFile = Join-Path $source (Join-Path "Payload" $relative)
    $target = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) {
        throw "模型负载缺少文件: $relative"
    }
    $sourceInfo = Get-Item -LiteralPath $sourceFile
    if ($sourceInfo.Length -ne [long]$record.size) {
        throw "模型负载大小校验失败: $relative"
    }
    $validTarget = (Test-Path -LiteralPath $target -PathType Leaf) -and
        ((Get-Item -LiteralPath $target).Length -eq [long]$record.size)
    if ($validTarget -and $record.sha256) {
        $targetDigest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
        $validTarget = $targetDigest -eq ([string]$record.sha256).ToLowerInvariant()
    }
    if (-not $validTarget) {
        $targetDirectory = Split-Path -Parent $target
        New-Item -ItemType Directory -Force -Path $targetDirectory | Out-Null
        $partial = "$target.part"
        Copy-Item -LiteralPath $sourceFile -Destination $partial -Force
        if ($record.sha256) {
            $digest = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($digest -ne ([string]$record.sha256).ToLowerInvariant()) {
                Remove-Item -LiteralPath $partial -Force
                throw "模型负载哈希校验失败: $relative"
            }
        }
        Move-Item -LiteralPath $partial -Destination $target -Force
    }
    $completed += 1
    Write-Progress `
        -Activity "安装 Woosh Studio 音乐模型" `
        -Status "$relative ($completed/$($records.Count))" `
        -PercentComplete ([int](100 * $completed / [Math]::Max($records.Count, 1)))
}
Write-Progress -Activity "安装 Woosh Studio 音乐模型" -Completed
