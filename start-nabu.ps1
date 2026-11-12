<#
.SYNOPSIS
  Start Nabu (beta) on Windows from this git clone.

.DESCRIPTION
  1. Checks this machine: 64-bit Windows 10/11 on x86-64, memory, free disk, git and Node.
  2. Installs Nabu from this clone the first time, and again whenever the clone changed
     (git pull, local edits): builds the review window and the release, then runs
     install\install.ps1. That installer asks once before it downloads Ollama or a model and
     shows the sizes first.
  3. Every start: starts Ollama if it is stopped and checks that the set-up model is installed.
     If not, it runs the model setup again (which asks before downloading).
  4. Opens the review window. Nabu runs until you press "Quit Nabu" in the window or Ctrl+C here.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File start-nabu.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File start-nabu.ps1 -Setup -Model qwen3.5:4b
#>
param(
  [switch]$Setup,       # run the Ollama and model setup again (e.g. to add a model after "no")
  [switch]$Reinstall,   # rebuild and reinstall Nabu even if the clone did not change
  [string]$Model = "auto",  # a model name instead of the recommended one, or "none"
  [switch]$NoLaunch     # set everything up, but do not open Nabu
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Repo = $PSScriptRoot
$Root = Join-Path $env:LOCALAPPDATA "Nabu"
$App = Join-Path $Root "app"
$Py = Join-Path $App "Scripts\python.exe"
$Uv = Join-Path $Root "uv\uv.exe"
$Marker = Join-Path $App "nabu-source.txt"   # which clone state is installed
$Release = Join-Path $Repo "dist\release"
$MinNode = 20
$MinFreeGB = 3   # Nabu itself (about 0.4 GB) plus room; the installer checks model space itself

function Say([string]$s) { Write-Host $s }
function Head([string]$s) { Write-Host ""; Write-Host "== $s" -ForegroundColor Cyan }
function Fail([string]$s) { Write-Host "start-nabu: $s" -ForegroundColor Red; exit 1 }

# Native programs: their stderr notes (git line-ending warnings, npm notices) must not stop
# the script, so errors are judged by exit code only.
function Native([string]$exe, [string[]]$argv) {
  $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try { $out = & $exe @argv 2>$null; return @{ code = $LASTEXITCODE; out = $out } }
  finally { $ErrorActionPreference = $old }
}
function Run([string]$exe, [string[]]$argv, [string]$what) {
  Say ("  $ " + $exe + " " + ($argv -join " "))
  $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try { & $exe @argv } finally { $ErrorActionPreference = $old }
  if ($LASTEXITCODE -ne 0) { Fail "$what failed (exit $LASTEXITCODE). See the messages above." }
}
function Have([string]$name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }
# Interactive children (the installer asks y/N) run attached to this console, never through a
# PowerShell pipe: a pipe holds a prompt that has no line end, so the question would not show.
# Returns only the exit code.
function Start-Child([string]$exe, [string[]]$argv) {
  $line = ($argv | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join " "
  $p = Start-Process -FilePath $exe -ArgumentList $line -NoNewWindow -Wait -PassThru
  return $p.ExitCode
}
function Start-Script([string]$file, [string[]]$argv) {
  return Start-Child "powershell" (@("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $file) + $argv)
}

# ---------------------------------------------------------------- 1. This machine
Head "Checking this machine"
$os = [Environment]::OSVersion.Version
if ($os.Major -lt 10) { Fail "Nabu needs Windows 10 or 11 (found $os)." }
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
  Fail "Nabu needs 64-bit Windows on an Intel or AMD processor (found $env:PROCESSOR_ARCHITECTURE). Windows on ARM is not supported yet."
}
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$drive = (Get-Item $env:LOCALAPPDATA).PSDrive
$freeGB = [math]::Round($drive.Free / 1GB, 1)
Say "  Windows $($os.Major).$($os.Build), 64-bit; memory $ramGB GB; free on $($drive.Name): $freeGB GB"
if ($freeGB -lt $MinFreeGB) { Fail "Only $freeGB GB free on $($drive.Name):. Free at least $MinFreeGB GB (more for a model) and run again." }
if ($ramGB -lt 7.5) {
  Say "  Note: under 8 GB memory. Nabu will offer no model (digital files and templates only) or the smallest one."
}

# ---------------------------------------------------------------- 2. Install or update Nabu
$installed = Test-Path $Py
$source = "unknown"
if (Have "git") {
  $head = Native "git" @("-C", $Repo, "rev-parse", "HEAD")
  if ($head.code -eq 0) {
    $source = ($head.out | Select-Object -First 1).Trim()
    $diff = Native "git" @("-C", $Repo, "diff", "HEAD", "--", ".", ":(exclude)tasks")
    if ($diff.out) {
      $bytes = [Text.Encoding]::UTF8.GetBytes(($diff.out -join "`n"))
      $hash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace("-", "").Substring(0, 12)
      $source += "+local-$hash"
    }
  }
} else {
  Say "  git not found: Nabu is installed once and only updated with -Reinstall."
}
$have = if (Test-Path $Marker) { (Get-Content $Marker -Raw).Trim() } else { "" }
$needBuild = $Reinstall -or -not $installed -or -not $have -or ($source -ne "unknown" -and $have -ne $source)

$justInstalled = $false
if ($needBuild) {
  Head ($(if ($installed) { "Updating Nabu from this clone ($source)" } else { "Installing Nabu from this clone" }))

  # Node builds the review window.
  if (-not (Have "node") -or -not (Have "npm.cmd")) {
    Fail "Node.js $MinNode or newer is needed to build Nabu's window. Install the LTS version from https://nodejs.org, open a new terminal, and run this script again."
  }
  $nodeVer = (Native "node" @("--version")).out | Select-Object -First 1
  if (-not ($nodeVer -match "^v(\d+)\.") -or [int]$Matches[1] -lt $MinNode) {
    Fail "Node.js $MinNode or newer is needed (found $nodeVer). Install the LTS version from https://nodejs.org and run again."
  }
  Say "  Node $nodeVer"

  # Pinned uv (checksum checked), from the same pins as the installer.
  if ((Start-Script (Join-Path $Repo "install\install.ps1") @("-UvOnly")) -ne 0) { Fail "could not set up uv (see above)." }

  Push-Location (Join-Path $Repo "ui")
  try {
    Run "npm.cmd" @("ci", "--no-audit", "--no-fund") "Installing the window's build tools (npm ci)"
    Run "npm.cmd" @("run", "build") "Building the review window"
  } finally { Pop-Location }

  $env:UV_PYTHON_INSTALL_DIR = Join-Path $Root "python"
  Run $Uv @("run", "--no-project", "--python", "3.12", (Join-Path $Repo "install\build_release.py"),
            "--uv", $Uv, "--out", $Release) "Building the release"

  Head "Running the installer"
  if ((Start-Script (Join-Path $Release "install.ps1") @("-Model", $Model)) -ne 0) {
    Fail "the installer reported problems (listed above). Fix them and run this script again; finished steps are not repeated."
  }
  if ($source -ne "unknown" -or -not $have) { Set-Content -Path $Marker -Value $source -Encoding ascii }
  $justInstalled = $true
}

# ---------------------------------------------------------------- 3. Ollama and the model
if (-not $justInstalled) {
  if ($Setup) {
    Head "Setting up Ollama and the model again"
    $rc = Start-Child $Py @("-m", "nabu.install", "--model", $Model)
    if ($rc -ne 0) { Fail "the setup reported problems (listed above). Fix them and run again." }
  } else {
    Head "Checking Ollama and the model"
    $rc = Start-Child $Py @("-m", "nabu.install", "--check")
    if ($rc -eq 3) {
      Say "  Running the model setup (it asks before downloading anything)."
      $rc = Start-Child $Py @("-m", "nabu.install", "--model", $Model)
      if ($rc -ne 0) { Say "  The setup reported problems (above). Nabu opens anyway; reads that need a model will say so." }
    } elseif ($rc -ne 0) {
      Fail "the check failed (exit $rc). See the message above."
    }
  }
}

# ---------------------------------------------------------------- 4. Open Nabu
if ($NoLaunch) { Say ""; Say "Ready. Start Nabu with this script or the Nabu shortcut in the Start menu."; exit 0 }
Head "Opening Nabu"
Say "  The review window opens in your browser. Stop Nabu with 'Quit Nabu' in the window, or Ctrl+C here."
exit (Start-Child $Py @("-m", "nabu.app"))
