param(
    [Parameter(Mandatory = $true)][string]$ReleaseRoot,
    [Parameter(Mandatory = $true)][string]$AppName
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3
$root = [IO.Path]::GetFullPath($ReleaseRoot).TrimEnd('\')
$shortcutPath = Join-Path $root "$AppName.lnk"
$item = Get-Item -LiteralPath $shortcutPath -Force
if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'The installed shortcut is not a normal file.'
}
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcutPath)
try {
    $target = Join-Path $root '.runtime\python\pythonw.exe'
    $expectedArguments = '-I "' + (Join-Path $root "$AppName.pyw") + '"'
    if ([IO.Path]::GetFullPath($link.TargetPath) -ine [IO.Path]::GetFullPath($target)) {
        throw 'The installed shortcut points to the wrong Python runtime.'
    }
    if ($link.Arguments -cne $expectedArguments) { throw 'The installed shortcut has unexpected arguments.' }
    if ([IO.Path]::GetFullPath($link.WorkingDirectory).TrimEnd('\') -ine $root) {
        throw 'The installed shortcut has the wrong working directory.'
    }
    if ($link.Description -cne $AppName -or [int]$link.WindowStyle -ne 1 -or $link.Hotkey) {
        throw 'The installed shortcut has unexpected metadata.'
    }
    if (($link.IconLocation -replace ',\s+', ',') -ine ($target + ',0')) {
        throw 'The installed shortcut has the wrong icon.'
    }
    Write-Host "Shortcut contract passed: $shortcutPath"
} finally {
    if ($link) { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($link) | Out-Null }
    if ($shell) { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null }
}

