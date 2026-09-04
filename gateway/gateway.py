"""
============================================================
WastelandZ Gateway — Flask REST API (multi-server hive)
============================================================
Bridges Arma Reforger to MySQL. Reforger's built-in RestApi
class calls these endpoints.

MULTI-SERVER HIVE
  The gateway serves MANY game servers from one process. config.SERVERS lists
  each server as {server_id, port, host, api_key}. The gateway opens a listener
  on EVERY configured port; a request is identified by the PORT it arrived on,
  which resolves that server's server_id and its own api_key. All servers share
  one MySQL database = one hive.

  Player data (money, bank, inventory, faction, stats, marker prefs) is shared
  hive-wide, keyed by (player_uid, hive_id). World context (position, stance,
  alive, /recover) is per-server in player_sessions. World objects (placements,
  money drops) are per-server. See docs/HIVE_SHARED_PLAN.md.

AUTH
  All requests except /api/ping use ?token= (XOR("VERB:ts", that server's key)).
  Legacy ?api_key= is accepted as a fallback. The key checked is the one for the
  server whose port the request arrived on.

ROBUSTNESS
  Every DB handler uses try/finally so the pooled connection is always returned.
  Raw DB error strings are logged server-side, never returned to the client.

Start: python gateway.py
============================================================
"""

from flask import Flask, request, jsonify, has_request_context
from datetime import datetime
import mysql.connector
from mysql.connector import pooling
import json
import sys
import ast
import os
import re
import time

import migrate

# --------------------------------------------------------
# Load config
# --------------------------------------------------------
try:
    import config
except ImportError:
    print("=" * 60)
    print("ERROR: config.py not found!")
    print("Copy config.example.py to config.py and edit it.")
    print("=" * 60)
    sys.exit(1)


# --------------------------------------------------------
# SELF-HEALING CONFIG — write missing optional settings on startup.
#
# Same idea the mod uses for its .conf files: a release that ADDS a setting
# should not leave an existing admin without it. Their config.py is never
# rewritten by an update (the kit ships config.example.py, not config.py), so
# without this the setting simply is not there and the fallback applies
# silently — and a default tuned for a two-server gateway is exactly wrong for
# the admin running six.
#
# RULES, in order of how badly each would hurt if broken:
#
#   1. APPEND ONLY. An existing value is never edited or reordered. Detection
#      is hasattr() on the imported module, not a text search, so a setting
#      that is present but commented out, or set in an unusual way, still
#      counts as present — what matters is whether it resolves at runtime.
#
#   2. NOTHING SECRET IS INVENTED. DB_PASSWORD, API_KEY and SERVERS are
#      deliberately absent from this list. There is no safe default for a
#      credential, and generating an api_key would produce one that does not
#      match the game server's HFWastelandZ_secrets.conf — the gateway would
#      then reject every request while looking healthy. A missing credential
#      must stop the gateway, not be papered over.
#
#   3. A FAILED WRITE IS NOT FATAL. Read-only file, wrong owner, running as a
#      service user with no write access — all plausible. The values are
#      applied IN MEMORY regardless, so this run behaves correctly, and the
#      admin is told exactly what to paste in by hand.
#
#   4. THE CURRENT RUN USES THEM IMMEDIATELY. setattr on the module means no
#      second restart to pick up what was just written.
# --------------------------------------------------------
CONFIG_AUTOFILL = [
    ("HIVE_ID", "default",
     "Which hive this gateway serves. Servers sharing a hive share money and\n"
     "# bank. Leave alone unless you run more than one independent hive."),
    ("DB_POOL_SIZE_v2", 32,
     "Pooled MySQL connections. 32 is the connector's maximum.\n"
     "# Keep HTTP_THREADS x number_of_servers <= this, or bursts return 503 —\n"
     "# and a 503 on a save is a lost save.\n"
     "#\n"
     "# REPLACES DB_POOL_SIZE, which shipped as 10 and is retired on startup.\n"
     "# Ten was fine while the development HTTP server dropped excess requests\n"
     "# at the socket; with waitress they reach the pool instead and 22 of 32\n"
     "# would have taken an HTTP 503. Raising the OLD default could not reach\n"
     "# anyone: every 0.7.x config.py already contains that line, and the\n"
     "# autofill only ever adds what is MISSING."),
    ("HTTP_SERVER", "auto",
     "auto | waitress | werkzeug. 'auto' uses waitress when installed and\n"
     "# falls back to Flask's development server, which drops requests under a\n"
     "# reconnect burst. pip install waitress."),
    ("HTTP_THREADS", 16,
     "Request threads per listening server. Lower this as you add servers —\n"
     "# see DB_POOL_SIZE_v2 above. 1-2 servers -> 16, 3 -> 10, 4 -> 8,\n"
     "# 6 -> 5, 10 -> 3, 16+ -> 2."),
    ("FLASK_DEBUG", False,
     "Never True on a live server: it exposes an interactive debugger."),
    ("MONITORING_ENABLED", False,
     "Enables /api/admin/health. Needs monitor.py present."),
    ("PLAYER_ONLINE_WINDOW_SEC", 900,
     "How recently a player must have been seen to count as online."),
    ("LOG_FILE", "gateway.log",
     "Rotating log file. Relative paths sit beside gateway.py.\n"
     "# Set to \"\" to log to the console only."),
    ("LOG_MAX_MB", 5,
     "Roll over at this size. Total disk use is capped at\n"
     "# LOG_MAX_MB x (LOG_BACKUPS + 1) and never grows past it - there are no\n"
     "# per-day files to prune."),
    ("LOG_BACKUPS", 3,
     "How many rolled files to keep (gateway.log.2, .3, .4)."),
    ("LOG_COLOR", True,
     "Colour the console. Switched off automatically when output is not a\n"
     "# terminal, or when NO_COLOR is set in the environment. The log FILE is\n"
     "# always plain text either way."),
]


# --------------------------------------------------------
# CONFIG FILE MAINTENANCE - shared by the autofill and the retirement.
#
# WHY THESE ARE SHARED. Both paths edit the SAME file on the SAME start, and
# both used to take their own backup and write with the platform default. That
# produced two .bak- files per boot and, on Windows, appended CRLF lines to an
# LF file. Neither breaks anything - Python does not care about mixed endings -
# but a self-maintaining config that leaves litter and mangles line endings is
# hard to trust, and trust is the whole point of a file the gateway edits on an
# admin's behalf.
#
# LINE ENDINGS. Every read and write below passes newline="", which switches
# off universal-newline translation in BOTH directions. Without it, reading on
# any platform turns CRLF into LF and writing on Windows turns LF back into
# CRLF, so a Linux admin's LF config.py silently becomes CRLF the first time a
# Windows gateway touches it - and vice versa. With it, whatever the admin
# wrote is what stays on disk, and appended lines match what is already there.
# --------------------------------------------------------

# One backup per process, however many paths want one.
_CONFIG_BACKUP = None


def _config_eol(text):
    """The line ending this file already uses. Default LF for a new file."""
    m = re.search(r"\r\n|\r|\n", text)
    return m.group(0) if m else "\n"


def _config_lines(text):
    """Split into lines KEEPING terminators, exactly where Python would.

    str.splitlines() also breaks on form feed, vertical tab and the Unicode
    separators, none of which end a line in Python source. A form feed is legal
    in a .py file, so splitlines() could split a line Python considers whole.
    """
    return re.findall(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$", text)


def _backup_config_once(path, text):
    """Write ONE timestamped backup per boot; return its basename.

    NEVER OVERWRITES AN EXISTING BACKUP. The stamp is only second-resolution,
    so two starts inside the same second would collide and the second one would
    destroy the first - and the backup it destroyed could be the only copy of
    what the admin had before any of this ran. "x" is exclusive creation: it
    raises rather than truncate, and the suffix loop walks to a free name.
    """
    global _CONFIG_BACKUP
    if _CONFIG_BACKUP:
        return os.path.basename(_CONFIG_BACKUP)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{path}.bak-{stamp}"
    candidate, n = base, 1
    while True:
        try:
            with open(candidate, "x", encoding="utf-8", newline="") as fh:
                fh.write(text)
            break
        except FileExistsError:
            n += 1
            candidate = f"{base}-{n}"
            if n > 50:                    # give up rather than spin forever
                raise

    _CONFIG_BACKUP = candidate
    return os.path.basename(candidate)


def ensure_config_defaults():
    """Append settings this build expects but this config.py does not define."""
    # Every name must be a legal Python identifier before it is written.
    #
    # Not paranoia - this exact failure shipped: a bulk rename across the file
    # rewrote the string "HIVE_ID" in the table above into "current_hive_id()",
    # hasattr() said the config lacked it (nothing is named that), and the
    # autofill appended `current_hive_id() = 'default'` to config.py. The next
    # start died on a SyntaxError in the ADMIN'S OWN file - a file this code is
    # trusted to edit and they did not write.
    #
    # Refuse loudly and skip the entry. A missing setting falls back to its
    # default; an unparseable config.py stops the gateway.
    bad = [k for (k, _v, _c) in CONFIG_AUTOFILL if not k.isidentifier()]
    if bad:
        print(f"[GATEWAY] BUG: CONFIG_AUTOFILL has non-identifier key(s) {bad} — "
              f"skipping them rather than writing an unparseable config.py")

    missing = [(k, v, c) for (k, v, c) in CONFIG_AUTOFILL
               if k.isidentifier() and not hasattr(config, k)]
    if not missing:
        return

    # Apply in memory FIRST, so a write failure below cannot leave the process
    # running without settings it is about to read.
    for name, value, _ in missing:
        setattr(config, name, value)

    names = ", ".join(n for n, _, _ in missing)
    print(f"[GATEWAY] config.py is missing {len(missing)} setting(s): {names}")

    path = getattr(config, "__file__", None)
    if not path:
        print("[GATEWAY]   cannot locate config.py on disk — using defaults for this run only")
        return

    try:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        with open(path, "r", encoding="utf-8", newline="") as fh:
            existing = fh.read()

        eol = _config_eol(existing)
        lines = []
        # A file not ending in a newline would glue our first line onto the
        # admin's last one.
        if existing and not existing.endswith(("\n", "\r")):
            lines.append("")
        lines.append("")
        lines.append("# " + "-" * 58)
        lines.append(f"# Added automatically on {stamp} by the gateway, which found them missing.")
        lines.append("# These are this build's defaults for settings your config.py did not")
        lines.append("# define. Edit them freely — they are only ever added, never changed.")
        lines.append("# " + "-" * 58)
        for name, value, comment in missing:
            lines.append("")
            lines.append(f"# {comment}")
            lines.append(f"{name} = {value!r}")
        lines.append("")

        # The comment blocks above embed literal \n inside their text, so the
        # appended block is normalised to this file's ending as a whole rather
        # than only at the joins.
        block = eol.join(lines).replace("\r\n", "\n").replace("\n", eol)
        updated = existing + block

        # Same guard the retirement uses: never leave a config.py that Python
        # cannot read. The values are already live in memory, so refusing to
        # write costs the admin nothing but a repeat of this message next boot.
        ast.parse(updated)

        backup_name = _backup_config_once(path, existing)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(updated)

        print(f"[GATEWAY]   written to config.py with this build's defaults")
        print(f"[GATEWAY]   previous file saved as {backup_name}")
    except Exception as exc:
        # Not fatal. The values are already live for this run.
        print(f"[GATEWAY]   could NOT write config.py ({exc})")
        print("[GATEWAY]   running with defaults; add these by hand to keep them:")
        for name, value, _ in missing:
            print(f"[GATEWAY]     {name} = {value!r}")


ensure_config_defaults()


# --------------------------------------------------------
# RETIRING A SETTING - the only code that DELETES from config.py.
#
# WHY A DELETE EXISTS AT ALL. DB_POOL_SIZE shipped as 10 in 0.7.1. That was
# correct while werkzeug dropped excess requests at the socket, before they
# could ever reach the pool. waitress does not: 16 threads x 2 listeners is 32
# requests in flight, and a pool of 10 leaves 22 of them taking an HTTP 503 -
# which on a save is a lost write. Changing the DEFAULT fixes nobody, because
# every 0.7.x config.py already contains the line and ensure_config_defaults()
# only ever adds what is MISSING. So the NAME is retired instead: the autofill
# above adds DB_POOL_SIZE_v2 at 32, this removes the dead line, and no admin is
# left tuning a setting that nothing reads.
#
# WRITTEN TO FAIL CLOSED. The comment at the top of ensure_config_defaults()
# records what a bad write to this file costs: an unparseable config.py and a
# gateway that dies on a SyntaxError in a file the admin did not write.
# Deleting a line is strictly riskier than appending one, so:
#
#   - Only a TOP-LEVEL assignment is matched, anchored at column 0. The name
#     inside a comment, a string, or an indented block is left alone.
#     DB_POOL_SIZE_v2 cannot match it: the next character is "_", which is
#     neither whitespace nor "=".
#   - The result is ast.parse()d BEFORE anything is written. If it does not
#     parse, NOTHING is written and the original file stands. A stale setting
#     is harmless; an unparseable config.py stops the gateway.
#   - A timestamped backup is taken first, exactly as the autofill does.
#   - Every failure path is non-fatal and says what it did. The value this
#     build actually uses is already live in memory either way.
# --------------------------------------------------------
RETIRED_CONFIG_KEYS = ["DB_POOL_SIZE"]


def retire_legacy_config_keys():
    """Delete settings this build no longer reads from the admin's config.py."""
    present = [k for k in RETIRED_CONFIG_KEYS if hasattr(config, k)]
    if not present:
        return

    path = getattr(config, "__file__", None)
    if not path:
        return

    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            original = fh.read()
    except Exception as exc:
        print(f"[GATEWAY] could not read config.py to retire old settings ({exc})")
        return

    matchers = [(k, re.compile(r"^" + re.escape(k) + r"\s*=")) for k in present]
    kept, dropped = [], []
    for line in _config_lines(original):
        hit = next((k for k, rx in matchers if rx.match(line)), None)
        if hit:
            dropped.append((hit, line.strip()))
        else:
            kept.append(line)

    if not dropped:
        return

    updated = "".join(kept)

    try:
        ast.parse(updated)
    except SyntaxError as exc:
        names = ", ".join(k for k, _ in dropped)
        print(f"[GATEWAY] removing {names} would leave config.py unparseable ({exc})")
        print("[GATEWAY]   config.py left exactly as it was")
        return

    try:
        backup_name = _backup_config_once(path, original)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(updated)
    except Exception as exc:
        print(f"[GATEWAY] could NOT rewrite config.py to retire old settings ({exc})")
        print("[GATEWAY]   left as it was; this build ignores the old setting anyway")
        return

    for name, text in dropped:
        print(f"[GATEWAY] retired {name} from config.py - this build does not read it")
        print(f"[GATEWAY]   removed:  {text}")
    print(f"[GATEWAY]   previous file saved as {backup_name}")

    # Drop it from the imported module too, so nothing in this run can read the
    # stale value by accident.
    for name, _ in dropped:
        if hasattr(config, name):
            delattr(config, name)


retire_legacy_config_keys()


# --------------------------------------------------------
# LOGGING — timestamped console, plus a rotating file that maintains itself.
#
# WHY A TEE RATHER THAN 95 EDITED print() CALLS. Every existing print keeps
# working untouched, and so does every print added later - nobody has to
# remember a convention. It also catches what matters most: an unhandled
# traceback goes to STDERR, so teeing that too means a crash leaves its stack
# in the file instead of only in a console window that has already closed.
#
# WHY SIZE-CAPPED AND NOT PER-DAY. Daily files accumulate forever and become a
# chore nobody does. This has a hard ceiling - LOG_MAX_MB x (LOG_BACKUPS + 1) -
# and once it reaches it, it stays there. Nothing to prune, nothing to
# schedule, and disk usage you can state in advance.
#
# The console is left exactly as it was. An admin watching the window sees the
# same lines, now with a time in front.
# --------------------------------------------------------
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text):
    """Escape codes are for a terminal, never for a file.

    The startup banner already emitted BOLD/RESET before any of this existed,
    so without stripping, the log filled with \x1b[1m litter that breaks grep
    and makes every line awkward to read in an editor.
    """
    return _ANSI_RE.sub("", text)


def _terminal_supports_colour():
    """TERM tells you what the far end of an SSH session actually is.

    isatty() only says "something interactive is attached" - it is true for a
    dumb terminal, a serial console and a CI harness alike. TERM is what
    distinguishes them, and it is the variable every other tool checks:

      unset   - no terminal type advertised, assume nothing
      dumb    - explicitly says it cannot do this

    PuTTY, xterm, Windows Terminal and a plain SSH login all advertise
    something real (xterm, xterm-256color, vt100) and handle the basic ANSI
    set fine.
    """
    if os.name == "nt":
        return True                  # decided by _enable_windows_ansi instead
    term = os.environ.get("TERM", "")
    return bool(term) and term != "dumb"


