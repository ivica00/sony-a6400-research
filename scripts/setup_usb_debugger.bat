@echo off
setlocal
cd /d "%~dp0.."

if exist "%~dp0..\venv\Scripts\python.exe" (
    set "PY=%~dp0..\venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3 was not found on PATH. Install Python 3.12+ and re-run.
        pause
        exit /b 1
    )
    set "PY=python"
)

"%PY%" -c "import Cryptodome, elftools" >nul 2>nul
if errorlevel 1 (
    if not exist "%~dp0..\.venv-debugger\Scripts\python.exe" (
        echo Creating local .venv-debugger and installing pycryptodome + pyelftools...
        "%PY%" -m venv "%~dp0..\.venv-debugger"
    )
    set "PY=%~dp0..\.venv-debugger\Scripts\python.exe"
    "%PY%" -m pip install --quiet pycryptodome pyelftools
)

"%PY%" "%~dp0..\tools\setup_usb_debugger.py" %*
pause
