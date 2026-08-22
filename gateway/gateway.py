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

from flask import Flask, request, jsonify
from datetime import datetime
import mysql.connector
from mysql.connector import pooling
import json
import sys
import os

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
GATEWAY_VERSION = "0.8.0"

# --------------------------------------------------------
# Server roster — multi-server hive.
# Preferred: config.SERVERS = [{server_id, port, host, api_key}, ...].
# Backward-compatible fallback: a single server from the legacy flat keys.
# --------------------------------------------------------
def _resolve_servers():
    raw = getattr(config, "SERVERS", None)
    if raw:
        out = []
        for s in raw:
            out.append({
                "server_id": str(s["server_id"]),
                "port": int(s["port"]),
                "host": str(s.get("host", "127.0.0.1")),
                "api_key": str(s["api_key"]),
            })
        return out
    # Legacy single-server fallback
    return [{
        "server_id": str(getattr(config, "SERVER_ID", "dev-01")),
        "port": int(getattr(config, "GATEWAY_PORT", 5000)),
        "host": str(getattr(config, "GATEWAY_HOST", "127.0.0.1")),
        "api_key": str(getattr(config, "API_KEY", "")),
    }]

SERVERS = _resolve_servers()
SERVERS_BY_PORT = {s["port"]: s for s in SERVERS}
HIVE_ID = str(getattr(config, "HIVE_ID", "default"))

# Flask web-service debug (gateway only — NOT the game server's DEV_MODE/HF_DEBUG).
FLASK_DEBUG = getattr(config, "FLASK_DEBUG", getattr(config, "DEBUG", False))

# --------------------------------------------------------
# Per-request server identity (by the port the request arrived on)
# --------------------------------------------------------
def current_server():
    """The configured server for the port this request arrived on, or None."""
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

def _init_db_pool():
    """Initialize MySQL connection pool (called once at startup)."""
    global _db_pool
    try:
        _db_pool = pooling.MySQLConnectionPool(
            pool_name="gateway_pool",
            pool_size=getattr(config, "DB_POOL_SIZE", 10),
            pool_reset_session=True,
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME
        )
        print(f"[GATEWAY] DB connection pool created (size={getattr(config, 'DB_POOL_SIZE', 10)})")
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
    try:
        return _db_pool.get_connection()
    except mysql.connector.Error as err:
        print(f"[GATEWAY] DB POOL GET ERROR: {err}")
        return None

def _close(conn):
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass

