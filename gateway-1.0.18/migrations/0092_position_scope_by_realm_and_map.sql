-- ============================================================
-- Migration 0092 - position is scoped per REALM and per MAP
-- Created 2026-08-29.
--
-- @auto-apply-nonlossy
-- @verify-rowcount: player_sessions
--
-- APPLIES WITHOUT --allow-destructive, and the runner does not take that
-- on trust. It still takes a backup first, and it counts player_sessions
-- before and after; if a single row is lost the migration is not
-- recorded, the gateway refuses to serve, and the message names the
-- backup. See the NON-LOSSY OPT-IN block in migrate.py.
--
-- Why this qualifies where 0091 did not bother to claim it: 0091 was
-- written before the opt-in existed and says so in its own header. The
-- reasoning is identical - both WIDEN a key.
--
-- DESTRUCTIVE IN MECHANISM, NON-LOSSY IN EFFECT.
--
--   Mechanism: MySQL cannot change a primary key in place. It needs
--   DROP PRIMARY KEY, ADD PRIMARY KEY, and the guard matches the verb.
--   Do not rephrase this to slip past that guard; the guard is the only
--   thing standing between an admin and a silent DELETE in some future
--   file. Opt in and let the runner VERIFY instead.
--
--   Effect: the key gains share_group and map_name. Widening can only
--   SPLIT rows apart, never merge them. Both columns are NOT NULL with
--   defaults by the time this runs (setup_database.sql adds them, and it
--   runs first on every start), so every existing row already carries a
--   value and maps to exactly one row under the new key.
--
--   MEASURED on the live database before shipping, not asserted:
--   player_sessions 3 rows -> 3 distinct under the new key.
--
-- WHAT IT FIXES
--
-- Gear is keyed per realm on player_data.share_group. Position was keyed
-- (player_uid, hive_id, server_id) only, so:
--
--   * switching gear set kept the OLD realm's position - a player logged
--     out on ALPHA/Eden and arrived on BRAVO/Eden standing where they
--     left ALPHA;
--   * map_name was a COLUMN but not in the KEY, so only ONE position
--     survived per server. Play Arland and the Eden spot was overwritten,
--     and returning to Eden forced a town spawn that should not have
--     been necessary.
--
-- After this, a position is remembered independently per
-- (player, hive, server, realm, map), which is the scope it always
-- described.
--
-- ⚠ THE QUERIES MATTER MORE THAN THIS FILE. hive_id has been in this
-- table's key since 0.9 and appeared in NONE of the gateway's queries
-- for it - not the select, not either insert, not the join - so every
-- row was written as hive 'default' and that widening shipped INERT.
-- Adding columns to a key achieves nothing until every read and write
-- carries them. Fixed in gateway.py in the same commit as this file.
-- ============================================================

-- Idempotent: guarded on the key not already containing share_group, so a
-- re-run is a no-op rather than an error. Written as a prepared statement
-- for the same reason every guard in setup_database.sql is - MySQL has no
-- conditional DDL.
SET @c = (SELECT COUNT(*) FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_sessions'
             AND INDEX_NAME = 'PRIMARY' AND COLUMN_NAME = 'share_group');

SET @ddl = IF(@c = 0,
    'ALTER TABLE player_sessions DROP PRIMARY KEY, ADD PRIMARY KEY (player_uid, hive_id, server_id, share_group, map_name)',
    'SELECT "0092: player_sessions PK already scoped by realm+map" AS msg');

PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;
