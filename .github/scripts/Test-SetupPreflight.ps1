param(
    [Parameter(Mandatory = $true)][string]$ReleaseRoot,
    [Parameter(Mandatory = $true)][string]$AppName
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3

$root = [IO.Path]::GetFullPath($ReleaseRoot).TrimEnd('\')
$scratchBase = [IO.Path]::GetFullPath($(if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() })).TrimEnd('\')
$scratch = Join-Path $scratchBase ('pf-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
[IO.Directory]::CreateDirectory($scratch) | Out-Null
$expected = @('Installer.bat', 'LICENSE', "$AppName.pyw", 'READ ME.txt', 'requirements-win-arm64.txt', 'requirements-win-x64.txt')
foreach ($name in $expected) {
    if (-not [IO.File]::Exists((Join-Path $root $name))) { throw "Release ZIP omitted $name." }
}

function New-Fixture([string]$Name, [string[]]$Omit = @(), [switch]$EmptySource, [switch]$BlockShortcut) {
    $target = Join-Path $scratch $Name
    [IO.Directory]::CreateDirectory($target) | Out-Null
    foreach ($file in $expected) {
        if ($file -in $Omit) { continue }
        $destination = Join-Path $target $file
        if ($EmptySource -and $file -eq "$AppName.pyw") {
            [IO.File]::WriteAllBytes($destination, [byte[]]@())
        } else {
            [IO.File]::Copy((Join-Path $root $file), $destination)
        }
    }
    if ($BlockShortcut) { [IO.Directory]::CreateDirectory((Join-Path $target "$AppName.lnk")) | Out-Null }
    return $target
}

function Assert-EarlyFailure([string]$Target, [string]$ExpectedMessage, [switch]$NoLocalState) {
    Push-Location -LiteralPath $Target
    try {
        $output = & "$env:SystemRoot\System32\cmd.exe" /d /s /c 'call "Installer.bat" --yes --no-pause' 2>&1
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    $text = $output -join "`n"
    if ($code -ne 1) { throw "Expected setup failure in $Target; exit code was $code.`n$text" }
    if ($text -notmatch [regex]::Escape($ExpectedMessage)) {
        throw "Expected error was absent in $Target.`n$text"
    }
    if ($text -notmatch 'How to fix:' -or $text -match 'Downloading and preparing private Python') {
        throw "Failure guidance was absent or setup attempted downloads in $Target.`n$text"
    }
    if ($NoLocalState) {
        foreach ($name in @('.runtime', 'setup.log', "$AppName.lnk")) {
            if (Test-Path -LiteralPath (Join-Path $Target $name)) {
                throw "Failure changed setup state before path validation: $name"
            }
        }
    }
    $downloads = Join-Path $Target '.runtime\downloads'
    if (Test-Path -LiteralPath $downloads) {
        if (@(Get-ChildItem -LiteralPath $downloads -File -Recurse).Count -ne 0) {
            throw "Failure left a downloaded file in $Target."
        }
    }
    Write-Host "Early failure passed: $ExpectedMessage"
}

$missingLicense = New-Fixture 'missing license' -Omit @('LICENSE')
Assert-EarlyFailure $missingLicense 'The bundled Tool License is missing' -NoLocalState
$missingApp = New-Fixture 'missing app' -Omit @("$AppName.pyw")
Assert-EarlyFailure $missingApp "$AppName.pyw is missing, empty, or unsafe"
$emptyApp = New-Fixture 'empty app' -EmptySource
Assert-EarlyFailure $emptyApp "$AppName.pyw is missing, empty, or unsafe"
$blockedShortcut = New-Fixture 'blocked shortcut' -BlockShortcut
Assert-EarlyFailure $blockedShortcut 'Windows shortcut support could not be verified before downloads'
$longPath = New-Fixture ('p' * 65)
if ($longPath.Length -le 72) { throw 'The long-path fixture was not long enough.' }
Assert-EarlyFailure $longPath 'The complete app folder path must be 72 characters or fewer' -NoLocalState
Write-Host 'All early setup preflight negatives passed.'
exit 0