def _enable_windows_ansi():
    """Turn on virtual-terminal processing so Windows renders ANSI.

    Windows 10+ supports it but does NOT enable it for a plain console by
    default. Modern Terminal does; conhost often does not. Wrapped in a broad
    except because on an old build, a redirected handle, or a non-Windows
    Python this simply is not available - and colour is never worth an
    exception on startup.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        # -11 = STD_OUTPUT_HANDLE. 7 = PROCESSED_OUTPUT | WRAP_AT_EOL |
        # VIRTUAL_TERMINAL_PROCESSING.
        return bool(k.SetConsoleMode(k.GetStdHandle(-11), 7))
    except Exception:
        return False


class _Colour:
    """Decides once whether colour is safe, then paints by line content.

    Three ways to end up with no colour, all deliberate:
      - LOG_COLOR = False in config.py
      - NO_COLOR set in the environment (the de-facto convention)
      - output is not a terminal, i.e. piped to a file or a service log,
        where escape codes are noise rather than formatting
    """

    RESET = "\x1b[0m"

    def __init__(self, enabled):
        self.on = bool(enabled)

    def paint(self, stamp, line):
        if not self.on:
            return f"{stamp} {line}"

        # ORIGINAL ANSI ONLY - 30-37 plus bold/dim. The 90-97 "bright" range
        # is an aixterm extension: xterm, PuTTY and Windows Terminal render
        # it, a strict VT100 need not, and no colour here is worth a line of
        # garbage on somebody's serial console.
        body = ""
        if "Traceback" in line or line.startswith("ERR ") or "Error" in line:
            body = "\x1b[31m"                              # red
        elif "WARN" in line or "WARNING" in line or "missing" in line:
            body = "\x1b[33m"                              # yellow
        elif line.startswith("[MIGRATE]"):
            body = "\x1b[36m"                              # cyan
        elif "OK" in line or "created" in line or "up." in line:
            body = "\x1b[32m"                              # green

        # Dim timestamp so the eye lands on the message. A terminal without
        # dim ignores the code and prints normally, so no fallback is needed.
        if not body:
            return f"\x1b[2m{stamp}{self.RESET} {line}"
        return f"\x1b[2m{stamp}{self.RESET} {body}{line}{self.RESET}"


class _TeeStream:
    """Line-buffered tee. BOTH console and file get a timestamp per line.

    Buffers until a newline because print() emits the text and the "\n" as
    SEPARATE writes - stamping every write would drop a timestamp into the
    middle of a line. Whatever is left unterminated is flushed on exit.

    The console is stamped as well as the file. It was not, briefly, on the
    reasoning that an admin watching the window wanted it unchanged - which was
    wrong. A console line with no time on it is the one you cannot correlate
    with anything later, and "when did the pool come up" is exactly the
    question a startup log gets asked.
    """

    def __init__(self, real, sink, tag, colour):
        self._real = real
        self._sink = sink
        self._tag = tag
        self._colour = colour
        self._buf = ""

    def _stamp(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _line(self, line):
        # Full date AND time on the console, same as the file. A server
        # window can stay open for weeks, so a bare clock time is ambiguous
        # the moment you scroll back past midnight.
        try:
            self._real.write(self._colour.paint(self._stamp(), line) + "\n")
        except Exception:
            pass
        if self._sink:
            # Plain text to disk, always. Colour is a property of the terminal
            # you are looking at, not of the event that happened.
            self._sink.emit(self._tag, _strip_ansi(line))

    def write(self, text):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._line(line)

    def flush(self):
        if self._buf:
            line, self._buf = self._buf, ""
            self._line(line)
        try:
            self._real.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self._real.isatty()
        except Exception:
            return False


class _RotatingSink:
    """Append lines, roll over at a size cap, keep a fixed number of old files.

    Deliberately not logging.handlers.RotatingFileHandler: that wants to OWN
    formatting and levels, and everything here is already a formatted print.
    This just needs "append a line, roll when big".
    """

    def __init__(self, path, max_bytes, backups):
        self._path = path
        self._max = max_bytes
        self._backups = backups
        self._fh = None
        self._open()

    def _open(self):
        try:
            d = os.path.dirname(self._path)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            self._fh = open(self._path, "a", encoding="utf-8", errors="replace")
        except Exception as exc:
            # Never take the gateway down over a log file. Console still works.
            sys.__stderr__.write(f"[GATEWAY] log file unavailable ({exc}) — console only\n")
            self._fh = None

    def _roll(self):
        """gateway.log -> .2, .2 -> .3, ... and the oldest is dropped.

        Backups are numbered from 2 so the live file keeps its plain name -
        an admin tailing gateway.log never has to think about which one is
        current.

        Walked OLDEST FIRST. Going the other way would rename .2 onto .3
        before .3 had moved, destroying a file that should have survived.
        """
        try:
            self._fh.close()
        except Exception:
            pass
        try:
            oldest = self._backups + 1        # e.g. backups=3 -> .4 is dropped
            if os.path.exists(f"{self._path}.{oldest}"):
                os.remove(f"{self._path}.{oldest}")

            for i in range(oldest - 1, 1, -1):     # .3 -> .4, then .2 -> .3
                src = f"{self._path}.{i}"
                if os.path.exists(src):
                    os.rename(src, f"{self._path}.{i + 1}")

            if os.path.exists(self._path):         # live file -> .2
                os.rename(self._path, f"{self._path}.2")
        except Exception:
            pass
        self._open()

    def emit(self, tag, line):
        if not self._fh:
            return
        try:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._fh.write(f"{stamp} {tag} {line}\n")
            self._fh.flush()          # flush every line: a crash must not lose the last one
            if self._max > 0 and self._fh.tell() >= self._max:
                self._roll()
        except Exception:
            pass


def _install_logging():
    # LOG_FILE "" means CONSOLE ONLY - not "no timestamps". Returning early
    # here skipped installing the tee altogether, so switching the file off
    # also silently switched the timestamps off, which is not what the setting
    # says and not what anyone would want.
    path = str(getattr(config, "LOG_FILE", "gateway.log"))
    sink = None
    max_mb = 0
    backups = 0
    if path:
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
        max_mb = float(getattr(config, "LOG_MAX_MB", 5))
        backups = int(getattr(config, "LOG_BACKUPS", 3))
        sink = _RotatingSink(path, int(max_mb * 1024 * 1024), backups)

    want = bool(getattr(config, "LOG_COLOR", True))
    if os.environ.get("NO_COLOR"):
        want = False
    tty = False
    try:
        tty = sys.__stdout__.isatty()
    except Exception:
        tty = False
    colour = _Colour(want and tty and _terminal_supports_colour()
                     and _enable_windows_ansi())

    sys.stdout = _TeeStream(sys.__stdout__, sink, "    ", colour)
    sys.stderr = _TeeStream(sys.__stderr__, sink, "ERR ", colour)

    if sink:
        total = max_mb * (backups + 1)
        print(f"[GATEWAY] logging to {path} (max {max_mb:g} MB x {backups + 1} files = {total:g} MB ceiling)")
    else:
        print("[GATEWAY] LOG_FILE is empty — console only, still timestamped")


_install_logging()

# --------------------------------------------------------
# Load crypto module
# --------------------------------------------------------
try:
    from hf_crypto import decrypt_auth_token, decrypt_payload, validate_timestamp
    CRYPTO_AVAILABLE = True
    print("[GATEWAY] hf_crypto loaded — encrypted token auth supported")
except ImportError:
    CRYPTO_AVAILABLE = False
    print("[GATEWAY] WARNING: hf_crypto.py not found — encrypted tokens disabled")
    print("[GATEWAY] Only legacy api_key param auth will work")

# --------------------------------------------------------
# Load monitor module (optional — powers /api/admin/health)
# --------------------------------------------------------
MONITOR_AVAILABLE = False
if getattr(config, "MONITORING_ENABLED", False):
    try:
        from monitor import collect_metrics
        MONITOR_AVAILABLE = True
        print("[GATEWAY] monitor loaded — /api/admin/health endpoint enabled")
    except ImportError as e:
        print(f"[GATEWAY] WARNING: monitor disabled — {e}")
    except Exception as e:
        print(f"[GATEWAY] WARNING: monitor failed to load — {e}")
else:
    print("[GATEWAY] monitor disabled (MONITORING_ENABLED=False)")

app = Flask(__name__)
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
app.config['JSON_SORT_KEYS'] = False

# --------------------------------------------------------
# Version
# --------------------------------------------------------
# 0.9.1 (2026-08-29) - NOT a cosmetic bump. Two materially different
# gateways shipped as 0.9.0: the earlier beta had no owner_dead at all.
# A mod expecting the death flag would have handshaked CLEAN against it,
# then read every player as alive and silently restored gear to the dead.
# The version exists to make exactly that loud, so it had to move.
# 0.9.2 (2026-08-29) — position is now scoped per realm and per map.
# player_sessions gained share_group, map_name joined the PRIMARY KEY, and
# every read and write of that table now carries all five key columns.
#
# The number MUST move with that. A 0.9.1 mod against this gateway sends no
# gear_group on save, so every position collapses into ALPHA; a 0.9.2 mod
# against a 0.9.1 gateway has its gear_group ignored and nothing is scoped.
# Both are SILENT degradations, and the version handshake is the only thing
# that turns either into a visible error. Two different gateways shipping as
# 0.9.0 is exactly how the owner_dead divergence went unnoticed.
# 0.9.3 (2026-08-30) - the held weapon moved to player_sessions.
#
# players.weapon is HIVE scoped: one value for the whole account, while gear is
# REALM scoped. A player holding an AK in ALPHA and an M249 in BRAVO had the
# second overwrite the first, and swapping back restored a weapon their ALPHA
# loadout did not contain - proven in a host log at 20:48, where the client
# polled for three seconds and correctly refused to equip a weapon that was not
# in its slots. player_sessions.weapon inherits the realm+map key from 0092.
#
# The number moves because a 0.9.2 mod against this gateway reads the session
# weapon that nothing has written yet, and a 0.9.3 mod against a 0.9.2 gateway
# gets the hive-wide value back. Both degrade quietly; the handshake is what
# makes either visible.
# 0.9.4 (2026-08-31) - the write stamp, and the realm list the join card asks
# for.
#
# Every player save now records the (server_id, boot_session_id) that wrote
# it, and the load hands it back. That lets one comparison separate "you
# played here earlier this run" from "this server has restarted since you
# left" - a distinction nothing could draw before, and the reason a returning
# player after a crash was held to the strict last-location rule they had no
# way to satisfy. The column has existed and sat NULL since 0.9.0; only the
# read and the write were missing. See PLAYER_GEAR_STATE_CARD.md S8.
#
# data_list gained ?groups=1: the realm names holding a namespace, as one flat
# CSV and no payloads, because the join card names where the gear actually is
# and Enforce cannot parse the full listing.
#
# The number moves because both directions degrade in silence. A 0.9.3 mod
# against this gateway sends no stamp, so every row saves NULL and every
# rejoin reads as a restart - the forgiving direction, but permanently on. A
# 0.9.4 mod against a 0.9.3 gateway sends a stamp nothing stores and reads
# back an empty one, reaching the identical always-restarted state with no
# error anywhere. That is precisely the failure the handshake exists for.
GATEWAY_VERSION = "0.9.5"

# --------------------------------------------------------
# Server roster — multi-server hive.
# Preferred: config.SERVERS = [{server_id, port, host, api_key}, ...].
# Backward-compatible fallback: a single server from the legacy flat keys.
# --------------------------------------------------------
def _resolve_servers():
    default_hive = str(getattr(config, "HIVE_ID", "default"))
    raw = getattr(config, "SERVERS", None)
    if raw:
        out = []
        for s in raw:
            out.append({
                "server_id": str(s["server_id"]),
                "port": int(s["port"]),
                "host": str(s.get("host", "127.0.0.1")),
                "api_key": str(s["api_key"]),
                # Per-entry hive. Omit it and the entry joins the gateway-wide
                # HIVE_ID, which is every existing config - so this is additive
                # and nobody's hive changes by upgrading.
                "hive_id": str(s.get("hive_id", default_hive)),
            })
        return out
    # Legacy single-server fallback
    return [{
        "server_id": str(getattr(config, "SERVER_ID", "dev-01")),
        "port": int(getattr(config, "GATEWAY_PORT", 5000)),
        "host": str(getattr(config, "GATEWAY_HOST", "127.0.0.1")),
        "api_key": str(getattr(config, "API_KEY", "")),
        "hive_id": default_hive,
    }]

def _key_is_usable(api_key):
    """False for a key that must never authenticate anyone.

    Empty, whitespace, or an obvious placeholder. Kept deliberately small
    and dumb: this is a floor, not a password policy. Its only job is that
    a key nobody chose can never be accepted, because the comparison in
    check_auth() treats an absent api_key parameter as "" and would
    otherwise match one.
    """
    if not api_key or not str(api_key).strip():
        return False
    lowered = str(api_key).strip().lower()
    # Every placeholder shipped in config.example.py or quoted on the
    # setup site. These are PUBLIC strings - running on one is running on
    # a key an attacker already has.
    for marker in ("change_me", "changeme", "your_key", "your-key",
                   "example", "placeholder", "todo"):
        if marker in lowered:
            return False
    return True


def _validate_keys(servers):
    """Names every server whose key cannot authenticate anyone.

    Startup half of the check in check_auth(). Reported before any port is
    bound, so an admin is told at boot rather than discovering it when
    saves stop - or, in the empty-key case, never discovering it at all
    because everything appears to work while being open to the internet.
    """
    return [s for s in servers if not _key_is_usable(s.get("api_key"))]


SERVERS = _resolve_servers()
SERVERS_BY_PORT = {s["port"]: s for s in SERVERS}

# DEFAULT hive for entries that name none. Still the only hive on a
# single-tenant gateway, which is almost every gateway.
#
# NOT the hive for a request - use current_hive_id(). One gateway can now serve
# several hives at once (a hosting provider giving each customer their own port
# and key), and reading this global instead of the request's own hive would let
# one customer read another's players. Every table is already hive-scoped; the
# process was the only thing that was not.
HIVE_ID = str(getattr(config, "HIVE_ID", "default"))


def current_hive_id():
    """The hive that owns THIS request, resolved from the listening port.

    Falls back to the module-level default when there is no request, or when
    the request arrived on a port that is not in SERVERS - which is the only
    sensible answer, and is what every caller expects.

    NOTE the fallback is HIVE_ID, the module global, NOT this function. It read
    `return current_hive_id()` for one commit: the bulk rewrite that replaced
    HIVE_ID with current_hive_id() across 62 lines also rewrote this function's
    own fallback, making it call itself forever."""
    srv = current_server()
    if srv:
        return srv["hive_id"]
    return HIVE_ID

# Flask web-service debug (gateway only — NOT the game server's DEV_MODE/HF_DEBUG).
FLASK_DEBUG = getattr(config, "FLASK_DEBUG", getattr(config, "DEBUG", False))

# --------------------------------------------------------
# Per-request server identity (by the port the request arrived on)
# --------------------------------------------------------
def current_server():
    """The configured server for the port this request arrived on, or None.

    Returns None OUTSIDE a request rather than raising. `request` is a proxy
    that throws "Working outside of request context" the moment it is touched
    with no active request, so startup code touching this - a banner, a
    migration, a warm-up query - would take the whole process down.

    Callers already handle None (they fall back to the gateway-wide default),
    so returning it is both safe and the honest answer: with no request there
    is genuinely no "current" server."""
    if not has_request_context():
        return None
    try:
        port = int(request.environ.get("SERVER_PORT", 0))
    except (TypeError, ValueError):
        return None
    return SERVERS_BY_PORT.get(port)

def current_server_id():
    srv = current_server()
    return srv["server_id"] if srv else "unknown"

# --------------------------------------------------------
# Database connection helper
# --------------------------------------------------------
_db_pool = None

# Highest applied migration, filled in at startup by the migration runner.
# Reported in /api/ping so the mod can show mod / gateway / schema versions
# together in the F8 SERVER tab instead of an admin inferring them.
SCHEMA_VERSION = 0

def _pool_size():
    """How many MySQL connections to pool.

    Default raised from 10 to 32 (the connector's maximum) after measuring
    this: with waitress serving 16 threads per listener, a two-server gateway
    can have 32 requests in flight, and a pool of 10 meant the other 22 got
    get_db() -> None -> HTTP 503. Under werkzeug the same overload was
    invisible, because requests were dropped at the socket before they ever
    reached the pool.

    A 503 on a save is a LOST WRITE, which is exactly what must not happen.
    """
    return min(int(getattr(config, "DB_POOL_SIZE_v2", 32)), 32)


def _init_db_pool():
    """Initialize MySQL connection pool (called once at startup)."""
    global _db_pool
    try:
        _db_pool = pooling.MySQLConnectionPool(
            pool_name="gateway_pool",
            pool_size=_pool_size(),
            pool_reset_session=True,
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME
        )
        print(f"[GATEWAY] DB connection pool created (size={_pool_size()})")
    except mysql.connector.Error as err:
        print(f"[GATEWAY] DB POOL ERROR: {err}")
        _db_pool = None

def get_db():
    """Get a MySQL connection from the pool. Caller MUST close it in a
    finally block so it returns to the pool even on error."""
    global _db_pool
    if not _db_pool:
        _init_db_pool()
    if not _db_pool:
        return None
    # Retry briefly rather than failing the request outright.
    #
    # An exhausted pool is a BURST, not an outage - the connections are busy,
    # not broken, and one is usually free within milliseconds. Returning None
    # immediately turns a 5 ms wait into an HTTP 503, and a 503 on a save is a
    # lost write. Three quick attempts smooth a burst without hiding a real
    # outage: if the pool is genuinely dead, this still gives up in ~60 ms.
    last = None
    for attempt in range(3):
        try:
            return _db_pool.get_connection()
        except mysql.connector.Error as err:
            last = err
            if attempt < 2:
                time.sleep(0.02)
    print(f"[GATEWAY] DB POOL EXHAUSTED after 3 attempts: {last}")
    return None

def _close(conn):
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass

def _iso(value):
    return value.isoformat() if value else ""

# MySQL error numbers worth retrying rather than failing the request.
#   1213  ER_LOCK_DEADLOCK        - InnoDB picked this transaction as the victim
#   1205  ER_LOCK_WAIT_TIMEOUT    - waited too long for a row lock
# Both are TRANSIENT and both are caused by CONCURRENCY, not by bad data. MySQL
# rolls the loser back and its own message says "try restarting transaction".
_RETRYABLE_ERRNOS = (1213, 1205)


def _is_retryable(err):
    return getattr(err, "errno", None) in _RETRYABLE_ERRNOS


def _db_retry(fn, tag, attempts=6):
    """Run a DB operation, retrying transient lock failures.

    Found by load test 2026-08-23: 128 players reconnecting at once produced
        1213 Deadlock found when trying to get lock; try restarting transaction
    in save_player, which returned HTTP 500. save_player touches `players`
    twice and `player_sessions` once per request, so concurrent saves for
    different players can still interleave into a deadlock on the shared
    table's indexes.

    A 500 there is a LOST SAVE. Retrying is the documented remedy - the losing
    transaction was rolled back cleanly, so re-running it is safe and is not a
    double-write.

    Backoff is tiny and jittered: deadlocks resolve in microseconds, and
    identical backoff across threads just re-collides them.
    """
    import random as _r
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except mysql.connector.Error as err:
            if not _is_retryable(err):
                raise
            last = err
            if attempt < attempts - 1:
                # Exponential-ish with jitter. A flat 5-20ms was not always
                # enough at high concurrency - the ramp test still produced a
                # few 500s at 3 attempts, and each one is a lost save.
                time.sleep((0.005 * (attempt + 1)) + _r.random() * 0.015)
                print(f"[GATEWAY] {tag}: transient lock error ({err.errno}) — retry {attempt + 1}")
    raise last


def _db_error(tag, err):
    print(f"[GATEWAY] {tag} DB error: {err}")
    return jsonify({"status": "error", "message": "database error"}), 500

def _internal_error(tag, err):
    print(f"[GATEWAY] {tag} error: {err}")
    return jsonify({"status": "error", "message": "internal error"}), 500

# --------------------------------------------------------
# Authentication — per-server key, chosen by the request's port.
#   1. Encrypted token (?token=...) — API key never on the wire
#   2. Legacy api_key param (?api_key=...) — backward compatible
# --------------------------------------------------------
def check_auth(expected_verb=None):
    srv = current_server()
    if not srv:
        print("[GATEWAY] Auth: request on an unconfigured port")
        return False
    api_key = srv["api_key"]

    # ------------------------------------------------------------------
    # A SERVER WITH NO USABLE KEY AUTHENTICATES NOBODY.
    #
    # The comparison at the bottom of this function is `key == api_key`,
    # where key defaults to "" when the caller sends no api_key at all. So
    # a configured key of "" made "" == "" TRUE and the gateway answered
    # every anonymous request - the economy database wide open, with
    # nothing in the log to suggest anything was wrong.
    #
    # That was reachable: the legacy single-server fallback in
    # _resolve_servers() builds its key from
    # getattr(config, "API_KEY", ""), so a config with neither a SERVERS
    # list nor an API_KEY produced exactly that.
    #
    # A placeholder is refused for the same reason. Example keys are
    # published in config.example.py and on the setup site, so running on
    # one is running on a key an attacker already has.
    #
    # Checked HERE, per request, rather than only at startup: this cannot
    # be bypassed by import order, a reloaded config, or a code path that
    # skips the boot checks. Startup refuses too - see _validate_keys() -
    # but this is the one that is always in the way.
    # ------------------------------------------------------------------
    if not _key_is_usable(api_key):
        print(f"[GATEWAY] Auth: REFUSED - server '{srv.get('server_id')}' has no "
              f"usable api_key configured. Every request on port {srv.get('port')} "
              f"is rejected until it is set.")
        return False

    token = request.args.get("token", "")
    if token and CRYPTO_AVAILABLE:
        verb, timestamp = decrypt_auth_token(token, api_key)
        if verb is not None:
            if expected_verb and verb != expected_verb:
                print(f"[GATEWAY] Auth: verb mismatch — expected {expected_verb}, got {verb}")
                return False
            return True
        print("[GATEWAY] Auth: encrypted token invalid")
        return False

    key = request.args.get("api_key", "")
    if key == api_key:
        return True
    return False


# --------------------------------------------------------
# ROUTES
# --------------------------------------------------------

@app.route("/api/ping", methods=["GET"])
def ping():
    """Health check — supports both encrypted and unauthenticated pings."""
    is_authed = check_auth("PING")

    db_status = "unknown"
    reregister = False
    conn = get_db()
    try:
        db_status = "connected" if (conn and conn.is_connected()) else "disconnected"

        # ------------------------------------------------------------------
        # HIVE HEARTBEAT.
        #
        # The ping is already sent every 60s, so the volatile fields ride it
        # rather than costing their own request: player count and the short
        # addon fingerprint. The full addon LIST is far too big for a query
        # string and stays on POST /api/hive/register.
        #
        # This is also what makes registration self-healing. Boot-state gateway
        # calls do not retry, so a gateway started AFTER the game server would
        # otherwise leave that server invisible in the hive forever - and an
        # invisible server is one whose mod mismatch nobody can see until it
        # eats a player's gear. If we have no row, or the fingerprint we hold
        # disagrees with the one being pinged, we ask for a full re-register and
        # the mod sends it within the minute.
        # ------------------------------------------------------------------
        if is_authed and conn and conn.is_connected():
            _sid = current_server_id()
            _hash = request.args.get("addon_hash", "")
            _online = request.args.get("players", "")
            try:
                _cur = conn.cursor()
                _cur.execute("SELECT addon_hash FROM hive_servers WHERE hive_id=%s AND server_id=%s",
                             (current_hive_id(), _sid))
                _row = _cur.fetchone()
                if not _row:
                    reregister = True
                elif _hash and _row[0] and _row[0] != _hash:
                    # The server's mod set changed since it registered. Its
                    # stored addon list is now a lie, and the F8 compliance view
                    # is only as good as that list.
                    reregister = True
                    print(f"[GATEWAY] {_sid} addon fingerprint changed -> asking for re-register")
                else:
                    _cur.execute(
                        "UPDATE hive_servers SET players_online=%s WHERE hive_id=%s AND server_id=%s",
                        (int(_online or 0), current_hive_id(), _sid))
                    conn.commit()
                _cur.close()
            except mysql.connector.Error as err:
                # A heartbeat must never take the ping down with it. The ping is
                # how the mod decides the gateway is reachable at all.
                print(f"[GATEWAY] hive heartbeat skipped: {err}")
    except Exception as e:
        db_status = f"error: {e}"
    finally:
        _close(conn)

    game_version = request.args.get("gv", "")
    if game_version and game_version != GATEWAY_VERSION:
        print("\033[91m\033[1m")
        print("  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("  GATEWAY VERSION MISMATCH!")
        print(f"  Game expects: {game_version}")
        print(f"  Gateway is:   {GATEWAY_VERSION}")
        print("  RESTART THE GATEWAY!")
        print("  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("\033[0m")

    return jsonify({
        "status": "ok",
        "gateway_version": GATEWAY_VERSION,
        "schema_version": SCHEMA_VERSION,
        # INT, not a bool. The mod parses this with a flat scanner that reads
        # quoted strings or digits; a bare JSON `true` matches neither and
        # would silently never trigger a re-register.
        "reregister": 1 if reregister else 0,
        "database": db_status,
        "server_id": current_server_id(),
        "hive_id": current_hive_id(),
        "authenticated": is_authed,
        "crypto_enabled": CRYPTO_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    })


@app.route("/api/admin/health", methods=["GET"])
def admin_health():
    """System + gateway metrics for the bot / admin tooling. Read-only."""
    if not MONITOR_AVAILABLE:
        return jsonify({"status": "error", "message": "monitoring disabled"}), 503
    if not check_auth("HEALTH"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    try:
        metrics = collect_metrics()
    except Exception as e:
        print(f"[GATEWAY] /api/admin/health metric collection failed: {e}")
        return jsonify({"status": "error", "message": "metric collection failed"}), 500

    db_status = "unknown"
    conn = get_db()
    try:
        db_status = "connected" if (conn and conn.is_connected()) else "disconnected"
    except Exception as e:
        db_status = f"error: {e}"
    finally:
        _close(conn)

    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "gateway": {
            "version": GATEWAY_VERSION,
            "schema_version": SCHEMA_VERSION,
            "server_id": current_server_id(),
            "hive_id": current_hive_id(),
            "database": db_status,
            "crypto_enabled": CRYPTO_AVAILABLE,
        },
        "system": metrics,
    })


# --------------------------------------------------------
# Player profile (SHARED, hive-wide) + session (per-server)
# --------------------------------------------------------

@app.route("/api/player/<uid>", methods=["GET"])
def get_player(uid):
    """Load a player: shared hive profile merged with this server's session row."""
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM players WHERE player_uid = %s AND hive_id = %s", (uid, current_hive_id()))
        prof = cursor.fetchone()
        if not prof:
            return jsonify({"status": "ok", "player": None, "new_player": True})

        # Phase 3 anti-clobber: claim ownership for this server on load (join).
        # A later/stale save from a server the player has left is then rejected.
        #
        # ARRIVAL GRACE (2026-08-22). current_server_id was doing two
        # contradictory jobs: "who owns this player right now" (overwritten on
        # every load) and "where did they last play" (must survive a load). The
        # claim won, so the second load of one arrival reported THIS server as
        # the last server and the mod wiped the player's gear.
        #
        # arrival_grace splits them. Armed ONLY when the stored owner differs
        # from this server; a same-server load leaves it untouched, which is
        # exactly what makes it durable across repeated loads, deploy-screen
        # reconnects and every dispatch site. The mod clears it on the first
        # save after a successful spawn.
        _prev_owner = prof.get("current_server_id")
        _arriving = bool(_prev_owner) and _prev_owner != sid
        if _arriving:
            cursor.execute(
                "UPDATE players SET current_server_id = %s, arrival_grace = 1 "
                "WHERE player_uid = %s AND hive_id = %s",
                (sid, uid, current_hive_id()))
            print(f"[GATEWAY] arrival: {uid} {_prev_owner} -> {sid} (grace armed)")
        else:
            cursor.execute(
                "UPDATE players SET current_server_id = %s "
                "WHERE player_uid = %s AND hive_id = %s",
                (sid, uid, current_hive_id()))
        conn.commit()

        # Read the realm + map the mod is asking about BEFORE anything uses
        # them. These moved up here when the session SELECT below started
        # filtering on them: they used to be defined further down, so the
        # query referenced them before assignment and get_player raised
        # UnboundLocalError on every single load. The save quarantine caught
        # the fallout - a failed load is never VERIFIED, so nothing was
        # written - but every player saw a blank profile until it was fixed.
        #
        # BACKWARD COMPATIBLE: a mod that sends no gear_group falls back to
        # the ALPHA default, which is what the resolver below already did.
        _gear_group = request.args.get("gear_group", "")
        _my_map     = request.args.get("map", "")

        # FILTER BY EVERY KEY COLUMN. This read carried only uid + server_id
        # while the PRIMARY KEY also holds hive_id (and, from this release,
        # share_group and map_name), so it returned an ARBITRARY row as soon
        # as more than one existed. The realm and map come from the query
        # params the mod already sends on every load.
        cursor.execute(
            "SELECT * FROM player_sessions "
            "WHERE player_uid = %s AND hive_id = %s AND server_id = %s "
            "  AND share_group = %s AND map_name = %s",
            (uid, current_hive_id(), sid, _gear_group or "ALPHA", _my_map or ""))
        sess = cursor.fetchone()

        player = dict(prof)
        # last_server_id = the server that last owned/saved this player (the stored
        # current_server_id BEFORE this load's claim). The mod uses it to decide
        # "same server -> restore last location + gear" (HFGameMode sameServer check).
        player["last_server_id"] = prof.get("current_server_id")
        player["current_server_id"] = sid
        player["arrival_grace"] = 1 if _arriving else int(prof.get("arrival_grace") or 0)

        # ------------------------------------------------------------------
        # RESOLVED GEAR ROW (2026-08-22)
        #
        # The mod sends the policy it wants applied — its gear group and its
        # current map — and gets back ONE already-chosen row in the SAME flat
        # `inventory` string field it has always parsed.
        #
        # WHY RESOLVE SERVER-SIDE. The alternative was shipping the full
        # candidate list and letting the mod pick. That needs new nested-JSON
        # parsing in Enforce: HFRestClient.ParseStringField finds the FIRST
        # "field" and reads a flat string, so it cannot walk an array of
        # objects whose keys repeat. Hand-rolled bracket matching is exactly
        # where this class of bug lives, and getting it wrong silently returns
        # the wrong player's gear.
        #
        # The gateway still does not DECIDE policy — it does not know what
        # ALPHA means, cannot invent a group, and applies only the rule it is
        # handed. The mod owns the config, the vocabulary and the choice; this
        # is a filtered SELECT, which is what a data layer is for.
        #
        # The read rule, verbatim from the design:
        #     share_group = mine  OR  (server_id = me AND map_name = my map)
        # with '' matching any map, so rows written before map tracking (and
        # the 0081 backfill) still resolve.
        #
        # BACKWARD COMPATIBLE: a mod that sends no gear_group falls back to the
        # legacy players.inventory column, so an older mod against a newer
        # gateway keeps working.
        # ------------------------------------------------------------------

        if _gear_group:
            # ONE ROW, no ordering, no fallback clause (migration 0088).
            #
            # Gear is per HIVE per SHARED GEAR SET. Not per server, not per map -
            # the same mods on a different map in the same hive and the same
            # group are the same gear. The old query also matched on
            # (server_id = me AND map_name = my map), which made exactly that
            # case resolve as two different rows, and then needed
            # ORDER BY updated_at DESC LIMIT 1 to pick between the candidates it
            # had just manufactured.
            #
            # share_group is part of the primary key, so this is a point
            # lookup that cannot return more than one row. `map` is still
            # accepted and recorded, it just no longer decides anything.
            #
            # scope_map = '' pins the FULL five-column key rather than a
            # prefix of it. GEAR IS DELIBERATELY NOT MAP-SCOPED: the same
            # mods on a different map in the same hive and the same group
            # are the same gear, so a map rotation is a config read and
            # nothing more. Naming scope_map explicitly is what keeps this
            # an exact-match point lookup instead of a range scan that a
            # future map-scoped namespace could wander into.
            cursor.execute("""
                SELECT server_id, share_group, map_name, format_ver, payload,
                       owner_dead, updated_at
                  FROM player_data
                 WHERE player_uid = %s AND hive_id = %s
                   AND share_group = %s AND namespace = 'inventory'
                   AND scope_map = ''
            """, (uid, current_hive_id(), _gear_group))
            _win = cursor.fetchone()
            if _win:
                player["inventory"]              = _win.get("payload")
                player["inventory_source"]       = _win.get("server_id")
                player["inventory_group"]        = _win.get("share_group")
                player["inventory_map"]          = _win.get("map_name") or ""
                player["inventory_format_ver"]   = _win.get("format_ver")
                # Travels WITH the gear it guards, from the same row, in the
                # same read. No second query and no way for the two to
                # disagree - which is the failure that put it here: is_alive
                # lives on another table at another scope, and the mod had to
                # remember to consult it. This one arrives attached.
                player["owner_dead"]             = int(_win.get("owner_dead") or 0)
                print(f"[GATEWAY] gear resolved: {uid} <- {_win.get('server_id')} "
                      f"group={_win.get('share_group')} map='{_win.get('map_name')}' "
                      f"(asked group={_gear_group} map='{_my_map}')")
            else:
                # No candidate is NOT an error: a brand-new player, or a first
                # visit to a server whose group has no rows yet. Faction
                # defaults apply; nothing is logged as a fault.
                player["inventory"]            = None
                player["inventory_source"]     = ""
                player["inventory_format_ver"] = 0
                # No row = nothing stored here = nobody has died here.
                player["owner_dead"]           = 0
        player["first_join"] = _iso(prof.get("first_join"))
        player["last_seen"] = _iso(prof.get("last_seen"))
        if sess:
            player["map_name"]           = sess.get("map_name")
            player["pos_x"]              = sess.get("pos_x")
            player["pos_y"]              = sess.get("pos_y")
            player["pos_z"]              = sess.get("pos_z")
            player["rotation_yaw"]       = sess.get("rotation_yaw")
            player["stance"]             = sess.get("stance", 0)
            player["is_alive"]           = sess.get("is_alive", 1)
            player["recover_veh_prefab"] = sess.get("recover_veh_prefab")
            player["recover_veh_class"]  = sess.get("recover_veh_class")
            player["recover_session_id"] = sess.get("recover_session_id")
            # THE WRITE STAMP - which boot of THIS server last wrote this row.
            # The SELECT * above has always fetched it; the response is built
            # key by key, so a column not named here never reaches the mod.
            # That is why the column sat NULL and inert: not a broken write,
            # an unbuilt read. See save_player and PLAYER_GEAR_STATE_CARD S8.
            player["boot_session_id"]    = sess.get("boot_session_id") or ""
            # THE HELD WEAPON NOW COMES FROM THE SESSION ROW, which is keyed by
            # realm and map - so each realm returns what THAT realm's character
            # was holding. players.weapon is hive-scoped and is DEPRECATED: one
            # value shared across every realm is what made a BRAVO weapon come
            # back in an ALPHA loadout that did not contain it.
            #
            # Falls back to the deprecated column only while it is still the
            # only thing an older row has, so an upgrade mid-session does not
            # blank someone's weapon before 0093 has seeded it.
            if sess.get("weapon"):
                player["weapon"] = sess.get("weapon")
        else:
            player["map_name"] = None
            player["pos_x"] = player["pos_y"] = player["pos_z"] = None
            player["rotation_yaw"] = None
            player["stance"] = 0
            player["is_alive"] = 1
            player["recover_veh_prefab"] = None
            player["recover_veh_class"] = None
            player["recover_session_id"] = None
            # No row for this realm+map on this server. No row means no write,
            # no write means no stamp - and an empty stamp reads as "assume
            # the server restarted", which is the forgiving answer and the
            # correct one for a player who has never saved here.
            player["boot_session_id"] = ""
        return jsonify({"status": "ok", "player": player})

    except mysql.connector.Error as err:
        return _db_error("get_player", err)
    except Exception as err:
        return _internal_error("get_player", err)
    finally:
        _close(conn)


@app.route("/api/player/<uid>/save", methods=["POST"])
def save_player(uid):
    """Save a player. Shared fields -> hive profile; world context -> this
    server's session row; sets current_server_id (claim)."""
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    display_name = data.get("display_name", "")
    money = data.get("money", 0)
    faction = data.get("faction", "GREEN")
    weapon = data.get("weapon")
    bank = data.get("bank", 0)

    map_name = data.get("map_name", data.get("map"))
    pos_x = data.get("pos_x")
    pos_y = data.get("pos_y")
    pos_z = data.get("pos_z")
    rotation_yaw = data.get("rotation_yaw")
    stance = data.get("stance", 0)
    is_alive = data.get("is_alive", 1)

    # POSITION IS SCOPED PER REALM AND MAP (2026-08-29).
    # The load already sends gear_group + map as query params; the save now
    # carries the same pair so a write lands on the row the next load reads.
    # A mod sending neither falls back to ALPHA and '', matching get_player's
    # own gear_group fallback - read and write MUST agree on the default, or
    # they address different rows and the player's position vanishes.
    save_group = (data.get("gear_group") or "ALPHA")[:32]

    # THE WRITE STAMP (2026-08-31, gw 0.9.4). Which boot of which server
    # wrote this row. server_id is already in the key, so this column only
    # has to supply the run - and the pair then answers "is the saved state
    # still current" with one comparison and no flags.
    #
    # Only ever written by a SAVE. That is the whole point: arrival_grace
    # exists because a LOAD mutated the value a LOAD was reading, so a second
    # read during one arrival contradicted the first. Nothing here is
    # reachable from get_player, so repeated loads cannot disturb it.
    # See docs/design/PLAYER_GEAR_STATE_CARD.md S8.
    boot_session_id = (data.get("boot_session_id") or "")[:64] or None

    inventory = data.get("inventory")
    if isinstance(inventory, (list, dict)):
        inventory = json.dumps(inventory, separators=(",", ":"))

    if not isinstance(money, int) or money < 0:
        return jsonify({"status": "error", "message": "invalid money value"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        # Phase 3 anti-clobber: reject a stale save from a server that no longer
        # owns this player (they have joined a different server in the hive).
        cursor.execute("SELECT current_server_id FROM players WHERE player_uid = %s AND hive_id = %s", (uid, current_hive_id()))
        _own = cursor.fetchone()
        if _own and _own[0] is not None and _own[0] != sid:
            print(f"[GATEWAY] save rejected: {uid} owned by {_own[0]}, not {sid}")
            return jsonify({"status": "error", "message": "player owned by another server",
                            "current_server_id": _own[0]}), 409

        # CONSUME the one-shot arrival grace. A save from the owning server means
        # the player is in the world - they have spawned, so the free faction and
        # spawn pick has been used. Cleared here rather than in the mod because
        # the mod would need a separate call for it, and a missed call would
        # leave the grace armed forever.
        #
        # Clearing on ANY owning save is deliberate: autosave, disconnect save
        # and the post-spawn save all mean the same thing. Worst case the grace
        # is consumed a moment early, which costs a free respawn. The other
        # direction - a grace that never clears - hands out an unlimited faction
        # and spawn reroll, which is the anti-battle-log rule defeated.
        # RETRY ON DEADLOCK. This block touches `players` twice and
        # `player_sessions` once, so concurrent saves can interleave and let
        # InnoDB pick one as the victim - seen in the 2026-08-23 load test as
        # 1213 during a 128-player reconnect burst, surfaced as HTTP 500.
        #
        # A 500 here is a LOST SAVE. The victim is rolled back cleanly, so
        # re-running is safe and is not a double write - which is precisely
        # what MySQL means by 'try restarting transaction'.
        def _write():
            cursor.execute("UPDATE players SET arrival_grace = 0 "
                           "WHERE player_uid = %s AND hive_id = %s AND arrival_grace <> 0",
                           (uid, current_hive_id()))
            if cursor.rowcount:
                print(f"[GATEWAY] arrival grace consumed: {uid} on {sid}")
            if inventory is not None:
                cursor.execute("""
                    INSERT INTO players (player_uid, hive_id, display_name, money, faction,
                                         weapon, inventory, bank, current_server_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        display_name = VALUES(display_name),
                        money = VALUES(money),
                        faction = VALUES(faction),
                        -- AN ABSENT WEAPON MUST NOT DESTROY THE STORED ONE.
                        -- The mod omits this field entirely when it has no
                        -- weapon to report, so VALUES(weapon) is NULL and a
                        -- plain assignment wiped a perfectly good value. That
                        -- is why every player's weapon kept reverting to NULL.
                        -- Same rule SaveInventory already follows by skipping
                        -- an empty payload: an empty read never overwrites a
                        -- known-good one. Sending an explicit empty string
                        -- still clears it, so "I am holding nothing" remains
                        -- expressible.
                        weapon = COALESCE(VALUES(weapon), weapon),
                        inventory = VALUES(inventory),
                        bank = VALUES(bank),
                        current_server_id = VALUES(current_server_id),
                        last_seen = CURRENT_TIMESTAMP
                """, (uid, current_hive_id(), display_name, money, faction, weapon, inventory, bank, sid))
            else:
                cursor.execute("""
                    INSERT INTO players (player_uid, hive_id, display_name, money, faction,
                                         weapon, bank, current_server_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        display_name = VALUES(display_name),
                        money = VALUES(money),
                        faction = VALUES(faction),
                        -- AN ABSENT WEAPON MUST NOT DESTROY THE STORED ONE.
                        -- The mod omits this field entirely when it has no
                        -- weapon to report, so VALUES(weapon) is NULL and a
                        -- plain assignment wiped a perfectly good value. That
                        -- is why every player's weapon kept reverting to NULL.
                        -- Same rule SaveInventory already follows by skipping
                        -- an empty payload: an empty read never overwrites a
                        -- known-good one. Sending an explicit empty string
                        -- still clears it, so "I am holding nothing" remains
                        -- expressible.
                        weapon = COALESCE(VALUES(weapon), weapon),
                        bank = VALUES(bank),
                        current_server_id = VALUES(current_server_id),
                        last_seen = CURRENT_TIMESTAMP
                """, (uid, current_hive_id(), display_name, money, faction, weapon, bank, sid))

            # EVERY KEY COLUMN MUST BE SUPPLIED. hive_id, share_group and
            # map_name are all in this table's PRIMARY KEY; omit any one and
            # MySQL inserts the column DEFAULT, collapsing every hive, realm
            # and map onto a single row. Not theoretical: hive_id was added to
            # this key in 0.9 and never added to these queries, so every
            # position row on this box was written as hive 'default'.
            cursor.execute("""
                INSERT INTO player_sessions (player_uid, hive_id, server_id, share_group, map_name,
                                             pos_x, pos_y, pos_z, rotation_yaw, stance, is_alive, weapon,
                                             boot_session_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    -- Same COALESCE rule as players.weapon had to learn: an
                    -- ABSENT weapon must not destroy the stored one. The mod
                    -- omits the field when it has nothing to report, and a
                    -- plain assignment would write that NULL over a good value.
                    weapon = COALESCE(VALUES(weapon), weapon),
                    pos_x = VALUES(pos_x),
                    pos_y = VALUES(pos_y),
                    pos_z = VALUES(pos_z),
                    rotation_yaw = VALUES(rotation_yaw),
                    stance = VALUES(stance),
                    is_alive = VALUES(is_alive),
                    -- PLAIN ASSIGNMENT, deliberately NOT the COALESCE the
                    -- weapon above needs. They look alike and mean opposite
                    -- things. An absent weapon means "I have nothing to
                    -- report", so the stored value stands. An absent stamp
                    -- means "the writer did not identify its run" - which is
                    -- itself the answer, and keeping the previous run's id
                    -- would let this row claim it was written by a boot that
                    -- did not write it. NULL reads as "unknown, assume
                    -- restarted", the forgiving direction, matching
                    -- HFServerSession.HasRestartedSince() on an empty id.
                    boot_session_id = VALUES(boot_session_id),
                    last_seen = CURRENT_TIMESTAMP
            """, (uid, current_hive_id(), sid, save_group, map_name or "",
                  pos_x, pos_y, pos_z, rotation_yaw, stance, is_alive, weapon,
                  boot_session_id))

            conn.commit()

        _db_retry(_write, "save_player")
        print(f"[GATEWAY] Player saved: {uid} @ {sid} money={money} bank={bank} alive={is_alive}")
        return jsonify({"status": "ok", "message": "player saved"})

    except mysql.connector.Error as err:
        return _db_error("save_player", err)
    except Exception as err:
        return _internal_error("save_player", err)
    finally:
        _close(conn)


@app.route("/api/player/<uid>/inventory", methods=["POST"])
def save_inventory(uid):
    """Save inventory only (shared profile)."""
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    inventory = data.get("inventory")
    if isinstance(inventory, (list, dict)):
        inventory = json.dumps(inventory, separators=(",", ":"))

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        # Phase 3 anti-clobber: reject a stale inventory save from a non-owner server.
        cursor.execute("SELECT current_server_id FROM players WHERE player_uid = %s AND hive_id = %s", (uid, current_hive_id()))
        _own = cursor.fetchone()
        if _own and _own[0] is not None and _own[0] != sid:
            print(f"[GATEWAY] inventory save rejected: {uid} owned by {_own[0]}, not {sid}")
            return jsonify({"status": "error", "message": "player owned by another server",
                            "current_server_id": _own[0]}), 409
        cursor.execute("""
            INSERT INTO players (player_uid, hive_id, inventory)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                inventory = VALUES(inventory),
                last_seen = CURRENT_TIMESTAMP
        """, (uid, current_hive_id(), inventory))
        conn.commit()
        print(f"[GATEWAY] Inventory saved: {uid} ({len(inventory) if inventory else 0} chars)")
        return jsonify({"status": "ok", "message": "inventory saved"})
    except mysql.connector.Error as err:
        return _db_error("save_inventory", err)
    except Exception as err:
        return _internal_error("save_inventory", err)
    finally:
        _close(conn)


@app.route("/api/player/<uid>/recovery", methods=["POST"])
def save_vehicle_recovery(uid):
    """Vehicle-recovery token write-through. Per-server (player_sessions)."""
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    prefab = data.get("recover_veh_prefab", "") or ""
    vclass = data.get("recover_veh_class", "") or ""
    session = data.get("recover_session_id", "") or ""
    # The recovery token lives on the SAME row as the position, so it must be
    # addressed with the same key. Without these two it would insert a row at
    # the column defaults - a different row from the position - and the token
    # would be written somewhere get_player never looks. Same ALPHA/'' default
    # as everywhere else so all three writers agree.
    rec_group = (data.get("gear_group") or "ALPHA")[:32]
    rec_map   = (data.get("map_name") or "")[:64]

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO player_sessions (player_uid, hive_id, server_id, share_group, map_name,
                                         recover_veh_prefab, recover_veh_class, recover_session_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                recover_veh_prefab = VALUES(recover_veh_prefab),
                recover_veh_class = VALUES(recover_veh_class),
                recover_session_id = VALUES(recover_session_id),
                last_seen = CURRENT_TIMESTAMP
        """, (uid, current_hive_id(), sid, rec_group, rec_map, prefab, vclass, session))
        conn.commit()
        print(f"[GATEWAY] Vehicle recovery saved: {uid} @ {sid} class={vclass}")
        return jsonify({"status": "ok", "message": "recovery saved"})
    except mysql.connector.Error as err:
        return _db_error("save_vehicle_recovery", err)
    except Exception as err:
        return _internal_error("save_vehicle_recovery", err)
    finally:
        _close(conn)


@app.route("/api/player/<uid>/transaction", methods=["POST"])
def player_transaction(uid):
    """Append a money-audit row. Does NOT modify balance (game is authoritative).
    Every money event MUST be logged. Types actually emitted by the mod/gateway:
    starting_money, respawn_starting_money, kill_reward, store_buy, store_sell,
    vehicle_buy, atm_deposit, atm_withdraw, pickup, player_drop, relocate_drop,
    downed_disconnect_drop, death_drop, fresh_start (wallet reset on a new-spawn/
    faction-change start-over), resupply, admin_give (gateway bulk grants).
    Planned/deferred: mission_reward. Any string is accepted."""
    if not check_auth("TRANSACTION"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    tx_type = data.get("type", "")
    amount = data.get("amount", 0)
    balance_after = data.get("balance_after", 0)
    details = data.get("details", "")

    if not tx_type:
        return jsonify({"status": "error", "message": "transaction type required"}), 400
    if not isinstance(amount, int):
        return jsonify({"status": "error", "message": "amount must be integer"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO transactions (player_uid, hive_id, server_id, type, amount, balance_after, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (uid, current_hive_id(), sid, tx_type, amount, balance_after, details))
        conn.commit()
        print(f"[GATEWAY] Transaction: {uid} @ {sid} {tx_type} {amount:+d} balance={balance_after}")
        return jsonify({"status": "ok", "transaction_type": tx_type, "amount": amount, "balance_after": balance_after})
    except mysql.connector.Error as err:
        return _db_error("player_transaction", err)
    except Exception as err:
        return _internal_error("player_transaction", err)
    finally:
        _close(conn)


@app.route("/api/player/<uid>/stats", methods=["POST"])
def save_player_stats(uid):
    """Accumulate today's stats for (player_uid, server_id)."""
    if not check_auth("STATS"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    kills = data.get("kills", 0)
    deaths = data.get("deaths", 0)
    playtime_seconds = data.get("playtime_seconds", 0)
    money_earned = data.get("money_earned", 0)
    money_spent = data.get("money_spent", 0)
    distance_traveled = data.get("distance_traveled", 0.0)
    longest_life_sec = data.get("longest_life_sec", 0)
    hvt_kills = data.get("hvt_kills", 0)
    missions_completed = data.get("missions_completed", 0)

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO player_stats_daily
                (player_uid, hive_id, server_id, stat_date, kills, deaths, playtime_seconds,
                 money_earned, money_spent, distance_traveled, longest_life_sec, hvt_kills,
                 missions_completed)
            VALUES (%s, %s, %s, CURDATE(), %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                kills = kills + VALUES(kills),
                deaths = deaths + VALUES(deaths),
                playtime_seconds = playtime_seconds + VALUES(playtime_seconds),
                money_earned = money_earned + VALUES(money_earned),
                money_spent = money_spent + VALUES(money_spent),
                distance_traveled = distance_traveled + VALUES(distance_traveled),
                longest_life_sec = GREATEST(longest_life_sec, VALUES(longest_life_sec)),
                hvt_kills = hvt_kills + VALUES(hvt_kills),
                missions_completed = missions_completed + VALUES(missions_completed)
        """, (uid, current_hive_id(), sid, kills, deaths, playtime_seconds,
              money_earned, money_spent, distance_traveled, longest_life_sec, hvt_kills,
              missions_completed))
        conn.commit()
        print(f"[GATEWAY] Stats saved: {uid} @ {sid} k={kills} d={deaths} hvt={hvt_kills}")
        return jsonify({"status": "ok", "message": "stats accumulated"})
    except mysql.connector.Error as err:
        return _db_error("save_player_stats", err)
    except Exception as err:
        return _internal_error("save_player_stats", err)
    finally:
        _close(conn)


@app.route("/api/player/<uid>/stats", methods=["GET"])
def get_player_stats(uid):
    """Get a player's daily stats row. Optional ?date=YYYY-MM-DD (today)."""
    if not check_auth("STATS"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    stat_date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        # hive_id is part of the key as of 0.9 (migration 0090 part 2), and it
        # belongs in the WHERE for the same reason: without it this read could
        # return another hive's row for a server_id both hives happen to use.
        # The write has always supplied hive_id; only the read was missing it.
        cursor.execute(
            "SELECT * FROM player_stats_daily "
            "WHERE player_uid = %s AND hive_id = %s AND server_id = %s AND stat_date = %s",
            (uid, current_hive_id(), sid, stat_date))
        row = cursor.fetchone()
        if row:
            row["stat_date"] = _iso(row.get("stat_date"))
            return jsonify({"status": "ok", "stats": row})
        return jsonify({"status": "ok", "stats": None})
    except mysql.connector.Error as err:
        return _db_error("get_player_stats", err)
    except Exception as err:
        return _internal_error("get_player_stats", err)
    finally:
        _close(conn)


# --------------------------------------------------------
# Marker Preferences — shared hive-wide (player_uid, hive_id)
# --------------------------------------------------------

@app.route("/api/player/<uid>/marker_prefs", methods=["GET"])
def get_marker_prefs(uid):
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM player_marker_prefs WHERE player_uid = %s AND hive_id = %s", (uid, current_hive_id()))
        row = cursor.fetchone()
        if row:
            row["updated_at"] = _iso(row.get("updated_at"))
            return jsonify({"status": "ok", "prefs": row})
        return jsonify({"status": "ok", "prefs": None})
    except mysql.connector.Error as err:
        return _db_error("get_marker_prefs", err)
    except Exception as err:
        return _internal_error("get_marker_prefs", err)
    finally:
        _close(conn)


@app.route("/api/player/<uid>/marker_prefs", methods=["POST"])
def save_marker_prefs(uid):
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    def clamp_int(value, lo, hi, default):
        try:
            v = int(value)
        except (TypeError, ValueError):
            return default
        return max(lo, min(v, hi))

    def clamp_bool(value, default):
        if value is None:
            return default
        try:
            return 1 if int(value) else 0
        except (TypeError, ValueError):
            return default

    icon_idx          = clamp_int(data.get("icon_idx"),          1,    50,    4)
    icon_size_px      = clamp_int(data.get("icon_size_px"),      8,    256,   48)
    marker_range_m    = clamp_int(data.get("marker_range_m"),    0,    50000, 5000)
    markers_enabled   = clamp_bool(data.get("markers_enabled"),   1)
    names_enabled     = clamp_bool(data.get("names_enabled"),     1)
    group_only        = clamp_bool(data.get("group_only"),        0)
    auto_vehicle_swap = clamp_bool(data.get("auto_vehicle_swap"), 1)
    # World-map player-marker prefs bitmask: 1=broadcast, 2=see-group, 4=see-team.
    map_flags         = clamp_int(data.get("map_flags"),         0,    7,     7)

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO player_marker_prefs
               (player_uid, hive_id, icon_idx, icon_size_px, marker_range_m,
                markers_enabled, names_enabled, group_only, auto_vehicle_swap, map_flags)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                icon_idx = VALUES(icon_idx),
                icon_size_px = VALUES(icon_size_px),
                marker_range_m = VALUES(marker_range_m),
                markers_enabled = VALUES(markers_enabled),
                names_enabled = VALUES(names_enabled),
                group_only = VALUES(group_only),
                auto_vehicle_swap = VALUES(auto_vehicle_swap),
                map_flags = VALUES(map_flags)
        """, (uid, current_hive_id(), icon_idx, icon_size_px, marker_range_m,
              markers_enabled, names_enabled, group_only, auto_vehicle_swap, map_flags))
        conn.commit()
        return jsonify({"status": "ok"})
    except mysql.connector.Error as err:
        return _db_error("save_marker_prefs", err)
    except Exception as err:
        return _internal_error("save_marker_prefs", err)
    finally:
        _close(conn)


# --------------------------------------------------------
# Stats Leaderboard — aggregated across the hive
# --------------------------------------------------------

@app.route("/api/stats/leaderboard", methods=["GET"])
def get_stats_leaderboard():
    """Top N for one metric across ALL servers in the hive over <days> days."""
    if not check_auth("STATS"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    ALLOWED_METRICS = {
        "kills", "deaths", "playtime_seconds",
        "money_earned", "money_spent", "distance_traveled",
        "longest_life_sec", "hvt_kills", "missions_completed",
    }
    metric = request.args.get("metric", "")
    if metric not in ALLOWED_METRICS:
        return jsonify({"status": "error",
                        "message": f"metric must be one of: {sorted(ALLOWED_METRICS)}"}), 400

    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 100))

    days_arg = request.args.get("days", "7")
    if days_arg == "all":
        date_clause = ""
        date_params = ()
    else:
        try:
            days = int(days_arg)
        except (TypeError, ValueError):
            days = 7
        days = max(1, min(days, 365))
        date_clause = "AND stat_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
        date_params = (days,)

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        agg = "MAX" if metric == "longest_life_sec" else "SUM"
        sql = f"""
            SELECT player_uid, {agg}({metric}) AS value
            FROM player_stats_daily
            WHERE hive_id = %s
              {date_clause}
            GROUP BY player_uid
            HAVING value > 0
            ORDER BY value DESC
            LIMIT %s
        """
        params = (current_hive_id(),) + date_params + (limit,)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return jsonify({"status": "ok", "metric": metric, "days": days_arg, "hive_id": current_hive_id(), "rows": rows})
    except mysql.connector.Error as err:
        return _db_error("get_stats_leaderboard", err)
    except Exception as err:
        return _internal_error("get_stats_leaderboard", err)
    finally:
        _close(conn)


# --------------------------------------------------------
# Delete Player — full wipe across the hive
# --------------------------------------------------------

@app.route("/api/player/<uid>/delete", methods=["POST"])
def delete_player(uid):
    if not check_auth("DELETE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transactions WHERE player_uid = %s AND hive_id = %s", (uid, current_hive_id()))
        tx_deleted = cursor.rowcount
        cursor.execute("DELETE FROM player_stats_daily WHERE player_uid = %s AND hive_id = %s", (uid, current_hive_id()))
        stats_deleted = cursor.rowcount
        cursor.execute("DELETE FROM player_sessions WHERE player_uid = %s", (uid,))
        sessions_deleted = cursor.rowcount
        cursor.execute("DELETE FROM players WHERE player_uid = %s AND hive_id = %s", (uid, current_hive_id()))
        player_deleted = cursor.rowcount
        conn.commit()

        if player_deleted == 0:
            return jsonify({"status": "error", "message": f"Player '{uid}' not found"}), 404

        print(f"[GATEWAY] DELETED player: {uid} (tx={tx_deleted}, stats={stats_deleted}, sessions={sessions_deleted})")
        return jsonify({"status": "ok", "message": f"Player {uid} deleted",
                        "deleted": {"player": player_deleted, "transactions": tx_deleted,
                                    "stats": stats_deleted, "sessions": sessions_deleted}})
    except mysql.connector.Error as err:
        return _db_error("delete_player", err)
    except Exception as err:
        return _internal_error("delete_player", err)
    finally:
        _close(conn)


# --------------------------------------------------------
# Players — bulk money, list, summary (hive-scoped)
# --------------------------------------------------------

@app.route("/api/players/bulk_money", methods=["POST"])
def bulk_money():
    """Add/remove money for all players in the hive (one row per player)."""
    if not check_auth("BULKMONEY"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True)
    if not data or "amount" not in data:
        return jsonify({"status": "error", "message": "JSON body with 'amount' required"}), 400

    amount = data["amount"]
    target = data.get("target", "wallet")
    if not isinstance(amount, int) or amount == 0:
        return jsonify({"status": "error", "message": "amount must be a non-zero integer"}), 400
    if target not in ("wallet", "bank", "both"):
        return jsonify({"status": "error", "message": "target must be 'wallet', 'bank', or 'both'"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT player_uid, display_name, money, bank FROM players WHERE hive_id = %s", (current_hive_id(),))
        before = {r["player_uid"]: r for r in cursor.fetchall()}

        set_parts = []
        if target in ("wallet", "both"):
            set_parts.append(f"money = money + {int(amount)}" if amount > 0
                             else f"money = GREATEST(0, money + ({int(amount)}))")
        if target in ("bank", "both"):
            set_parts.append(f"bank = bank + {int(amount)}" if amount > 0
                             else f"bank = GREATEST(0, bank + ({int(amount)}))")

        cursor.execute(f"UPDATE players SET {', '.join(set_parts)} WHERE hive_id = %s", (current_hive_id(),))
        rows_affected = cursor.rowcount
        conn.commit()

        cursor.execute("SELECT player_uid, display_name, money, bank FROM players WHERE hive_id = %s", (current_hive_id(),))
        after = {r["player_uid"]: r for r in cursor.fetchall()}

        op = "give" if amount > 0 else "take"
        sid = current_server_id()
        results = []
        tx_rows = []
        for puid, row in after.items():
            b = before.get(puid, {})
            wallet_before = b.get("money", 0)
            bank_before = b.get("bank", 0)
            results.append({
                "player_uid": puid, "display_name": row["display_name"],
                "wallet_before": wallet_before, "wallet_after": row["money"],
                "bank_before": bank_before, "bank_after": row["bank"]})
            # Audit row — log the ACTUAL applied delta (GREATEST(0,...) can clamp a take).
            delta = (row["money"] - wallet_before) + (row["bank"] - bank_before)
            if delta != 0:
                tx_rows.append((puid, current_hive_id(), sid, "admin_give", delta, row["money"],
                                f"bulk {op} {target} ${abs(amount):,}"))

        if tx_rows:
            cursor.executemany(
                "INSERT INTO transactions (player_uid, hive_id, server_id, type, amount, balance_after, details) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)", tx_rows)
            conn.commit()

        print(f"[GATEWAY] Bulk {op}: ${abs(amount):,} to {target} for {rows_affected} players (hive {current_hive_id()}); {len(tx_rows)} audit rows")
        return jsonify({"status": "ok", "operation": op, "amount": abs(amount),
                        "target": target, "players_affected": rows_affected, "results": results})
    except mysql.connector.Error as err:
        return _db_error("bulk_money", err)
    except Exception as err:
        return _internal_error("bulk_money", err)
    finally:
        _close(conn)


@app.route("/api/players", methods=["GET"])
def get_all_players():
    """List players in the hive. Position/alive are this server's session values."""
    if not check_auth("PLAYERS"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    search = request.args.get("search", "")

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        base = """
            SELECT p.player_uid, p.display_name, p.money, p.bank, p.faction,
                   p.current_server_id, s.pos_x, s.pos_y, s.pos_z, s.is_alive, p.last_seen
            FROM players p
            LEFT JOIN player_sessions s ON s.player_uid = p.player_uid
                                        AND s.hive_id = p.hive_id
                                        AND s.server_id = %s
            WHERE p.hive_id = %s
        """
        if search:
            cursor.execute(base + " AND (p.display_name LIKE %s OR p.player_uid LIKE %s) ORDER BY p.last_seen DESC",
                           (sid, current_hive_id(), f"%{search}%", f"%{search}%"))
        else:
            cursor.execute(base + " ORDER BY p.last_seen DESC", (sid, current_hive_id()))
        rows = cursor.fetchall()
        for row in rows:
            if row.get("last_seen"):
                row["last_seen"] = row["last_seen"].isoformat() if hasattr(row["last_seen"], "isoformat") else str(row["last_seen"])
        return jsonify({"status": "ok", "total": len(rows), "data": rows})
    except mysql.connector.Error as err:
        return _db_error("get_all_players", err)
    except Exception as err:
        return _internal_error("get_all_players", err)
    finally:
        _close(conn)


@app.route("/api/server/summary", methods=["GET"])
def server_summary():
    """Economy + population summary for the whole hive."""
    if not check_auth("SUMMARY"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) as total_players FROM players WHERE hive_id = %s", (current_hive_id(),))
        total = cursor.fetchone()["total_players"]
        cursor.execute("""
            SELECT COUNT(DISTINCT s.player_uid) as alive FROM player_sessions s
            JOIN players p ON p.player_uid = s.player_uid AND p.hive_id = s.hive_id
            WHERE p.hive_id = %s AND s.is_alive = 1
        """, (current_hive_id(),))
        alive = cursor.fetchone()["alive"]
        cursor.execute("SELECT COALESCE(SUM(money),0) as total_wallet, COALESCE(SUM(bank),0) as total_bank FROM players WHERE hive_id = %s", (current_hive_id(),))
        economy = cursor.fetchone()
        cursor.execute("SELECT display_name, (money + bank) as total_money FROM players WHERE hive_id = %s ORDER BY total_money DESC LIMIT 5", (current_hive_id(),))
        top5 = cursor.fetchall()
        cursor.execute("SELECT faction, COUNT(*) as count FROM players WHERE hive_id = %s AND faction IS NOT NULL AND faction != '' GROUP BY faction", (current_hive_id(),))
        factions = {row["faction"]: row["count"] for row in cursor.fetchall()}
        tx_count = 0
        try:
            cursor.execute("SELECT COUNT(*) as tx_count FROM transactions WHERE hive_id = %s AND timestamp >= NOW() - INTERVAL 1 DAY", (current_hive_id(),))
            tx_count = cursor.fetchone()["tx_count"]
        except mysql.connector.Error:
            pass
        return jsonify({
            "status": "ok", "hive_id": current_hive_id(),
            "total_players": total, "alive_players": alive,
            "total_wallet_economy": economy["total_wallet"], "total_bank_economy": economy["total_bank"],
            "total_economy": economy["total_wallet"] + economy["total_bank"],
            "top_5_richest": top5, "factions": factions, "transactions_24h": tx_count})
    except mysql.connector.Error as err:
        return _db_error("server_summary", err)
    except Exception as err:
        return _internal_error("server_summary", err)
    finally:
        _close(conn)


# --------------------------------------------------------
# Security Events
# --------------------------------------------------------
@app.route("/api/security/event", methods=["POST"])
def log_security_event():
    if not check_auth("SECURITY"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    player_uid = data.get("player_uid", "")
    display_name = data.get("display_name", "")
    event_type = data.get("event_type", "UNKNOWN")
    item_prefab = data.get("item_prefab", "")
    details = data.get("details", "")
    severity = data.get("severity", "WARN")

    if not player_uid:
        return jsonify({"status": "error", "message": "player_uid required"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO security_events
                (player_uid, server_id, hive_id, display_name, event_type, item_prefab, details, severity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (player_uid, sid, current_hive_id(), display_name, event_type, item_prefab, details, severity))
        conn.commit()
        event_id = cursor.lastrowid
        print(f"[SECURITY] Event #{event_id}: {player_uid} @ {sid} {event_type} severity={severity}")
        return jsonify({"status": "ok", "event_id": event_id})
    except mysql.connector.Error as err:
        return _db_error("log_security_event", err)
    except Exception as err:
        return _internal_error("log_security_event", err)
    finally:
        _close(conn)


@app.route("/api/security/events/<uid>", methods=["GET"])
def get_security_events(uid):
    if not check_auth("SECURITY"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    limit = request.args.get("limit", 50, type=int)
    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM security_events WHERE player_uid = %s ORDER BY timestamp DESC LIMIT %s", (uid, limit))
        events = cursor.fetchall()
        for e in events:
            if e.get("timestamp"):
                e["timestamp"] = e["timestamp"].isoformat()
        return jsonify({"status": "ok", "count": len(events), "events": events})
    except mysql.connector.Error as err:
        return _db_error("get_security_events", err)
    except Exception as err:
        return _internal_error("get_security_events", err)
    finally:
        _close(conn)


# --------------------------------------------------------
# Blacklist — ban management (server / hive / global)
# --------------------------------------------------------
@app.route("/api/blacklist/check/<uid>", methods=["GET"])
def check_blacklist(uid):
    if not check_auth("BLACKLIST"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()
    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM blacklist
            WHERE player_uid = %s AND is_active = 1
              AND (expires_at IS NULL OR expires_at > NOW())
              AND (scope = 'global'
                   OR (scope = 'hive' AND hive_id = %s)
                   OR (scope = 'server' AND server_id = %s))
            ORDER BY CASE scope WHEN 'global' THEN 1 WHEN 'hive' THEN 2 WHEN 'server' THEN 3 END
            LIMIT 1
        """, (uid, current_hive_id(), sid))
        ban = cursor.fetchone()
        if ban:
            if ban.get("banned_at"):
                ban["banned_at"] = ban["banned_at"].isoformat()
            if ban.get("expires_at"):
                ban["expires_at"] = ban["expires_at"].isoformat()
            return jsonify({"status": "ok", "is_banned": True, "scope": ban["scope"],
                            "reason": ban["reason"], "banned_by": ban["banned_by"],
                            "banned_at": ban.get("banned_at"), "expires_at": ban.get("expires_at")})
        return jsonify({"status": "ok", "is_banned": False})
    except mysql.connector.Error as err:
        return _db_error("check_blacklist", err)
    except Exception as err:
        return _internal_error("check_blacklist", err)
    finally:
        _close(conn)


@app.route("/api/blacklist/ban", methods=["POST"])
def ban_player():
    if not check_auth("BLACKLIST"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    player_uid = data.get("player_uid", "")
    display_name = data.get("display_name", "")
    scope = data.get("scope", "server")
    reason = data.get("reason", "")
    banned_by = data.get("banned_by", "system")
    expires_at = data.get("expires_at")

    if not player_uid:
        return jsonify({"status": "error", "message": "player_uid required"}), 400
    if scope not in ("server", "hive", "global"):
        return jsonify({"status": "error", "message": "scope must be server/hive/global"}), 400

    ban_server_id = sid if scope == "server" else None
    ban_hive_id = current_hive_id() if scope in ("server", "hive") else None

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO blacklist
                (player_uid, display_name, scope, server_id, hive_id, reason, banned_by, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (player_uid, display_name, scope, ban_server_id, ban_hive_id, reason, banned_by, expires_at))
        conn.commit()
        ban_id = cursor.lastrowid
        print(f"[SECURITY] BAN #{ban_id}: {player_uid} scope={scope} by={banned_by}")
        return jsonify({"status": "ok", "ban_id": ban_id})
    except mysql.connector.Error as err:
        return _db_error("ban_player", err)
    except Exception as err:
        return _internal_error("ban_player", err)
    finally:
        _close(conn)


@app.route("/api/blacklist/unban", methods=["POST"])
def unban_player():
    if not check_auth("BLACKLIST"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    player_uid = data.get("player_uid", "")
    scope = data.get("scope", "server")
    if not player_uid:
        return jsonify({"status": "error", "message": "player_uid required"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        if scope == "global":
            cursor.execute("UPDATE blacklist SET is_active = 0 WHERE player_uid = %s AND scope = 'global' AND is_active = 1", (player_uid,))
        elif scope == "hive":
            cursor.execute("UPDATE blacklist SET is_active = 0 WHERE player_uid = %s AND scope = 'hive' AND hive_id = %s AND is_active = 1", (player_uid, current_hive_id()))
        else:
            cursor.execute("UPDATE blacklist SET is_active = 0 WHERE player_uid = %s AND scope = 'server' AND server_id = %s AND is_active = 1", (player_uid, sid))
        affected = cursor.rowcount
        conn.commit()
        print(f"[SECURITY] UNBAN: {player_uid} scope={scope} ({affected} records)")
        return jsonify({"status": "ok", "unbanned": affected})
    except mysql.connector.Error as err:
        return _db_error("unban_player", err)
    except Exception as err:
        return _internal_error("unban_player", err)
    finally:
        _close(conn)


@app.route("/api/blacklist/list", methods=["GET"])
def list_blacklist():
    if not check_auth("BLACKLIST"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    scope = request.args.get("scope", "global").lower()
    if scope not in ("server", "hive", "global"):
        return jsonify({"status": "error", "message": "scope must be server/hive/global"}), 400
    try:
        limit = int(request.args.get("limit", "200"))
    except ValueError:
        limit = 200
    limit = max(1, min(limit, 1000))

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cols = "id, player_uid, display_name, scope, server_id, hive_id, reason, banned_by, banned_at, expires_at"
        if scope == "global":
            cursor.execute(f"SELECT {cols} FROM blacklist WHERE is_active = 1 AND scope = 'global' AND (expires_at IS NULL OR expires_at > NOW()) ORDER BY banned_at DESC LIMIT %s", (limit,))
        elif scope == "hive":
            cursor.execute(f"SELECT {cols} FROM blacklist WHERE is_active = 1 AND scope = 'hive' AND hive_id = %s AND (expires_at IS NULL OR expires_at > NOW()) ORDER BY banned_at DESC LIMIT %s", (current_hive_id(), limit))
        else:
            cursor.execute(f"SELECT {cols} FROM blacklist WHERE is_active = 1 AND scope = 'server' AND server_id = %s AND (expires_at IS NULL OR expires_at > NOW()) ORDER BY banned_at DESC LIMIT %s", (sid, limit))
        rows = cursor.fetchall()
        for r in rows:
            if r.get("banned_at"):
                r["banned_at"] = r["banned_at"].isoformat()
            if r.get("expires_at"):
                r["expires_at"] = r["expires_at"].isoformat()
        return jsonify({"status": "ok", "scope": scope, "count": len(rows), "bans": rows})
    except mysql.connector.Error as err:
        return _db_error("list_blacklist", err)
    except Exception as err:
        return _internal_error("list_blacklist", err)
    finally:
        _close(conn)


# --------------------------------------------------------
# PLACEMENTS — HF Carry & Place (per-server world objects)
# --------------------------------------------------------

@app.route("/api/placements/insert", methods=["POST"])
def placements_insert():
    if not check_auth("PLACEMENT"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    map_name    = data.get("map", "")
    carry_class = data.get("carry_class", 2)
    prefab_path = data.get("prefab_path", "")
    pos_x = data.get("pos_x", 0.0); pos_y = data.get("pos_y", 0.0); pos_z = data.get("pos_z", 0.0)
    yaw = data.get("yaw", 0.0); pitch = data.get("pitch", 0.0); roll = data.get("roll", 0.0)
    owner_uid = data.get("owner_uid", "")

    if not map_name or not prefab_path or not owner_uid:
        return jsonify({"status": "error", "message": "map, prefab_path, owner_uid required"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO hf_placements
                (hive_id, server_id, map_name, carry_class, prefab_path,
                 pos_x, pos_y, pos_z, yaw, pitch, roll, owner_uid, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
        """, (current_hive_id(), sid, map_name, int(carry_class), prefab_path,
              float(pos_x), float(pos_y), float(pos_z),
              float(yaw), float(pitch), float(roll), owner_uid))
        new_id = cursor.lastrowid
        conn.commit()
        print(f"[GATEWAY] placement inserted id={new_id} server={sid} map={map_name}")
        return jsonify({"status": "ok", "id": new_id})
    except mysql.connector.Error as err:
        return _db_error("placements_insert", err)
    except Exception as err:
        return _internal_error("placements_insert", err)
    finally:
        _close(conn)


@app.route("/api/placements/update", methods=["POST"])
def placements_update():
    if not check_auth("PLACEMENT"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    row_id = data.get("id", 0)
    if not isinstance(row_id, int) or row_id <= 0:
        return jsonify({"status": "error", "message": "id required"}), 400

    pos_x = data.get("pos_x", 0.0); pos_y = data.get("pos_y", 0.0); pos_z = data.get("pos_z", 0.0)
    yaw = data.get("yaw", 0.0); pitch = data.get("pitch", 0.0); roll = data.get("roll", 0.0)

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE hf_placements
               SET pos_x = %s, pos_y = %s, pos_z = %s, yaw = %s, pitch = %s, roll = %s,
                   last_moved_at = CURRENT_TIMESTAMP
             WHERE id = %s AND server_id = %s AND is_active = 1
        """, (float(pos_x), float(pos_y), float(pos_z), float(yaw), float(pitch), float(roll), row_id, sid))
        affected = cursor.rowcount
        conn.commit()
        if affected == 0:
            return jsonify({"status": "error", "message": f"no active row id={row_id}"}), 404
        print(f"[GATEWAY] placement updated id={row_id} server={sid}")
        return jsonify({"status": "ok", "id": row_id})
    except mysql.connector.Error as err:
        return _db_error("placements_update", err)
    except Exception as err:
        return _internal_error("placements_update", err)
    finally:
        _close(conn)


@app.route("/api/placements/delete", methods=["POST"])
def placements_delete():
    if not check_auth("PLACEMENT"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    row_id = data.get("id", 0)
    if not isinstance(row_id, int) or row_id <= 0:
        return jsonify({"status": "error", "message": "id required"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE hf_placements SET is_active = 0, last_moved_at = CURRENT_TIMESTAMP WHERE id = %s AND server_id = %s", (row_id, sid))
        affected = cursor.rowcount
        conn.commit()
        print(f"[GATEWAY] placement deleted id={row_id} server={sid} (affected={affected})")
        return jsonify({"status": "ok", "id": row_id, "affected": affected})
    except mysql.connector.Error as err:
        return _db_error("placements_delete", err)
    except Exception as err:
        return _internal_error("placements_delete", err)
    finally:
        _close(conn)


@app.route("/api/placements/list", methods=["GET"])
def placements_list():
    if not check_auth("PLACEMENT"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    map_name = request.args.get("map", "")
    if not map_name:
        return jsonify({"status": "error", "message": "map required"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, map_name, carry_class, prefab_path, pos_x, pos_y, pos_z, yaw, pitch, roll, owner_uid
              FROM hf_placements
             WHERE map_name = %s AND server_id = %s AND is_active = 1
             ORDER BY id ASC
        """, (map_name, sid))
        rows = cursor.fetchall()
        print(f"[GATEWAY] placements listed server={sid} map={map_name} count={len(rows)}")
        return jsonify({"status": "ok", "map": map_name, "count": len(rows), "rows": rows})
    except mysql.connector.Error as err:
        return _db_error("placements_list", err)
    except Exception as err:
        return _internal_error("placements_list", err)
    finally:
        _close(conn)


# --------------------------------------------------------
# Money Drops — per-server session world objects.
# server_id is taken from the request's port (config), not the body.
# --------------------------------------------------------

@app.route("/api/money_drops/insert", methods=["POST"])
def money_drops_insert():
    if not check_auth("PLACEMENT"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    map_name = data.get("map_name", "")
    pos_x = data.get("pos_x", 0.0); pos_y = data.get("pos_y", 0.0); pos_z = data.get("pos_z", 0.0)
    amount = data.get("amount", 0)
    drop_source = data.get("drop_source", "death")
    dropper_uid = data.get("dropper_uid", "")
    dropper_name = data.get("dropper_name", "")
    expires_at = data.get("expires_at", "")

    if not map_name or not expires_at:
        return jsonify({"status": "error", "message": "map_name, expires_at required"}), 400
    if not isinstance(amount, int) or amount <= 0:
        return jsonify({"status": "error", "message": "amount must be positive integer"}), 400
    if drop_source not in ("death", "player_drop", "admin_money"):
        return jsonify({"status": "error", "message": "drop_source must be 'death', 'player_drop' or 'admin_money'"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO money_drops
                (hive_id, server_id, map_name, pos_x, pos_y, pos_z, amount,
                 drop_source, dropper_uid, dropper_name, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (current_hive_id(), sid, map_name, float(pos_x), float(pos_y), float(pos_z),
              int(amount), drop_source, dropper_uid, dropper_name, expires_at))
        new_id = cursor.lastrowid
        conn.commit()
        print(f"[GATEWAY] money_drop inserted id={new_id} server={sid} map={map_name} amount={amount}")
        return jsonify({"status": "ok", "id": new_id})
    except mysql.connector.Error as err:
        return _db_error("money_drops_insert", err)
    except Exception as err:
        return _internal_error("money_drops_insert", err)
    finally:
        _close(conn)


@app.route("/api/money_drops/delete", methods=["POST"])
def money_drops_delete():
    if not check_auth("PLACEMENT"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    row_id = data.get("id", 0)
    if not isinstance(row_id, int) or row_id <= 0:
        return jsonify({"status": "error", "message": "id required"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM money_drops WHERE id = %s AND server_id = %s", (row_id, sid))
        affected = cursor.rowcount
        conn.commit()
        print(f"[GATEWAY] money_drop deleted id={row_id} server={sid} (affected={affected})")
        return jsonify({"status": "ok", "id": row_id, "affected": affected})
    except mysql.connector.Error as err:
        return _db_error("money_drops_delete", err)
    except Exception as err:
        return _internal_error("money_drops_delete", err)
    finally:
        _close(conn)


@app.route("/api/money_drops/wipe", methods=["POST"])
def money_drops_wipe():
    if not check_auth("PLACEMENT"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    map_name = data.get("map_name", "")
    if not map_name:
        return jsonify({"status": "error", "message": "map_name required"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM money_drops WHERE server_id = %s AND map_name = %s", (sid, map_name))
        affected = cursor.rowcount
        conn.commit()
        print(f"[GATEWAY] money_drops wiped server={sid} map={map_name} affected={affected}")
        return jsonify({"status": "ok", "server_id": sid, "map_name": map_name, "affected": affected})
    except mysql.connector.Error as err:
        return _db_error("money_drops_wipe", err)
    except Exception as err:
        return _internal_error("money_drops_wipe", err)
    finally:
        _close(conn)


# --------------------------------------------------------
# Startup — bind a listener on every configured server port
# --------------------------------------------------------

# ============================================================
# GENERIC NAMESPACED PLAYER DATA  (/api/data/...)
# ============================================================
# One table, one set of endpoints, every player-owned per-scope feature.
# Adding a feature means picking a new `namespace` string in the MOD - no new
# table, no migration, and no gateway release. That is the whole point: admins
# distrust gateway updates, so the way to make them rare is a schema that does
# not need to change.
#
# THE WRITE RULE IS ENFORCED HERE, NOT JUST DOCUMENTED. A server may write only
# its own server_id, or the shared '@hive' scope. Every data-loss hazard in this
# area came from one server overwriting a value another server owned; refusing
# the write at the gateway makes that class impossible rather than merely
# discouraged.
#
# The gateway does NOT know what a share_group means or which row the mod should
# restore. It stores what it is given and returns every candidate. Policy lives
# in the mod, next to the config file that sets it.
# ============================================================

def _csvsafe(value):
    """Strip the row/field separators out of a value.

    Addon titles and server names are admin-controlled free text. One stray
    '~' or '|' would shift every later field in that row, and the F8 view
    would quietly show a server's mod count in its map column. Replacing beats
    escaping: the mod parses with a plain split, so there is nothing on the far
    side that would honour an escape.
    """
    t = str(value if value is not None else "")
    return t.replace("~", "-").replace("|", "/")


# ------------------------------------------------------------------
# THE KEY IS THE SCOPE
# ------------------------------------------------------------------
# A row is addressed by exactly one thing: its key.
#
#     (player_uid, hive_id, share_group, namespace, scope_map)
#
# share_group carries the whole scope model, and the mod decides what to
# put there. The gateway does not know or care what any of it MEANS:
#
#     '@hive'                 one row for the whole hive
#     'ALPHA'..'ZULU'         a shared gear or vehicle set
#     '@private:<server_id>'  a group of one - "sharing off"
#
# scope_map is '' for anything not map-scoped, which is gear, perks,
# payments and most settings. It carries a map name only when a feature
# genuinely differs per map.
#
# WHY THERE IS NO LONGER A '@self' SCOPE IN THE URL. The old endpoints
# addressed a row by server_id and enforced "a server may write only its
# own rows". Migration 0088 took server_id OUT of the key, which left
# that check guarding something that was no longer identity: the read
# still filtered on server_id and so could not address a row by group at
# all, and could match several rows and pick between them with no
# ORDER BY. Rows are per-GROUP now, and every server in a group is
# supposed to write the same row - that is what sharing IS.
#
# server_id survives as an informational "last writer" column, and it is
# now stamped from the LISTENING PORT on every write. The caller cannot
# state it and therefore cannot get it wrong or lie about it. That is
# strictly safer than accepting '@self' on trust, and it removes the
# second source of truth that caused the original cross-server gear loss.
#
# The real tenant boundary was never this check anyway: it is the
# per-server API key and the per-server hive_id, both resolved from the
# port the request arrived on.
# ------------------------------------------------------------------

GROUP_HIVE = "@hive"


def _valid_namespace(ns):
    """Shape only. THERE IS NO LIST OF VALID NAMESPACES, and adding one
    would destroy the property this whole table exists for: a new
    player-owned feature is a new namespace string, with no gateway
    release and no migration. Perks, payments, night-vision settings and
    stored vehicles are all just labels."""
    return bool(ns) and len(ns) <= 32 and all(c.isalnum() or c in "_-" for c in ns)


def _valid_group(group):
    """Shape only, same reasoning as _valid_namespace.

    '@' and ':' are allowed because '@hive' and '@private:<server_id>'
    are groups like any other - resolving them in the mod rather than
    special-casing them here is what keeps ONE read rule for every case
    instead of a branch per scope.
    """
    return bool(group) and len(group) <= 32 and all(
        c.isalnum() or c in "_-@:." for c in group
    )


def _valid_scope_map(scope_map):
    """'' is the normal value and always valid: most things are not
    map-scoped."""
    return len(scope_map) <= 64 and all(
        c.isalnum() or c in "_-." for c in scope_map
    )


@app.route("/api/data/<uid>/<namespace>", methods=["GET"])
def data_list(uid, namespace):
    """Every row this player has in this namespace, across all groups.

    Diagnostic and admin use. The mod reads a single row by key; this is
    for answering "where IS their gear" when a player says it vanished -
    which is almost always a group they are no longer in, with the row
    sitting untouched exactly where they left it.

    ?groups=1 answers the same question in a form the MOD can actually read
    (gw 0.9.4). Two reasons the full listing above cannot serve the join
    card that now asks this question on the player's behalf:

      1. Enforce cannot parse it. HFRestClient.ParseStringField finds the
         FIRST "field" and reads a flat string, so it cannot walk an array
         of objects whose keys repeat. Hand-rolled bracket matching is
         exactly where this class of bug lives - the same reasoning that
         put the gear resolver in get_player instead of the mod.

      2. It returns every payload. One call per join drags back every
         loadout that player owns; at 128 simultaneous logins that is real
         bandwidth for a question whose whole answer is a list of names.

    So the groups form returns ONE flat comma-separated string and no
    payloads at all: {"groups": "ALPHA,BRAVO"}. CSV because that is already
    how this mod moves lists across a boundary Enforce cannot parse
    structurally, and it splits with IndexOf(",") the way HFAdminBanList
    already does.
    """
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)

        if request.args.get("groups"):
            cursor.execute("""
                SELECT DISTINCT share_group
                  FROM player_data
                 WHERE player_uid = %s AND hive_id = %s AND namespace = %s
                 ORDER BY share_group
            """, (uid, current_hive_id(), namespace))
            # A comma inside a name would split one realm into two, and the
            # mod would name a group that does not exist. Dropped rather
            # than escaped: the mod's own config writers already REFUSE a
            # comma in a stored value (HFLootPoolConfig, HFWorldLootConfig),
            # so a realm containing one is already outside what this system
            # supports and inventing an escape scheme here would be the only
            # place that understood it.
            names = [str(r.get("share_group") or "").replace(",", "")
                     for r in cursor.fetchall()]
            names = [n for n in names if n]
            return jsonify({"status": "ok", "namespace": namespace,
                            "groups": ",".join(names)})

        cursor.execute("""
            SELECT share_group, scope_map, server_id, map_name,
                   format_ver, payload, updated_at
              FROM player_data
             WHERE player_uid = %s AND hive_id = %s AND namespace = %s
             ORDER BY share_group, scope_map
        """, (uid, current_hive_id(), namespace))
        rows = [{
            "share_group": r.get("share_group"),
            "scope_map":   r.get("scope_map") or "",
            "server_id":   r.get("server_id"),
            "map_name":    r.get("map_name") or "",
            "format_ver":  r.get("format_ver"),
            "payload":     r.get("payload"),
            "updated_at":  _iso(r.get("updated_at")),
        } for r in cursor.fetchall()]
        return jsonify({"status": "ok", "namespace": namespace, "rows": rows})
    except mysql.connector.Error as err:
        return _db_error("data_list", err)
    except Exception as err:
        return _internal_error("data_list", err)
    finally:
        _close(conn)


@app.route("/api/data/<uid>/<namespace>/<group>", methods=["GET"])
def data_get(uid, namespace, group):
    """ONE row, addressed by its full key. ?map= supplies scope_map.

    A point lookup on the primary key: no ORDER BY, no fallback clause,
    no candidate list. It CANNOT match more than one row, so there is no
    "which row wins" question to answer - the previous version filtered
    on server_id, a column that is not in the key, and so could match
    several rows and take an arbitrary one via fetchone().
    """
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400
    if not _valid_group(group):
        return jsonify({"status": "error", "message": "bad share_group"}), 400

    scope_map = request.args.get("map", "")
    if not _valid_scope_map(scope_map):
        return jsonify({"status": "error", "message": "bad map"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT share_group, scope_map, server_id, map_name,
                   format_ver, payload, updated_at
              FROM player_data
             WHERE player_uid = %s AND hive_id = %s AND share_group = %s
               AND namespace = %s AND scope_map = %s
        """, (uid, current_hive_id(), group, namespace, scope_map))
        r = cursor.fetchone()
        if not r:
            # NOT an error. A first visit, or a namespace this player has
            # never written, or a group with no rows yet. The mod decides
            # what "nothing here" means - for gear it means faction
            # defaults, and it is emphatically not data loss.
            return jsonify({"status": "ok", "namespace": namespace,
                            "share_group": group, "scope_map": scope_map,
                            "row": None})
        return jsonify({"status": "ok", "namespace": namespace,
                        "share_group": group, "scope_map": scope_map, "row": {
            "share_group": r.get("share_group"),
            "scope_map":   r.get("scope_map") or "",
            "server_id":   r.get("server_id"),
            "map_name":    r.get("map_name") or "",
            "format_ver":  r.get("format_ver"),
            "payload":     r.get("payload"),
            "updated_at":  _iso(r.get("updated_at")),
        }})
    except mysql.connector.Error as err:
        return _db_error("data_get", err)
    except Exception as err:
        return _internal_error("data_get", err)
    finally:
        _close(conn)


@app.route("/api/data/<uid>/<namespace>/<group>", methods=["PUT", "POST"])
def data_put(uid, namespace, group):
    """Upsert ONE row, addressed by its full key.

    server_id is stamped from the listening port and is NEVER taken from
    the caller, so it cannot drift and cannot be forged. It is
    informational - "last written by dev-01 on GM_Arland" - and decides
    nothing.
    """
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400
    if not _valid_group(group):
        return jsonify({"status": "error", "message": "bad share_group"}), 400

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    # owner_dead (0.9) - "the character who owns this state is dead".
    # Accepted here rather than on a route of its own, because it is a
    # property OF this row and belongs on the write that owns the row.
    #
    # The gateway does not interpret it. It does not know that death
    # forfeits gear or that a garage survives death - the MOD decides
    # which namespaces death touches and simply says so.
    owner_dead = data.get("owner_dead")
    if owner_dead is not None:
        try:
            owner_dead = 1 if int(owner_dead) else 0
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "owner_dead must be 0 or 1"}), 400

    payload = data.get("payload")

    # FLAG-ONLY UPDATE. A body carrying owner_dead and no payload updates
    # just that column and leaves the stored gear untouched.
    #
    # This exists so DEATH does not have to rewrite the loadout. Flipping
    # one bit by re-uploading a few thousand characters of gear is both
    # wasteful and risky: the death path runs while the character is being
    # torn down, which is exactly when a serialize returns a partial read.
    # Sending no payload cannot corrupt what is stored.
    if payload is None:
        if owner_dead is None:
            return jsonify({"status": "error", "message": "payload required"}), 400

        scope_map_f = (data.get("scope_map") or "")[:64]
        if not _valid_scope_map(scope_map_f):
            return jsonify({"status": "error", "message": "bad scope_map"}), 400

        conn = get_db()
        if not conn:
            return jsonify({"status": "error", "message": "database unavailable"}), 503
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE player_data SET owner_dead = %s
                 WHERE player_uid = %s AND hive_id = %s AND share_group = %s
                   AND namespace = %s AND scope_map = %s
            """, (owner_dead, uid, current_hive_id(), group, namespace, scope_map_f))
            conn.commit()
            # rowcount 0 is NOT an error. A player who has never stored
            # anything in this namespace has no row to flag, and creating an
            # empty one to hold a flag would invent state they do not have.
            # No row already reads as alive.
            print(f"[GATEWAY] owner_dead={owner_dead}: {uid} ns={namespace} "
                  f"group={group} (rows={cursor.rowcount})")
            return jsonify({"status": "ok", "message": "flag updated",
                            "rows": cursor.rowcount})
        except mysql.connector.Error as err:
            return _db_error("data_put_flag", err)
        except Exception as err:
            return _internal_error("data_put_flag", err)
        finally:
            _close(conn)

    if isinstance(payload, (list, dict)):
        payload = json.dumps(payload, separators=(",", ":"))

    scope_map = (data.get("scope_map") or "")[:64]
    if not _valid_scope_map(scope_map):
        return jsonify({"status": "error", "message": "bad scope_map"}), 400

    map_name   = (data.get("map_name") or "")[:64]
    format_ver = int(data.get("format_ver") or 1)
    sid = current_server_id()

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()

        # RETRY ON A TRANSIENT LOCK ERROR, same as save_player.
        #
        # Defence in depth, not a gap being closed: the mod already
        # re-sends once on an error, and its dedupe cache only updates on
        # a CONFIRMED write, so a payload that fails twice is still
        # re-sent by the next ordinary save rather than being suppressed
        # as "already stored". Absorbing a lock blip here just means that
        # machinery never has to run.
        #
        # Safe to re-run: a single idempotent upsert of absolute values,
        # so replaying it writes the same row - there is nothing to
        # double.
        # owner_dead is only touched when the caller SAYS so.
        #
        # Omitting it must leave the stored flag alone: an ordinary gear
        # save happens every few seconds, and folding a silent "= 0" into
        # it would resurrect a dead character on the next autosave. A new
        # row still inserts 0, because a row that has never existed
        # belongs to nobody who has died.
        if owner_dead is None:
            dead_insert = 0
            dead_update = ""
        else:
            dead_insert = owner_dead
            dead_update = "owner_dead = VALUES(owner_dead),"

        def _write():
            cursor.execute("""
                INSERT INTO player_data
                    (player_uid, hive_id, share_group, namespace, scope_map,
                     server_id, map_name, payload, format_ver, owner_dead)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    server_id   = VALUES(server_id),
                    map_name    = VALUES(map_name),
                    payload     = VALUES(payload),
                    """ + dead_update + """
                    format_ver  = VALUES(format_ver)
            """, (uid, current_hive_id(), group, namespace, scope_map,
                  sid, map_name, payload, format_ver, dead_insert))
            conn.commit()

        _db_retry(_write, "data_put")
        print(f"[GATEWAY] data saved: {uid} ns={namespace} group={group} "
              f"map={scope_map or '-'} by={sid} ({len(payload)} chars)")
        return jsonify({"status": "ok", "message": "saved"})
    except mysql.connector.Error as err:
        # A write that fails here leaves the PREVIOUS value in place,
        # which is the outcome to want: stale gear beats garbage gear,
        # and the mod re-sends on the next save anyway.
        return _db_error("data_put", err)
    except Exception as err:
        return _internal_error("data_put", err)
    finally:
        _close(conn)


@app.route("/api/data/<uid>/<namespace>/<group>", methods=["DELETE"])
def data_delete(uid, namespace, group):
    """Delete ONE row, addressed by its full key. ?map= supplies scope_map.

    Deliberately narrow: it can only ever remove the single row named by
    the key, so a mistake costs one namespace for one player in one
    group, and never a whole table.
    """
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400
    if not _valid_group(group):
        return jsonify({"status": "error", "message": "bad share_group"}), 400

    scope_map = request.args.get("map", "")
    if not _valid_scope_map(scope_map):
        return jsonify({"status": "error", "message": "bad map"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM player_data
             WHERE player_uid = %s AND hive_id = %s AND share_group = %s
               AND namespace = %s AND scope_map = %s
        """, (uid, current_hive_id(), group, namespace, scope_map))
        conn.commit()
        removed = cursor.rowcount
        print(f"[GATEWAY] data deleted: {uid} ns={namespace} group={group} "
              f"map={scope_map or '-'} ({removed} row)")
        return jsonify({"status": "ok", "deleted": removed})
    except mysql.connector.Error as err:
        return _db_error("data_delete", err)
    except Exception as err:
        return _internal_error("data_delete", err)
    finally:
        _close(conn)


# ============================================================
# HIVE-LEVEL STORAGE  (/api/hivedata/...)  +  CROSS-PLAYER READS
# ============================================================
# The player_data endpoints above answer "what does THIS player own".
# These answer the three questions a bot or an admin tool asks that they
# cannot: what does the hive know, who has a given namespace, and what
# namespaces exist at all.
#
# They exist so that adding a FEATURE never needs a gateway update. A
# tool that can read any namespace and any hive key does not need a new
# endpoint when the mod starts storing something new - it needs a new
# string.
#
# WHAT IS DELIBERATELY NOT HERE: a generic query endpoint taking filters
# or SQL fragments. That is the obvious way to never update the gateway
# again, and it hands anyone holding the API key an arbitrary read of
# the economy database - over a key that travels in a query string.
# Every query below is a fixed shape with a bounded result.
#
# The prefix is /api/hivedata/ and NOT /api/hive/ because
# /api/hive/servers and /api/hive/share_groups already exist: a
# <namespace> placeholder under /api/hive/ would silently make
# "servers" and "share_groups" unusable as namespace names.
# ============================================================

# Reads that walk more than one player are capped. A guardrail, not a
# tuning knob - a caller that wants everything pages for it.
NAMESPACE_PAGE_DEFAULT = 100
NAMESPACE_PAGE_MAX = 500


def _page_args():
    """limit/offset from the query string, clamped.

    Bad input is CLAMPED rather than refused: a report that returns the
    first 100 rows beats one that 400s because someone typed limit=abc.
    """
    try:
        limit = int(request.args.get("limit", NAMESPACE_PAGE_DEFAULT))
    except (TypeError, ValueError):
        limit = NAMESPACE_PAGE_DEFAULT
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(limit, NAMESPACE_PAGE_MAX)), max(0, offset)


@app.route("/api/hivedata/<namespace>/<scope>", methods=["GET"])
def hivedata_get(namespace, scope):
    """ONE hive row, addressed by its full key."""
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400
    if not _valid_scope_map(scope):
        return jsonify({"status": "error", "message": "bad scope"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT namespace, scope, server_id, payload, format_ver, updated_at
              FROM hive_data
             WHERE hive_id = %s AND namespace = %s AND scope = %s
        """, (current_hive_id(), namespace, scope))
        r = cursor.fetchone()
        if not r:
            # NOT an error - nothing has written this key yet.
            return jsonify({"status": "ok", "namespace": namespace,
                            "scope": scope, "row": None})
        return jsonify({"status": "ok", "namespace": namespace, "scope": scope, "row": {
            "namespace":  r.get("namespace"),
            "scope":      r.get("scope") or "",
            "server_id":  r.get("server_id"),
            "payload":    r.get("payload"),
            "format_ver": r.get("format_ver"),
            "updated_at": _iso(r.get("updated_at")),
        }})
    except mysql.connector.Error as err:
        return _db_error("hivedata_get", err)
    except Exception as err:
        return _internal_error("hivedata_get", err)
    finally:
        _close(conn)


@app.route("/api/hivedata/<namespace>", methods=["GET"])
def hivedata_list(namespace):
    """Every scope this hive holds in one namespace."""
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400
    limit, offset = _page_args()

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT scope, server_id, payload, format_ver, updated_at
              FROM hive_data
             WHERE hive_id = %s AND namespace = %s
             ORDER BY scope
             LIMIT %s OFFSET %s
        """, (current_hive_id(), namespace, limit, offset))
        rows = [{
            "scope":      r.get("scope") or "",
            "server_id":  r.get("server_id"),
            "payload":    r.get("payload"),
            "format_ver": r.get("format_ver"),
            "updated_at": _iso(r.get("updated_at")),
        } for r in cursor.fetchall()]
        return jsonify({"status": "ok", "namespace": namespace,
                        "limit": limit, "offset": offset, "rows": rows})
    except mysql.connector.Error as err:
        return _db_error("hivedata_list", err)
    except Exception as err:
        return _internal_error("hivedata_list", err)
    finally:
        _close(conn)


@app.route("/api/hivedata/<namespace>/<scope>", methods=["PUT", "POST"])
def hivedata_put(namespace, scope):
    """Upsert ONE hive row.

    server_id is stamped from the listening port and never taken from the
    caller, exactly as player data does it - informational, and it cannot
    be forged.
    """
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400
    if not _valid_scope_map(scope):
        return jsonify({"status": "error", "message": "bad scope"}), 400

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400
    payload = data.get("payload")
    if payload is None:
        return jsonify({"status": "error", "message": "payload required"}), 400
    if isinstance(payload, (list, dict)):
        payload = json.dumps(payload, separators=(",", ":"))
    format_ver = int(data.get("format_ver") or 1)

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO hive_data
                (hive_id, namespace, scope, server_id, payload, format_ver)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                server_id  = VALUES(server_id),
                payload    = VALUES(payload),
                format_ver = VALUES(format_ver)
        """, (current_hive_id(), namespace, scope, current_server_id(),
              payload, format_ver))
        conn.commit()
        print(f"[GATEWAY] hive data saved: ns={namespace} "
              f"scope={scope or '-'} ({len(payload)} chars)")
        return jsonify({"status": "ok", "message": "saved"})
    except mysql.connector.Error as err:
        return _db_error("hivedata_put", err)
    except Exception as err:
        return _internal_error("hivedata_put", err)
    finally:
        _close(conn)


@app.route("/api/hivedata/<namespace>/<scope>", methods=["DELETE"])
def hivedata_delete(namespace, scope):
    """Delete ONE hive row, addressed by its full key.

    Narrow on purpose: it can never remove more than the single key
    named, so a mistake costs one scope of one namespace.
    """
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400
    if not _valid_scope_map(scope):
        return jsonify({"status": "error", "message": "bad scope"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM hive_data
             WHERE hive_id = %s AND namespace = %s AND scope = %s
        """, (current_hive_id(), namespace, scope))
        conn.commit()
        removed = cursor.rowcount
        print(f"[GATEWAY] hive data deleted: ns={namespace} "
              f"scope={scope or '-'} ({removed} row)")
        return jsonify({"status": "ok", "deleted": removed})
    except mysql.connector.Error as err:
        return _db_error("hivedata_delete", err)
    except Exception as err:
        return _internal_error("hivedata_delete", err)
    finally:
        _close(conn)


@app.route("/api/namespace/<namespace>", methods=["GET"])
def namespace_rows(namespace):
    """Every PLAYER's rows in one namespace, across the hive.

    The cross-player read the per-uid endpoints cannot do: a leaderboard
    over a custom namespace, an export, "who has perks yet". Bounded by
    limit/offset; ?group= narrows to one share_group.

    display_name is joined in because every caller that wants this wants
    to label the rows, and making them call /api/players separately to do
    it is a second round trip for nothing.
    """
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400

    group = request.args.get("group", "")
    if group and not _valid_group(group):
        return jsonify({"status": "error", "message": "bad share_group"}), 400
    limit, offset = _page_args()

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        sql = """
            SELECT d.player_uid, p.display_name, d.share_group, d.scope_map,
                   d.server_id, d.map_name, d.payload, d.format_ver, d.updated_at
              FROM player_data d
              LEFT JOIN players p
                     ON p.player_uid = d.player_uid AND p.hive_id = d.hive_id
             WHERE d.hive_id = %s AND d.namespace = %s
        """
        args = [current_hive_id(), namespace]
        if group:
            sql += " AND d.share_group = %s"
            args.append(group)
        sql += " ORDER BY d.player_uid, d.share_group, d.scope_map LIMIT %s OFFSET %s"
        args.extend([limit, offset])
        cursor.execute(sql, tuple(args))
        rows = [{
            "player_uid":   r.get("player_uid"),
            "display_name": r.get("display_name") or "",
            "share_group":  r.get("share_group"),
            "scope_map":    r.get("scope_map") or "",
            "server_id":    r.get("server_id"),
            "map_name":     r.get("map_name") or "",
            "payload":      r.get("payload"),
            "format_ver":   r.get("format_ver"),
            "updated_at":   _iso(r.get("updated_at")),
        } for r in cursor.fetchall()]
        return jsonify({"status": "ok", "namespace": namespace,
                        "share_group": group, "limit": limit,
                        "offset": offset, "rows": rows})
    except mysql.connector.Error as err:
        return _db_error("namespace_rows", err)
    except Exception as err:
        return _internal_error("namespace_rows", err)
    finally:
        _close(conn)


@app.route("/api/namespaces", methods=["GET"])
def namespaces_list():
    """What namespaces exist, player-level and hive-level, with counts.

    Discovery. Without it a tool hardcodes the names the mod happens to
    use today and gets no signal when a release starts storing something
    new; with it the tool lists what is actually there, and the answer is
    current by construction.
    """
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT namespace, COUNT(*) AS rows_total,
                   COUNT(DISTINCT player_uid) AS players,
                   MAX(updated_at) AS last_write
              FROM player_data
             WHERE hive_id = %s
             GROUP BY namespace
             ORDER BY namespace
        """, (current_hive_id(),))
        player_ns = [{
            "namespace":  r.get("namespace"),
            "rows":       r.get("rows_total"),
            "players":    r.get("players"),
            "last_write": _iso(r.get("last_write")),
        } for r in cursor.fetchall()]

        cursor.execute("""
            SELECT namespace, COUNT(*) AS rows_total, MAX(updated_at) AS last_write
              FROM hive_data
             WHERE hive_id = %s
             GROUP BY namespace
             ORDER BY namespace
        """, (current_hive_id(),))
        hive_ns = [{
            "namespace":  r.get("namespace"),
            "rows":       r.get("rows_total"),
            "last_write": _iso(r.get("last_write")),
        } for r in cursor.fetchall()]

        return jsonify({"status": "ok", "hive_id": current_hive_id(),
                        "player": player_ns, "hive": hive_ns})
    except mysql.connector.Error as err:
        return _db_error("namespaces_list", err)
    except Exception as err:
        return _internal_error("namespaces_list", err)
    finally:
        _close(conn)


# ============================================================
# HIVE REGISTRATION  (/api/hive/...)
# ============================================================
# A server announces itself once at OnGameStart (map + share groups + full addon
# list) and refreshes the cheap volatile bits on its existing 60s ping.
#
# WHY THE ADDON LIST IS THE POINT: gear is stored as prefab paths, and on a
# server missing the owning addon the item silently fails to restore and the
# shrunken payload is written back over the profile. Registration lets an admin
# SEE the mod delta BEFORE putting a server into a shared gear pool, instead of
# discovering it when a player's rifle disappears.
# ============================================================

@app.route("/api/hive/register", methods=["POST"])
def hive_register():
    """Full startup announcement. Upsert - a restart just refreshes the row."""
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    data = request.get_json(force=True, silent=True) or {}
    addon_list = data.get("addon_list")
    if isinstance(addon_list, (list, dict)):
        addon_list = json.dumps(addon_list, separators=(",", ":"))

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO hive_servers
                (hive_id, server_id, display_name, map_name, gear_group, garage_group,
                 mod_version, addon_count, addon_hash, addon_list, players_online,
                 boot_session_id, started_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                display_name = VALUES(display_name),
                map_name     = VALUES(map_name),
                gear_group   = VALUES(gear_group),
                garage_group = VALUES(garage_group),
                mod_version  = VALUES(mod_version),
                addon_count  = VALUES(addon_count),
                addon_hash   = VALUES(addon_hash),
                addon_list   = VALUES(addon_list),
                players_online  = VALUES(players_online),
                -- started_at MEANS started_at again (gw 0.9.4). It was
                -- rewritten by every register, and a reregister fires
                -- whenever the GATEWAY lost the row - so the column was
                -- named started_at and behaved like last_registered_at.
                -- The boot session is the honest test for "is this a new
                -- run": same id, same run, leave the timestamp alone.
                -- <=> is NULL-safe, so an older mod that sends no session
                -- id compares '' to '' and keeps the stored timestamp
                -- rather than resetting it on every re-register.
                --
                -- ORDER IS LOAD-BEARING, and it is the trap in this idiom.
                -- MySQL evaluates these assignments LEFT TO RIGHT, and a
                -- column read after it has been assigned yields the NEW
                -- value. Written the other way round - boot_session_id
                -- first - the comparison below would compare the incoming
                -- id to itself, be true on every single register, and
                -- started_at would never move again. Silently: the syntax
                -- is valid and the column merely freezes.
                started_at      = IF(hive_servers.boot_session_id <=> VALUES(boot_session_id),
                                     hive_servers.started_at, VALUES(started_at)),
                boot_session_id = VALUES(boot_session_id)
        """, (
            current_hive_id(), sid,
            (data.get("display_name") or "")[:128],
            (data.get("map_name") or "")[:64],
            (data.get("gear_group") or "")[:32],
            (data.get("garage_group") or "")[:32],
            (data.get("mod_version") or "")[:32],
            int(data.get("addon_count") or 0),
            (data.get("addon_hash") or "")[:64],
            addon_list,
            int(data.get("players_online") or 0),
            (data.get("boot_session_id") or "")[:64],
        ))
        conn.commit()
        print(f"[GATEWAY] hive register: {sid} map={data.get('map_name')} "
              f"gear={data.get('gear_group')} addons={data.get('addon_count')}")
        return jsonify({"status": "ok", "message": "registered", "server_id": sid})
    except mysql.connector.Error as err:
        return _db_error("hive_register", err)
    except Exception as err:
        return _internal_error("hive_register", err)
    finally:
        _close(conn)


@app.route("/api/hive/servers", methods=["GET"])
def hive_servers():
    """Every registered server in this hive, with its mod fingerprint."""
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT server_id, display_name, map_name, gear_group, garage_group,
                   mod_version, addon_count, addon_hash, addon_list,
                   players_online, last_seen,
                   TIMESTAMPDIFF(SECOND, last_seen, NOW()) AS seconds_ago
              FROM hive_servers
             WHERE hive_id = %s
             ORDER BY gear_group, server_id
        """, (current_hive_id(),))
        rows = []
        for r in cursor.fetchall():
            r["last_seen"] = _iso(r.get("last_seen"))
            rows.append(r)
        # FLAT TEXT for the mod (?format=csv).
        #
        # The mod parses responses with a flat scanner - ParseStringField finds
        # the FIRST "field" and reads a string, so it cannot walk an array of
        # objects whose keys repeat. Rather than hand-roll bracket matching in
        # Enforce (where this class of bug lives and fails SILENTLY), the
        # gateway formats the rows and the mod passes the string straight to
        # the UI. Same reasoning as the resolved inventory row.
        #
        # Separators are '~' between fields and '|' between records - the same
        # convention HEALTH_ENTRIES already uses.
        #
        # NOT control characters: jsonify escapes those as \u001f, and the mod's
        # ParseStringField unescapes \" and \\ but NOT unicode escapes, so the
        # UI would have been handed literal backslash-u text. Every field goes
        # through _csvsafe() so a mod title containing a separator cannot shift
        # the rest of the row.
        if request.args.get("format") == "csv":
            recs = []
            for r in rows:
                recs.append("~".join([
                    _csvsafe(r.get("server_id")),
                    _csvsafe(r.get("display_name")),
                    _csvsafe(r.get("map_name")),
                    _csvsafe(r.get("gear_group")),
                    _csvsafe(r.get("garage_group")),
                    _csvsafe(r.get("mod_version")),
                    str(r.get("addon_count") or 0),
                    _csvsafe(r.get("addon_hash")),
                    str(r.get("players_online") or 0),
                    str(r.get("seconds_ago") if r.get("seconds_ago") is not None else -1),
                ]))
            return jsonify({"status": "ok", "hive_id": current_hive_id(),
                            "you": current_server_id(), "text": "|".join(recs)})

        return jsonify({"status": "ok", "hive_id": current_hive_id(),
                        "you": current_server_id(), "servers": rows})
    except mysql.connector.Error as err:
        return _db_error("hive_servers", err)
    except Exception as err:
        return _internal_error("hive_servers", err)
    finally:
        _close(conn)


@app.route("/api/hive/group/<group_name>", methods=["GET"])
def hive_group(group_name):
    """Members of one gear group, each flagged compliant against the CALLER.

    Compliance is advisory. A mismatched server is flagged, never blocked -
    hard-blocking risks locking an admin out over an addon they dropped on
    purpose.
    """
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    sid = current_server_id()

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT addon_hash, addon_list FROM hive_servers WHERE hive_id=%s AND server_id=%s",
                       (current_hive_id(), sid))
        me = cursor.fetchone() or {}
        my_hash = me.get("addon_hash")
        try:
            # id -> title, so a mismatch can be reported by NAME. An admin
            # reading "missing Nasty MP7" can act on it; "missing B2" is noise.
            my_addons = {a.get("id"): a.get("title") for a in json.loads(me.get("addon_list") or "[]")}
        except Exception:
            my_addons = {}

        cursor.execute("""
            SELECT server_id, display_name, map_name, gear_group, garage_group,
                   mod_version, addon_count, addon_hash, addon_list,
                   players_online, last_seen,
                   TIMESTAMPDIFF(SECOND, last_seen, NOW()) AS seconds_ago
              FROM hive_servers
             WHERE hive_id = %s AND gear_group = %s
             ORDER BY server_id
        """, (current_hive_id(), group_name))

        members = []
        for r in cursor.fetchall():
            r["last_seen"] = _iso(r.get("last_seen"))
            r["compliant"] = bool(my_hash) and r.get("addon_hash") == my_hash
            try:
                theirs = {a.get("id"): a.get("title") for a in json.loads(r.get("addon_list") or "[]")}
            except Exception:
                theirs = {}
            # missing_there = addons WE have that THEY lack. That is the
            # direction that loses gear: a player carrying one of these from
            # here to there cannot have it restored.
            # missing_here = the reverse, for the return trip.
            r["missing_there"] = sorted(t or i for i, t in my_addons.items() if i not in theirs)
            r["missing_here"]  = sorted(t or i for i, t in theirs.items() if i not in my_addons)
            # Their FULL mod list, sorted by title, for the F8 tab's per-server
            # mod pane. Sorted here because a server reports its addons in load
            # order, which differs between servers running the same set - the
            # match test is already order-independent (sorted id hash), and a
            # list a human reads should be too.
            r["addon_titles"] = sorted((t or i) for i, t in theirs.items())
            members.append(r)

        if request.args.get("format") == "csv":
            recs = []
            for m in members:
                recs.append("~".join([
                    _csvsafe(m.get("server_id")),
                    _csvsafe(m.get("map_name")),
                    str(m.get("addon_count") or 0),
                    str(m.get("players_online") or 0),
                    "1" if m.get("compliant") else "0",
                    str(m.get("seconds_ago") if m.get("seconds_ago") is not None else -1),
                    _csvsafe(", ".join(m.get("missing_there") or [])),
                    _csvsafe(", ".join(m.get("missing_here") or [])),
                    # Field 9, appended 2026-08-23. Trailing on purpose: a mod
                    # reading the first 8 fields is unaffected, so this needs no
                    # coordinated mod+gateway rollout.
                    _csvsafe(", ".join(m.get("addon_titles") or [])),
                ]))
            return jsonify({"status": "ok", "group": group_name, "you": sid,
                            "text": "|".join(recs)})

        return jsonify({"status": "ok", "group": group_name,
                        "you": sid, "your_addon_hash": my_hash, "members": members})
    except mysql.connector.Error as err:
        return _db_error("hive_group", err)
    except Exception as err:
        return _internal_error("hive_group", err)
    finally:
        _close(conn)


@app.route("/api/hive/share_groups", methods=["GET"])
def hive_share_groups():
    """Group descriptions plus a live member count per group."""
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT g.group_name, g.description, g.updated_by, g.updated_at,
                   (SELECT COUNT(*) FROM hive_servers s
                     WHERE s.hive_id = g.hive_id AND s.gear_group = g.group_name) AS members
              FROM hive_share_groups g
             WHERE g.hive_id = %s
             ORDER BY g.group_name
        """, (current_hive_id(),))
        described = {r["group_name"]: r for r in cursor.fetchall()}
        for r in described.values():
            r["updated_at"] = _iso(r.get("updated_at"))

        # Groups in USE but never described still have to appear, or a group an
        # admin joined without labelling would be invisible in the picker.
        cursor.execute("""
            SELECT gear_group AS group_name, COUNT(*) AS members
              FROM hive_servers WHERE hive_id = %s AND gear_group IS NOT NULL AND gear_group <> ''
             GROUP BY gear_group
        """, (current_hive_id(),))
        for r in cursor.fetchall():
            if r["group_name"] not in described:
                described[r["group_name"]] = {
                    "group_name": r["group_name"], "description": None,
                    "updated_by": None, "updated_at": "", "members": r["members"],
                }

        ordered = sorted(described.values(), key=lambda g: g["group_name"])
        if request.args.get("format") == "csv":
            recs = ["~".join([
                _csvsafe(g.get("group_name")),
                str(g.get("members") or 0),
                _csvsafe(g.get("description")),
            ]) for g in ordered]
            return jsonify({"status": "ok", "hive_id": current_hive_id(), "text": "|".join(recs)})

        return jsonify({"status": "ok", "hive_id": current_hive_id(), "groups": ordered})
    except mysql.connector.Error as err:
        return _db_error("hive_share_groups", err)
    except Exception as err:
        return _internal_error("hive_share_groups", err)
    finally:
        _close(conn)


@app.route("/api/hive/share_groups/<group_name>", methods=["PUT", "POST"])
def hive_share_group_set(group_name):
    """Label a group. Admin-tier is checked MOD-side before this is called."""
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO hive_share_groups (hive_id, group_name, description, updated_by)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                description = VALUES(description),
                updated_by  = VALUES(updated_by)
        """, (current_hive_id(), group_name[:32],
              (data.get("description") or "")[:255],
              (data.get("updated_by") or "")[:64]))
        conn.commit()
        return jsonify({"status": "ok", "message": "saved"})
    except mysql.connector.Error as err:
        return _db_error("hive_share_group_set", err)
    except Exception as err:
        return _internal_error("hive_share_group_set", err)
    finally:
        _close(conn)


if __name__ == "__main__":
    from werkzeug.serving import make_server
    from werkzeug.debug import DebuggedApplication
    import threading

    RESET = "\033[0m"; BOLD = "\033[1m"
    print("=" * 60)
    print(f"  {BOLD}WastelandZ Gateway v{GATEWAY_VERSION}{RESET}")
    _hives = []
    for _s in SERVERS:
        if _s["hive_id"] not in _hives:
            _hives.append(_s["hive_id"])
    if len(_hives) == 1:
        print(f"  Hive ID:   {_hives[0]}")
    else:
        # One gateway can serve several hives now, so there is no single
        # answer here - list them rather than picking one.
        print(f"  Hives ({len(_hives)}): {', '.join(_hives)}")
    print(f"  Database:  {config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}")
    print(f"  Crypto:    {'ENABLED' if CRYPTO_AVAILABLE else 'DISABLED (hf_crypto.py missing)'}")
    print(f"  Monitor:   {'ENABLED' if MONITOR_AVAILABLE else 'DISABLED'}")
    print(f"  Flask debug: {FLASK_DEBUG}")
    print(f"  Servers ({len(SERVERS)}):")
    for s in SERVERS:
        print(f"    - {s['server_id']:<14} {s['host']}:{s['port']}")
    print("=" * 60)

    _init_db_pool()
    conn = get_db()
    if conn and conn.is_connected():
        print("[GATEWAY] Database connection: OK")
    else:
        print("[GATEWAY] WARNING: Database connection FAILED — check config.py")

    # ------------------------------------------------------------------
    # SCHEMA MIGRATIONS — before a single listener binds.
    #
    # An admin updates the mod, updates the gateway, restarts. The database
    # catches itself up here. No SQL by hand, ever.
    #
    # Destructive migrations (DROP / TRUNCATE / DELETE) are SKIPPED unless
    # --allow-destructive is passed, and even then only after a successful
    # mysqldump. Additive work still applies; only the destructive step is
    # held, and everything after it is held too so ordering is preserved.
    #
    # A hard failure here does NOT bind listeners. Serving traffic against a
    # half-migrated schema is how a rollout turns into data loss.
    # ------------------------------------------------------------------
    if conn and conn.is_connected():
        allow_destructive = ("--allow-destructive" in sys.argv) or                             (os.environ.get("MIGRATE_ALLOW_DESTRUCTIVE") == "1")
        if allow_destructive:
            print("[MIGRATE] --allow-destructive is SET: destructive migrations may run (after a backup).")
        try:
            ok, _applied, _msg = migrate.run_migrations(
                conn,
                {
                    "host": config.DB_HOST,
                    "port": config.DB_PORT,
                    "user": config.DB_USER,
                    "password": config.DB_PASSWORD,
                    "database": config.DB_NAME,
                },
                GATEWAY_VERSION,
                allow_destructive=allow_destructive,
            )
            if not ok:
                print("[GATEWAY] Migrations did not complete — refusing to start.")
                _close(conn)
                sys.exit(1)
            SCHEMA_VERSION = migrate.current_schema_version(conn)
        except Exception as e:
            print(f"[GATEWAY] Migration runner crashed: {e}")
            print("[GATEWAY] Refusing to start rather than serve an unknown schema.")
            _close(conn)
            sys.exit(1)
    else:
        print("[MIGRATE] Skipped — no database connection. Schema state is UNKNOWN.")

    _close(conn)

    # ------------------------------------------------------------------
    # NOTHING BINDS A PORT WITHOUT A USABLE KEY.
    #
    # An empty key used to authenticate ANY caller, because check_auth
    # compares against "" when no api_key is sent. A placeholder is just as
    # bad in a different way: those strings are published in
    # config.example.py and on the setup site.
    #
    # Refusing to start is the right answer rather than starting with that
    # port disabled. A half-running gateway looks healthy while one server
    # silently saves nothing, and the admin finds out from a player.
    # ------------------------------------------------------------------
    _bad_keys = _validate_keys(SERVERS)
    if _bad_keys:
        print("[GATEWAY] " + "=" * 62)
        print("[GATEWAY] REFUSING TO START - server(s) with no usable api_key:")
        for s in _bad_keys:
            shown = (s.get("api_key") or "")
            why = "empty" if not shown.strip() else f"placeholder ({shown[:20]}...)"
            print(f"[GATEWAY]   {s.get('server_id')} on port {s.get('port')}: {why}")
        print("[GATEWAY]")
        print("[GATEWAY] An empty key would accept EVERY request, from anyone,")
        print("[GATEWAY] with nothing in the log to say so. A placeholder is a")
        print("[GATEWAY] key that is published in our own example file.")
        print("[GATEWAY]")
        print("[GATEWAY] Generate one per server:")
        print('[GATEWAY]   python -c "import secrets; print(secrets.token_hex(32))"')
        print("[GATEWAY] Put it in config.py SERVERS, and the SAME value in that")
        print("[GATEWAY] server's HFWastelandZ_secrets.conf (API_KEY line).")
        print("[GATEWAY] " + "=" * 62)
        sys.exit(1)

    wsgi = DebuggedApplication(app, evalex=True) if FLASK_DEBUG else app

    # ------------------------------------------------------------------
    # HTTP SERVER: waitress if available, werkzeug otherwise.
    #
    # werkzeug.serving is a DEVELOPMENT server - its own documentation says
    # so. It spawns a thread per request and stops accepting under load.
    # Measured on this box 2026-08-23: throughput plateaued at ~650 req/s and
    # requests began FAILING at 32 concurrent (39 of 320 dropped). Steady
    # state for a full hive is only ~9 req/s, so that ceiling is not the
    # problem - a burst is. 128 players reconnecting after a restart puts far
    # more than 32 requests in flight at once, and that is exactly where it
    # drops them.
    #
    # waitress is a production WSGI server: pure Python, no compiler, same
    # behaviour on Linux and Windows, and it QUEUES work across a fixed
    # thread pool instead of spawning threads until it falls over.
    #
    # AUTO-DETECTED ON PURPOSE. An admin who never installs it keeps exactly
    # the behaviour they have today - the upgrade is "pip install waitress"
    # and a restart, with no config edit and nothing to get wrong. Set
    # HTTP_SERVER in config.py to "waitress" or "werkzeug" to force one,
    # which is also how you A/B the two on identical load.
    # ------------------------------------------------------------------
    _forced = getattr(config, "HTTP_SERVER", "auto").lower()
    _waitress = None
    if _forced in ("auto", "waitress"):
        try:
            from waitress import create_server as _waitress
        except ImportError:
            if _forced == "waitress":
                print("[GATEWAY] HTTP_SERVER=waitress but waitress is NOT installed — run: pip install waitress")
                sys.exit(1)

    _threads_per = getattr(config, "HTTP_THREADS", 16)

    httpds = []
    for s in SERVERS:
        try:
            if _waitress:
                srv = _waitress(wsgi, host=s["host"], port=s["port"],
                                threads=_threads_per, clear_untrusted_proxy_headers=True)
            else:
                srv = make_server(s["host"], s["port"], wsgi, threaded=True)
            httpds.append((s, srv))
        except OSError as e:
            print(f"[GATEWAY] FAILED to bind {s['host']}:{s['port']} ({s['server_id']}) — {e}")

    if not httpds:
        print("[GATEWAY] No listeners bound — exiting.")
        sys.exit(1)

    # Capacity sanity check. Worker threads that outnumber pooled connections
    # means requests will queue on the DB and, at the edge, 503. Say so at
    # startup rather than letting an admin discover it as random errors.
    _max_inflight = _threads_per * len(httpds)
    if _waitress and _max_inflight > _pool_size():
        print(f"[GATEWAY] NOTE: {_threads_per} threads x {len(httpds)} listener(s) = {_max_inflight} "
              f"possible concurrent requests, but the DB pool is {_pool_size()}.")
        print(f"[GATEWAY]   Bursts will queue on the database. Either raise DB_POOL_SIZE "
              f"(max 32) or lower HTTP_THREADS in config.py.")

    if _waitress:
        print(f"[GATEWAY] HTTP server: waitress ({_threads_per} threads per listener)")
    else:
        print("[GATEWAY] HTTP server: werkzeug (DEVELOPMENT server)")
        print("[GATEWAY]   Fine for a small server. For a busy hive install waitress:")
        print("[GATEWAY]   pip install waitress   — then restart. Nothing else to change.")

    threads = []
    for s, srv in httpds:
        # waitress exposes run(); werkzeug exposes serve_forever().
        _entry = srv.run if _waitress else srv.serve_forever
        t = threading.Thread(target=_entry, daemon=True, name=f"gw-{s['server_id']}-{s['port']}")
        t.start()
        threads.append(t)
        print(f"[GATEWAY] Listening {s['host']}:{s['port']} -> {s['server_id']}")

    print("[GATEWAY] All listeners up. Ctrl+C to stop.")
    print()
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\n[GATEWAY] Shutting down...")
        for s, srv in httpds:
            try:
                # werkzeug: shutdown(). waitress: close(). Try both rather than
                # branching on a flag that could drift out of sync with the
                # server actually in use.
                if hasattr(srv, "shutdown"):
                    srv.shutdown()
                elif hasattr(srv, "close"):
                    srv.close()
            except Exception:
                pass
