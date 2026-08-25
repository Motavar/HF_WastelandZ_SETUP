#!/usr/bin/env python3
"""Wasteland-Z server action watchdog.

Watches for SERVER_COMMAND.txt, runs whatever YOU decide the command means,
deletes the file. Works on Linux and Windows. Standard library only.

    python3 wz_watchdog.py /path/to/profile/hf_wastelandz/configs

Run it from cron, a systemd timer, or Task Scheduler - it does one pass and
exits, so there is no daemon to babysit. Add --loop if you would rather it
stay resident.

WHAT THE MOD DOES
    An admin picks an action in F8 -> SERVER. The mod writes SERVER_COMMAND.txt
    into the configs folder. That is all it does - it never runs anything. The
    word it wrote means whatever this script decides it means.

WHAT YOU EDIT
    ACTIONS, below. Nothing else. Keep the keys identical to the COMMAND column
    in HFWastelandZ_server_action_commands.conf.
"""

import os
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# EDIT THIS. Keys must match the COMMAND column in the .conf exactly.
# Anything not listed here is logged and ignored, which is the safe default:
# an unknown command should do nothing, not guess.
#
# Values are argv LISTS, never strings, and are run WITHOUT a shell. That is
# deliberate - with shell=False nothing in the file can be interpreted as shell
# syntax, so a malformed or hostile command cannot become an injection.
# ---------------------------------------------------------------------------
ACTIONS = {
    # --- Linux examples -----------------------------------------------------
    "REBOOT_SERVER":       ["systemctl", "restart", "wz-server1"],
    "RESTART_GATEWAY":     ["systemctl", "restart", "wz-gateway"],
    "RESTART_DISCORD_BOT": ["systemctl", "restart", "wz-discord"],
    "COLD_REBOOT_SERVER":  ["shutdown", "-r", "now"],

    # --- Windows equivalents: swap the lines above for these ---------------
    # "REBOOT_SERVER":      ["powershell", "-c", "Restart-Service wz-server1"],
    # "RESTART_GATEWAY":    ["powershell", "-c", "Restart-Service wz-gateway"],
    # "COLD_REBOOT_SERVER": ["shutdown", "/r", "/t", "0"],

    # --- Your own: point at a script and put the logic there ---------------
    # "MAP_LOAD_PLUNDER":  ["/opt/wz/load_map.sh", "plunder"],
    # "DATABASE_MAINT":    ["/opt/wz/db_maint.sh"],
}

FILENAME = "SERVER_COMMAND.txt"


def log(msg):
    print(f"[wz-watchdog] {msg}", flush=True)


def read_command(path):
    """Return the COMMAND word, or None if the file is not ready or not valid.

    Two guards, both load-bearing:

    1. NO 'END' LINE MEANS STILL BEING WRITTEN. The game engine cannot rename a
       file atomically, so the mod writes in place and a watchdog polling every
       second can catch it half-finished. A file without END is not corrupt -
       it is simply not done yet, so we leave it and look again next pass.

    2. STRIP CARRIAGE RETURNS. If the file ever picks up Windows line endings,
       the command becomes "REBOOT_SERVER\\r", which prints identically to
       "REBOOT_SERVER", compares unequal to it, and silently matches nothing.
       Nothing errors; the admin just watches their file vanish and nothing
       happen. One strip removes the entire class of problem.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip("\r\n") for ln in fh]
    except OSError as exc:
        log(f"cannot read {path}: {exc}")
        return None

    if not any(ln.strip() == "END" for ln in lines):
        return None                      # still being written

    for ln in lines:
        if ln.startswith("COMMAND"):
            parts = ln.split()
            if len(parts) >= 2:
                return parts[1].strip()
    return None


def run_once(folder):
    path = os.path.join(folder, FILENAME)
    if not os.path.isfile(path):
        return

    cmd = read_command(path)
    if cmd is None:
        return                           # incomplete; try again next pass

    # DELETE BEFORE ACTING, and the order matters.
    #
    # Delete-then-act can lose a command if this process dies in between.
    # Act-then-delete can REPEAT one. For a reboot a repeat is survivable; for
    # anything destructive it is not, and a lost command is always the cheaper
    # mistake. The mod makes the same call when it disarms a pending wipe
    # before performing it.
    try:
        os.remove(path)
    except OSError as exc:
        log(f"could not delete {path} ({exc}) - refusing to act, or it would "
            f"run again on every pass")
        return

    argv = ACTIONS.get(cmd)
    if not argv:
        log(f"unknown command {cmd!r} - ignored. Add it to ACTIONS if you want it.")
        return

    log(f"running {cmd}: {' '.join(argv)}")
    try:
        # shell=False (the default with a list) is the security boundary here.
        result = subprocess.run(argv, shell=False, timeout=120)
        log(f"{cmd} exited {result.returncode}")
    except subprocess.TimeoutExpired:
        log(f"{cmd} timed out after 120s")
    except OSError as exc:
        log(f"{cmd} failed to start: {exc}")


def main():
    args = [a for a in sys.argv[1:] if a != "--loop"]
    loop = "--loop" in sys.argv
    if not args:
        print(__doc__)
        return 1

    folder = args[0]
    if not os.path.isdir(folder):
        log(f"not a folder: {folder}")
        return 1

    if not loop:
        run_once(folder)
        return 0

    log(f"watching {os.path.join(folder, FILENAME)}")
    while True:
        run_once(folder)
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
