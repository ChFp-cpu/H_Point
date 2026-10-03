@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo H-POINT START
echo ========================================
echo.

if not exist "run.py" (
    echo ERROR: run.py not found
    pause
    exit /b 1
)

echo Checking Python...

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    goto python_ok
)

where py >nul 2>&1
if not errorlevel 1 (
    echo Creating virtual environment...
    py -m venv .venv
    if errorlevel 1 (
        echo ERROR: venv creation failed
        pause
        exit /b 1
    )
    set "PYTHON=.venv\Scripts\python.exe"
    goto python_ok
)

where python >nul 2>&1
if not errorlevel 1 (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: venv creation failed
        pause
        exit /b 1
    )
    set "PYTHON=.venv\Scripts\python.exe"
    goto python_ok
)

echo ERROR: Python not found
pause
exit /b 1

:python_ok

echo.
echo Python OK
echo.

if not exist ".venv\.installed" (
    echo Installing dependencies...
    "%PYTHON%" -m pip install -r requirements.txt

    if errorlevel 1 (
        echo ERROR: dependency installation failed
        pause
        exit /b 1
    )

    type nul > ".venv\.installed"
)

echo.
echo Starting H-Point...
echo.
echo Website: http://127.0.0.1:8000
echo.

"%PYTHON%" run.py

echo.
echo ========================================
echo H-POINT STOPPED
echo ========================================
echo Exit code: %errorlevel%
echo.
pause