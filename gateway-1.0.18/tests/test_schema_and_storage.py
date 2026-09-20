"""
Schema convergence + namespaced storage tests.

WHAT THIS PROVES, AND WHY IT EXISTS
-----------------------------------
The schema used to be defined in TWO places - setup_database.sql for a
fresh install, and migrations/*.sql for an upgrade - and they drifted.
player_marker_prefs ended up utf8mb4_unicode_ci when created fresh and
utf8mb4_0900_ai_ci when created by a migration that omitted a COLLATE
clause. The visible consequence was a hard `ERROR 1267 Illegal mix of
collations` on any join between that table and players: a query that
PASSES on a developer's fresh database and FAILS on every server in the
field.

setup_database.sql is now the single source and is applied on every
start, so both paths execute the same SQL. THIS TEST IS WHAT KEEPS THAT
TRUE. It builds a database both ways and diffs information_schema.

    Any difference is a defect, not a curiosity.

RUNNING IT
----------
    python tests/test_schema_and_storage.py --i-know-this-wipes-the-db

*** IT WIPES EVERY TABLE IN THE CONFIGURED DATABASE. ***

Point config.py at a scratch database first, or accept that the one it
is pointed at will be emptied. The flag is required precisely so this
cannot be run by reflex against something that matters. It also refuses
outright if the database contains rows that do not look like fixture
data - see _refuse_if_real_data().
"""

import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GW = os.path.dirname(HERE)
sys.path.insert(0, GW)

# ----------------------------------------------------------------------
# config.py is what tells these tests which database to talk to, and it is
# NEVER in the kit - it holds your database password and gateway key, so it
# is deliberately not distributed. Run these from your RUNNING gateway
# folder (the one the service actually uses), not from the downloaded kit.
#
# Python's own ModuleNotFoundError does not explain any of that, so say it.
# ----------------------------------------------------------------------
if not os.path.exists(os.path.join(GW, "config.py")):
    raise SystemExit(
        "\n  No config.py found in:\n    " + GW + "\n"
        "\n  These tests read your database settings from config.py, which is"
        "\n  never shipped in the kit - it holds your password and gateway key."
        "\n"
        "\n  Run them from your RUNNING gateway folder instead, e.g.:"
        "\n    cd /opt/wastelandz-gateway   (Linux)"
        "\n    cd C:\\wastelandz-gateway    (Windows)"
        "\n    python tests/test_endpoints.py"
        "\n"
        "\n  If you only want to read the tests rather than run them, that is"
        "\n  what they are shipped for - no config.py needed.\n"
    )

import config      # noqa: E402
import migrate     # noqa: E402
import mysql.connector  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "published_0_7_1_schema.sql")
FIXTURE_OLD = os.path.join(HERE, "fixtures", "pre_0_7_0_schema.sql")
SCHEMA = os.path.join(GW, "setup_database.sql")

DB = {
    "host": config.DB_HOST, "port": config.DB_PORT, "user": config.DB_USER,
    "password": config.DB_PASSWORD, "database": config.DB_NAME,
}

PASS = FAIL = 0


def ok(label):
    global PASS
    PASS += 1
    print(f"  PASS  {label}")


def bad(label, detail=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}")
    if detail:
        print("        " + detail.replace("\n", "\n        "))


def check(label, got, want):
    if got == want:
        ok(label)
    else:
        bad(label, f"got  {got!r}\nwant {want!r}")


def connect():
    return mysql.connector.connect(**DB)


def _refuse_if_real_data():
    """Second interlock: never wipe a database holding real players.

    The --i-know-this-wipes-the-db flag guards against running this by
    reflex. This guards against running it deliberately against the
    WRONG database, which is the mistake that actually costs something.
    """
    try:
        conn = connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'players'", (DB["database"],)
        )
        if not cur.fetchone()[0]:
            conn.close()
            return
        cur.execute("SELECT COUNT(*) FROM players WHERE player_uid NOT LIKE 'TESTFIX-%'")
        real = int(cur.fetchone()[0])
        conn.close()
    except mysql.connector.Error:
        return  # nothing readable to protect

    if real:
        raise SystemExit(
            f"\nREFUSING TO RUN: database '{DB['database']}' holds {real} player row(s)\n"
            f"that are not fixture data. This test WIPES every table.\n"
            f"Point config.py at a scratch database and run it again.\n"
        )


def wipe():
    conn = connect()
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                (DB["database"],))
    for (t,) in list(cur.fetchall()):
        cur.execute(f"DROP TABLE IF EXISTS `{t}`")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()
    conn.close()


def load_sql(path):
    env = dict(os.environ)
    env["MYSQL_PWD"] = DB["password"]
    cmd = ["mysql", f"--host={DB['host']}", f"--port={DB['port']}",
           f"--user={DB['user']}", DB["database"]]
    with open(path, "rb") as fh:
        proc = subprocess.run(cmd, stdin=fh, stderr=subprocess.PIPE, env=env)
    if proc.returncode != 0:
        raise SystemExit(f"loading {path} failed: {proc.stderr.decode('utf-8','replace')}")


