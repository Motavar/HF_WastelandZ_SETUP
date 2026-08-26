-- ============================================================
-- Migration 0084 - hive_servers (registration + mod compliance)
-- Created 2026-08-22.
--
-- Every server announces itself on startup: map, share groups, mod version
-- and its full addon list. Written by the ping the mod already sends, so
-- this costs no new traffic.
--
-- WHY THE ADDON LIST MATTERS. Gear is stored as prefab paths. On a server
-- missing the owning addon, Resource.Load returns null, the item is dropped
-- at Log tier, and the shrunken payload is written back over the profile -
-- permanent, hive-wide, no warning. This table lets an admin SEE the mod
-- delta before putting a server in a shared gear pool, instead of finding
-- out when a player's rifle disappears.
--
-- addon_hash answers 'do these two match' in one comparison; addon_list
-- makes the difference readable when they do not.
--
-- APPLIED AUTOMATICALLY by the gateway on startup (migrate.py).
-- Safe to re-run: MySQL implicitly commits DDL, so a migration and its
-- ledger row cannot be atomic. Idempotency is what makes a retry safe.
-- ============================================================

USE wastelandz;

CREATE TABLE IF NOT EXISTS hive_servers (
  hive_id         VARCHAR(64)  NOT NULL DEFAULT 'default',
  server_id       VARCHAR(64)  NOT NULL,
  display_name    VARCHAR(128),
  map_name        VARCHAR(64),
  gear_group      VARCHAR(32),
  garage_group    VARCHAR(32),
  mod_version     VARCHAR(32),
  addon_count     INT          NOT NULL DEFAULT 0,
  addon_hash      VARCHAR(64),
  addon_list      JSON,
  players_online  INT          NOT NULL DEFAULT 0,
  boot_session_id VARCHAR(64),
  started_at      DATETIME,
  last_seen       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (hive_id, server_id),
  KEY idx_group (hive_id, gear_group)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
