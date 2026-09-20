-- ============================================================
-- Migration 0088 - player_data keyed by SHARE GROUP, not by server
-- Created 2026-08-24.
--
-- WHAT WAS WRONG
-- 0080 keyed this table on (player_uid, hive_id, server_id, namespace),
-- with share_group and map_name as ordinary columns, and resolved a read
-- with:
--     WHERE share_group = <mine>
--        OR (server_id = <me> AND (map_name = <my map> OR map_name = ''))
--     ORDER BY updated_at DESC LIMIT 1
--
-- That encodes the wrong idea of what gear belongs to. Gear is per HIVE
-- per SHARED GEAR SET. It is not per server and it is not per map: the
-- same mods on a different map in the same hive and the same group are
-- the same gear, and the map clause above made them resolve as two
-- different things.
--
-- Two consequences, both real:
--
--   1. ONE ROW PER SERVER meant a server could not hold ALPHA gear and
--      BETA gear at the same time. Changing group RELABELLED the single
--      existing row, so ALPHA-earned gear became BETA gear and leaked
--      into every other BETA server's pool - possibly carrying items
--      from mods BETA does not have. Switching back did not bring the
--      old set back, because there was never a second row to return to.
--
--   2. The ORDER BY/LIMIT tie-break meant "whichever server saved most
--      recently wins", which silently shadowed a player's real gear on
--      another server.
--
-- AFTER THIS
-- One row per (player, hive, group, namespace). ALPHA gear lives in the
-- ALPHA row and BETA gear in the BETA row, so switching a server's group
-- is non-destructive and reversible in both directions, and a map change
-- is just a config read. The gateway read becomes a single-row lookup
-- with no ordering and no fallback clause, which removes the whole
-- "which row wins" question rather than answering it.
--
-- server_id and map_name are KEPT as informational columns - "last
-- written by dev-01 on GM_Arland" is useful for support, it just is not
-- identity.
--
-- PRIVATE is unaffected: it resolves to '@private:<server_id>', which is
-- simply another share_group value, so a private server still gets its
-- own row by the same rule with no special case.
--
-- ⚠ THIS ONE CAN DISCARD ROWS. If a hive runs two servers in the SAME
-- group and a player has a row on each, those two rows become one and
-- the older is deleted. That is unavoidable - they are now the same
-- identity - and most-recent-wins is exactly the rule the old ORDER BY
-- already applied at read time, so this changes when the loser is
-- dropped, not which one. Step 1 reports the count before step 2 acts,
-- and migrate.py takes a mysqldump before any migration runs.
--
-- On a single-server hive the count is 0 and nothing is deleted.
-- ============================================================

USE wastelandz;

-- 1. Report what will merge. Shows in the gateway's startup output so an
--    admin sees it happen rather than discovering it later.
SELECT
  (SELECT COUNT(*) FROM player_data)
  - (SELECT COUNT(*) FROM (
        SELECT 1 FROM player_data
         GROUP BY player_uid, hive_id, share_group, namespace
     ) t) AS rows_that_will_merge;

-- 2. Keep the newest row per new identity, drop the rest.
--
-- The self-join tie-breaks on updated_at, then on server_id so the
-- result is deterministic when two rows share a timestamp - without
-- that, a tie would delete BOTH sides of the pair.
DELETE older
  FROM player_data AS older
  JOIN player_data AS newer
    ON  older.player_uid  = newer.player_uid
    AND older.hive_id     = newer.hive_id
    AND older.share_group = newer.share_group
    AND older.namespace   = newer.namespace
    AND ( older.updated_at < newer.updated_at
          OR ( older.updated_at = newer.updated_at
               AND older.server_id > newer.server_id ) );

-- 3. Re-key. Guarded so a re-run is a no-op rather than an error - the
--    ledger already prevents that, but a migration that is safe to run
--    twice is one less way to lose an evening.
SET @already = (
  SELECT COUNT(*) FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = DATABASE()
     AND TABLE_NAME   = 'player_data'
     AND INDEX_NAME   = 'PRIMARY'
     AND COLUMN_NAME  = 'share_group'
);
SET @ddl = IF(@already = 0,
  'ALTER TABLE player_data DROP PRIMARY KEY, ADD PRIMARY KEY (player_uid, hive_id, share_group, namespace)',
  'SELECT "player_data already keyed by share_group" AS msg');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4. server_id is no longer part of the key but is still looked up when
--    support asks "where was this last written". Cheap index, and the
--    old PRIMARY was the only thing covering it before.
SET @idx = (
  SELECT COUNT(*) FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = DATABASE()
     AND TABLE_NAME   = 'player_data'
     AND INDEX_NAME   = 'idx_last_writer'
);
SET @ddl2 = IF(@idx = 0,
  'ALTER TABLE player_data ADD INDEX idx_last_writer (hive_id, server_id, namespace)',
  'SELECT "idx_last_writer already present" AS msg');
PREPARE stmt2 FROM @ddl2; EXECUTE stmt2; DEALLOCATE PREPARE stmt2;
