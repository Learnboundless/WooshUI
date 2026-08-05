param(
    [Parameter(Mandatory = $true)]
    [string]$SourceWxs,
    [Parameter(Mandatory = $true)]
    [string]$LocaleWxl,
    [Parameter(Mandatory = $true)]
    [string]$ModelArchiveDirectory,
    [Parameter(Mandatory = $true)]
    [string]$LicenseFile,
    [Parameter(Mandatory = $true)]
    [string]$OutputMsi,
    [string]$WixTools = (Join-Path $env:LOCALAPPDATA "tauri\WixTools314")
)

$ErrorActionPreference = "Stop"

foreach ($path in @($SourceWxs, $LocaleWxl, $ModelArchiveDirectory, $LicenseFile)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required MSI input is missing: $path"
    }
}

$requiredArchives = @(
    "Woosh-DFlow.zip",
    "Woosh-Flow.zip",
    "Woosh-AE.zip",
    "TextConditionerA.zip"
)
foreach ($archive in $requiredArchives) {
    $path = Join-Path $ModelArchiveDirectory $archive
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required model archive is missing: $path"
    }
}

$candle = Join-Path $WixTools "candle.exe"
$light = Join-Path $WixTools "light.exe"
if (-not (Test-Path -LiteralPath $candle) -or -not (Test-Path -LiteralPath $light)) {
    throw "WiX 3.14 tools were not found. Run a Tauri MSI build first."
}

$workDirectory = Join-Path `
    (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $OutputMsi))) `
    ".wix-models"
New-Item -ItemType Directory -Force -Path $workDirectory | Out-Null
$customWxs = Join-Path $workDirectory "main-models.wxs"
$customWixObject = Join-Path $workDirectory "main-models.wixobj"

[xml]$document = Get-Content -LiteralPath $SourceWxs -Raw
$namespace = $document.DocumentElement.NamespaceURI
$namespaceManager = [System.Xml.XmlNamespaceManager]::new($document.NameTable)
$namespaceManager.AddNamespace("w", $namespace)

function New-WixElement([string]$name) {
    return $document.CreateElement($name, $namespace)
}

function Set-WixAttributes($element, [hashtable]$attributes) {
    foreach ($entry in $attributes.GetEnumerator()) {
        $element.SetAttribute([string]$entry.Key, [string]$entry.Value)
    }
}

$product = $document.SelectSingleNode("//w:Product", $namespaceManager)
$installDirectory = $document.SelectSingleNode(
    "//w:DirectoryRef[@Id='INSTALLDIR']",
    $namespaceManager
)
$externalFeature = $document.SelectSingleNode(
    "//w:Feature[@Id='External']",
    $namespaceManager
)
if ($null -eq $product -or $null -eq $installDirectory -or $null -eq $externalFeature) {
    throw "The generated Tauri WiX layout is not compatible with the model installer builder."
}

$ui = $document.SelectSingleNode("//w:Product/w:UI", $namespaceManager)
$uiReference = $document.SelectSingleNode(
    "//w:UIRef[@Id='WixUI_InstallDir']",
    $namespaceManager
)
if ($null -eq $ui -or $null -eq $uiReference) {
    throw "The generated Tauri WiX UI layout was not found."
}
$welcomeNext = $ui.SelectSingleNode(
    "w:Publish[@Dialog='WelcomeDlg'][@Control='Next'][@Value='InstallDirDlg']",
    $namespaceManager
)
if ($null -eq $welcomeNext) {
    throw "The generated Tauri welcome navigation was not found."
}
$welcomeNext.SetAttribute("Value", "ModelSelectionDlg")

Set-WixAttributes $externalFeature @{
    Title = "可选离线模型 (CC BY-NC 4.0)"
    Description = "选择随程序安装的 Sony Woosh 非商业研究模型。共享依赖只安装一次。"
    Display = "hidden"
    Level = "1"
}

$modelDirectory = New-WixElement "Directory"
Set-WixAttributes $modelDirectory @{
    Id = "OfflineModelArchives"
    Name = "offline-model-archives"
}
$installDirectory.AppendChild($modelDirectory) | Out-Null

