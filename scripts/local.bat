@echo off
rem Bootstraps and starts the LogAn API and web workbench for local development.
rem Standalone cmd.exe implementation, behavior-matched to scripts\local.ps1:
rem creates .venv and installs dependencies on first run, copies .env.example
rem to .env when missing, loads .env into this process, then starts the web
rem workbench in a second window and the API in this window.
rem
rem Usage:
rem   scripts\local.bat               start API in this window, web in a new window
rem   scripts\local.bat -ApiOnly      API only, in this window
rem   scripts\local.bat -WebOnly      web workbench only, in this window
rem   scripts\local.bat -SkipInstall  skip dependency checks and installs

setlocal EnableExtensions
for %%I in ("%~dp0..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"

set "API_ONLY="
set "WEB_ONLY="
set "SKIP_INSTALL="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="-ApiOnly" set "API_ONLY=1" & shift & goto parse_args
if /I "%~1"=="-WebOnly" set "WEB_ONLY=1" & shift & goto parse_args
if /I "%~1"=="-SkipInstall" set "SKIP_INSTALL=1" & shift & goto parse_args
echo Unknown option: %~1
echo Supported options: -ApiOnly, -WebOnly, -SkipInstall
exit /b 1
:args_done

if defined API_ONLY if defined WEB_ONLY (
    echo Use only one of -ApiOnly or -WebOnly.
    exit /b 1
)

set "VENV_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"

if defined SKIP_INSTALL goto ensure_env
if defined WEB_ONLY goto install_web

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH. Install Python 3.11+ from https://www.python.org/downloads/ and reopen the terminal.
    exit /b 1
)
if not exist "%VENV_PYTHON%" (
    echo Creating .venv ...
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
"%VENV_PYTHON%" -c "import app, logan_workers, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo Installing Python dependencies - the first run takes a few minutes ...
    "%VENV_PYTHON%" -m pip install --upgrade pip
    if errorlevel 1 exit /b 1
    "%VENV_PYTHON%" -m pip install -e .
    if errorlevel 1 exit /b 1
)
if defined API_ONLY goto ensure_env

:install_web
where npm >nul 2>nul
if errorlevel 1 (
    echo npm was not found on PATH. Install Node.js 20.9+ from https://nodejs.org/ and reopen the terminal.
    exit /b 1
)
if not exist "%REPO_ROOT%\node_modules" (
    echo Installing npm workspace dependencies ...
    call npm install
    if errorlevel 1 exit /b 1
)

:ensure_env
if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo Created .env from .env.example.
)

rem The API does not parse .env itself, so export it into this process.
rem Lines starting with # are skipped; values keep everything after the first
rem equals sign; surrounding double or single quotes are stripped.
for /f "usebackq eol=# tokens=1* delims==" %%A in (".env") do call :set_env_var "%%A" "%%~B"

if defined WEB_ONLY (
    echo Starting web workbench: http://localhost:3000 - Ctrl+C to stop
    call npm run dev --workspace @logan/web
    exit /b %ERRORLEVEL%
)

if not defined API_ONLY (
    echo Starting web workbench in a new window: http://localhost:3000
    start "LogAn web workbench" /d "%REPO_ROOT%" cmd /k "npm run dev --workspace @logan/web"
)

echo.
echo LogAn API:      http://localhost:8000 - Ctrl+C to stop
echo Web workbench:  http://localhost:3000
echo Sign in with "Continue with SSO" - the local mock SSO needs no credentials.
echo.
"%VENV_PYTHON%" -m uvicorn app.main:app --reload --app-dir apps/api --host 127.0.0.1 --port 8000
exit /b %ERRORLEVEL%

:set_env_var
set "_name=%~1"
set "_value=%~2"
if not defined _name goto :eof
rem Strip one pair of surrounding single quotes; double quotes were already
rem stripped by the %~2 expansion above.
if defined _value (
    if "%_value:~0,1%"=="'" if "%_value:~-1%"=="'" set "_value=%_value:~1,-1%"
)
set "%_name%=%_value%"
set "_name="
set "_value="
goto :eof
