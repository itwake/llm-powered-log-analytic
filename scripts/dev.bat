@echo off
rem Bootstraps and starts the LogAn API and web workbench for local development.
rem Thin cmd.exe wrapper around scripts\dev.ps1 (the single source of truth)
rem that also bypasses the PowerShell execution policy for this local script,
rem so it works from cmd.exe and by double-clicking in Explorer.
rem
rem Usage:
rem   scripts\dev.bat               start API (this window) + web (new window)
rem   scripts\dev.bat -ApiOnly      API only, in this window
rem   scripts\dev.bat -WebOnly      web workbench only, in this window
rem   scripts\dev.bat -SkipInstall  skip dependency checks and installs

setlocal
where powershell >nul 2>&1
if errorlevel 1 (
    echo PowerShell was not found on PATH. Install Windows PowerShell 5.1 or PowerShell 7+.
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
exit /b %ERRORLEVEL%
