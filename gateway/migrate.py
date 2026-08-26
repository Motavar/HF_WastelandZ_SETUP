"""
============================================================
WastelandZ Gateway - schema migration runner
============================================================
Brings the database up to date on gateway startup so an admin never
runs SQL by hand. Update the mod, update the gateway, restart - the
database catches itself up and logs what it did.

TWO STEPS, IN THIS ORDER, EVERY START
  1. setup_database.sql - THE schema. Every table is defined there and
     nowhere else. It is idempotent and strictly additive, so applying
     it to a current database is a no-op and to an old one is the
     upgrade. See apply_schema().
  2. migrations/*.sql - DATA transformations only. Never a table
     definition.

  WHY THE SPLIT. The schema used to live in setup_database.sql for
  fresh installs AND in migrations for upgrades, and keeping two
  definitions in agreement is a discipline rather than a guarantee.
  It lapsed: a migration created player_marker_prefs without a COLLATE
  clause, so it inherited the server default and a fresh install ended
  up utf8mb4_unicode_ci while an upgraded one was utf8mb4_0900_ai_ci.
  The result was a hard ERROR 1267 on any join between that table and
  players - a query that passes on a developer's fresh database and
  fails on every server in the field. Running ONE file against BOTH
  cases removes the possibility instead of reducing the odds.

HOW RE-RUNNING IS PREVENTED
  A ledger table, schema_migrations, holds one row per applied
  version. On startup we read the applied set, diff it against the
  files on disk, and run only what is missing. There is no timer and
  no flag to forget to reset - the database itself is the record.

  IMPORTANT, AND THE REASON EVERY MIGRATION MUST STAY IDEMPOTENT:
  MySQL performs an IMPLICIT COMMIT on DDL (CREATE TABLE, ALTER
  TABLE). A migration and its ledger row therefore CANNOT be made
  atomic - that is a MySQL fact, not a design choice. If a migration
  dies halfway, its version is not recorded and it runs again next
  boot. Safety comes from every migration being re-runnable:
      - CREATE TABLE IF NOT EXISTS
      - ADD COLUMN guarded via information_schema + PREPARE
        (see the SCHEMA UPGRADES section of setup_database.sql)
      - data backfills written INSERT ... ON DUPLICATE KEY UPDATE
        so a second run fills gaps and never overwrites
  A non-idempotent migration is a bug.

DESTRUCTIVE MIGRATIONS
  Any DROP / TRUNCATE / DELETE / REPLACE INTO anywhere in the file
  marks it destructive - the verbs, not particular spellings of them,
  because an allow-list of spellings cannot be complete and the one it
  misses is the one that costs an admin their database.
  Those NEVER run without a successful mysqldump taken first; if the
  backup fails, the migration is refused.

  A HELD MIGRATION IS A FAILURE, NOT A SUCCESS. It used to break out
  of the loop and report ok, so the gateway started normally against a
  schema known to be out of date, silently. It now refuses to start and
  names the migration, the reason, and the exact command that applies
  it. A half-upgraded database serving a mod that expects the new shape
  is worse than no gateway at all, because nothing announces it.

  This is also why the day-one upgrade path is deliberately 100%
  additive: nothing in it can be held, so an admin's first boot after
  updating cannot stall. Removals are separate migrations, opted into
  later, at a moment of the admin's choosing.

DOWNGRADE GUARD
  If the database records a version higher than any file we ship, the
  gateway REFUSES TO START. An older gateway writing against a newer
  schema corrupts data quietly; failing loudly is the whole point.
============================================================
"""

import os
import re
import subprocess
from datetime import datetime

import mysql.connector

MIGRATIONS_DIRNAME = "migrations"

# THE schema. Applied on every start, before any numbered migration.
# See apply_schema() for why it works this way.
SCHEMA_FILENAME = "setup_database.sql"

