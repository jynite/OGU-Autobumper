@echo off
setlocal
cd /d "%~dp0"
title OGU Autobumper
echo Installing the declared local dependencies...
python -m pip install -r requirements-bot.txt
if errorlevel 1 goto :failed
pushd frontend
call npm ci
if errorlevel 1 goto :frontend_failed
call npm run build
if errorlevel 1 goto :frontend_failed
popd
echo Open http://127.0.0.1:8000 after the server is ready.
echo Starting the server does not start the bot. Use Start in the dashboard.
echo Use Stop and wait for Idle, then press Ctrl+C here to close the server.
python autobumper_linux.py
if errorlevel 1 goto :failed
exit /b 0
:frontend_failed
popd
:failed
echo Setup or launch failed. Read the error above.
pause
exit /b 1