def start_gateway():
    """Exactly what gateway.py does at startup."""
    conn = connect()
    result = migrate.run_migrations(conn, DB, "TEST")
    conn.close()
    return result


def snapshot():
    """Normalised schema: columns, indexes, table collations.

    schema_migrations rows legitimately differ between a fresh install
    and an upgrade - that is bookkeeping, not schema - so the table's
    CONTENT is not compared, only its shape, like any other table.
    """
    conn = connect()
    cur = conn.cursor()
    lines = []
    cur.execute("""SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,
                          COALESCE(COLUMN_DEFAULT,'<none>'), COALESCE(COLLATION_NAME,'-'), EXTRA
                     FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s
                    ORDER BY TABLE_NAME, COLUMN_NAME""", (DB["database"],))
    lines += ["COL " + " | ".join(str(x) for x in r) for r in cur.fetchall()]
    cur.execute("""SELECT TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME, NON_UNIQUE
                     FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s
                    ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX""", (DB["database"],))
    lines += ["IDX " + " | ".join(str(x) for x in r) for r in cur.fetchall()]
    cur.execute("""SELECT TABLE_NAME, ENGINE, TABLE_COLLATION
                     FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s
                    ORDER BY TABLE_NAME""", (DB["database"],))
    lines += ["TBL " + " | ".join(str(x) for x in r) for r in cur.fetchall()]
    conn.close()
    return lines


