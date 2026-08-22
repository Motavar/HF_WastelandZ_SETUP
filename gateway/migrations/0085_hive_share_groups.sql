-- ============================================================
-- Migration 0085 - hive_share_groups (group descriptions)
-- Created 2026-08-22.
--
-- Labels for the fixed A-Z groups, so ALPHA can read as 'PvE Arland
-- cluster' on every server instead of being a bare codename.
--
-- At most 27 rows per hive (ALPHA..ZULU plus PRIVATE). Group NAMES are a
-- closed vocabulary in the mod, never free text: matching between servers
-- has to be exact, and a typo would split a pool silently - nobody notices
-- until a player loses their gear.
--
-- APPLIED AUTOMATICALLY by the gateway on startup (migrate.py).
-- Safe to re-run: MySQL implicitly commits DDL, so a migration and its
-- ledger row cannot be atomic. Idempotency is what makes a retry safe.
-- ============================================================

USE wastelandz;

CREATE TABLE IF NOT EXISTS hive_share_groups (
  hive_id     VARCHAR(64)  NOT NULL DEFAULT 'default',
  group_name  VARCHAR(32)  NOT NULL,
  description VARCHAR(255),
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                           ON UPDATE CURRENT_TIMESTAMP,
  updated_by  VARCHAR(64),
  PRIMARY KEY (hive_id, group_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
