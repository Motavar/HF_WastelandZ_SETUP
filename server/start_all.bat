@echo off
rem ============================================================
rem  Wasteland-Z — start EVERYTHING with one double-click:
rem  the gateway first, then the game server(s).
rem
rem  Each piece opens in its OWN labeled window:
rem    WZ-Gateway    the gateway (leave it running)
rem    WZ-Server-1   game server 1
rem  Close any window to stop just that piece.
rem
rem  Start on boot: press Win+R, type  shell:startup  , press
rem  Enter, and put a SHORTCUT to this file in the folder that
rem  opens.
rem
rem  EDIT THIS PATH ONCE:
rem ============================================================
set GATEWAY_DIR=C:\wastelandz-gateway

start "WZ-Gateway" /d "%GATEWAY_DIR%" start_gateway.bat
echo Waiting for the gateway to come up ...
timeout /t 8 >nul

start "" "%~dp0start_server1.bat"

rem -- Running more servers? Remove 'rem' from the lines below. --
rem timeout /t 5 >nul
rem start "" "%~dp0start_server2.bat"
rem timeout /t 5 >nul
rem start "" "%~dp0start_server3.bat"
