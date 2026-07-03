@echo off
rem ============================================================
rem  Wasteland-Z — install OR update the Arma Reforger server
rem  Safe to re-run any time (it only downloads what changed).
rem  Run it again after every official Reforger update.
rem
rem  EDIT THESE TWO PATHS if you chose different folders:
rem ============================================================
set STEAMCMD=C:\reforger\steamcmd\steamcmd.exe
set INSTALL_DIR=C:\reforger\server

if not exist "%STEAMCMD%" (
  echo.
  echo SteamCMD not found at %STEAMCMD%
  echo Download it from https://developer.valvesoftware.com/wiki/SteamCMD
  echo and unzip it to C:\reforger\steamcmd\  ^(or edit the path above^).
  pause
  exit /b 1
)

"%STEAMCMD%" +force_install_dir "%INSTALL_DIR%" +login anonymous +app_update 1874900 validate +quit

echo.
echo ============================================================
echo  Done. The server is installed / up to date in:
echo    %INSTALL_DIR%
echo ============================================================
pause
