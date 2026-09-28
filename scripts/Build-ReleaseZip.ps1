param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$output = [IO.Path]::GetFullPath($OutputPath)
$appName = 'Lua Obfuscator'
$archiveStem = 'Lua-Obfuscator'
$releaseFiles = @('Lua Obfuscator.pyw', 'Installer.bat', 'LICENSE', 'READ ME.txt', 'requirements-win-arm64.txt', 'requirements-win-x64.txt')

function Read-TrackedBlob([string]$RelativePath) {
    $start = [Diagnostics.ProcessStartInfo]::new('git')
    $start.WorkingDirectory = $root
    $start.ArgumentList.Add('cat-file')
    $start.ArgumentList.Add('blob')
    $start.ArgumentList.Add("HEAD:$RelativePath")
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($start)
    try {
        $buffer = [IO.MemoryStream]::new()
        try {
            $process.StandardOutput.BaseStream.CopyTo($buffer)
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) {
                throw ('Could not read committed release input {0}: {1}' -f $RelativePath, $process.StandardError.ReadToEnd())
            }
            return ,$buffer.ToArray()
        } finally { $buffer.Dispose() }
    } finally { $process.Dispose() }
}

$outputDirectory = [IO.Path]::GetDirectoryName($output)
if (-not [IO.Directory]::Exists($outputDirectory)) { throw "Output directory does not exist: $outputDirectory" }
if ([IO.File]::Exists($output) -or [IO.Directory]::Exists($output)) {
    throw "Refusing to overwrite an existing release archive: $output"
}

Push-Location -LiteralPath $root
try {
    $dirty = @(& git status --porcelain --untracked-files=normal)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw 'The release source tree must be clean before packaging.' }
    $commit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not resolve the release commit.' }
    $source = [Text.UTF8Encoding]::new($false, $true).GetString((Read-TrackedBlob "$appName.pyw"))
    $versionMatch = [regex]::Match($source, '(?m)^APP_VERSION = "(?<version>\d+\.\d+\.\d+)"\s*$')
    if (-not $versionMatch.Success) { throw 'The app has no unambiguous release version.' }
    $version = $versionMatch.Groups['version'].Value
    if ([IO.Path]::GetFileName($output) -cne "$archiveStem-v$version.zip") {
        throw "The archive filename must be $archiveStem-v$version.zip."
    }
    $paths = @($releaseFiles | Sort-Object -CaseSensitive)
    if ($paths.Count -ne 6 -or (@($paths | Select-Object -Unique)).Count -ne 6) {
        throw 'The explicit release file list is incomplete or contains duplicates.'
    }
    $committed = @{}
    foreach ($relative in $paths) {
        $item = Get-Item -LiteralPath (Join-Path $root $relative) -Force
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $item.Length -lt 1) {
            throw "Release input is missing, empty, or unsafe: $relative"
        }
        $blob = [byte[]](Read-TrackedBlob $relative)
        if ($relative -eq 'Installer.bat') {
            # Git stores LF; the distributed Windows batch file must use CRLF.
            $batchText = [Text.UTF8Encoding]::new($false, $true).GetString($blob)
            if ($batchText.Contains([char]13)) { throw 'Committed Installer.bat contains unexpected CR bytes.' }
            $blob = [Text.UTF8Encoding]::new($false).GetBytes(
                $batchText.Replace([string][char]10, ([string][char]13 + [string][char]10))
            )
        }
        if ($blob.Length -lt 1) { throw "Committed release input is empty: $relative" }
        $committed[$relative] = $blob
    }

    Add-Type -AssemblyName System.IO.Compression
    $stamp = [DateTimeOffset]::Parse('2026-09-27T10:00:00+00:00')
    $stream = [IO.File]::Open($output, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create, $true)
        try {
            foreach ($relative in $paths) {
                $entry = $zip.CreateEntry($relative, [IO.Compression.CompressionLevel]::Optimal)
                $entry.LastWriteTime = $stamp
                $target = $entry.Open()
                try {
                    $bytes = [byte[]]$committed[$relative]
                    $target.Write($bytes, 0, $bytes.Length)
                } finally { $target.Dispose() }
            }
        } finally { $zip.Dispose() }
    } finally { $stream.Dispose() }

    $check = [IO.Compression.ZipFile]::OpenRead($output)
    try {
        $actual = @($check.Entries | ForEach-Object FullName)
        if ($actual.Count -ne $paths.Count -or (Compare-Object $paths $actual)) {
            throw 'The completed archive entry list does not match the release file list.'
        }
        foreach ($entry in $check.Entries) {
            $sourceHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([byte[]]$committed[$entry.FullName]))
            $input = $entry.Open()
            try {
                $sha = [Security.Cryptography.SHA256]::Create()
                try { $entryHash = [Convert]::ToHexString($sha.ComputeHash($input)) }
                finally { $sha.Dispose() }
            } finally { $input.Dispose() }
            if ($entryHash -cne $sourceHash) { throw "Archive content mismatch: $($entry.FullName)" }
        }
    } finally { $check.Dispose() }

    Write-Host "Release commit: $commit"
    Write-Host "Release version: $version"
    Write-Host "Archive files: $($paths.Count)"
    Write-Host "Archive bytes: $((Get-Item -LiteralPath $output).Length)"
    Write-Host "Archive SHA-256: $((Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash)"
    Write-Host "Archive path: $output"
} finally { Pop-Location }

