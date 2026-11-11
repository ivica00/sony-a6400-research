@echo off
title Sony ILCE-6400 Live Wi-Fi Debug Terminal
echo ========================================================
echo   SONY ILCE-6400 LIVE WI-FI ROOT TERMINAL (Port 2323)
echo ========================================================
rem This launcher lives in scripts/; tools/ stays at the repository root (%~dp0..).
py -3.12 "%~dp0..\tools\cam_live_terminal.py"
pause
