-- ============================================================
-- Migration 0086 - hf_bases, hf_base_access, placement grouping
-- Created 2026-08-22.
--
-- Player base ownership and door access.
--
-- ACCESS BELONGS TO A BASE, NOT A DOOR. Re-typing a code at every door is
-- miserable, and an owner wants one place to change it.
--
-- access_code_hash IS A SECRET AND NEVER LEAVES THE SERVER. No list or read
-- endpoint may select it. Enfusion replicates component state to clients, so
-- a code that reached the mod could be read by every player. Verification is
-- a dedicated endpoint that returns only a boolean and writes the grant
-- server-side.
--
-- TWO LOCKS, NOT ONE - the lesson HFVehicleLockRegistry already paid for:
-- an owner-keyed lock that ALSO extends lifetime is a denial exploit (lock
-- a town's vehicles, dump them, nobody can use them and they still eat the
-- budget). So access_mode decides who may open, last_touched_at decides how
-- long it lives, and locking never touches the second one.
--
-- base_id goes onto hf_placements NOW even though nothing uses it yet:
-- backfilling a grouping key onto placements already in the wild is far
-- worse than carrying an unused nullable column.
--
-- APPLIED AUTOMATICALLY by the gateway on startup (migrate.py).
-- Safe to re-run: MySQL implicitly commits DDL, so a migration and its
-- ledger row cannot be atomic. Idempotency is what makes a retry safe.
-- ============================================================

USE wastelandz;

CREATE TABLE IF NOT EXISTS hf_bases (
  id                BIGINT       NOT NULL AUTO_INCREMENT,
  hive_id           VARCHAR(64)  NOT NULL DEFAULT 'default',
  server_id         VARCHAR(64)  NOT NULL,
  map_name          VARCHAR(64)  NOT NULL,
  owner_uid         VARCHAR(64)  NOT NULL,
  display_name      VARCHAR(64),
  access_mode       TINYINT      NOT NULL DEFAULT 0,
  access_code_hash  VARCHAR(128),
  created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_touched_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP,
  is_active         TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  KEY idx_owner (owner_uid, hive_id),
  KEY idx_place (hive_id, server_id, map_name, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hf_base_access (
  base_id     BIGINT      NOT NULL,
  player_uid  VARCHAR(64) NOT NULL,
  granted_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  granted_by  VARCHAR(64),
  PRIMARY KEY (base_id, player_uid),
  KEY idx_player (player_uid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hf_placements' AND COLUMN_NAME = 'base_id');
SET @ddl = IF(@c = 0,
              'ALTER TABLE hf_placements ADD COLUMN base_id BIGINT DEFAULT NULL',
              'SELECT "base_id already present" AS msg');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hf_placements' AND COLUMN_NAME = 'meta');
SET @ddl = IF(@c = 0,
              'ALTER TABLE hf_placements ADD COLUMN meta JSON DEFAULT NULL',
              'SELECT "meta already present" AS msg');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
