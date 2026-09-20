-- MySQL dump 10.13  Distrib 8.0.45, for Win64 (x86_64)
--
-- Host: localhost    Database: wastelandz
-- ------------------------------------------------------
-- Server version	8.0.45

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `blacklist`
--

DROP TABLE IF EXISTS `blacklist`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `blacklist` (
  `id` int NOT NULL AUTO_INCREMENT,
  `player_uid` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `display_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `scope` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'server',
  `server_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `hive_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reason` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `banned_by` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT 'system',
  `banned_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `expires_at` datetime DEFAULT NULL,
  `is_active` tinyint DEFAULT '1',
  PRIMARY KEY (`id`),
  KEY `idx_player` (`player_uid`),
  KEY `idx_scope` (`scope`,`server_id`,`hive_id`),
  KEY `idx_active` (`is_active`,`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `blacklist`
--

/*!40000 ALTER TABLE `blacklist` DISABLE KEYS */;
/*!40000 ALTER TABLE `blacklist` ENABLE KEYS */;

--
-- Table structure for table `hf_placements`
--

DROP TABLE IF EXISTS `hf_placements`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hf_placements` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `hive_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'default',
  `server_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `map_name` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `carry_class` tinyint NOT NULL,
  `prefab_path` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `pos_x` float NOT NULL,
  `pos_y` float NOT NULL,
  `pos_z` float NOT NULL,
  `yaw` float NOT NULL DEFAULT '0',
  `pitch` float NOT NULL DEFAULT '0',
  `roll` float NOT NULL DEFAULT '0',
  `owner_uid` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `placed_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `last_moved_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`id`),
  KEY `idx_server_map` (`server_id`,`map_name`),
  KEY `idx_owner` (`owner_uid`),
  KEY `idx_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hf_placements`
--

/*!40000 ALTER TABLE `hf_placements` DISABLE KEYS */;
/*!40000 ALTER TABLE `hf_placements` ENABLE KEYS */;

--
-- Table structure for table `money_drops`
--

DROP TABLE IF EXISTS `money_drops`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `money_drops` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `hive_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'default',
  `server_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `map_name` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `pos_x` float NOT NULL,
  `pos_y` float NOT NULL,
  `pos_z` float NOT NULL,
  `amount` int NOT NULL,
  `drop_source` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'death',
  `dropper_uid` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `dropper_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `expires_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_server_map` (`server_id`,`map_name`),
  KEY `idx_expires` (`expires_at`)
) ENGINE=InnoDB AUTO_INCREMENT=297 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `money_drops`
--

/*!40000 ALTER TABLE `money_drops` DISABLE KEYS */;
/*!40000 ALTER TABLE `money_drops` ENABLE KEYS */;

--
-- Table structure for table `player_marker_prefs`
--

