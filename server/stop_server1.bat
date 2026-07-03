@echo off
rem ============================================================
rem  Wasteland-Z — stop game server #1 (and its restart loop).
rem  The gateway and any other game servers keep running.
rem ============================================================
echo stop> "%~dp0server1.stop"
taskkill /f /t /fi "WINDOWTITLE eq WZ-Server-1*" >nul 2>&1
echo Server 1 stopped.
timeout /t 3 >nul
