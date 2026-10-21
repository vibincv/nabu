<#
.SYNOPSIS
  Install Nabu for this user on Windows (FR-1.2). No admin rights needed.

.DESCRIPTION
  Run from the release folder, which holds this script, the nabu wheel, requirements.txt and
  SHA256SUMS. Steps:
    1. Check every release file against SHA256SUMS.
    2. Get uv (pinned version, checksum checked) into %LOCALAPPDATA%\Nabu\uv.
    3. Create Nabu's own Python environment in %LOCALAPPDATA%\Nabu\app and install the
       hash-pinned requirements and the wheel. No system Python is used or changed.
    4. Hand over to `python -m nabu.install`: runtime, model, OCR packs, config, shortcut,
       test read. It asks before every download.
  Running it again changes nothing that is already in place and downloads nothing.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun
#>
param(
  [switch]$DryRun,     # print every detection and command, change nothing (FR-1.8)
  [switch]$Yes,        # answer yes to every download question
  [string]$Model = "auto",  # a model name, or "none" for no-model mode
  [switch]$NoShortcut
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$UvVersion = "0.12.19"
$UvZip = "uv-x86_64-pc-windows-msvc.zip"
$UvSha256 = "6dbb02d79e419522f1c500f0adb1cddcff0cda7d59b0d66ea7f5e3b4a1b2f5f0"
$UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$UvZip"
$PythonVersion = "3.12"

$Here = $PSScriptRoot
$Root = Join-Path $env:LOCALAPPDATA "Nabu"
$UvDir = Join-Path $Root "uv"
$Uv = Join-Path $UvDir "uv.exe"
$App = Join-Path $Root "app"
$Py = Join-Path $App "Scripts\python.exe"

function Say([string]$s) { Write-Host $s }
function Show([string[]]$cmd) { Say ("  $ " + (($cmd | ForEach-Object { if ($_ -match " ") { "`"$_`"" } else { $_ } }) -join " ")) }
function Fail([string]$s) { Write-Host "nabu install: $s" -ForegroundColor Red; exit 1 }
function Run([string]$exe, [string[]]$argv) {
  Show (@($exe) + $argv)
  & $exe @argv
  if ($LASTEXITCODE -ne 0) { Fail "the command above failed (exit $LASTEXITCODE)" }
}

if ([Environment]::Is64BitOperatingSystem -eq $false -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
  Fail "this release is for 64-bit Windows on x86-64 (found $env:PROCESSOR_ARCHITECTURE)"
}

# 1. Release files (FR-1.12)
$sums = Join-Path $Here "SHA256SUMS"
if (-not (Test-Path $sums)) { Fail "SHA256SUMS is missing next to install.ps1" }
$wheel = $null
foreach ($line in Get-Content $sums) {
  if ($line -notmatch "^([0-9a-f]{64})\s+\*?(.+)$") { continue }
  $want = $Matches[1]; $name = $Matches[2].Trim()
  $file = Join-Path $Here $name
  if (-not (Test-Path $file)) { Fail "$name is listed in SHA256SUMS but missing" }
  $got = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLower()
  if ($got -ne $want) { Fail "$name does not match its checksum in SHA256SUMS; the release folder is damaged" }
  if ($name -like "nabu-*.whl") { $wheel = $file }
}
if (-not $wheel) { Fail "no nabu wheel listed in SHA256SUMS" }
$req = Join-Path $Here "requirements.txt"
Say "Release files checked against SHA256SUMS."

# 2. uv
$haveUv = (Test-Path $Uv) -and ((& $Uv --version 2>$null) -match [regex]::Escape($UvVersion))
if ($haveUv) {
  Say "uv $UvVersion already in place: $Uv"
} elseif ($DryRun) {
  Say "Would download uv $UvVersion ($UvUrl), check sha256 $UvSha256, unpack to $UvDir"
} else {
  New-Item -ItemType Directory -Force $UvDir | Out-Null
  $zip = Join-Path $env:TEMP $UvZip
  Say "Downloading uv $UvVersion"
  Invoke-WebRequest -Uri $UvUrl -OutFile $zip -UseBasicParsing
  if ((Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower() -ne $UvSha256) {
    Remove-Item $zip -Force
    Fail "$UvZip does not match the checksum shipped with Nabu; it was deleted and nothing was installed"
  }
  Expand-Archive -Path $zip -DestinationPath $UvDir -Force
  Remove-Item $zip -Force
  Say "uv $UvVersion installed: $Uv"
}

# 3. Nabu's own Python environment
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Root "python"
$env:UV_NO_CACHE = "1"  # nothing reuses a cache: a re-run skips installed steps
$wheelVersion = ([IO.Path]::GetFileName($wheel) -split "-")[1]
$wheelSha = (Get-FileHash -Algorithm SHA256 $wheel).Hash.ToLower()
$marker = Join-Path $App "nabu-wheel.sha256"  # which wheel is installed; same version can differ
$haveApp = (Test-Path $Py) -and (Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq $wheelSha)
if ($haveApp) {
  Say "Nabu $wheelVersion already installed: $App"
} elseif ($DryRun) {
  Say "Would create $App with Python $PythonVersion and install:"
  Show @($Uv, "venv", $App, "--python", $PythonVersion)
  Show @($Uv, "pip", "install", "--python", $Py, "--require-hashes", "-r", $req)
  Show @($Uv, "pip", "install", "--python", $Py, "--no-deps", $wheel)
} else {
  if (-not (Test-Path $Py)) { Run $Uv @("venv", $App, "--python", $PythonVersion) }
  Run $Uv @("pip", "install", "--python", $Py, "--require-hashes", "-r", $req)
  Run $Uv @("pip", "install", "--python", $Py, "--no-deps", "--reinstall-package", "nabu", $wheel)
  Set-Content -Path $marker -Value $wheelSha -Encoding ascii
  Say "Nabu $wheelVersion installed: $App"
}

# 4. Runtime, model, OCR packs, config, shortcut, test read
if (-not (Test-Path $Py)) {
  Say ""
  Say "Dry run: Nabu is not installed yet, so the model and OCR plan is printed after the real install."
  Say "Dry run: nothing was changed."
  exit 0
}
$argv = @("-m", "nabu.install", "--model", $Model)
if ($DryRun) { $argv += "--dry-run" }
if ($Yes) { $argv += "--yes" }
if ($NoShortcut) { $argv += "--no-shortcut" }
Say ""
& $Py @argv
exit $LASTEXITCODE
