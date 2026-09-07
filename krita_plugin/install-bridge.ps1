# Install files explicitly: copying a directory onto an existing directory
# can create beeref_bridge/beeref_bridge, which shadows beeref_bridge.py.
$ErrorActionPreference = 'Stop'
$pluginRoot = [IO.Path]::GetFullPath((Join-Path $env:APPDATA 'krita\pykrita'))
$pluginTarget = [IO.Path]::GetFullPath((Join-Path $pluginRoot 'beeref_bridge'))
$backupRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'BeeRef\bridge-backups'))
$backupTarget = Join-Path $backupRoot ('beeref_bridge-' + [Guid]::NewGuid().ToString('N'))
$sourceRoot = Join-Path $PSScriptRoot 'beeref_bridge'

foreach ($name in @('__init__.py', 'beeref_bridge.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot $name) -PathType Leaf)) {
        throw "Missing bridge source: $name"
    }
}
$metadata = Join-Path $PSScriptRoot 'kritapykrita_beeref_bridge.desktop'
if (-not (Test-Path -LiteralPath $metadata -PathType Leaf)) {
    throw 'Missing Krita plugin metadata'
}

New-Item -ItemType Directory -Path $pluginRoot -Force | Out-Null
if (Test-Path -LiteralPath $pluginTarget) {
    # Check resolved paths before moving the entire old plugin, including
    # any nested copies, out of Krita's import search path. Keep it as backup.
    $resolvedTarget = (Resolve-Path -LiteralPath $pluginTarget).Path
    if (-not [String]::Equals($resolvedTarget, $pluginTarget, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected plugin path: $resolvedTarget"
    }
    if ((Get-Item -LiteralPath $pluginTarget).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Refusing to move a linked plugin directory'
    }
    if (-not $backupTarget.StartsWith($backupRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Backup path is outside the backup directory'
    }
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    Move-Item -LiteralPath $pluginTarget -Destination $backupTarget
    Write-Output "Previous plugin preserved at: $backupTarget"
}
New-Item -ItemType Directory -Path $pluginTarget | Out-Null
foreach ($name in @('__init__.py', 'beeref_bridge.py')) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination (Join-Path $pluginTarget $name)
}
Copy-Item -LiteralPath $metadata -Destination (Join-Path $pluginRoot 'kritapykrita_beeref_bridge.desktop') -Force
Write-Output "Installed bridge at: $pluginTarget"
Write-Output 'Restart Krita to load the corrected plugin.'
