@echo off
title AI Pokemon NPC Launcher

:: Check if Python is installed
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not in your PATH!
    echo Please install Python 3 from https://python.org and check "Add Python to PATH".
    pause
    exit /b
)

:: Launch the GUI and close the terminal
start "" pythonw "%~dp0launcher.py"
