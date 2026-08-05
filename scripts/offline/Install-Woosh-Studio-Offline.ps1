$ErrorActionPreference = "Stop"
$packageRoot = $PSScriptRoot
$installer = Join-Path $packageRoot "Woosh-Studio-0.2.0-standard.exe"
$assets = @("Woosh-DFlow.zip", "Woosh-Flow.zip", "Woosh-AE.zip", "TextConditionerA.zip")

if (Get-Process "woosh-studio" -ErrorAction SilentlyContinue) {
    throw "Please close Woosh Studio before running the offline installer."
}

$installerProcess = Start-Process -FilePath $installer -Wait -PassThru
if ($installerProcess.ExitCode -ne 0) {
    throw "Woosh Studio installer exited with code $($installerProcess.ExitCode)."
}

$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Woosh Studio"
$registration = Get-ItemProperty -LiteralPath $uninstallKey -ErrorAction Stop
$installDirectory = $registration.InstallLocation.Trim('"')
$application = Join-Path $installDirectory "woosh-studio.exe"
if (-not (Test-Path -LiteralPath $application)) {
    throw "Woosh Studio installation directory was not found."
}

$archiveTarget = Join-Path $installDirectory "offline-model-archives"
$dataTarget = Join-Path $installDirectory "data"
$modelTarget = Join-Path $dataTarget "models"
New-Item -ItemType Directory -Force -Path $archiveTarget, $dataTarget, $modelTarget | Out-Null

function Copy-WithProgress([string]$Source, [string]$Destination, [string]$Label) {
    $input = [System.IO.File]::OpenRead($Source)
    try {
        $output = [System.IO.File]::Create($Destination)
        try {
            $buffer = New-Object byte[] (8MB)
            $copied = 0L
            while (($read = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $output.Write($buffer, 0, $read)
                $copied += $read
                Write-Progress -Activity "Installing offline models" -Status $Label -PercentComplete (100 * $copied / $input.Length)
            }
        }
        finally {
            $output.Dispose()
        }
    }
    finally {
        $input.Dispose()
    }
}

foreach ($asset in $assets) {
    Copy-WithProgress (Join-Path $packageRoot "model-archives\$asset") (Join-Path $archiveTarget $asset) $asset
}
Write-Progress -Activity "Installing offline models" -Completed
Copy-Item -LiteralPath (Join-Path $packageRoot "MODEL_LICENSES.md") -Destination (Join-Path $dataTarget "MODEL_LICENSES.md") -Force
Copy-Item -LiteralPath (Join-Path $packageRoot "model-manifest.json") -Destination (Join-Path $modelTarget "model-manifest.json") -Force

Start-Process -FilePath $application
