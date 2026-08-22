-- ============================================================
-- Migration 0081 - backfill players.inventory -> player_data
-- Created 2026-08-22.
--
-- COPIES existing gear into player_data. Nothing is moved and nothing is
-- deleted: players.inventory stays authoritative for one more release so a
-- rollback is possible. Migration 0090 drops it, a release later.
--
-- NO BEHAVIOUR CHANGES ON MIGRATION DAY. Every row lands in share_group
-- ALPHA, which is also every server's default, so the whole hive stays in
-- one shared pool exactly as it behaves today. Splitting is opt-in later.
--
-- map_name is left EMPTY for legacy rows. The read rule treats empty as
-- 'matches any map', the same backward-compatibility trick HFGameMode
-- already uses for positions saved before map tracking existed. Rows
-- re-stamp with a real map on the player's next save.
--
-- server_id comes from players.current_server_id - whichever server last
-- claimed the player. COALESCE covers a profile that has never joined one.
--
-- ON DUPLICATE KEY UPDATE ... = itself is a DELIBERATE NO-OP. It makes a
-- re-run fill gaps only. Without it, running this again months later would
-- overwrite live gear with the stale legacy column.
--
-- APPLIED AUTOMATICALLY by the gateway on startup (migrate.py).
-- Safe to re-run: MySQL implicitly commits DDL, so a migration and its
-- ledger row cannot be atomic. Idempotency is what makes a retry safe.
-- ============================================================

USE wastelandz;

INSERT INTO player_data
    (player_uid, hive_id, server_id, namespace, share_group, map_name, payload, format_ver)
SELECT
    p.player_uid,
    p.hive_id,
    COALESCE(NULLIF(p.current_server_id, ''), 'unknown'),
    'inventory',
    'ALPHA',
    '',
    p.inventory,
    1
FROM players p
WHERE p.inventory IS NOT NULL
  AND p.inventory <> ''
  AND p.inventory <> '[]'
  AND JSON_VALID(p.inventory)
ON DUPLICATE KEY UPDATE player_uid = player_data.player_uid;
