# Retired migrations

These twelve files are **kept for history and are never executed.** The
migration runner scans `migrations/` non-recursively and matches
`NNNN_name.sql`, so nothing in this folder is discovered.

## Why they were retired

They defined **tables**. Table definitions now live in exactly one place,
`setup_database.sql`, which is applied on every gateway start — fresh
database or decade-old one alike.

The schema used to live in two places at once: `setup_database.sql` for a
fresh install, and these files for an upgrade. Two definitions that must
agree is a discipline rather than a guarantee, and it lapsed —
`0060_marker_prefs.sql` ends `DEFAULT CHARSET=utf8mb4;` with no `COLLATE`
clause and so inherited the server default, while `setup_database.sql`
named `utf8mb4_unicode_ci` explicitly. A fresh install and an upgraded
one ended up with different collations on `player_marker_prefs`, and any
join to `players` threw `ERROR 1267` on one and not the other.

Running one file against both cases removes that possibility instead of
reducing its odds. `migrations/` now carries **data transformations
only**.

## Why they were kept rather than deleted

They are the written record of how the schema got here, and several carry
reasoning worth reading — particularly `0088`, which explains why gear is
keyed by share group rather than by server.

## Two of them are worth knowing about

**`0070_vehicle_recovery_columns.sql` targets the wrong table.** It adds
`recover_veh_prefab` / `recover_veh_class` / `recover_session_id` to
`players`, while the gateway reads and writes them on `player_sessions`.
Its idempotency guard checks `TABLE_NAME = 'players'` for a column that
lives on `player_sessions`, so the guard always found nothing, always
passed, and the `ALTER` always fired — adding three permanently dead
columns.

It was never caught because the migration runner shipped *after* the last
public release, so on a real published database this file had never once
run. It would have fired for the first time on an admin's upgrade.

> A guard that names the wrong table is worse than no guard: it evaluates
> false every time, so it looks like protection while providing none.

**`0088_player_data_key_by_group.sql` evaded the destructive guard.** The
old pattern was
`DROP\s+(TABLE|COLUMN|DATABASE|INDEX)|TRUNCATE|DELETE\s+FROM`, and this
file contains `DELETE older FROM player_data AS older` — where the table
alias breaks `DELETE\s+FROM` — and `DROP PRIMARY KEY`, which is not in
that `DROP` list. Neither matched, so a migration that **deletes rows and
re-keys a table** was classified additive, ran unattended, and took no
backup, while its own header stated that a backup is always taken.

The guard now matches the verbs — any `DROP`, `TRUNCATE`, `DELETE` or
`REPLACE INTO` — because an allow-list of destructive *spellings* cannot
be complete, and the spelling it misses is the one that costs an admin
their database.

## If you are restoring one of these

Don't. Add the change to `setup_database.sql` instead — as a
`CREATE TABLE IF NOT EXISTS`, or as a guarded `ALTER` in its SCHEMA
UPGRADES section — so the fresh and upgrade paths cannot disagree about
it. `tests/test_schema_and_storage.py` proves they still agree.
