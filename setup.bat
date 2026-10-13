@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python 3.10-3.13 was not found. Install a 64-bit version from https://www.python.org/.
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :failed
)

echo Installing dependencies. OCR packages are large and may take several minutes...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo Setup completed. You can now run run.bat.
pause
exit /b 0

:failed
echo.
echo [ERROR] Setup failed. Check the messages above, your Python version, and your network connection.
pause
exit /b 1
