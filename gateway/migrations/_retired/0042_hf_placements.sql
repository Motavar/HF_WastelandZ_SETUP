-- ============================================================
-- Migration 0042 — HF Carry & Place System
-- Created 2026-05-11.
--
-- Adds the hf_placements table for PLACE-class entities (player
-- builds, admin-positioned fixtures). Run once on existing servers:
--
--     mysql -u wastelandz -p wastelandz < migrations/0042_hf_placements.sql
--
-- Safe to re-run — uses IF NOT EXISTS.
-- ============================================================

USE wastelandz;

CREATE TABLE IF NOT EXISTS hf_placements (
  id             BIGINT        AUTO_INCREMENT PRIMARY KEY,
  map_name       VARCHAR(64)   NOT NULL,
  carry_class    TINYINT       NOT NULL,
  prefab_path    VARCHAR(255)  NOT NULL,
  pos_x          FLOAT         NOT NULL,
  pos_y          FLOAT         NOT NULL,
  pos_z          FLOAT         NOT NULL,
  yaw            FLOAT         NOT NULL DEFAULT 0,
  pitch          FLOAT         NOT NULL DEFAULT 0,
  roll           FLOAT         NOT NULL DEFAULT 0,
  owner_uid      VARCHAR(64)   NOT NULL,
  placed_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_moved_at  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_active      TINYINT(1)    NOT NULL DEFAULT 1,
  INDEX idx_map (map_name),
  INDEX idx_owner (owner_uid),
  INDEX idx_active (is_active)
) ENGINE=InnoDB;

SELECT 'Migration 0042 applied — hf_placements ready.' AS status;
SHOW COLUMNS FROM hf_placements;
