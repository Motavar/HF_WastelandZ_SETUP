"""
============================================================
WastelandZ Gateway — schema migration runner
============================================================
Applies migrations/*.sql on gateway startup so an admin never
runs SQL by hand. Update the mod, update the gateway, restart —
the database catches itself up and logs what it did.

HOW RE-RUNNING IS PREVENTED
  A ledger table, schema_migrations, holds one row per applied
  version. On startup we read the applied set, diff it against the
  files on disk, and run only what is missing. There is no timer and
  no flag to forget to reset — the database itself is the record.

  IMPORTANT, AND THE REASON EVERY MIGRATION MUST STAY IDEMPOTENT:
  MySQL performs an IMPLICIT COMMIT on DDL (CREATE TABLE, ALTER
  TABLE). A migration and its ledger row therefore CANNOT be made
  atomic — that is a MySQL fact, not a design choice. If a migration
  dies halfway, its version is not recorded and it runs again next
  boot. Safety comes from every migration being re-runnable:
      - CREATE TABLE IF NOT EXISTS
      - ADD COLUMN guarded via information_schema + PREPARE
        (see 0070_vehicle_recovery_columns.sql)
      - data backfills written INSERT ... ON DUPLICATE KEY UPDATE
        so a second run fills gaps and never overwrites
  A non-idempotent migration is a bug.

DESTRUCTIVE MIGRATIONS
  Anything containing DROP / TRUNCATE / DELETE FROM is treated as
  destructive. Those NEVER run without a successful mysqldump taken
  first — if the backup fails, the migration is refused. Additive
  work still applies; only the destructive step is held.

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

# Words that mark a migration as destructive. Matched on comment-stripped
# SQL so a mention inside documentation cannot trip the guard.
_DESTRUCTIVE = re.compile(
    r"\b(DROP\s+(TABLE|COLUMN|DATABASE|INDEX)|TRUNCATE|DELETE\s+FROM)\b",
    re.IGNORECASE,
)

_FILENAME = re.compile(r"^(\d{4})_(.+)\.sql$", re.IGNORECASE)


def _strip_sql_comments(sql):
    """Remove -- line comments and /* */ blocks.

    Only used for destructive DETECTION. The SQL actually executed is the
    original text — never the stripped copy — because stripping is a
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
    bootstraps itself — it cannot be recorded in a table that does not
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

    # Drop comment-only fragments — they are not statements and MySQL
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


def _backup(db_config, out_dir):
    """mysqldump before anything destructive.

    Returns the path on success, None on failure. A None return MUST block
    the destructive migration — never treat a missing backup as 'probably
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
    # Password via env, never argv — argv is world-readable in a process list.
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
    migrations_dir = os.path.join(base_dir, MIGRATIONS_DIRNAME)

    files = _discover(migrations_dir)
    if not files:
        print(f"[MIGRATE] No migrations found in {migrations_dir}")
        return True, 0, "no migrations"

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
    # is reached — not on every boot, and not when everything is additive.
    backup_done = False
    applied_count = 0

    for version, name, path in pending:
        with open(path, "r", encoding="utf-8") as fh:
            sql = fh.read()

        destructive = bool(_DESTRUCTIVE.search(_strip_sql_comments(sql)))

        if destructive:
            if not allow_destructive:
                print(f"[MIGRATE] {version:04d}_{name} is DESTRUCTIVE and was SKIPPED.")
                print("[MIGRATE]   It drops or deletes data. Start the gateway with")
                print("[MIGRATE]   --allow-destructive (or MIGRATE_ALLOW_DESTRUCTIVE=1) to apply it.")
                print("[MIGRATE]   Everything after it is held back too, so migrations stay in order.")
                break

            if not backup_done:
                backup_path = _backup(db_config, os.path.join(base_dir, "backups"))
                if not backup_path:
                    print(f"[MIGRATE] {version:04d}_{name} HELD - destructive work requires a backup and none was taken.")
                    break
                backup_done = True

        print(f"[MIGRATE] applying {version:04d}_{name}{' [DESTRUCTIVE]' if destructive else ''} ...")
        try:
            _run_sql(conn, sql)
        except mysql.connector.Error as err:
            # Deliberately NOT recorded, so it retries next boot. This is safe
            # only because migrations are idempotent — see the module header.
            msg = f"migration {version:04d}_{name} FAILED: {err}"
            print(f"[MIGRATE] {msg}")
            print("[MIGRATE] Not recorded - it will retry on the next start. Refusing to serve.")
            return False, applied_count, msg

        _record(conn, version, name, gateway_version)
        applied_count += 1
        print(f"[MIGRATE]   ok -> schema now at {version}")

    final = current_schema_version(conn)
    print(f"[MIGRATE] Done. {applied_count} applied; schema version {final}.")
    return True, applied_count, f"applied {applied_count}, now at {final}"
