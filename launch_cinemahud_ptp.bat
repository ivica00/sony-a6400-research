@echo off
cd /d "%~dp0"
echo CinemaHUD - original Sony firmware / USB PC Remote
echo Set the camera USB Connection to PC Remote before starting.
"%~dp0venv\Scripts\python.exe" -m tools.research.ptp_liveview_client --source ptp --serve --no-auto-deploy %*
pause