# Words that mark a migration as destructive. Matched on comment-stripped
# SQL so a mention inside documentation cannot trip the guard.
#
# DELIBERATELY BROAD - a bare DROP / TRUNCATE / DELETE / REPLACE anywhere.
#
# The previous pattern was specific:
#     DROP\s+(TABLE|COLUMN|DATABASE|INDEX) | TRUNCATE | DELETE\s+FROM
# and a real migration walked straight through it. 0088 contained BOTH
#     DELETE older FROM player_data AS older   -- alias breaks DELETE\s+FROM
#     ALTER TABLE ... DROP PRIMARY KEY         -- not in the DROP list
# so a migration that deleted rows AND re-keyed a table was classified as
# additive, ran unattended, and took no backup - while its own header
# stated that a backup is always taken. Verified empirically: it applied
# in a clean test run with no [DESTRUCTIVE] marker and no backup file.
#
# The lesson is that an allow-list of destructive SPELLINGS cannot be
# complete - SQL has too many ways to remove data, and the one that gets
# missed is the one that costs an admin their database. So this matches
# the verbs instead.
#
# A FALSE POSITIVE COSTS AN ADMIN ONE FLAG. A FALSE NEGATIVE COSTS DATA.
# When those are the stakes the guard errs toward stopping. If a genuinely
# additive migration trips it - say the word DROP inside a string literal
# - rephrase the migration rather than narrowing this pattern.
_DESTRUCTIVE = re.compile(
    r"\b(DROP|TRUNCATE|DELETE|REPLACE\s+INTO)\b",
    re.IGNORECASE,
)

_FILENAME = re.compile(r"^(\d{4})_(.+)\.sql$", re.IGNORECASE)


def _strip_sql_comments(sql):
    """Remove -- line comments and /* */ blocks.

    Only used for destructive DETECTION. The SQL actually executed is the
    original text - never the stripped copy - because stripping is a
    heuristic and must not be able to change what runs.
    """
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _discover(migrations_dir):
    """Every migrations/NNNN_name.sql, ordered by version number."""
    found = []
    if not os.path.isdir(migrations_dir):
        return found
    for entry in sorted(os.listdir(migrations_dir)):
        m = _FILENAME.match(entry)
        if not m:
            continue
        found.append((int(m.group(1)), m.group(2), os.path.join(migrations_dir, entry)))
    found.sort(key=lambda row: row[0])
    return found


