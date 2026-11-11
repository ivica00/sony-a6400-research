@echo off
echo ========================================================
echo   Sony a6400 Cinema Monitor (mpv + AMD FSR Upscaler)
echo ========================================================
echo Connecting to Live View stream at http://127.0.0.1:8080/liveview.mjpg
echo Using AMD FidelityFX Super Resolution (FSR) GLSL shader...
echo.

rem This launcher lives in scripts/; artifacts/ stays at the repository root (%~dp0..).
mpv http://127.0.0.1:8080/liveview.mjpg --profile=low-latency --untimed --title="Sony a6400 Cinema Monitor [AMD FSR]" --glsl-shaders="%~dp0..\artifacts\shaders\FSR.glsl" --geometry=1920x1080 --autofit=100%

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Note: If mpv is not installed or not in PATH, you can open:
    echo   http://127.0.0.1:8080/
    echo in your web browser (Chrome/Edge) with the built-in WebGL2 AMD FSR engine!
    pause
)
