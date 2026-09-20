-- ============================================================
-- Migration 0050 — Money Drops Phase 2
-- Created 2026-05-17.
--
-- Adds the money_drops table for DB-backed money pickup entities
-- (death drops + /drop player command). Drops are session-only —
-- the server boot-wipes all rows for the current server_id + map_name
-- on startup; they do NOT restore across restarts. Persistence here
-- is for in-session crash recovery + admin audit + race-condition
-- protection during async insert.
--
-- Run once on existing servers:
--
--     mysql -u wastelandz -p wastelandz < migrations/0050_money_drops.sql
--
-- Safe to re-run — uses IF NOT EXISTS.
--
-- Design reference: HF_WastelandZ/docs/design/MONEY_PIPELINE.md §3.6.2
-- ============================================================

USE wastelandz;

CREATE TABLE IF NOT EXISTS money_drops (
  id            BIGINT       AUTO_INCREMENT PRIMARY KEY,
  server_id     VARCHAR(64)  NOT NULL,
  map_name      VARCHAR(64)  NOT NULL,
  pos_x         FLOAT        NOT NULL,
  pos_y         FLOAT        NOT NULL,
  pos_z         FLOAT        NOT NULL,
  amount        INT          NOT NULL,
  drop_source   VARCHAR(16)  NOT NULL DEFAULT 'death',   -- 'death' | 'player_drop'
  dropper_uid   VARCHAR(64)  DEFAULT '',                 -- audit; empty when no player owner
  dropper_name  VARCHAR(128) DEFAULT '',                 -- audit
  created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
  expires_at    DATETIME     NOT NULL,
  INDEX idx_server_map (server_id, map_name),
  INDEX idx_expires (expires_at)
) ENGINE=InnoDB;

SELECT 'Migration 0050 applied — money_drops ready.' AS status;
SHOW COLUMNS FROM money_drops;