def _ensure_ledger(conn):
    """Create schema_migrations if absent. This is migration zero, and it
    bootstraps itself - it cannot be recorded in a table that does not
    exist yet."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version          INT          NOT NULL,
          name             VARCHAR(128) NOT NULL,
          applied_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
          gateway_version  VARCHAR(16),
          PRIMARY KEY (version)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    conn.commit()
    cur.close()


def _applied_versions(conn):
    cur = conn.cursor()
    cur.execute("SELECT version FROM schema_migrations")
    rows = {int(r[0]) for r in cur.fetchall()}
    cur.close()
    return rows


def _record(conn, version, name, gateway_version):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO schema_migrations (version, name, gateway_version) "
        "VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE applied_at = applied_at",
        (version, name[:128], (gateway_version or "")[:16]),
    )
    conn.commit()
    cur.close()


def _split_statements(sql):
    """Split a migration into individual statements.

    We split ourselves rather than using cursor.execute(multi=True): that
    keyword was REMOVED in mysql-connector-python 9.x, and relying on it
    would break on some admins' machines and not others depending on which
    connector version pip resolved. Splitting here works on every version.

    The scanner tracks single quotes, double quotes and comments so a
    semicolon inside a quoted string or a comment does not split a
    statement. That matters: the ADD COLUMN guards build their DDL as a
    quoted string, and a naive split on ';' would cut one in half.
    """
    out, buf = [], []
    i, n = 0, len(sql)
    in_s = in_d = in_line = in_block = False

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line:
            if ch == "\n":
                in_line = False
            buf.append(ch); i += 1; continue
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False; buf.append(ch); buf.append(nxt); i += 2; continue
            buf.append(ch); i += 1; continue
        if in_s:
            buf.append(ch)
            # '' inside a single-quoted string is an escaped quote, not the end
            if ch == "'" and nxt == "'":
                buf.append(nxt); i += 2; continue
            if ch == "'":
                in_s = False
            i += 1; continue
        if in_d:
            buf.append(ch)
            if ch == '"':
                in_d = False
            i += 1; continue

        if ch == "-" and nxt == "-":
            in_line = True; buf.append(ch); i += 1; continue
        if ch == "/" and nxt == "*":
            in_block = True; buf.append(ch); buf.append(nxt); i += 2; continue
        if ch == "'":
            in_s = True; buf.append(ch); i += 1; continue
        if ch == '"':
            in_d = True; buf.append(ch); i += 1; continue

        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1; continue

        buf.append(ch); i += 1

    tail = "".join(buf).strip()
    if tail:
        out.append(tail)

    # Drop comment-only fragments - they are not statements and MySQL
    # rejects an empty query.
    return [s for s in out if _strip_sql_comments(s).strip()]


def _run_sql(conn, sql):
    """Execute every statement in a migration file, in order.

    Each result must be consumed or the connector leaves the connection in
    an unread state and the NEXT query fails with a confusing error that
    points at the wrong statement.
    """
    cur = conn.cursor()
    try:
        for idx, stmt in enumerate(_split_statements(sql), start=1):
            try:
                cur.execute(stmt)
                if cur.with_rows:
                    cur.fetchall()
            except mysql.connector.Error as err:
                # Name the statement that actually failed. Without this the
                # error says only "you have an error in your SQL syntax" for
                # a file that may hold a dozen statements.
                head = " ".join(stmt.split())[:120]
                raise mysql.connector.Error(
                    msg=f"statement {idx} failed [{head}...]: {err}"
                ) from err
        conn.commit()
    finally:
        cur.close()


def apply_schema(conn, base_dir):
    """Apply setup_database.sql - THE schema - on every start.

    THIS IS WHAT MAKES A FRESH INSTALL AND AN UPGRADED ONE IDENTICAL.

    The schema used to live in two places: setup_database.sql for fresh
    installs and migrations/*.sql for upgrades. Keeping two definitions in
    agreement is a discipline, and disciplines lapse. This one did:
    player_marker_prefs ended up utf8mb4_unicode_ci when created fresh and
    utf8mb4_0900_ai_ci when created by the migration that omitted a
    COLLATE clause. The consequence was a hard ERROR 1267 on any join
    between player_marker_prefs and players - a query that passes on a
    developer's fresh database and fails on every server in the field.

    Running the ONE file against BOTH cases removes the possibility rather
    than the likelihood. Numbered migrations still exist, but they carry
    DATA transformations only; no table is defined in one.

    setup_database.sql is written to be idempotent - CREATE TABLE IF NOT
    EXISTS for tables, information_schema-guarded ALTERs for columns and
    keys - so applying it to an up-to-date database is a no-op. Verified
    over three consecutive applications producing byte-identical schemas.

    It is also strictly additive, so this can never be the step that loses
    data. Removals are separate numbered destructive migrations that an
    admin opts in to.

    Returns (ok, message). ok=False means the gateway must NOT serve.
    """
    path = os.path.join(base_dir, SCHEMA_FILENAME)
    if not os.path.exists(path):
        msg = (
            f"{SCHEMA_FILENAME} is MISSING from {base_dir}. This file is the "
            f"schema; without it the gateway cannot know the database is "
            f"correctly shaped. Restore it from the setup kit and restart."
        )
        print(f"[SCHEMA] REFUSING TO START - {msg}")
        return False, msg

    with open(path, "r", encoding="utf-8") as fh:
        sql = fh.read()

    # The schema file must never contain destructive work. Checked rather
    # than trusted: it runs unattended on every boot, so a DROP landing in
    # here by accident would execute on every admin's database with no
    # backup and no prompt. This is the one guard that cannot be opted out
    # of with a flag.
    if _DESTRUCTIVE.search(_strip_sql_comments(sql)):
        msg = (
            f"{SCHEMA_FILENAME} contains DROP/DELETE/TRUNCATE. The schema file "
            f"is applied automatically on EVERY start and must be additive "
            f"only. Move the destructive step into a numbered migration, which "
            f"an admin applies deliberately with --allow-destructive."
        )
        print(f"[SCHEMA] REFUSING TO START - {msg}")
        return False, msg

    try:
        _run_sql(conn, sql)
    except mysql.connector.Error as err:
        msg = f"{SCHEMA_FILENAME} FAILED: {err}"
        print(f"[SCHEMA] {msg}")
        print("[SCHEMA] Refusing to serve against a schema of unknown shape.")
        print("[SCHEMA] Nothing was removed - the file is additive - so the")
        print("[SCHEMA] database is unchanged apart from any statement that")
        print("[SCHEMA] already succeeded, and every one of those is a no-op")
        print("[SCHEMA] on the next attempt. Fix the cause and restart.")
        return False, msg

    # ---- the one shape CREATE TABLE IF NOT EXISTS cannot fix -----------
    ok, msg = _verify_player_data_key(conn)
    if not ok:
        return False, msg

    print(f"[SCHEMA] {SCHEMA_FILENAME} applied (idempotent; no-op when current).")
    return True, "schema applied"


def _verify_player_data_key(conn):
    """Refuse to run against a player_data carrying a PRE-RELEASE key.

    CREATE TABLE IF NOT EXISTS does nothing to a table that already
    exists, so a player_data built by a pre-release build keeps its old
    primary key and the schema file cannot correct it.

    Re-keying it is genuinely destructive - the old key
    (player_uid, hive_id, server_id, namespace) and the new one
    (player_uid, hive_id, share_group, namespace, scope_map) can collide,
    and collapsing two rows into one loses whichever loses the tie. So it
    is deliberately NOT attempted automatically.

    This costs nothing in the field: player_data has never shipped. The
    released gateway is 0.7.1 and its schema has no such table - verified
    against the published database. Only a development box can reach this,
    and the fix there is to drop the table and let the schema file rebuild
    it.

    What matters is that a wrong key must never be used SILENTLY. Reading
    or writing gear against the old key would resolve the wrong row, which
    presents to a player as their gear vanishing.
    """
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM information_schema.TABLES
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_data'
            """
        )
        exists = int(cur.fetchone()[0])
        if not exists:
            cur.close()
            return True, "player_data absent"

        cur.execute(
            """
            SELECT COLUMN_NAME FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_data'
               AND INDEX_NAME = 'PRIMARY'
             ORDER BY SEQ_IN_INDEX
            """
        )
        key = [r[0] for r in cur.fetchall()]
        cur.close()
    except mysql.connector.Error as err:
        return False, f"could not read player_data key: {err}"

    expected = ["player_uid", "hive_id", "share_group", "namespace", "scope_map"]
    if key == expected:
        return True, "player_data key correct"

    msg = (
        f"player_data has a PRE-RELEASE primary key {key}, expected {expected}. "
        f"Gear read or written against the wrong key resolves the wrong row, "
        f"which a player sees as their gear vanishing. This table never shipped, "
        f"so only a development database can be in this state. Fix: back up, then "
        f"DROP TABLE player_data and restart - the schema file rebuilds it correctly "
        f"and migration 0081 refills it from players.inventory."
    )
    print("[SCHEMA] " + "=" * 62)
    # ASCII only. These lines are read on an admin's console, and a
    # Windows console at cp1252 turns a dash like this into a replacement
    # character right in the middle of the sentence they need to act on.
    print("[SCHEMA] REFUSING TO START - player_data has the wrong primary key.")
    print(f"[SCHEMA]   found    : {key}")
    print(f"[SCHEMA]   expected : {expected}")
    print("[SCHEMA]   fix      : back up, DROP TABLE player_data, restart.")
    print("[SCHEMA]              The schema rebuilds it; 0081 refills the gear")
    print("[SCHEMA]              from players.inventory, which is never deleted.")
    print("[SCHEMA] " + "=" * 62)
    return False, msg


def _backup(db_config, out_dir):
    """mysqldump before anything destructive.

    Returns the path on success, None on failure. A None return MUST block
    the destructive migration - never treat a missing backup as 'probably
    fine'.
    """
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, f"{db_config['database']}_premigration_{stamp}.sql")

    cmd = [
        "mysqldump",
        f"--host={db_config['host']}",
        f"--port={db_config['port']}",
        f"--user={db_config['user']}",
        "--single-transaction",
        "--routines",
        "--triggers",
        db_config["database"],
    ]
    env = dict(os.environ)
    # Password via env, never argv - argv is world-readable in a process list.
    env["MYSQL_PWD"] = db_config["password"]

    try:
        with open(path, "wb") as fh:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, env=env, timeout=900)
    except FileNotFoundError:
        print("[MIGRATE] mysqldump not found on PATH - cannot back up, so destructive migrations are BLOCKED.")
        return None
    except subprocess.TimeoutExpired:
        print("[MIGRATE] mysqldump timed out - destructive migrations BLOCKED.")
        return None
    except Exception as err:
        print(f"[MIGRATE] backup failed ({err}) - destructive migrations BLOCKED.")
        return None

    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        print(f"[MIGRATE] mysqldump exited {proc.returncode}: {detail}")
        print("[MIGRATE] Backup FAILED - destructive migrations BLOCKED.")
        return None

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        print("[MIGRATE] Backup file is empty - destructive migrations BLOCKED.")
        return None

    print(f"[MIGRATE] Backup written: {path} ({os.path.getsize(path)} bytes)")
    return path


def current_schema_version(conn):
    """Highest applied version, or 0. Reported in /api/ping so an admin can
    see mod / gateway / schema versions together without leaving the game."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
        row = cur.fetchone()
        cur.close()
        return int(row[0]) if row else 0
    except mysql.connector.Error:
        return 0


def run_migrations(conn, db_config, gateway_version, allow_destructive=False, base_dir=None):
    """Bring the database up to date.

    Returns (ok, applied_count, message). ok=False means the gateway must
    NOT serve traffic.
    """
    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))

    # ---- STEP 1: THE SCHEMA, always, before anything else ---------------
    # setup_database.sql defines every table. It is idempotent and additive,
    # so this is a no-op on a current database and the upgrade path on an
    # older one. Running it unconditionally is what guarantees a fresh
    # install and an upgraded install end up identical. See apply_schema().
    schema_ok, schema_msg = apply_schema(conn, base_dir)
    if not schema_ok:
        return False, 0, schema_msg

    # ---- STEP 2: numbered DATA migrations -------------------------------
    # These carry data transformations and deliberate removals ONLY. No
    # table is defined here; that is the schema file's job, and splitting
    # the two is what stopped them drifting apart.
    migrations_dir = os.path.join(base_dir, MIGRATIONS_DIRNAME)

    files = _discover(migrations_dir)
    if not files:
        print("[MIGRATE] No data migrations pending; schema is current.")
        return True, 0, "schema applied; no data migrations"

    _ensure_ledger(conn)
    applied = _applied_versions(conn)

    # ---- downgrade guard -------------------------------------------------
    highest_shipped = max(v for v, _, _ in files)
    highest_applied = max(applied) if applied else 0
    if highest_applied > highest_shipped:
        msg = (
            f"database schema is version {highest_applied} but this gateway only ships "
            f"up to {highest_shipped}. The gateway has been rolled back further than the "
            f"database. Refusing to start: an older gateway writing a newer schema "
            f"corrupts data quietly. Update the gateway, or restore a matching backup."
        )
        print(f"[MIGRATE] REFUSING TO START - {msg}")
        return False, 0, msg

    pending = [row for row in files if row[0] not in applied]
    if not pending:
        print(f"[MIGRATE] Schema up to date (version {highest_applied}).")
        return True, 0, f"up to date at {highest_applied}"

    print(f"[MIGRATE] {len(pending)} migration(s) pending; schema is at {highest_applied}.")

    # A backup is taken ONCE, lazily, the first time a destructive migration
    # is reached - not on every boot, and not when everything is additive.
    backup_done = False
    applied_count = 0
    held = None  # (version, name, reason, remedy) - see the return below

    for version, name, path in pending:
        with open(path, "r", encoding="utf-8") as fh:
            sql = fh.read()

        destructive = bool(_DESTRUCTIVE.search(_strip_sql_comments(sql)))

        if destructive:
            if not allow_destructive:
                print(f"[MIGRATE] {version:04d}_{name} is DESTRUCTIVE and was HELD.")
                print("[MIGRATE]   It drops or deletes data, so it is never applied unattended.")
                print("[MIGRATE]   Everything after it is held too, so migrations stay in order.")
                held = (
                    version, name,
                    "it removes data and destructive migrations are never applied unattended",
                    "python gateway.py --allow-destructive   (or set MIGRATE_ALLOW_DESTRUCTIVE=1)",
                )
                break

            if not backup_done:
                backup_path = _backup(db_config, os.path.join(base_dir, "backups"))
                if not backup_path:
                    print(f"[MIGRATE] {version:04d}_{name} HELD - destructive work requires a backup and none was taken.")
                    held = (
                        version, name,
                        "it removes data and the safety backup could not be taken",
                        "make mysqldump available on PATH and writable to the backups/ folder, then restart",
                    )
                    break
                backup_done = True

        print(f"[MIGRATE] applying {version:04d}_{name}{' [DESTRUCTIVE]' if destructive else ''} ...")
        try:
            _run_sql(conn, sql)
        except mysql.connector.Error as err:
            # Deliberately NOT recorded, so it retries next boot. This is safe
            # only because migrations are idempotent - see the module header.
            msg = f"migration {version:04d}_{name} FAILED: {err}"
            print(f"[MIGRATE] {msg}")
            print("[MIGRATE] Not recorded - it will retry on the next start. Refusing to serve.")
            return False, applied_count, msg

        _record(conn, version, name, gateway_version)
        applied_count += 1
        print(f"[MIGRATE]   ok -> schema now at {version}")

    final = current_schema_version(conn)

    # ---- A HELD MIGRATION IS A FAILURE, NOT A SUCCESS -------------------
    # This used to `break` out of the loop and fall straight into the
    # success return below, so the caller was told everything was fine and
    # the gateway started NORMALLY against a schema that was known to be
    # out of date. Nothing surfaced to the admin. A half-upgraded database
    # serving a mod that expects the new shape is the worst outcome
    # available here - worse than refusing to start, because it is silent.
    #
    # The message names the migration, why it stopped, and the exact
    # command that applies it. "Refusing to start" on its own is a support
    # ticket; with the remedy attached it is a thirty-second fix.
    if held:
        version, name, reason, remedy = held
        msg = (
            f"migration {version:04d}_{name} was HELD because {reason}. "
            f"The database is at version {final} and the gateway expects "
            f"everything through {max(v for v, _, _ in files):04d}. "
            f"To apply it:  {remedy}"
        )
        print("[MIGRATE] " + "=" * 62)
        print("[MIGRATE] REFUSING TO START - schema is INCOMPLETE.")
        print(f"[MIGRATE]   held migration : {version:04d}_{name}")
        print(f"[MIGRATE]   reason         : {reason}")
        print(f"[MIGRATE]   to apply it    : {remedy}")
        print(f"[MIGRATE]   applied so far : {applied_count}; schema now at {final}")
        print("[MIGRATE] Serving against a half-upgraded schema is how a")
        print("[MIGRATE] rollout turns into data loss, so the gateway stops here.")
        print("[MIGRATE] " + "=" * 62)
        return False, applied_count, msg

    print(f"[MIGRATE] Done. {applied_count} applied; schema version {final}.")
    return True, applied_count, f"applied {applied_count}, now at {final}"