$components = @(
    @{
        Id = "ModelArchiveDFlow"
        FileId = "ModelFileDFlow"
        FileName = "Woosh-DFlow.zip"
        Guid = "dfcceaf0-4f68-5aa4-a9cd-55c6578fd653"
    },
    @{
        Id = "ModelArchiveFlow"
        FileId = "ModelFileFlow"
        FileName = "Woosh-Flow.zip"
        Guid = "ca0f82a7-4cf7-5a2a-880f-c06dfbaad5b4"
    },
    @{
        Id = "ModelArchiveAE"
        FileId = "ModelFileAE"
        FileName = "Woosh-AE.zip"
        Guid = "4103ce76-cc10-56b4-a0f4-5e97f397f70f"
    },
    @{
        Id = "ModelArchiveTextConditioner"
        FileId = "ModelFileTextConditioner"
        FileName = "TextConditionerA.zip"
        Guid = "0df76bbd-d198-5df7-83eb-cc050851d2e0"
    }
)

foreach ($definition in $components) {
    $component = New-WixElement "Component"
    Set-WixAttributes $component @{
        Id = $definition.Id
        Guid = $definition.Guid
        Win64 = '$(var.Win64)'
    }
    $file = New-WixElement "File"
    Set-WixAttributes $file @{
        Id = $definition.FileId
        Name = $definition.FileName
        Source = (Join-Path $ModelArchiveDirectory $definition.FileName)
        KeyPath = "yes"
        Compressed = "no"
        DiskId = "1"
    }
    $component.AppendChild($file) | Out-Null
    $modelDirectory.AppendChild($component) | Out-Null
}

$licenseComponent = New-WixElement "Component"
Set-WixAttributes $licenseComponent @{
    Id = "ModelLicenseNotice"
    Guid = "f83721a5-e1e6-53d2-bb7f-b86e75dc9619"
    Win64 = '$(var.Win64)'
}
$license = New-WixElement "File"
Set-WixAttributes $license @{
    Id = "ModelLicenseFile"
    Name = "MODEL_LICENSES.md"
    Source = $LicenseFile
    KeyPath = "yes"
}
$licenseComponent.AppendChild($license) | Out-Null
$modelDirectory.AppendChild($licenseComponent) | Out-Null

function Add-ModelFeature(
    [string]$id,
    [string]$title,
    [string]$description,
    [string[]]$componentIds,
    [int]$level
) {
    $feature = New-WixElement "Feature"
    Set-WixAttributes $feature @{
        Id = $id
        Title = $title
        Description = $description
        Level = [string]$level
        AllowAdvertise = "no"
        Absent = "allow"
    }
    foreach ($componentId in $componentIds) {
        $reference = New-WixElement "ComponentRef"
        $reference.SetAttribute("Id", $componentId)
        $feature.AppendChild($reference) | Out-Null
    }
    $externalFeature.AppendChild($feature) | Out-Null
}

$sharedComponents = @("ModelArchiveAE", "ModelArchiveTextConditioner", "ModelLicenseNotice")
Add-ModelFeature `
    "OfflineDFlow" `
    "Woosh-DFlow 快速模型" `
    "默认四步生成模型；同时安装 Woosh-AE 与 TextConditionerA。" `
    (@("ModelArchiveDFlow") + $sharedComponents) `
    1
Add-ModelFeature `
    "OfflineFlow" `
    "Woosh-Flow 质量模型" `
    "完整流匹配模型；同时安装 Woosh-AE 与 TextConditionerA。" `
    (@("ModelArchiveFlow") + $sharedComponents) `
    2

$dflowProperty = New-WixElement "Property"
Set-WixAttributes $dflowProperty @{
    Id = "INSTALL_DFLOW"
    Value = "1"
}
$product.InsertBefore($dflowProperty, $ui) | Out-Null

$dialog = New-WixElement "Dialog"
Set-WixAttributes $dialog @{
    Id = "ModelSelectionDlg"
    Width = "370"
    Height = "270"
    Title = "[ProductName] 安装"
}
$ui.AppendChild($dialog) | Out-Null

function Add-DialogControl(
    [string]$id,
    [string]$type,
    [int]$x,
    [int]$y,
    [int]$width,
    [int]$height,
    [string]$text,
    [hashtable]$extra = @{}
) {
    $control = New-WixElement "Control"
    $attributes = @{
        Id = $id
        Type = $type
        X = [string]$x
        Y = [string]$y
        Width = [string]$width
        Height = [string]$height
    }
    if ($text) {
        $attributes.Text = $text
    }
    foreach ($entry in $extra.GetEnumerator()) {
        $attributes[$entry.Key] = $entry.Value
    }
    Set-WixAttributes $control $attributes
    $dialog.AppendChild($control) | Out-Null
}

