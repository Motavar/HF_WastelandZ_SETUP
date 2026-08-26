# ============================================================
# WastelandZ Gateway — Configuration
# ============================================================
# Copy this file to config.py and edit with your values.
# config.py is in .gitignore — your credentials stay local.
# ============================================================

# --- MySQL Database ---
DB_HOST = "localhost"
DB_PORT = 3306
DB_USER = "wastelandz"
DB_PASSWORD = "CHANGE_ME"
DB_NAME = "wastelandz"
DB_POOL_SIZE = 32              # Pooled MySQL connections (max 32).
                               # Must be >= HTTP_THREADS x number of servers, or
                               # bursts queue on the database and can 503 - and a
                               # 503 on a save is a lost write. The gateway warns
                               # at startup if these do not line up.
                              # (more servers hitting one gateway). Max 32.

# --- Gateway runtime ---
# FLASK_DEBUG — debug mode for THIS gateway (the Python/Flask web service).
# This is NOT the game server's debug. The Arma game server has its own
# separate controls (DEV_MODE and HF_DEBUG in HFWastelandZ_server.conf).
#
# What it does: auto-reload on code edits + an interactive traceback page.
# Performance: negligible either way — it adds no per-request cost (the
# debugger only activates on an exception). Errors are printed to the console
# log regardless of this flag, so you are not blind with it off.
#
# Private / local box: fine to leave True for convenience.
# Public / production: MUST be False — True exposes the Werkzeug interactive
# debugger (remote code execution) on any unhandled error.
FLASK_DEBUG = False

# --- HTTP server ---
# "auto"     use waitress if installed, otherwise werkzeug   (default)
# "waitress" require waitress; refuse to start without it
# "werkzeug" force the built-in development server
#
# werkzeug is a DEVELOPMENT server. It works, but it spawns a thread per
# request and starts DROPPING them under concurrency - measured at 39 of 320
# failing at 32 simultaneous requests. Steady state for a busy hive is only a
# handful of requests per second, so that ceiling does not matter day to day.
# A burst does: 128 players reconnecting after a restart hits it immediately.
#
# waitress is a production WSGI server - pure Python, no compiler, identical on
# Linux and Windows. Upgrading is:
#     pip install waitress
# then restart. No config change needed; "auto" picks it up by itself.
HTTP_SERVER  = "auto"

# Worker threads per listener. 16 suits a 128-player server. Raise it if one
# gateway fronts many servers.
HTTP_THREADS = 16

# --- Servers (multi-server hive) ---
#
# ============================================================================
#  !!  SECURITY — READ BEFORE EDITING  !!
#  * Replace EVERY CHANGE_ME with a UNIQUE strong key. Never run on a default
#    or example key — example keys are public and WILL be exploited.
#        generate one per server:  python -c "import secrets; print(secrets.token_hex(32))"
#    A generated key is 64 hex characters and looks like:
#        74eda400e341b42edcaba2c1968811603b248641e50295dbf82dcd5d40e076f0
#    (that one is a PUBLIC example — never use it). The same key also goes in
#    that game server's HFWastelandZ_secrets.conf (API_KEY line).
#  * host "127.0.0.1" = same-box game server only. Safe; no firewall needed.
#  * host "0.0.0.0"   = reachable from the INTERNET. You MUST firewall-allowlist
#    the SOURCE IP of that game server (e.g. ufw allow from <ip> to any port N).
#    NEVER leave a 0.0.0.0 port open to 0.0.0.0/0 — that exposes the economy DB
#    to the whole world.
#  * Full key/encryption model + why local is safe and remote needs TLS:
#    see docs/SECURITY.md.
# ============================================================================
#
# One entry per game server. The gateway listens on every ACTIVE port below and
# identifies each request by the port it arrived on (-> that server's id + key).
# Keep unused servers COMMENTED OUT so no port ever runs on a default key.
#
# THE PORT IS WHAT IDENTIFIES A SERVER - not the key, and not anything the
# game server tells us. That is deliberate: a server cannot claim to be a
# different one, and there is no second value to drift out of sync.
#
# So EACH GAME SERVER MUST POINT AT ITS OWN PORT. The port here has to match
# the GATEWAY_URL in that server's HFWastelandZ_server.conf:
#
#     server_id    this file      that server's GATEWAY_URL
#     ----------   ------------   -------------------------------
#     server-1     port 5000      http://127.0.0.1:5000/
#     server-2     port 5001      http://127.0.0.1:5001/
#     server-3     port 5002      http://127.0.0.1:5002/
#
# Point two game servers at the SAME port and the gateway treats them as one
# server: they will overwrite each other's per-server data (last position,
# placements, money drops). Money and gear are hive-wide so those survive, but
# it is still wrong and it is silent.
#
# api_key = the GATEWAY KEY for that server. Each server needs its OWN unique key
#   (generate one with: python3 -c "import secrets; print(secrets.token_hex(32))").
#   The SAME key must go in that server's HFWastelandZ_secrets.conf (API_KEY).
#   If they differ the gateway rejects every request while the game server
#   looks perfectly healthy - no money, no gear, no obvious error.
SERVERS = [
    {"server_id": "server-1", "port": 5000, "host": "127.0.0.1", "api_key": "CHANGE_ME_UNIQUE_KEY_1"},

    # --- More local servers: uncomment one block each, set a UNIQUE key ---
    # {"server_id": "server-2", "port": 5001, "host": "127.0.0.1", "api_key": "CHANGE_ME_UNIQUE_KEY_2"},
    # {"server_id": "server-3", "port": 5002, "host": "127.0.0.1", "api_key": "CHANGE_ME_UNIQUE_KEY_3"},

    # --- Remote server: host "0.0.0.0" is INTERNET-FACING — FIREWALL-ALLOWLIST ITS IP ---
    # {"server_id": "remote-1", "port": 5003, "host": "0.0.0.0", "api_key": "CHANGE_ME_UNIQUE_KEY_4"},
]