DROP TABLE IF EXISTS `player_marker_prefs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player_marker_prefs` (
  `player_uid` varchar(64) NOT NULL,
  `hive_id` varchar(64) NOT NULL DEFAULT 'default',
  `icon_idx` int NOT NULL DEFAULT '4',
  `icon_size_px` int NOT NULL DEFAULT '48',
  `marker_range_m` int NOT NULL DEFAULT '5000',
  `markers_enabled` tinyint(1) NOT NULL DEFAULT '1',
  `names_enabled` tinyint(1) NOT NULL DEFAULT '1',
  `group_only` tinyint(1) NOT NULL DEFAULT '0',
  `auto_vehicle_swap` tinyint(1) NOT NULL DEFAULT '1',
  `map_flags` int NOT NULL DEFAULT '7',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_uid`,`hive_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `player_marker_prefs`
--

/*!40000 ALTER TABLE `player_marker_prefs` DISABLE KEYS */;
/*!40000 ALTER TABLE `player_marker_prefs` ENABLE KEYS */;

--
-- Table structure for table `player_sessions`
--

DROP TABLE IF EXISTS `player_sessions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player_sessions` (
  `player_uid` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `server_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `map_name` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `pos_x` float DEFAULT NULL,
  `pos_y` float DEFAULT NULL,
  `pos_z` float DEFAULT NULL,
  `rotation_yaw` float DEFAULT NULL,
  `stance` tinyint DEFAULT '0',
  `is_alive` tinyint DEFAULT '1',
  `recover_veh_prefab` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `recover_veh_class` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `recover_session_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `last_seen` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_uid`,`server_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `player_sessions`
--

/*!40000 ALTER TABLE `player_sessions` DISABLE KEYS */;
/*!40000 ALTER TABLE `player_sessions` ENABLE KEYS */;

--
-- Table structure for table `player_stats_daily`
--

DROP TABLE IF EXISTS `player_stats_daily`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player_stats_daily` (
  `player_uid` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hive_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'default',
  `server_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `stat_date` date NOT NULL,
  `kills` int DEFAULT '0',
  `deaths` int DEFAULT '0',
  `playtime_seconds` int DEFAULT '0',
  `money_earned` int DEFAULT '0',
  `money_spent` int DEFAULT '0',
  `distance_traveled` float DEFAULT '0',
  `longest_life_sec` int DEFAULT '0',
  `hvt_kills` int DEFAULT '0',
  `missions_completed` int DEFAULT '0',
  PRIMARY KEY (`player_uid`,`server_id`,`stat_date`),
  KEY `idx_date` (`stat_date`),
  KEY `idx_player_hive` (`player_uid`,`hive_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `player_stats_daily`
--

/*!40000 ALTER TABLE `player_stats_daily` DISABLE KEYS */;
/*!40000 ALTER TABLE `player_stats_daily` ENABLE KEYS */;

--
-- Table structure for table `players`
--

DROP TABLE IF EXISTS `players`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `players` (
  `player_uid` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hive_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'default',
  `display_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `money` int NOT NULL DEFAULT '0',
  `bank` int NOT NULL DEFAULT '0',
  `faction` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT 'GREEN',
  `weapon` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `inventory` text COLLATE utf8mb4_unicode_ci,
  `current_server_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `first_join` datetime DEFAULT CURRENT_TIMESTAMP,
  `last_seen` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_uid`,`hive_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `players`
--

/*!40000 ALTER TABLE `players` DISABLE KEYS */;
/*!40000 ALTER TABLE `players` ENABLE KEYS */;

--
-- Table structure for table `security_events`
--

DROP TABLE IF EXISTS `security_events`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `security_events` (
  `id` int NOT NULL AUTO_INCREMENT,
  `player_uid` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `server_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'dev-01',
  `hive_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'default',
  `display_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `event_type` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `item_prefab` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `details` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `severity` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT 'WARN',
  `timestamp` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_player` (`player_uid`),
  KEY `idx_server` (`server_id`,`hive_id`),
  KEY `idx_severity` (`severity`),
  KEY `idx_timestamp` (`timestamp`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `security_events`
--

/*!40000 ALTER TABLE `security_events` DISABLE KEYS */;
/*!40000 ALTER TABLE `security_events` ENABLE KEYS */;

--
-- Table structure for table `transactions`
--

DROP TABLE IF EXISTS `transactions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `transactions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `player_uid` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hive_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'default',
  `server_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'dev-01',
  `type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `amount` int NOT NULL,
  `balance_after` int NOT NULL,
  `details` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `timestamp` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_player` (`player_uid`,`hive_id`),
  KEY `idx_timestamp` (`timestamp`)
) ENGINE=InnoDB AUTO_INCREMENT=1690 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `transactions`
--

/*!40000 ALTER TABLE `transactions` DISABLE KEYS */;
/*!40000 ALTER TABLE `transactions` ENABLE KEYS */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-08-22 13:58:45
-- ============================================================
-- SYNTHETIC SEED DATA
-- ============================================================
-- Deliberately fake. The real pre-upgrade dump this fixture was
-- derived from carried live player UIDs, display names and balances,
-- and a test fixture must never carry anyone's data into a repo.
--
-- The values are chosen so a failure is obvious at a glance:
--   money/bank are distinctive numbers, not 0 or 100
--   one player has an empty inventory (must NOT get a namespace row)
--   one has invalid JSON     (must be SKIPPED by JSON_VALID, not copied)
--   one has a normal loadout (must be copied verbatim)
-- ============================================================

INSERT INTO players (player_uid, hive_id, display_name, money, bank, faction, inventory, current_server_id) VALUES
  ('TESTFIX-0000-0001', 'default', 'Fixture Alpha',  30850,   1761, 'FIA', '[{"p":"rifle"},{"p":"medkit"}]', 'dev-01'),
  ('TESTFIX-0000-0002', 'default', 'Fixture Bravo',   2000, 251300, 'US',  '[{"p":"pistol"}]',               'dev-01'),
  ('TESTFIX-0000-0003', 'default', 'Fixture Empty',      0,      0, 'FIA', '',                                'dev-01'),
  ('TESTFIX-0000-0004', 'default', 'Fixture Broken',   777,    888, 'US',  '{not valid json',                 'dev-01');

INSERT INTO transactions (player_uid, hive_id, server_id, type, amount, balance_after, details) VALUES
  ('TESTFIX-0000-0001', 'default', 'dev-01', 'atm_deposit',  -500, 30350, 'fixture'),
  ('TESTFIX-0000-0001', 'default', 'dev-01', 'atm_withdraw',  500, 30850, 'fixture'),
  ('TESTFIX-0000-0002', 'default', 'dev-01', 'store_buy',    -250,  1750, 'fixture');

INSERT INTO player_sessions (player_uid, server_id, map_name, pos_x, pos_y, pos_z, is_alive) VALUES
  ('TESTFIX-0000-0001', 'dev-01', 'GM_Arland', 100.5, 20.0, 300.25, 1);

INSERT INTO player_marker_prefs (player_uid, hive_id, icon_idx, icon_size_px) VALUES
  ('TESTFIX-0000-0001', 'default', 7, 64);
