-- ============================================================
-- Migration 0082 - players.arrival_grace
-- Created 2026-08-22.
--
-- One-shot cross-server arrival flag.
--
-- players.current_server_id was doing two contradictory jobs: 'who owns
-- this player right now' (must be overwritten on every load) and 'where did
-- they last play' (must survive a load). The claim won, so the history was
-- destroyed by the act of reading it - which is why a second load during one
-- arrival reported THIS server as the last server and wiped the player's gear.
--
-- This column splits them. Set when the stored current_server_id differs
-- from the loading server; cleared by the first save after a successful
-- spawn. Fails OPEN - a missed clear grants one extra free respawn, never a
-- wipe.
--
-- APPLIED AUTOMATICALLY by the gateway on startup (migrate.py).
-- Safe to re-run: MySQL implicitly commits DDL, so a migration and its
-- ledger row cannot be atomic. Idempotency is what makes a retry safe.
-- ============================================================

USE wastelandz;

SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'players' AND COLUMN_NAME = 'arrival_grace');
SET @ddl = IF(@c = 0,
              'ALTER TABLE players ADD COLUMN arrival_grace TINYINT NOT NULL DEFAULT 0',
              'SELECT "arrival_grace already present" AS msg');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
