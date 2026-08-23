-- ============================================================
-- Migration 0080 - player_data (namespaced per-scope player state)
-- Created 2026-08-22.
--
-- One row per (player, hive, server, namespace). Replaces the single
-- players.inventory value, which could not hold more than one server's
-- gear no matter how it was read.
--
-- WRITE RULE, ABSOLUTE: a server writes only rows whose server_id is its
-- own (or '@hive'). Every data-loss hazard here came from one server
-- overwriting another's value; that class is now impossible by
-- construction rather than merely guarded.
--
-- payload is JSON so MySQL validates it on write - a malformed inventory
-- is REJECTED and the previous good value survives, which is strictly
-- better than storing garbage.
--
-- share_group + map_name drive the read rule:
--   share_group = mine  OR  (server_id = me AND map_name = my map)
-- The map test stops a server that rotated to a new map (and a new mod
-- set) from handing players gear whose prefabs no longer resolve.
--
-- APPLIED AUTOMATICALLY by the gateway on startup (migrate.py).
-- Safe to re-run: MySQL implicitly commits DDL, so a migration and its
-- ledger row cannot be atomic. Idempotency is what makes a retry safe.
-- ============================================================

USE wastelandz;

CREATE TABLE IF NOT EXISTS player_data (
  player_uid   VARCHAR(64)  NOT NULL,
  hive_id      VARCHAR(64)  NOT NULL DEFAULT 'default',
  server_id    VARCHAR(64)  NOT NULL,
  namespace    VARCHAR(32)  NOT NULL,
  share_group  VARCHAR(32)  NOT NULL DEFAULT 'ALPHA',
  map_name     VARCHAR(64)  NOT NULL DEFAULT '',
  payload      MEDIUMTEXT   NOT NULL,   -- see 0087: JSON normalisation broke the mod parser
  format_ver   INT          NOT NULL DEFAULT 1,
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (player_uid, hive_id, server_id, namespace),
  KEY idx_ns    (hive_id, namespace, share_group),
  KEY idx_owner (player_uid, hive_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
