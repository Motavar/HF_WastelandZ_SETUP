-- ============================================================
-- Migration 0091 - primary key corrections (hive_id into the key)
-- Created 2026-08-28.
--
-- SPLIT OUT OF 0090 DELIBERATELY. 0090 states in its own header that it
-- is additive and therefore applies unattended, with no flag, no backup
-- gate and no chance of being held. Carrying these ALTERs inside it made
-- that paragraph false and turned the one migration that moves an
-- admin's GEAR across the 7 -> 9 upgrade into a held one. The backfill
-- and the re-key have different risk profiles and belong in different
-- files.
--
-- THIS MIGRATION IS DESTRUCTIVE IN MECHANISM AND NON-LOSSY IN EFFECT.
--
-- Mechanism: a primary key cannot be changed in place. MySQL requires
-- DROP PRIMARY KEY, ADD PRIMARY KEY, and the guard matches the verb. It
-- will hold this migration and require --allow-destructive, which is
-- correct: a false positive costs an admin one flag, a false negative
-- costs data. Do not try to phrase this to slip past the guard.
--
-- Effect: both statements WIDEN a key by adding hive_id. Widening can
-- only SPLIT rows, never merge them. hive_id has been present and
-- NOT NULL DEFAULT 'default' on both tables since the hive model landed,
-- so every existing row already carries a value and maps to exactly one
-- row under the new key. Row counts are identical before and after.
-- Measured on a real database before shipping: player_stats_daily 126
-- rows to 126 distinct under the new key, player_sessions 4 to 4.
--
-- Contrast 0088, which genuinely could discard rows and said so.
--
-- WHAT IT FIXES. hive_id was already a COLUMN on both tables and simply
-- was not in the KEY, so two hives in one database that share a
-- server_id string collided on a single row. server_id is an
-- admin-chosen string; "dev-01" existing in two hives is not exotic.
--
--   player_stats_daily - the collision was SILENT and CUMULATIVE. The
--   endpoint writes with ON DUPLICATE KEY UPDATE, so kills, deaths,
--   playtime, money_earned and money_spent were SUMMED across both hives
--   into one row. hive_id is not in that UPDATE list, so the row also
--   kept whichever hive inserted it first and reported the merged totals
--   under that hive's name.
--
--   player_sessions - the collision landed on position and is_alive,
--   i.e. on where a player is standing and whether they are alive.
--
-- IDEMPOTENT. Each statement is guarded on the CURRENT key shape read
-- from information_schema, so a re-run is a no-op rather than an error.
-- MySQL has no "ALTER TABLE ... DROP PRIMARY KEY IF EXISTS".
-- ============================================================

-- ---- player_stats_daily: (uid, server_id, stat_date)
--                       -> (uid, hive_id, server_id, stat_date) --------
SET @k = (SELECT COUNT(*) FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_stats_daily'
             AND INDEX_NAME = 'PRIMARY'
             AND COLUMN_NAME = 'hive_id');
SET @ddl = IF(@k = 0,
    'ALTER TABLE player_stats_daily DROP PRIMARY KEY, ADD PRIMARY KEY (player_uid, hive_id, server_id, stat_date)',
    'SELECT "player_stats_daily already keyed by hive" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- player_sessions: (uid, server_id)
--                    -> (uid, hive_id, server_id) ----------------------
SET @k = (SELECT COUNT(*) FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_sessions'
             AND INDEX_NAME = 'PRIMARY'
             AND COLUMN_NAME = 'hive_id');
SET @ddl = IF(@k = 0,
    'ALTER TABLE player_sessions DROP PRIMARY KEY, ADD PRIMARY KEY (player_uid, hive_id, server_id)',
    'SELECT "player_sessions already keyed by hive" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;
