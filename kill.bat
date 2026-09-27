@echo off
title Terminate Autobumper Processes
echo.
echo ====================================================
echo      KILLING ALL ACTIVE PYTHON AND CHROME DRIVERS
echo ====================================================
echo.

echo Terminating python.exe...
taskkill /F /IM python.exe
echo Terminating chromedriver.exe...
taskkill /F /IM chromedriver.exe

echo.
echo Done! All Autobumper-related processes have been wiped.
echo You can now safely launch run.bat without any Port 8000 crashes.
echo.
pause
