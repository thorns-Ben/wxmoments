@echo off
setlocal
cd /d "%~dp0"
title WeChat Moments Search Tool

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Dependencies are not installed. Run setup.bat first.
    pause
    exit /b 1
)

if not exist data mkdir data
".venv\Scripts\python.exe" -m wm.gui 2>data\crash.log
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo [ERROR] The program exited unexpectedly. Details were saved to data\crash.log:
    echo ------------------------------------------------------------
    type data\crash.log
    echo ------------------------------------------------------------
    pause
)

exit /b %RC%