def scalar(sql, args=()):
    conn = connect()
    cur = conn.cursor()
    cur.execute(sql, args)
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# ======================================================================
def main():
    if "--i-know-this-wipes-the-db" not in sys.argv:
        raise SystemExit(__doc__)
    _refuse_if_real_data()

    print("=" * 70)
    print(" SCHEMA CONVERGENCE + NAMESPACED STORAGE")
    print(f" database: {DB['database']} on {DB['host']}:{DB['port']}")
    print("=" * 70)

    # -- 1. fresh install: empty database, start the gateway ------------
    print("\n-- 1. Fresh install (empty database, gateway does the rest) --")
    wipe()
    okk, _, msg = start_gateway()
    check("gateway started", okk, True)
    fresh = snapshot()
    check("all tables created",
          scalar("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s",
                 (DB["database"],)), 15)

    # -- 2. upgrade from the published 0.7.1 shape ---------------------
    print("\n-- 2. Upgrade from a published 0.7.1 database, unattended --")
    wipe()
    load_sql(FIXTURE)
    okk, _, msg = start_gateway()
    check("gateway started with no flags", okk, True)
    upgraded = snapshot()

    # -- 2b. the OLDEST format anyone could still be on ----------------
    # Pre-0.7.0: no hive_id anywhere, and `players` keyed
    # (player_uid, server_id) so money was PER SERVER. The 2026-06-30
    # note told admins to start fresh at 0.7.0, so almost nobody is here
    # - but the alternative to converting it was failing with "Unknown
    # column 'p.hive_id'", which tells an admin nothing.
    print("\n-- 2b. Upgrade from the OLDEST format (pre-0.7.0), unattended --")
    wipe()
    load_sql(FIXTURE_OLD)
    okk, _, msg = start_gateway()
    check("gateway started with no flags", okk, True)
    check("money survived the re-key",
          scalar("SELECT money FROM players WHERE player_uid='TESTFIX-OLD-0001'"), 4242)
    check("bank survived the re-key",
          scalar("SELECT bank FROM players WHERE player_uid='TESTFIX-OLD-0001'"), 8484)
    check("players re-keyed to (player_uid, hive_id)",
          scalar("""SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)
                      FROM information_schema.STATISTICS
                     WHERE TABLE_SCHEMA=%s AND TABLE_NAME='players'
                       AND INDEX_NAME='PRIMARY'""", (DB["database"],)),
          "player_uid,hive_id")
    # Compared as a RANGE, not an exact value: pos_x is a FLOAT, so the
    # stored 100.5 does not round-trip to an exact decimal and ROUND()
    # on it is not worth asserting against. What matters is that the
    # position moved from `players` to `player_sessions` at all.
    _px = scalar("SELECT pos_x FROM player_sessions WHERE player_uid='TESTFIX-OLD-0001'")
    check("last-known position carried into player_sessions",
          _px is not None and 100.0 <= float(_px) <= 101.0, True)
    check("gear copied into the namespace",
          scalar("SELECT COUNT(*) FROM player_data "
                 "WHERE player_uid='TESTFIX-OLD-0001' AND namespace='inventory'"), 1)
    # These are the columns whose absence made an old database start
    # cleanly and then fail at runtime. They are QUERIED, not decorative.
    for tbl in ("player_stats_daily", "transactions"):
        check(f"{tbl}.hive_id added",
              scalar("""SELECT COUNT(*) FROM information_schema.COLUMNS
                         WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
                           AND COLUMN_NAME='hive_id'""", (DB["database"], tbl)), 1)
    try:
        scalar("SELECT COUNT(*) FROM player_stats_daily WHERE hive_id='default'")
        scalar("SELECT COUNT(*) FROM transactions WHERE hive_id='default'")
        ok("the queries that used to fail now run")
    except mysql.connector.Error as err:
        bad("the queries that used to fail now run", str(err))

    # Re-run the 0.7.1 case so the convergence gate below compares the
    # right two databases.
    wipe()
    load_sql(FIXTURE)
    start_gateway()
    upgraded = snapshot()

    print("\n-- 3. THE CONVERGENCE GATE: fresh == upgraded --")
    if fresh == upgraded:
        ok("schemas are identical")
    else:
        import difflib
        d = "\n".join(list(difflib.unified_diff(fresh, upgraded, "fresh", "upgraded", lineterm=""))[:40])
        bad("SCHEMAS DIVERGE - this is a defect", d)

    # -- 4. the data an admin actually cares about ---------------------
    print("\n-- 4. Player data survives the upgrade --")
    check("wallet preserved",
          scalar("SELECT money FROM players WHERE player_uid='TESTFIX-0000-0001'"), 30850)
    check("bank preserved",
          scalar("SELECT bank FROM players WHERE player_uid='TESTFIX-0000-0001'"), 1761)
    check("large bank preserved",
          scalar("SELECT bank FROM players WHERE player_uid='TESTFIX-0000-0002'"), 251300)
    check("transactions preserved", scalar("SELECT COUNT(*) FROM transactions"), 3)
    check("ATM history preserved",
          scalar("SELECT COUNT(*) FROM transactions WHERE type LIKE 'atm%%'"), 2)
    check("gear copied into the namespace",
          scalar("SELECT LENGTH(payload) FROM player_data "
                 "WHERE player_uid='TESTFIX-0000-0001' AND namespace='inventory'"),
          len('[{"p":"rifle"},{"p":"medkit"}]'))
    check("legacy inventory column KEPT as a rollback path",
          scalar("SELECT COUNT(*) FROM players WHERE inventory <> ''"), 3)
    check("empty inventory got NO namespace row",
          scalar("SELECT COUNT(*) FROM player_data WHERE player_uid='TESTFIX-0000-0003'"), 0)
    check("invalid JSON was SKIPPED, not copied",
          scalar("SELECT COUNT(*) FROM player_data WHERE player_uid='TESTFIX-0000-0004'"), 0)
    check("broken-gear player kept their money",
          scalar("SELECT money FROM players WHERE player_uid='TESTFIX-0000-0004'"), 777)

    # -- 5. restart is a no-op ----------------------------------------
    print("\n-- 5. Restarting the gateway changes nothing --")
    before_rows = scalar("SELECT COUNT(*) FROM player_data")
    for _ in range(3):
        okk, _, _ = start_gateway()
        check("restart ok", okk, True)
    check("schema unchanged after 3 restarts", snapshot(), upgraded)
    check("backfill did not double-write",
          scalar("SELECT COUNT(*) FROM player_data"), before_rows)

    # -- 6. the collation bug that started all this --------------------
    print("\n-- 6. The join that used to throw ERROR 1267 --")
    try:
        scalar("SELECT COUNT(*) FROM players p "
               "JOIN player_marker_prefs m ON p.player_uid = m.player_uid")
        ok("players JOIN player_marker_prefs")
    except mysql.connector.Error as err:
        bad("players JOIN player_marker_prefs", str(err))

    # -- 7. the key ----------------------------------------------------
    print("\n-- 7. player_data key and indexes --")
    check("five-column primary key",
          scalar("""SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)
                      FROM information_schema.STATISTICS
                     WHERE TABLE_SCHEMA=%s AND TABLE_NAME='player_data'
                       AND INDEX_NAME='PRIMARY'""", (DB["database"],)),
          "player_uid,hive_id,share_group,namespace,scope_map")
    check("no redundant secondary indexes",
          scalar("""SELECT COUNT(DISTINCT INDEX_NAME) FROM information_schema.STATISTICS
                     WHERE TABLE_SCHEMA=%s AND TABLE_NAME='player_data'
                       AND INDEX_NAME<>'PRIMARY'""", (DB["database"],)), 0)
    check("no dead recover_* columns on players",
          scalar("""SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA=%s AND TABLE_NAME='players'
                       AND COLUMN_NAME LIKE 'recover%%'""", (DB["database"],)), 0)

    # -- 8. destructive detection -------------------------------------
    print("\n-- 8. Destructive-migration detection --")
    def destructive(path):
        return bool(migrate._DESTRUCTIVE.search(
            migrate._strip_sql_comments(io.open(path, encoding="utf-8").read())))

    check("setup_database.sql is additive (it runs unattended)",
          destructive(SCHEMA), False)
    retired88 = os.path.join(GW, "migrations", "_retired",
                             "0088_player_data_key_by_group.sql")
    if os.path.exists(retired88):
        # The exact migration that slipped through the old guard: it
        # contains `DELETE older FROM ...` (alias breaks DELETE\s+FROM)
        # and `DROP PRIMARY KEY` (not in the old DROP list).
        check("the migration that slipped through is now caught",
              destructive(retired88), True)

    print("\n" + "=" * 70)
    print(f" RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
