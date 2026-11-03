param(
    [Parameter(Mandatory = $true)]
    [string]$ComfyUIPath
)

$ErrorActionPreference = 'Stop'
$comfyRoot = (Resolve-Path -LiteralPath $ComfyUIPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $comfyRoot 'main.py') -PathType Leaf)) {
    throw 'Choose the ComfyUI folder containing main.py, for example C:\path\to\ComfyUI.'
}
$archive = Join-Path $PSScriptRoot 'nodeui_bridge.zip'
if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    throw 'Keep nodeui_bridge.zip beside this installer.'
}
$customNodes = Join-Path $comfyRoot 'custom_nodes'
$destination = Join-Path $customNodes 'nodeui_bridge'
$staging = "$destination.installing-$PID"
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("NodeUI-" + [guid]::NewGuid().ToString())
$backup = $null
$legacyBackup = $null
$legacy = Join-Path $customNodes 'comfymobile_bridge'
$installed = $false
$stagingOwned = $false
try {
    New-Item -ItemType Directory -Path $temporary -Force | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $temporary
    $prepared = Join-Path $temporary 'nodeui_bridge'
    foreach ($file in @('__init__.py', 'filesystem.py', 'routes.py', 'downloads.py', 'resources.py', 'resource_gpu.py', 'resource_windows.py')) {
        if (-not (Test-Path -LiteralPath (Join-Path $prepared $file) -PathType Leaf)) {
            throw "The archive is missing runtime file $file."
        }
    }
    New-Item -ItemType Directory -Path $customNodes -Force | Out-Null
    if (Test-Path -LiteralPath $staging) { throw "Remove the incomplete staging folder before retrying: $staging" }
    $stagingOwned = $true
    Copy-Item -LiteralPath $prepared -Destination $staging -Recurse
    if (Test-Path -LiteralPath $destination) {
        $backupFolder = Join-Path $comfyRoot '.nodeui-backups'
        New-Item -ItemType Directory -Path $backupFolder -Force | Out-Null
        $backup = Join-Path $backupFolder "nodeui_bridge-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$PID"
        if (Test-Path -LiteralPath $backup) { throw "Backup already exists: $backup" }
        Move-Item -LiteralPath $destination -Destination $backup
    }
    if (Test-Path -LiteralPath $legacy) {
        $backupFolder = Join-Path $comfyRoot '.nodeui-backups'
        New-Item -ItemType Directory -Path $backupFolder -Force | Out-Null
        $legacyBackup = Join-Path $backupFolder "legacy-bridge-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$PID"
        if (Test-Path -LiteralPath $legacyBackup) { throw "Backup already exists: $legacyBackup" }
        Move-Item -LiteralPath $legacy -Destination $legacyBackup
    }
    Move-Item -LiteralPath $staging -Destination $destination
    $installed = $true
    Write-Host "Installed: $destination"
    if ($backup) { Write-Host "Previous version preserved: $backup" }
    Write-Host 'Wait until the ComfyUI queue is idle, then restart ComfyUI once.'
    Write-Host 'Verify: Invoke-RestMethod http://localhost:8188/nodeui/v1/capabilities'
}
finally {
    if (-not $installed -and $backup -and (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $destination)) {
        Move-Item -LiteralPath $backup -Destination $destination
    }
    if (-not $installed -and $legacyBackup -and (Test-Path -LiteralPath $legacyBackup) -and -not (Test-Path -LiteralPath $legacy)) {
        Move-Item -LiteralPath $legacyBackup -Destination $legacy
    }
    if ($stagingOwned -and (Test-Path -LiteralPath $staging)) { Remove-Item -LiteralPath $staging -Recurse -Force }
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
