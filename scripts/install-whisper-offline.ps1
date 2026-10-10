param(
    [string]$PackageRoot = $PSScriptRoot,
    [string]$ModelRoot = "",
    [string]$InstallDirectory = "",
    [switch]$VerifyOnly
)
$ErrorActionPreference = "Stop"
$package = (Resolve-Path -LiteralPath $PackageRoot).Path
$manifest = Get-Content -LiteralPath (Join-Path $package "package-manifest.json") -Raw | ConvertFrom-Json
function Resolve-Child([string]$Parent, [string]$Child) {
    $parentPath = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\')
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $parentPath $Child))
    if (-not $candidate.StartsWith($parentPath + '\', [System.StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe package path: $Child" }
    return $candidate
}
function Assert-Hash([string]$File, [long]$Size, [string]$Hash) {
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { throw "Missing payload: $File" }
    if ((Get-Item -LiteralPath $File).Length -ne $Size -or (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash -ine $Hash) { throw "Payload verification failed: $File" }
}
foreach($item in $manifest.files) {
    $file = Resolve-Child $package $item.path
    Write-Output "Verifying $($item.path)..."
    Assert-Hash $file $item.size_bytes $item.sha256
}
if($VerifyOnly) { Write-Output "Offline package verified."; exit 0 }
if([string]::IsNullOrWhiteSpace($ModelRoot)) { $ModelRoot = [Environment]::GetEnvironmentVariable('WOOSH_MODEL_HOME','User') }
if([string]::IsNullOrWhiteSpace($ModelRoot)) { $ModelRoot = $env:WOOSH_MODEL_HOME }
if([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $drive = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -ne 'C:\' -and $_.Free -gt 30000000000 } | Sort-Object Free -Descending | Select-Object -First 1
    if(-not $drive) { throw "Choose a non-system model directory using -ModelRoot." }
    $ModelRoot = Join-Path $drive.Root 'AIModels\WooshStudio'
}
$ModelRoot = [System.IO.Path]::GetFullPath($ModelRoot).TrimEnd('\')
if([System.IO.Path]::GetPathRoot($ModelRoot) -ieq 'C:\' -or $ModelRoot -eq [System.IO.Path]::GetPathRoot($ModelRoot).TrimEnd('\')) { throw "Models must use a non-system subdirectory." }
New-Item -ItemType Directory -Force -Path $ModelRoot | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Expand-Safe([string]$Archive, [string]$Destination) {
    $bundle = [System.IO.Compression.ZipFile]::OpenRead($Archive)
    try { foreach($entry in $bundle.Entries) { if($entry.FullName.TrimEnd('/')) { $null = Resolve-Child $Destination ($entry.FullName.Replace('/','\').TrimEnd('\')) } } }
    finally { $bundle.Dispose() }
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Destination)
}
function Test-Runtime([string]$Directory) {
    $file = Join-Path $Directory 'runtime-manifest.json'
    if(-not (Test-Path -LiteralPath $file)) { return $false }
    try {
        $data = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
        if($data.version -ne $manifest.runtime_version -or -not (Test-Path -LiteralPath (Join-Path $Directory 'uv-cache'))) { return $false }
        foreach($entry in $data.files) { Assert-Hash (Resolve-Child $Directory $entry.path) $entry.size_bytes $entry.sha256 }
        return $true
    } catch { return $false }
}
function Test-Model([string]$Directory, [object[]]$Records = $manifest.model_files) {
    try { foreach($entry in $Records) { Assert-Hash (Resolve-Child $Directory $entry.path) $entry.size_bytes $entry.sha256 }; return $true }
    catch { return $false }
}
function Install-Payload([string]$Archive, [string]$Inner, [string]$TargetName, [string]$Kind, [object[]]$Records = $manifest.model_files) {
    $target = Resolve-Child $ModelRoot $TargetName
    $ready = if($Kind -eq 'runtime') { Test-Runtime $target } else { Test-Model $target $Records }
    if($ready) { Write-Output "Ready: $TargetName"; return }
    $staging = Resolve-Child $ModelRoot ('.woosh-install-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $staging | Out-Null
    try {
        Expand-Safe (Resolve-Child $package $Archive) $staging
        $source = Resolve-Child $staging $Inner
        $valid = if($Kind -eq 'runtime') { Test-Runtime $source } else { Test-Model $source $Records }
        if(-not $valid) { throw "Extracted payload invalid: $TargetName" }
        if(Test-Path -LiteralPath $target) {
            $backup = Resolve-Child $ModelRoot ($TargetName + '.previous-' + [guid]::NewGuid().ToString('N'))
            # Both resolved directories were checked to remain under ModelRoot.
            Move-Item -LiteralPath $target -Destination $backup
            Write-Output "Preserved previous files: $backup"
        }
        $verifiedSource = Resolve-Child $staging $Inner
        $verifiedTarget = Resolve-Child $ModelRoot $TargetName
        Move-Item -LiteralPath $verifiedSource -Destination $verifiedTarget
    } finally {
        $verifiedStaging = Resolve-Child $ModelRoot (Split-Path -Leaf $staging)
        if(Test-Path -LiteralPath $verifiedStaging) { Remove-Item -LiteralPath $verifiedStaging -Recurse -Force }
    }
}
# Close the app gracefully before upgrading; never discard unsaved work forcibly.
foreach($app in (Get-Process -Name 'woosh-studio' -ErrorAction SilentlyContinue)) {
    if(-not $app.CloseMainWindow() -or -not $app.WaitForExit(15000)) { throw "Save and close Woosh Studio, then run the installer again." }
}
Install-Payload $manifest.runtime_archive 'runtime' '.runtime' 'runtime'
Install-Payload $manifest.model_archive $manifest.model_id $manifest.model_id 'model'
foreach($model in $manifest.additional_models) { Install-Payload $model.archive $model.inner $model.id 'model' $model.files }
[Environment]::SetEnvironmentVariable('WOOSH_MODEL_HOME',$ModelRoot,'User')
$env:WOOSH_MODEL_HOME = $ModelRoot
if([string]::IsNullOrWhiteSpace($InstallDirectory)) {
    $installed = Get-ChildItem 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall' -ErrorAction SilentlyContinue | Get-ItemProperty | Where-Object { $_.DisplayName -eq 'Woosh Studio' -and $_.InstallLocation } | Select-Object -First 1
    $InstallDirectory = if($installed) { $installed.InstallLocation.Trim('"') } else { Join-Path ([System.IO.Path]::GetPathRoot($ModelRoot)) 'Apps\Woosh Studio' }
}
$msi = Resolve-Child $package $manifest.installer
$logDirectory = Resolve-Child $ModelRoot '.installation-logs'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$log = Resolve-Child $logDirectory ("Woosh-Studio-" + $manifest.version + '.log')
$env:TEMP = $logDirectory
$env:TMP = $logDirectory
$arguments = @('/i',('"' + $msi + '"'),'/qn','/norestart',('INSTALLDIR="' + $InstallDirectory + '"'),'/l*v',('"' + $log + '"'))
$installation = Start-Process -FilePath 'msiexec.exe' -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
if($installation.ExitCode -notin @(0,3010)) { throw "MSI installation failed ($($installation.ExitCode)). Log: $log" }
Write-Output "Woosh Studio $($manifest.version) installed at $InstallDirectory"
Write-Output "Whisper installed at $(Join-Path $ModelRoot $manifest.model_id)"
