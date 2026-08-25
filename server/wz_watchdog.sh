#!/bin/sh
# Wasteland-Z server action watchdog — POSIX shell.
#
#   ./wz_watchdog.sh /opt/reforger/profile/hf_wastelandz/configs
#   ./wz_watchdog.sh /path/to/configs --loop
#
# Runs one pass and exits, so cron or a systemd timer can drive it. --loop
# stays resident and checks every 5 seconds.
#
# EDIT ONE THING: the run_command() case block. Nothing else.
#
# No dependencies. Uses sh, grep, awk, tr and rm — all already on your server.

CONFIG_DIR="$1"
[ -n "$CONFIG_DIR" ] || {
    echo "usage: $0 <configs-folder> [--loop]" >&2
    exit 1
}
FILE="$CONFIG_DIR/SERVER_COMMAND.txt"

log() { echo "[wz-watchdog] $*"; }

# ---------------------------------------------------------------------------
# EDIT HERE. Each command name from HFWastelandZ_server_action_commands.conf
# gets a branch. Anything not listed is logged and ignored — an unknown command
# should do nothing, never guess.
# ---------------------------------------------------------------------------
run_command() {
    case "$1" in
        REBOOT_SERVER)       systemctl restart wz-server1 ;;
        RESTART_GATEWAY)     systemctl restart wz-gateway ;;
        RESTART_DISCORD_BOT) systemctl restart wz-discord ;;
        COLD_REBOOT_SERVER)  shutdown -r now ;;

        # Your own — point at a script and put the logic there:
        # MAP_LOAD_PLUNDER)  /opt/wz/load_map.sh plunder ;;
        # DATABASE_MAINT)    /opt/wz/db_maint.sh ;;

        *) log "unknown command '$1' — ignored" ; return 0 ;;
    esac
    log "$1 finished with status $?"
}

one_pass() {
    [ -f "$FILE" ] || return 0

    # No END line means the mod is still writing it. The game cannot rename a
    # file atomically, so it writes in place and a fast poll can catch it
    # half-finished. Not corrupt — just not done. Look again next pass.
    grep -q '^END' "$FILE" || return 0

    # tr -d '\r' is not optional. If the file ever picks up Windows line
    # endings the command becomes "REBOOT_SERVER" plus a carriage return: it
    # prints identically, matches nothing, and every branch falls through with
    # no error at all.
    cmd=$(awk '/^COMMAND/{print $2; exit}' "$FILE" | tr -d '\r')

    # DELETE BEFORE ACTING. If this script dies after acting but before
    # deleting, the command runs again on the next pass. Losing a reboot is
    # cheap; repeating a database wipe is not.
    if ! rm -f "$FILE"; then
        log "could not delete $FILE — refusing to act, or it would repeat forever"
        return 1
    fi

    [ -n "$cmd" ] || { log "no COMMAND line found — ignored"; return 0; }
    log "running $cmd"
    run_command "$cmd"
}

if [ "$2" = "--loop" ]; then
    log "watching $FILE"
    while true; do
        one_pass
        sleep 5
    done
else
    one_pass
fi
