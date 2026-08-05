param(
    [string]$Output = "$PSScriptRoot\..\desktop\src-tauri\app-icon.png"
)

Add-Type -AssemblyName System.Drawing
$size = 1024
$bitmap = [System.Drawing.Bitmap]::new($size, $size)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear([System.Drawing.Color]::Transparent)

$background = [System.Drawing.Drawing2D.GraphicsPath]::new()
$radius = 176
$background.AddArc(32, 32, $radius, $radius, 180, 90)
$background.AddArc($size - 32 - $radius, 32, $radius, $radius, 270, 90)
$background.AddArc($size - 32 - $radius, $size - 32 - $radius, $radius, $radius, 0, 90)
$background.AddArc(32, $size - 32 - $radius, $radius, $radius, 90, 90)
$background.CloseFigure()
$graphics.FillPath([System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 21, 23, 26)), $background)

$heights = @(124, 248, 356, 512, 680, 442, 264, 532, 760, 532, 264, 442, 680, 512, 356, 248, 124)
$barWidth = 26
$gap = 25
$totalWidth = $heights.Count * $barWidth + ($heights.Count - 1) * $gap
$x = ($size - $totalWidth) / 2
$brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 55, 137, 237))
foreach ($height in $heights) {
    $y = ($size - $height) / 2
    $graphics.FillRectangle($brush, $x, $y, $barWidth, $height)
    $x += $barWidth + $gap
}

$directory = Split-Path -Parent $Output
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$bitmap.Save($Output, [System.Drawing.Imaging.ImageFormat]::Png)
$brush.Dispose()
$background.Dispose()
$graphics.Dispose()
$bitmap.Dispose()
Write-Output $Output
