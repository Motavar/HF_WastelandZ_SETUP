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
DB_POOL_SIZE = 10              # Connections in the pool. Raise for a busy hive
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
# api_key = the GATEWAY KEY for that server. Each server needs its OWN unique key
#   (generate one with: python3 -c "import secrets; print(secrets.token_hex(32))").
#   The SAME key must go in that server's HFWastelandZ_secrets.conf (API_KEY).
SERVERS = [
    {"server_id": "server-1", "port": 5000, "host": "127.0.0.1", "api_key": "CHANGE_ME_UNIQUE_KEY_1"},

    # --- More local servers: uncomment one block each, set a UNIQUE key ---
    # {"server_id": "server-2", "port": 5001, "host": "127.0.0.1", "api_key": "CHANGE_ME_UNIQUE_KEY_2"},
    # {"server_id": "server-3", "port": 5002, "host": "127.0.0.1", "api_key": "CHANGE_ME_UNIQUE_KEY_3"},

    # --- Remote server: host "0.0.0.0" is INTERNET-FACING — FIREWALL-ALLOWLIST ITS IP ---
    # {"server_id": "remote-1", "port": 5003, "host": "0.0.0.0", "api_key": "CHANGE_ME_UNIQUE_KEY_4"},
]

# All SERVERS above share ONE database = ONE hive. Player money/bank/inventory
# are shared hive-wide; per-server data (position, placements, money drops) is
# separated by each entry's server_id.
HIVE_ID = "default"

# Legacy single-server fallback — used ONLY if SERVERS is absent or empty.
# SERVER_ID    = "dev-01"
# API_KEY      = "CHANGE_ME_TO_A_RANDOM_STRING"
# GATEWAY_HOST = "127.0.0.1"
# GATEWAY_PORT = 5000

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
