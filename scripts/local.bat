@echo off
rem Starts the LogAn API and web application for local development.
rem
rem Usage:
rem   scripts\local.bat               API in this window, web in a new window
rem   scripts\local.bat -ApiOnly      API only
rem   scripts\local.bat -WebOnly      web only
rem   scripts\local.bat -SkipInstall  skip dependency installation

setlocal EnableExtensions
for %%I in ("%~dp0..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"

set "API_ONLY="
set "WEB_ONLY="
set "SKIP_INSTALL="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="-ApiOnly" (
    set "API_ONLY=1"
    shift
    goto parse_args
)
if /I "%~1"=="-WebOnly" (
    set "WEB_ONLY=1"
    shift
    goto parse_args
)
if /I "%~1"=="-SkipInstall" (
    set "SKIP_INSTALL=1"
    shift
    goto parse_args
)
echo Unknown option: %~1
echo Supported options: -ApiOnly, -WebOnly, -SkipInstall
exit /b 1

:args_done
if defined API_ONLY if defined WEB_ONLY (
    echo Use only one of -ApiOnly or -WebOnly.
    exit /b 1
)

set "VENV_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"

if not defined SKIP_INSTALL (
    if not defined WEB_ONLY (
        call :install_api
        if errorlevel 1 exit /b 1
    )
    if not defined API_ONLY (
        call :install_web
        if errorlevel 1 exit /b 1
    )
)

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo Created .env from .env.example.
    echo Configure the SSO values in .env before signing in.
)

for /f "usebackq eol=# tokens=1* delims==" %%A in (".env") do call :set_env_var "%%A" "%%~B"

if defined WEB_ONLY (
    where npm >nul 2>nul
    if errorlevel 1 (
        echo npm was not found on PATH. Install Node.js 22 or newer and reopen the terminal.
        exit /b 1
    )
    echo Starting web application at http://localhost:3000
    call npm run dev --workspace @logan/web
    exit /b %ERRORLEVEL%
)

if not exist "%VENV_PYTHON%" (
    echo .venv was not found. Run without -SkipInstall first.
    exit /b 1
)

echo Applying database migrations ...
"%VENV_PYTHON%" -m alembic -c apps/api/alembic.ini upgrade head
if errorlevel 1 exit /b 1

if not defined API_ONLY (
    echo Starting web application in a new window at http://localhost:3000
    start "LogAn web" /d "%REPO_ROOT%" cmd /k "npm run dev --workspace @logan/web"
)

echo.
echo LogAn API: http://localhost:8000
if not defined API_ONLY echo LogAn web: http://localhost:3000
echo Press Ctrl+C to stop the API.
echo.
"%VENV_PYTHON%" -m uvicorn app.main:app --reload --env-file .env --app-dir apps/api --host 127.0.0.1 --port 8000
exit /b %ERRORLEVEL%

:install_api
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH. Install Python 3.11 or newer and reopen the terminal.
    exit /b 1
)
if not exist "%VENV_PYTHON%" (
    echo Creating .venv ...
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
"%VENV_PYTHON%" -c "import alembic, app, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo Installing Python dependencies ...
    "%VENV_PYTHON%" -m pip install -e ".[dev]"
    if errorlevel 1 exit /b 1
)
exit /b 0

:install_web
where npm >nul 2>nul
if errorlevel 1 (
    echo npm was not found on PATH. Install Node.js 22 or newer and reopen the terminal.
    exit /b 1
)
call npm ls --depth=0 >nul 2>nul
if errorlevel 1 (
    echo Installing web dependencies ...
    call npm ci
    if errorlevel 1 exit /b 1
)
exit /b 0

:set_env_var
set "_name=%~1"
set "_value=%~2"
if not defined _name goto :eof
if defined _value (
    if "%_value:~0,1%"=="'" if "%_value:~-1%"=="'" set "_value=%_value:~1,-1%"
)
set "%_name%=%_value%"
set "_name="
set "_value="
goto :eof