# Hive for any SERVERS entry that does not name its own.
#
# Entries sharing a hive share money, bank and gear. Per-server data - last
# position, placements, money drops - is separated by server_id regardless.
#
# Hosting for other people? ONE HIVE PER CUSTOMER. Give each their own
# hive_id on their SERVERS entry. Never give them a gear group instead:
# groups separate GEAR ONLY, so two customers in one hive would share a
# bank - one deposits, the other withdraws.
HIVE_ID = "default"

# NOTE: do not add GATEWAY_PORT / GATEWAY_HOST / API_KEY / SERVER_ID here.
#
# They are the OLD single-server way of doing this, and while SERVERS is set
# the gateway never reads them - so a GATEWAY_PORT sitting in your config
# does nothing at all except mislead whoever reads it next. Everything lives
# in the SERVERS list above now, one entry per server.
#
# They still work as a fallback for a config that has no SERVERS list, which
# is the only reason they have not been deleted outright. If you are
# following an older guide that tells you to set them, that guide predates
# multi-server support.

# --- Health monitoring ---
# When True, the /api/admin/health endpoint is enabled and returns CPU/RAM/
# disk/uptime metrics via psutil. Used by the Discord bot, admin tooling,
# and the publish_status.py script. Off by default — fresh installs opt in
# only after confirming psutil is installed and the endpoint behaves.
MONITORING_ENABLED = False

# --- Public Status Publishing ---
# publish_status.py reads these every run. When PUBLISH_ENABLED is False,
# the script is a no-op (safe to leave the cron job in place).
#
# Upload destination is FTP-family or WebDAV. Set WEBHOST_PROTO to "none"
# to write the local JSON file but skip the upload (useful for testing).
PUBLISH_ENABLED         = False
PUBLISH_LOCAL_PATH      = "/tmp/wastelandz_status.json"  # local scratch path
PUBLISH_REMOTE_PATH     = "status.json"                   # filename at the destination
PLAYER_ONLINE_WINDOW_SEC = 900   # last_seen ≤ 15 min counts as "online"

# Which fields end up in the published JSON. Order is preserved in the output.
# Available: updated_at, server, server_id, players_online, uptime,
#   uptime_seconds, cpu_percent, mem_percent, mem_total_bytes, mem_used_bytes,
#   disk_percent, disk_total_bytes, disk_free_bytes, platform, platform_release
PUBLISH_FIELDS = [
    "updated_at",
    "server",
    "server_id",
    "players_online",
    "uptime",
    "cpu_percent",
    "mem_percent",
]

# Web host upload credentials. Generate the password in your host's panel
# (cPanel: Files → FTP Accounts → Add FTP Account, scope it to one folder).
# Never commit real values — config.py is gitignored.
WEBHOST_USER  = "CHANGE_ME"             # e.g. status@yourdomain.com
WEBHOST_PASS  = "CHANGE_ME"             # cPanel-generated password
WEBHOST_HOST  = "CHANGE_ME"             # e.g. ftp.yourdomain.com
WEBHOST_PROTO = "ftps"                  # ftps | sftp | webdav | none
