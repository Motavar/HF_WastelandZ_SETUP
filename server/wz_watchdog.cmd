@echo off
setlocal EnableDelayedExpansion
rem ==========================================================================
rem  Wasteland-Z server action watchdog - Windows batch.
rem
rem    wz_watchdog.cmd C:\reforger\profile\hf_wastelandz\configs
rem
rem  Runs one pass and exits. Point Task Scheduler at it on a 1-minute
rem  trigger, or call it from a loop of your own.
rem
rem  EDIT ONE THING: the :run_command labels near the bottom. Nothing else.
rem
rem  No dependencies. Uses only findstr, del and net - all built in.
rem ==========================================================================

if "%~1"=="" (
    echo usage: %~nx0 ^<configs-folder^>
    exit /b 1
)

set "CONFIG_DIR=%~1"
set "FILE=%CONFIG_DIR%\SERVER_COMMAND.txt"

rem Nothing waiting. This is the normal case on almost every run.
if not exist "%FILE%" exit /b 0

rem No END line means the mod is still writing the file. The game cannot rename
rem atomically, so it writes in place and a fast poll can catch it half done.
rem Not corrupt - just not finished. Come back next time.
findstr /b /c:"END" "%FILE%" >nul 2>&1
if errorlevel 1 exit /b 0

rem Pull the second token off the COMMAND line.
rem
rem NOTE: 'for /f' strips carriage returns by itself, so the CRLF problem that
rem bites shell scripts does not arise here. Mentioned because the bash and
rem Python versions need an explicit strip and someone comparing them will ask.
set "CMD="
for /f "tokens=2" %%A in ('findstr /b /c:"COMMAND" "%FILE%"') do set "CMD=%%A"

rem DELETE BEFORE ACTING. If this script dies after acting but before deleting,
rem the command runs again on the next pass. Losing a reboot is cheap;
rem repeating a database wipe is not.
del /f /q "%FILE%" >nul 2>&1
if exist "%FILE%" (
    echo [wz-watchdog] could not delete "%FILE%" - refusing to act, or it would repeat forever
    exit /b 1
)

if "!CMD!"=="" (
    echo [wz-watchdog] no COMMAND line found - ignored
    exit /b 0
)

echo [wz-watchdog] running !CMD!
call :run_command "!CMD!"
exit /b 0

rem ==========================================================================
rem  EDIT HERE. One block per command from
rem  HFWastelandZ_server_action_commands.conf. Anything not listed is logged
rem  and ignored - an unknown command should do nothing, never guess.
rem ==========================================================================
:run_command
set "C=%~1"

if /i "%C%"=="REBOOT_SERVER" (
    net stop wz-server1 & net start wz-server1
    goto :eof
)
if /i "%C%"=="RESTART_GATEWAY" (
    net stop wz-gateway & net start wz-gateway
    goto :eof
)
if /i "%C%"=="RESTART_DISCORD_BOT" (
    net stop wz-discord & net start wz-discord
    goto :eof
)
if /i "%C%"=="COLD_REBOOT_SERVER" (
    shutdown /r /t 0
    goto :eof
)

rem Your own - point at a script and put the logic there:
rem if /i "%C%"=="MAP_LOAD_PLUNDER" ( call C:\wz\load_map.cmd plunder & goto :eof )
rem if /i "%C%"=="DATABASE_MAINT"   ( call C:\wz\db_maint.cmd        & goto :eof )

echo [wz-watchdog] unknown command "%C%" - ignored
goto :eof
