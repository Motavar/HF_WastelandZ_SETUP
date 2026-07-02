@echo off
REM Double-click this file to start the WastelandZ gateway.
REM Leave this window OPEN while the server is running.
REM To stop the gateway: click this window and press Ctrl+C.
cd /d "%~dp0"
python gateway.py
pause
