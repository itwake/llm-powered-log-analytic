#Requires -Version 5.1
<#
.SYNOPSIS
Bootstraps and starts the LogAn API and web workbench for local development.

.DESCRIPTION
Creates .venv and installs Python/npm dependencies on first run, copies
.env.example to .env when .env is missing, loads .env into this process
(the API reads process environment variables only), then starts the Next.js
workbench in a second window and the FastAPI backend in this window.

.PARAMETER ApiOnly
Start only the FastAPI backend in the current window.

.PARAMETER WebOnly
Start only the web workbench in the current window.

.PARAMETER SkipInstall
Skip dependency checks and installs; just load .env and start processes.

.EXAMPLE
.\scripts\local.ps1
.EXAMPLE
.\scripts\local.ps1 -ApiOnly
#>
[CmdletBinding()]
param(
    [switch]$ApiOnly,
    [switch]$WebOnly,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

if ($ApiOnly -and $WebOnly) {
    throw "Use only one of -ApiOnly or -WebOnly."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$apiUrl = "http://localhost:8000"
$webUrl = "http://localhost:3000"

function Assert-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found on PATH. $Hint"
    }
}

if (-not $SkipInstall) {
    if (-not $WebOnly) {
        Assert-Command python "Install Python 3.11+ from https://www.python.org/downloads/ and reopen the terminal."
        if (-not (Test-Path $venvPython)) {
            Write-Host "Creating .venv ..."
            python -m venv .venv
            if ($LASTEXITCODE -ne 0) { throw "python -m venv .venv failed." }
        }
        $probe = Start-Process -FilePath $venvPython `
            -ArgumentList "-c", "import app, logan_workers, uvicorn" `
            -Wait -PassThru -WindowStyle Hidden
        if ($probe.ExitCode -ne 0) {
            Write-Host "Installing Python dependencies (first run takes a few minutes) ..."
            & $venvPython -m pip install --upgrade pip
            if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
            & $venvPython -m pip install -e .
            if ($LASTEXITCODE -ne 0) { throw "pip install -e . failed." }
        }
    }
    if (-not $ApiOnly) {
        Assert-Command npm "Install Node.js 20.9+ from https://nodejs.org/ and reopen the terminal."
        if (-not (Test-Path (Join-Path $repoRoot "node_modules"))) {
            Write-Host "Installing npm workspace dependencies ..."
            npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
        }
    }
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example."
}

# The API does not parse .env itself, so export it into this process.
foreach ($line in Get-Content ".env") {
    $trimmed = $line.Trim()
    if (-not $trimmed) { continue }
    if ($trimmed.StartsWith("#")) { continue }
    $separator = $trimmed.IndexOf("=")
    if ($separator -lt 1) { continue }
    $name = $trimmed.Substring(0, $separator).Trim()
    $value = $trimmed.Substring($separator + 1).Trim()
    if ($value.Length -ge 2 -and (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'")))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    Set-Item -Path "env:$name" -Value $value
}

if ($WebOnly) {
    Write-Host "Starting web workbench: $webUrl (Ctrl+C to stop)"
    npm run dev --workspace @logan/web
    exit $LASTEXITCODE
}

if (-not $ApiOnly) {
    Write-Host "Starting web workbench in a new window: $webUrl"
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$repoRoot'; npm run dev --workspace @logan/web"
    )
}

Write-Host ""
Write-Host "LogAn API:      $apiUrl (Ctrl+C to stop)"
Write-Host "Web workbench:  $webUrl"
Write-Host "Sign in with 'Continue with SSO' - the local mock SSO needs no credentials."
Write-Host ""
& $venvPython -m uvicorn app.main:app --reload --app-dir apps/api --host 127.0.0.1 --port 8000
