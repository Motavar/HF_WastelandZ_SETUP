-- ============================================================
-- Migration 0087 - player_data.payload JSON -> MEDIUMTEXT  (URGENT FIX)
-- Created 2026-08-22.
--
-- WHAT BROKE
-- 0080 declared payload as JSON to get write-time validation. MySQL
-- NORMALISES a JSON column: it re-emits with a space after every colon
-- and SORTS object keys alphabetically. So what the mod wrote as
--     [{"p":"{BE19...}","l":"body:LoadoutHeadCoverArea","o":"..."}]
-- came back as
--     [{"l": "body:LoadoutHeadCoverArea", "o": "...", "p": "{BE19...}"}]
--
-- The mod parses this by hand and is whitespace- and order-sensitive.
-- Its format probe looks for the literal "l":" with NO space:
--     isPositionalFormat = FindSubstringFrom(json, "\"l\":\"", 0) >= 0
-- which never matched, so every restore fell through to the legacy
-- parser and returned "0 restored, 0 failed". Players spawned with no
-- headgear, no boots and no backpack.
--
-- Nothing was LOST - players.inventory still holds the original text,
-- untouched, because the legacy column is still written this release
-- exactly so a rollback is possible. This migration puts the payload
-- back into a byte-preserving column and re-seeds it from that
-- original.
--
-- WHAT WE GIVE UP: JSON validation on write and JSON_TABLE queries over
-- the payload. Correctness wins - the mod's parser is the real consumer
-- and it needs the bytes it wrote. hive_servers.addon_list stays JSON;
-- only the gateway reads that, and it round-trips through a real JSON
-- parser rather than a substring scan.
--
-- APPLIED AUTOMATICALLY by the gateway on startup (migrate.py).
-- Not flagged destructive: MODIFY changes a type, it drops no data.
-- ============================================================

USE wastelandz;

-- 1. Byte-preserving column. MEDIUMTEXT keeps exactly what is written.
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_data'
             AND COLUMN_NAME = 'payload' AND DATA_TYPE = 'json');
SET @ddl = IF(@c = 1,
              'ALTER TABLE player_data MODIFY payload MEDIUMTEXT NOT NULL',
              'SELECT "payload already MEDIUMTEXT" AS msg');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2. Re-seed the mangled rows from the untouched original.
--
-- Overwrites on purpose - unlike the 0081 backfill, which fills gaps
-- only. Every inventory payload written while the column was JSON is
-- unreadable by the mod, so keeping it would preserve nothing but the
-- corruption. players.inventory is the pre-migration original and is
-- still byte-exact.
--
-- Restricted to rows that actually look normalised ('", "' only appears
-- in MySQL's re-emitted form, never in what the mod writes), so a row
-- already saved correctly after this migration is left alone.
UPDATE player_data d
  JOIN players p
    ON p.player_uid = d.player_uid AND p.hive_id = d.hive_id
   SET d.payload = p.inventory
 WHERE d.namespace = 'inventory'
   AND p.inventory IS NOT NULL
   AND p.inventory <> ''
   AND p.inventory <> '[]'
   AND d.payload LIKE '%", "%';
