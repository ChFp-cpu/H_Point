@echo off
setlocal
cd /d "%~dp0"

if not exist "run.py" (
    echo [ERROR] run.py not found.
    pause
    exit /b 1
)

echo ========================================
echo H-POINT START
echo ========================================
echo.

REM Use the Windows Python launcher directly.
REM This avoids reading a Unicode Python path through CMD/OEM encoding.
if exist ".venv\Scripts\python.exe" goto venv_ok

where py >nul 2>&1
if not errorlevel 1 goto create_venv_with_py

where python >nul 2>&1
if not errorlevel 1 goto create_venv_with_python

echo [ERROR] Python was not found.
echo Install Python from https://www.python.org/downloads/windows/
echo and make sure the Python launcher or PATH is enabled.
pause
exit /b 1

:create_venv_with_py
echo Creating virtual environment...
py -3 -m venv .venv
if errorlevel 1 (
    echo [ERROR] Could not create .venv.
    echo Try running: py -3 --version
    pause
    exit /b 1
)
goto venv_ok

:create_venv_with_python
echo Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] Could not create .venv.
    echo Try running: python --version
    pause
    exit /b 1
)

goto venv_ok

:venv_ok
echo Python environment OK.
echo.

if not exist ".venv\.deps-installed" (
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        pause
        exit /b 1
    )
    type nul > ".venv\.deps-installed"
)

if not exist ".env" (
    if exist ".env.example" (
        echo Creating .env from .env.example...
        copy /Y ".env.example" ".env" >nul
    ) else (
        echo [ERROR] .env.example not found.
        pause
        exit /b 1
    )
    echo.
    echo [ACTION REQUIRED] Open .env and enter your BOT_TOKEN.
    echo Then run start.bat again.
    echo.
    pause
    exit /b 0
)

echo Starting H-Point: website + Telegram bot...
echo Website: http://127.0.0.1:8000
echo.

".venv\Scripts\python.exe" run.py

set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo ========================================
echo H-POINT STOPPED - code %EXIT_CODE%
echo ========================================
pause
exit /b %EXIT_CODE%
