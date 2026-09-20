-- ============================================================
-- Migration 0070 — Vehicle recovery (/recover) token columns
-- Created 2026-06-06.
--
-- Adds three columns to `players` backing the /recover command:
-- a player who was the driver/pilot of a vehicle when the server
-- went down can re-spawn that vehicle once after a restart.
--
--   recover_veh_prefab  the vehicle prefab to re-spawn
--   recover_veh_class   GROUND / HELI / PLANE / BOAT
--   recover_session_id  the HFServerSession id the driver got in
--                       during (anti-dupe: /recover is only honored
--                       when this != the current boot session).
--
-- Run once on existing gateways:
--
--     mysql -u wastelandz -p wastelandz < migrations/0070_vehicle_recovery_columns.sql
--
-- New installs created from setup_database.sql post-migration get
-- these columns for free (already in the base players CREATE TABLE).
--
-- Idempotency: ADD COLUMN IF NOT EXISTS is not portable pre-8.0.29,
-- so each column is guarded via information_schema + a prepared
-- statement. Safe to re-run.
-- ============================================================

USE wastelandz;

-- recover_veh_prefab
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME = 'players'
                   AND COLUMN_NAME = 'recover_veh_prefab');
SET @ddl = IF(@col_exists = 0,
              'ALTER TABLE players ADD COLUMN recover_veh_prefab VARCHAR(256) DEFAULT NULL',
              'SELECT "recover_veh_prefab already present" AS msg');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- recover_veh_class
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME = 'players'
                   AND COLUMN_NAME = 'recover_veh_class');
SET @ddl = IF(@col_exists = 0,
              'ALTER TABLE players ADD COLUMN recover_veh_class VARCHAR(16) DEFAULT NULL',
              'SELECT "recover_veh_class already present" AS msg');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- recover_session_id
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME = 'players'
                   AND COLUMN_NAME = 'recover_session_id');
SET @ddl = IF(@col_exists = 0,
              'ALTER TABLE players ADD COLUMN recover_session_id VARCHAR(64) DEFAULT NULL',
              'SELECT "recover_session_id already present" AS msg');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