Add-DialogControl "Title" "Text" 15 8 340 24 "{\WixUI_Font_Title}选择离线模型" @{
    Transparent = "yes"
    NoPrefix = "yes"
}
Add-DialogControl "Intro" "Text" 20 42 330 30 "模型会从安装包本地复制，首次启动时自动验证并解压。也可以全部不选，稍后在应用内下载。" @{
    NoPrefix = "yes"
}
Add-DialogControl "DFlow" "CheckBox" 24 83 320 20 "Woosh-DFlow 快速模型（约 3.17 GiB，推荐）" @{
    Property = "INSTALL_DFLOW"
    CheckBoxValue = "1"
}
Add-DialogControl "DFlowInfo" "Text" 43 105 300 24 "适合快速生成与批量探索，自动包含 Woosh-AE 和 TextConditionerA。" @{
    NoPrefix = "yes"
}
Add-DialogControl "Flow" "CheckBox" 24 139 320 20 "Woosh-Flow 质量模型（约 3.14 GiB）" @{
    Property = "INSTALL_FLOW"
    CheckBoxValue = "1"
}
Add-DialogControl "FlowInfo" "Text" 43 161 300 24 "开放 CFG、ODE solver 与容差设置；与 DFlow 共享依赖。" @{
    NoPrefix = "yes"
}
Add-DialogControl "SpaceInfo" "Text" 20 194 330 28 "同时选择两个模型共约 4.35 GiB。选择模型即表示接受 CC BY-NC 4.0，仅限研究和非商业用途。" @{
    NoPrefix = "yes"
}
Add-DialogControl "BottomLine" "Line" 0 234 370 0 ""
Add-DialogControl "Back" "PushButton" 180 243 56 17 "上一步"
Add-DialogControl "Next" "PushButton" 236 243 56 17 "下一步" @{
    Default = "yes"
}
Add-DialogControl "Cancel" "PushButton" 304 243 56 17 "取消" @{
    Cancel = "yes"
}

function Add-Publish(
    [string]$dialogId,
    [string]$controlId,
    [string]$event,
    [string]$value,
    [int]$order,
    [string]$condition
) {
    $publish = New-WixElement "Publish"
    Set-WixAttributes $publish @{
        Dialog = $dialogId
        Control = $controlId
        Event = $event
        Value = $value
        Order = [string]$order
    }
    $publish.InnerText = $condition
    $ui.AppendChild($publish) | Out-Null
}

# Put model selection immediately after WelcomeDlg so WixUI cannot skip it.
Add-Publish "ModelSelectionDlg" "Back" "NewDialog" "WelcomeDlg" 1 "1"
Add-Publish "ModelSelectionDlg" "Next" "AddLocal" "OfflineDFlow" 1 'INSTALL_DFLOW = "1"'
Add-Publish "ModelSelectionDlg" "Next" "Remove" "OfflineDFlow" 2 'INSTALL_DFLOW <> "1"'
Add-Publish "ModelSelectionDlg" "Next" "AddLocal" "OfflineFlow" 3 'INSTALL_FLOW = "1"'
Add-Publish "ModelSelectionDlg" "Next" "Remove" "OfflineFlow" 4 'INSTALL_FLOW <> "1"'
Add-Publish "ModelSelectionDlg" "Next" "NewDialog" "InstallDirDlg" 5 "1"
Add-Publish "ModelSelectionDlg" "Cancel" "SpawnDialog" "CancelDlg" 1 "1"

$settings = [System.Xml.XmlWriterSettings]::new()
$settings.Encoding = [System.Text.UTF8Encoding]::new($false)
$settings.Indent = $true
$writer = [System.Xml.XmlWriter]::Create($customWxs, $settings)
try {
    $document.Save($writer)
}
finally {
    $writer.Dispose()
}

& $candle -nologo -arch x64 -ext WixUIExtension -out $customWixObject $customWxs
if ($LASTEXITCODE -ne 0) {
    throw "WiX candle failed for the selectable-model installer."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputMsi) | Out-Null
& $light `
    -nologo `
    -ext WixUIExtension `
    -cultures:zh-cn `
    -loc $LocaleWxl `
    -pdbout (Join-Path $workDirectory "main-models.wixpdb") `
    -out $OutputMsi `
    $customWixObject
if ($LASTEXITCODE -ne 0) {
    throw "WiX light failed for the selectable-model installer."
}

Get-Item -LiteralPath $OutputMsi | Select-Object FullName, Length, LastWriteTime
