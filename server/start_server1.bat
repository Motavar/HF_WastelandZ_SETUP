@echo off
rem ============================================================
rem  Wasteland-Z — game server #1
rem  Double-click to start. The server runs in THIS window and
rem  restarts itself automatically if it closes or crashes.
rem
rem  TO STOP FOR GOOD: just close this window (the X), or run
rem  stop_server1.bat. The gateway is separate and stays up.
rem
rem  EDIT THESE FOUR LINES ONCE:
rem ============================================================
set SERVER_EXE=C:\reforger\server\ArmaReforgerServer.exe
set CONFIG=C:\reforger\configs\server1.json
set PROFILE=C:\reforger\profiles\server1
set ADDONS=C:\reforger\workshop

title WZ-Server-1
set STOPFLAG=%~dp0server1.stop
if exist "%STOPFLAG%" del "%STOPFLAG%"

:loop
echo [%date% %time%] Starting Wasteland-Z server 1 ...
"%SERVER_EXE%" -config "%CONFIG%" -profile "%PROFILE%" -addonsDir "%ADDONS%" -maxFPS 60
if exist "%STOPFLAG%" (
  del "%STOPFLAG%"
  echo Stopped by stop_server1.bat.
  exit
)
echo.
echo Server closed or crashed. Restarting in 10 seconds ...
echo   (to stop for good: close this window, or run stop_server1.bat)
timeout /t 10
goto loop