def _iso(value):
    return value.isoformat() if value else ""

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
                             (HIVE_ID, _sid))
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
                        (int(_online or 0), HIVE_ID, _sid))
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
        "hive_id": HIVE_ID,
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
            "hive_id": HIVE_ID,
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
        cursor.execute("SELECT * FROM players WHERE player_uid = %s AND hive_id = %s", (uid, HIVE_ID))
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
                (sid, uid, HIVE_ID))
            print(f"[GATEWAY] arrival: {uid} {_prev_owner} -> {sid} (grace armed)")
        else:
            cursor.execute(
                "UPDATE players SET current_server_id = %s "
                "WHERE player_uid = %s AND hive_id = %s",
                (sid, uid, HIVE_ID))
        conn.commit()

        cursor.execute("SELECT * FROM player_sessions WHERE player_uid = %s AND server_id = %s", (uid, sid))
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
        _gear_group = request.args.get("gear_group", "")
        _my_map     = request.args.get("map", "")

        if _gear_group:
            cursor.execute("""
                SELECT server_id, share_group, map_name, format_ver, payload, updated_at
                  FROM player_data
                 WHERE player_uid = %s AND hive_id = %s AND namespace = 'inventory'
                   AND ( share_group = %s
                         OR ( server_id = %s AND (map_name = %s OR map_name = '') ) )
                 ORDER BY updated_at DESC
                 LIMIT 1
            """, (uid, HIVE_ID, _gear_group, sid, _my_map))
            _win = cursor.fetchone()
            if _win:
                player["inventory"]              = _win.get("payload")
                player["inventory_source"]       = _win.get("server_id")
                player["inventory_group"]        = _win.get("share_group")
                player["inventory_map"]          = _win.get("map_name") or ""
                player["inventory_format_ver"]   = _win.get("format_ver")
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
        else:
            player["map_name"] = None
            player["pos_x"] = player["pos_y"] = player["pos_z"] = None
            player["rotation_yaw"] = None
            player["stance"] = 0
            player["is_alive"] = 1
            player["recover_veh_prefab"] = None
            player["recover_veh_class"] = None
            player["recover_session_id"] = None
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
        cursor.execute("SELECT current_server_id FROM players WHERE player_uid = %s AND hive_id = %s", (uid, HIVE_ID))
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
        cursor.execute("UPDATE players SET arrival_grace = 0 "
                       "WHERE player_uid = %s AND hive_id = %s AND arrival_grace <> 0",
                       (uid, HIVE_ID))
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
                    weapon = VALUES(weapon),
                    inventory = VALUES(inventory),
                    bank = VALUES(bank),
                    current_server_id = VALUES(current_server_id),
                    last_seen = CURRENT_TIMESTAMP
            """, (uid, HIVE_ID, display_name, money, faction, weapon, inventory, bank, sid))
        else:
            cursor.execute("""
                INSERT INTO players (player_uid, hive_id, display_name, money, faction,
                                     weapon, bank, current_server_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    display_name = VALUES(display_name),
                    money = VALUES(money),
                    faction = VALUES(faction),
                    weapon = VALUES(weapon),
                    bank = VALUES(bank),
                    current_server_id = VALUES(current_server_id),
                    last_seen = CURRENT_TIMESTAMP
            """, (uid, HIVE_ID, display_name, money, faction, weapon, bank, sid))

        cursor.execute("""
            INSERT INTO player_sessions (player_uid, server_id, map_name,
                                         pos_x, pos_y, pos_z, rotation_yaw, stance, is_alive)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                map_name = VALUES(map_name),
                pos_x = VALUES(pos_x),
                pos_y = VALUES(pos_y),
                pos_z = VALUES(pos_z),
                rotation_yaw = VALUES(rotation_yaw),
                stance = VALUES(stance),
                is_alive = VALUES(is_alive),
                last_seen = CURRENT_TIMESTAMP
        """, (uid, sid, map_name, pos_x, pos_y, pos_z, rotation_yaw, stance, is_alive))

        conn.commit()
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
        cursor.execute("SELECT current_server_id FROM players WHERE player_uid = %s AND hive_id = %s", (uid, HIVE_ID))
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
        """, (uid, HIVE_ID, inventory))
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

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO player_sessions (player_uid, server_id, recover_veh_prefab,
                                         recover_veh_class, recover_session_id)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                recover_veh_prefab = VALUES(recover_veh_prefab),
                recover_veh_class = VALUES(recover_veh_class),
                recover_session_id = VALUES(recover_session_id),
                last_seen = CURRENT_TIMESTAMP
        """, (uid, sid, prefab, vclass, session))
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
        """, (uid, HIVE_ID, sid, tx_type, amount, balance_after, details))
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
        """, (uid, HIVE_ID, sid, kills, deaths, playtime_seconds,
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
        cursor.execute(
            "SELECT * FROM player_stats_daily WHERE player_uid = %s AND server_id = %s AND stat_date = %s",
            (uid, sid, stat_date))
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
        cursor.execute("SELECT * FROM player_marker_prefs WHERE player_uid = %s AND hive_id = %s", (uid, HIVE_ID))
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
        """, (uid, HIVE_ID, icon_idx, icon_size_px, marker_range_m,
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
        params = (HIVE_ID,) + date_params + (limit,)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return jsonify({"status": "ok", "metric": metric, "days": days_arg, "hive_id": HIVE_ID, "rows": rows})
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
        cursor.execute("DELETE FROM transactions WHERE player_uid = %s AND hive_id = %s", (uid, HIVE_ID))
        tx_deleted = cursor.rowcount
        cursor.execute("DELETE FROM player_stats_daily WHERE player_uid = %s AND hive_id = %s", (uid, HIVE_ID))
        stats_deleted = cursor.rowcount
        cursor.execute("DELETE FROM player_sessions WHERE player_uid = %s", (uid,))
        sessions_deleted = cursor.rowcount
        cursor.execute("DELETE FROM players WHERE player_uid = %s AND hive_id = %s", (uid, HIVE_ID))
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
        cursor.execute("SELECT player_uid, display_name, money, bank FROM players WHERE hive_id = %s", (HIVE_ID,))
        before = {r["player_uid"]: r for r in cursor.fetchall()}

        set_parts = []
        if target in ("wallet", "both"):
            set_parts.append(f"money = money + {int(amount)}" if amount > 0
                             else f"money = GREATEST(0, money + ({int(amount)}))")
        if target in ("bank", "both"):
            set_parts.append(f"bank = bank + {int(amount)}" if amount > 0
                             else f"bank = GREATEST(0, bank + ({int(amount)}))")

        cursor.execute(f"UPDATE players SET {', '.join(set_parts)} WHERE hive_id = %s", (HIVE_ID,))
        rows_affected = cursor.rowcount
        conn.commit()

        cursor.execute("SELECT player_uid, display_name, money, bank FROM players WHERE hive_id = %s", (HIVE_ID,))
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
                tx_rows.append((puid, HIVE_ID, sid, "admin_give", delta, row["money"],
                                f"bulk {op} {target} ${abs(amount):,}"))

        if tx_rows:
            cursor.executemany(
                "INSERT INTO transactions (player_uid, hive_id, server_id, type, amount, balance_after, details) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)", tx_rows)
            conn.commit()

        print(f"[GATEWAY] Bulk {op}: ${abs(amount):,} to {target} for {rows_affected} players (hive {HIVE_ID}); {len(tx_rows)} audit rows")
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
            LEFT JOIN player_sessions s ON s.player_uid = p.player_uid AND s.server_id = %s
            WHERE p.hive_id = %s
        """
        if search:
            cursor.execute(base + " AND (p.display_name LIKE %s OR p.player_uid LIKE %s) ORDER BY p.last_seen DESC",
                           (sid, HIVE_ID, f"%{search}%", f"%{search}%"))
        else:
            cursor.execute(base + " ORDER BY p.last_seen DESC", (sid, HIVE_ID))
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
        cursor.execute("SELECT COUNT(*) as total_players FROM players WHERE hive_id = %s", (HIVE_ID,))
        total = cursor.fetchone()["total_players"]
        cursor.execute("""
            SELECT COUNT(*) as alive FROM player_sessions s
            JOIN players p ON p.player_uid = s.player_uid
            WHERE p.hive_id = %s AND s.is_alive = 1
        """, (HIVE_ID,))
        alive = cursor.fetchone()["alive"]
        cursor.execute("SELECT COALESCE(SUM(money),0) as total_wallet, COALESCE(SUM(bank),0) as total_bank FROM players WHERE hive_id = %s", (HIVE_ID,))
        economy = cursor.fetchone()
        cursor.execute("SELECT display_name, (money + bank) as total_money FROM players WHERE hive_id = %s ORDER BY total_money DESC LIMIT 5", (HIVE_ID,))
        top5 = cursor.fetchall()
        cursor.execute("SELECT faction, COUNT(*) as count FROM players WHERE hive_id = %s AND faction IS NOT NULL AND faction != '' GROUP BY faction", (HIVE_ID,))
        factions = {row["faction"]: row["count"] for row in cursor.fetchall()}
        tx_count = 0
        try:
            cursor.execute("SELECT COUNT(*) as tx_count FROM transactions WHERE hive_id = %s AND timestamp >= NOW() - INTERVAL 1 DAY", (HIVE_ID,))
            tx_count = cursor.fetchone()["tx_count"]
        except mysql.connector.Error:
            pass
        return jsonify({
            "status": "ok", "hive_id": HIVE_ID,
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
        """, (player_uid, sid, HIVE_ID, display_name, event_type, item_prefab, details, severity))
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
        """, (uid, HIVE_ID, sid))
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
    ban_hive_id = HIVE_ID if scope in ("server", "hive") else None

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
            cursor.execute("UPDATE blacklist SET is_active = 0 WHERE player_uid = %s AND scope = 'hive' AND hive_id = %s AND is_active = 1", (player_uid, HIVE_ID))
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
            cursor.execute(f"SELECT {cols} FROM blacklist WHERE is_active = 1 AND scope = 'hive' AND hive_id = %s AND (expires_at IS NULL OR expires_at > NOW()) ORDER BY banned_at DESC LIMIT %s", (HIVE_ID, limit))
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
        """, (HIVE_ID, sid, map_name, int(carry_class), prefab_path,
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
        """, (HIVE_ID, sid, map_name, float(pos_x), float(pos_y), float(pos_z),
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


SCOPE_HIVE = "@hive"
SCOPE_SELF = "@self"


def _resolve_scope(scope):
    """'@self' means 'whatever THIS gateway calls the calling server'.

    The mod sends @self rather than its own configured SERVER_ID on purpose.
    The gateway identifies a server by the PORT the request arrived on, and if
    a server's local SERVER_ID has drifted from that, sending the local value
    would get every save refused 403. That drift is exactly the bug that caused
    the cross-server gear loss in the first place; @self removes the second
    source of truth instead of asking admins to keep two values in sync.
    """
    if scope == SCOPE_SELF:
        return current_server_id()
    return scope


def _scope_writable(scope):
    """A server may write only its own rows, or the hive-wide scope."""
    return scope == SCOPE_HIVE or scope == current_server_id()


def _valid_namespace(ns):
    return bool(ns) and len(ns) <= 32 and all(c.isalnum() or c in "_-" for c in ns)


@app.route("/api/data/<uid>/<namespace>", methods=["GET"])
def data_list(uid, namespace):
    """Every row for this player in this namespace, across all scopes."""
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT server_id, share_group, map_name, format_ver, payload, updated_at
              FROM player_data
             WHERE player_uid = %s AND hive_id = %s AND namespace = %s
             ORDER BY updated_at DESC
        """, (uid, HIVE_ID, namespace))
        rows = [{
            "server_id":   r.get("server_id"),
            "share_group": r.get("share_group"),
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


@app.route("/api/data/<uid>/<namespace>/<scope>", methods=["GET"])
def data_get(uid, namespace, scope):
    """One row - this scope only."""
    if not check_auth("LOAD"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400
    scope = _resolve_scope(scope)

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT server_id, share_group, map_name, format_ver, payload, updated_at
              FROM player_data
             WHERE player_uid = %s AND hive_id = %s AND namespace = %s AND server_id = %s
        """, (uid, HIVE_ID, namespace, scope))
        r = cursor.fetchone()
        if not r:
            # Not an error. A first visit, or a namespace this player has never
            # written. The mod decides what "nothing here" means.
            return jsonify({"status": "ok", "namespace": namespace, "scope": scope, "row": None})
        return jsonify({"status": "ok", "namespace": namespace, "scope": scope, "row": {
            "server_id":   r.get("server_id"),
            "share_group": r.get("share_group"),
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


@app.route("/api/data/<uid>/<namespace>/<scope>", methods=["PUT", "POST"])
def data_put(uid, namespace, scope):
    """Upsert one row. A server may write only its OWN scope, or '@hive'."""
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    if not _valid_namespace(namespace):
        return jsonify({"status": "error", "message": "bad namespace"}), 400
    scope = _resolve_scope(scope)

    if not _scope_writable(scope):
        # Refused, not silently redirected. A server trying to write another
        # server's row is a bug worth surfacing loudly, and honouring it would
        # reintroduce exactly the clobber class this design removes.
        print(f"[GATEWAY] data_put REFUSED: {current_server_id()} tried to write scope '{scope}'")
        return jsonify({"status": "error",
                        "message": "a server may only write its own scope",
                        "your_scope": current_server_id()}), 403

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    payload = data.get("payload")
    if payload is None:
        return jsonify({"status": "error", "message": "payload required"}), 400
    if isinstance(payload, (list, dict)):
        payload = json.dumps(payload, separators=(",", ":"))

    share_group = (data.get("share_group") or "ALPHA")[:32]
    map_name    = (data.get("map_name") or "")[:64]
    format_ver  = int(data.get("format_ver") or 1)

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO player_data
                (player_uid, hive_id, server_id, namespace, share_group, map_name, payload, format_ver)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                share_group = VALUES(share_group),
                map_name    = VALUES(map_name),
                payload     = VALUES(payload),
                format_ver  = VALUES(format_ver)
        """, (uid, HIVE_ID, scope, namespace, share_group, map_name, payload, format_ver))
        conn.commit()
        print(f"[GATEWAY] data saved: {uid} ns={namespace} scope={scope} "
              f"group={share_group} map={map_name or '-'} ({len(payload)} chars)")
        return jsonify({"status": "ok", "message": "saved"})
    except mysql.connector.Error as err:
        # A malformed payload is REJECTED by the JSON column rather than stored.
        # That is deliberate: the previous good value surviving beats writing
        # garbage over it.
        return _db_error("data_put", err)
    except Exception as err:
        return _internal_error("data_put", err)
    finally:
        _close(conn)


@app.route("/api/data/<uid>/<namespace>/<scope>", methods=["DELETE"])
def data_delete(uid, namespace, scope):
    """Delete one row. Same write rule as PUT."""
    if not check_auth("SAVE"):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    scope = _resolve_scope(scope)
    if not _scope_writable(scope):
        return jsonify({"status": "error",
                        "message": "a server may only write its own scope"}), 403

    conn = get_db()
    if not conn:
        return jsonify({"status": "error", "message": "database unavailable"}), 503
    try:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM player_data
             WHERE player_uid = %s AND hive_id = %s AND namespace = %s AND server_id = %s
        """, (uid, HIVE_ID, namespace, scope))
        conn.commit()
        return jsonify({"status": "ok", "deleted": cursor.rowcount})
    except mysql.connector.Error as err:
        return _db_error("data_delete", err)
    except Exception as err:
        return _internal_error("data_delete", err)
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
                boot_session_id = VALUES(boot_session_id),
                started_at      = VALUES(started_at)
        """, (
            HIVE_ID, sid,
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
        """, (HIVE_ID,))
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
            return jsonify({"status": "ok", "hive_id": HIVE_ID,
                            "you": current_server_id(), "text": "|".join(recs)})

        return jsonify({"status": "ok", "hive_id": HIVE_ID,
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
                       (HIVE_ID, sid))
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
        """, (HIVE_ID, group_name))

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
        """, (HIVE_ID,))
        described = {r["group_name"]: r for r in cursor.fetchall()}
        for r in described.values():
            r["updated_at"] = _iso(r.get("updated_at"))

        # Groups in USE but never described still have to appear, or a group an
        # admin joined without labelling would be invisible in the picker.
        cursor.execute("""
            SELECT gear_group AS group_name, COUNT(*) AS members
              FROM hive_servers WHERE hive_id = %s AND gear_group IS NOT NULL AND gear_group <> ''
             GROUP BY gear_group
        """, (HIVE_ID,))
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
            return jsonify({"status": "ok", "hive_id": HIVE_ID, "text": "|".join(recs)})

        return jsonify({"status": "ok", "hive_id": HIVE_ID, "groups": ordered})
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
        """, (HIVE_ID, group_name[:32],
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
    print(f"  Hive ID:   {HIVE_ID}")
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

    wsgi = DebuggedApplication(app, evalex=True) if FLASK_DEBUG else app

    httpds = []
    for s in SERVERS:
        try:
            srv = make_server(s["host"], s["port"], wsgi, threaded=True)
            httpds.append((s, srv))
        except OSError as e:
            print(f"[GATEWAY] FAILED to bind {s['host']}:{s['port']} ({s['server_id']}) — {e}")

    if not httpds:
        print("[GATEWAY] No listeners bound — exiting.")
        sys.exit(1)

    threads = []
    for s, srv in httpds:
        t = threading.Thread(target=srv.serve_forever, daemon=True, name=f"gw-{s['server_id']}-{s['port']}")
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
                srv.shutdown()
            except Exception:
                pass
