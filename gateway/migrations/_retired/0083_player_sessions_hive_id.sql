-- ============================================================
-- Migration 0083 - player_sessions.hive_id
-- Created 2026-08-22.
--
-- player_sessions was the only per-server table without hive_id. Harmless
-- with one gateway serving one hive, but two hives sharing a database would
-- collide on the same session row.
--
-- The column is added; the PRIMARY KEY is deliberately NOT changed. Folding
-- hive_id into the key rewrites the whole table, and nobody runs two hives on
-- one database today. Deferred until someone actually does - a table rebuild
-- for a hypothetical is risk without benefit.
--
-- APPLIED AUTOMATICALLY by the gateway on startup (migrate.py).
-- Safe to re-run: MySQL implicitly commits DDL, so a migration and its
-- ledger row cannot be atomic. Idempotency is what makes a retry safe.
-- ============================================================

USE wastelandz;

SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_sessions' AND COLUMN_NAME = 'hive_id');
SET @ddl = IF(@c = 0,
              'ALTER TABLE player_sessions ADD COLUMN hive_id VARCHAR(64) NOT NULL DEFAULT ''default''',
              'SELECT "hive_id already present" AS msg');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
