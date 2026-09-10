@echo off
rem Bootstraps and starts the LogAn API and web application for local development.
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

for %%A in (%*) do (
    if /I "%%~A"=="-ApiOnly" (
        set "API_ONLY=1"
    ) else if /I "%%~A"=="-WebOnly" (
        set "WEB_ONLY=1"
    ) else if /I "%%~A"=="-SkipInstall" (
        set "SKIP_INSTALL=1"
    ) else (
        echo Unknown option: %%~A
        echo Supported options: -ApiOnly, -WebOnly, -SkipInstall
        exit /b 1
    )
)

if defined API_ONLY if defined WEB_ONLY (
    echo Use only one of -ApiOnly or -WebOnly.
    exit /b 1
)

set "VENV_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"

if not defined WEB_ONLY (
    powershell -NoProfile -NonInteractive -Command ^
        "if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) { exit 1 }"
    if errorlevel 1 (
        echo Port 8000 is already in use. Stop the existing API process and run this launcher again.
        exit /b 1
    )
)

if not defined API_ONLY (
    powershell -NoProfile -NonInteractive -Command ^
        "if (Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue) { exit 1 }"
    if errorlevel 1 (
        echo Port 3000 is already in use. Stop the existing web process and run this launcher again.
        exit /b 1
    )
)

if not defined WEB_ONLY if not defined SKIP_INSTALL (
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
)

if not defined API_ONLY (
    where npm >nul 2>nul
    if errorlevel 1 (
        echo npm was not found on PATH. Install Node.js 22 or newer and reopen the terminal.
        exit /b 1
    )

    set "WEB_DEPS_READY="
    if exist "%REPO_ROOT%\node_modules\.bin\next.cmd" (
        call npm ls --workspace @logan/web --depth=0 >nul 2>nul
        if not errorlevel 1 set "WEB_DEPS_READY=1"
    )

    if defined SKIP_INSTALL (
        if not defined WEB_DEPS_READY (
            echo Web dependencies are missing or incomplete.
            echo Run scripts\local.bat without -SkipInstall to install them.
            exit /b 1
        )
    ) else if not defined WEB_DEPS_READY (
        echo Installing web dependencies ...
        call npm ci
        if errorlevel 1 (
            echo Failed to install web dependencies with npm ci.
            exit /b 1
        )
        if not exist "%REPO_ROOT%\node_modules\.bin\next.cmd" (
            echo Web dependency installation completed without a usable Next.js executable.
            exit /b 1
        )
        call npm ls --workspace @logan/web --depth=0 >nul 2>nul
        if errorlevel 1 (
            echo Web dependencies are incomplete after npm ci.
            exit /b 1
        )
    )
)

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo Created .env from .env.example.
)

for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%~B"

if defined WEB_ONLY (
    echo Starting web application at http://localhost:3000
    call npm run dev --workspace @logan/web
    exit /b
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
