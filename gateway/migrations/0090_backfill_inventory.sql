-- ============================================================
-- Migration 0090 - backfill players.inventory -> player_data
-- Created 2026-08-22 as 0081. Renumbered and rewritten 2026-08-25.
--
-- WHY 0090 AND NOT 0081. Twelve pure-schema migrations (0042-0088) were
-- retired when setup_database.sql became the single source of the
-- schema. A development database that had already applied them records
-- version 88 in its ledger, and the downgrade guard reads "ledger newer
-- than any shipped file" as a rollback and refuses to start - which is
-- exactly what it should do, applied to a situation that is not one.
-- Numbering the surviving migration ABOVE the retired range keeps the
-- guard meaningful without weakening it. Caught by running the real
-- development database through the new startup path rather than a
-- rebuilt one.
--
-- THIS IS A DATA MIGRATION, AND THE ONLY KIND THAT BELONGS IN THIS
-- FOLDER. Tables are defined in setup_database.sql, which is applied on
-- every start; migrations here carry data movement only. Splitting the
-- two is what stopped the schema drifting between a fresh install and an
-- upgraded one.
--
-- WHAT IT DOES. Copies each player's existing gear out of the legacy
-- players.inventory column into the 'inventory' namespace. This is the
-- step that carries an upgrading admin's gear across.
--
-- COPIES. NOTHING IS MOVED AND NOTHING IS DELETED. players.inventory
-- stays exactly as it was, so a rollback to the previous gateway is
-- possible for one release. That is also why this migration is additive
-- and therefore applies unattended - no flag, no backup gate, no chance
-- of being held. Removing the legacy column is a separate, deliberate,
-- destructive migration for a later release.
--
-- MONEY AND BANK ARE NOT TOUCHED, HERE OR ANYWHERE. players.money and
-- players.bank are the same columns, of the same type, in the same table,
-- before and after the upgrade. Nothing reads them, moves them or
-- rewrites them. Anything spendable stays a real column so the DATABASE
-- decides affordability atomically -
--     UPDATE players SET money = money - 500 WHERE money >= 500
-- - where affected_rows = 0 IS the insufficient-funds answer. A JSON
-- payload would force read-modify-write, and two overlapping purchases
-- would both read 1200, both write 700, and create 500 from nothing.
--
-- NO BEHAVIOUR CHANGE ON MIGRATION DAY. Every row lands in share_group
-- ALPHA, which is also every server's default, so the whole hive stays in
-- one shared pool exactly as it behaves today. Splitting into other gear
-- sets is opt-in afterwards, and non-destructive in both directions
-- because each group is its own row.
--
-- scope_map is '' - gear is deliberately NOT map-scoped. The same mods on
-- a different map in the same hive and the same group are the same gear.
--
-- map_name is left EMPTY for legacy rows; it is informational only ("last
-- written on") and re-stamps on the player's next save.
--
-- server_id likewise records the last writer for support, and comes from
-- players.current_server_id. COALESCE covers a profile that has never
-- joined one.
--
-- JSON_VALID is the gate: a malformed legacy value is SKIPPED rather than
-- copied. A player whose gear was already corrupt keeps their previous
-- behaviour instead of gaining a broken namespace row.
--
-- ON DUPLICATE KEY UPDATE ... = itself is a DELIBERATE NO-OP that makes a
-- re-run fill gaps ONLY. Without it, running this again months later
-- would overwrite live gear with the stale legacy column. That single
-- clause is what makes this safe to re-run forever.
--
-- APPLIED AUTOMATICALLY by the gateway on startup (migrate.py).
-- ============================================================

INSERT INTO player_data
    (player_uid, hive_id, share_group, namespace, scope_map,
     server_id, map_name, payload, format_ver)
SELECT
    p.player_uid,
    p.hive_id,
    'ALPHA',                                              -- share_group
    'inventory',                                          -- namespace
    '',                                                   -- scope_map: gear is not map-scoped
    COALESCE(NULLIF(p.current_server_id, ''), 'unknown'),  -- informational
    '',                                                   -- informational
    p.inventory,
    1
FROM players p
WHERE p.inventory IS NOT NULL
  AND p.inventory <> ''
  AND p.inventory <> '[]'
  AND JSON_VALID(p.inventory)
ON DUPLICATE KEY UPDATE player_uid = player_data.player_uid;
