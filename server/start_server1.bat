@echo off
rem ============================================================
rem  Wasteland-Z — game server #1
rem  Double-click to start. The server runs in THIS window and
rem  restarts itself automatically if it closes or crashes.
rem
rem  TO STOP FOR GOOD: just close this window (the X), or run
rem  stop_server1.bat. The gateway is separate and stays up.
rem
rem  Updated for Arma Reforger 1.8 - 2026-08-17: the loop now runs SteamCMD
rem  before each start, so the server is never behind its clients (a server on
rem  an older build than the players is unjoinable).
rem
rem  EDIT THESE SIX LINES ONCE:
rem ============================================================
set SERVER_EXE=C:\reforger\server\ArmaReforgerServer.exe
set CONFIG=C:\reforger\configs\server1.json
set PROFILE=C:\reforger\profiles\server1
set ADDONS=C:\reforger\workshop
set STEAMCMD=C:\reforger\steamcmd\steamcmd.exe
set INSTALL_DIR=C:\reforger\server

title WZ-Server-1
set STOPFLAG=%~dp0server1.stop
if exist "%STOPFLAG%" del "%STOPFLAG%"

:loop
rem  Bring the game up to date first. No "validate" here on purpose - that
rem  re-checks every file and would add minutes to every restart; it belongs in
rem  install_or_update_server.bat, which is the repair tool.
echo [%date% %time%] Checking for a game update ...
"%STEAMCMD%" +force_install_dir "%INSTALL_DIR%" +login anonymous +app_update 1874900 +quit

echo [%date% %time%] Starting Wasteland-Z server 1 ...
rem  -maxFPS: BI recommends 60-120, and NEVER omitting it - uncapped, the
rem  server will try to use every available CPU cycle. Raise to 120 on a
rem  strong box.
"%SERVER_EXE%" -config "%CONFIG%" -profile "%PROFILE%" -addonDownloadDir "%ADDONS%" -maxFPS 60
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
