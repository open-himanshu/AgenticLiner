@echo off
title AgenticLiner - Public Server Launcher
cd /d "%~dp0"
if not "%ALLOW_PUBLIC_TUNNEL%"=="1" (
    echo ERROR: Refusing to start without ALLOW_PUBLIC_TUNNEL=1.
    echo Set it only after review. This makes the application publicly accessible with reachable endpoints.
    exit /b 1
)
echo ===================================================
echo Starting AgenticLiner Public Server...
echo ===================================================
echo WARNING: The public tunnel makes the login page, application, and reachable endpoints publicly accessible.
python -u start_live_server.py
pause
