-- ============================================================
-- Migration 0060 — Player Marker Preferences
-- Created 2026-05-27.
--
-- Stores per-player team-marker UI preferences so a player's marker
-- picks (icon, size, visibility, range, group filter, vehicle swap)
-- follow them across servers via their UID.
--
-- Cross-server by design — there is NO server_id filter on this
-- table. A player's preferred dot size is the same on every HF
-- server. Player_uid is the primary key, one row per UID.
--
-- Run once on existing gateways:
--
--     mysql -u wastelandz -p wastelandz < migrations/0060_marker_prefs.sql
--
-- Safe to re-run — uses IF NOT EXISTS.
-- ============================================================

USE wastelandz;

CREATE TABLE IF NOT EXISTS player_marker_prefs (
  player_uid          VARCHAR(64) NOT NULL PRIMARY KEY,
  icon_idx            INT         NOT NULL DEFAULT 4,
  icon_size_px        INT         NOT NULL DEFAULT 48,
  marker_range_m      INT         NOT NULL DEFAULT 5000,
  markers_enabled     TINYINT(1)  NOT NULL DEFAULT 1,
  names_enabled       TINYINT(1)  NOT NULL DEFAULT 1,
  group_only          TINYINT(1)  NOT NULL DEFAULT 0,
  auto_vehicle_swap   TINYINT(1)  NOT NULL DEFAULT 1,
  updated_at          TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
