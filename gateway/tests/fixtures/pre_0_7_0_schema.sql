-- MySQL dump 10.13  Distrib 8.0.45, for Win64 (x86_64)
--
-- Host: localhost    Database: wastelandez
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
-- Table structure for table `player_stats_daily`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player_stats_daily` (
  `player_uid` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `server_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `stat_date` date NOT NULL,
  `kills` int DEFAULT '0',
  `deaths` int DEFAULT '0',
  `playtime_seconds` int DEFAULT '0',
  `money_earned` int DEFAULT '0',
  `money_spent` int DEFAULT '0',
  `distance_traveled` float DEFAULT '0',
  `longest_life_sec` int DEFAULT '0',
  PRIMARY KEY (`player_uid`,`server_id`,`stat_date`),
  KEY `idx_date` (`stat_date`),
  KEY `idx_player` (`player_uid`,`server_id`)
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

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `players` (
  `player_uid` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `server_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'dev-01',
  `display_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `money` int NOT NULL DEFAULT '0',
  `faction` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT 'GREEN',
  `first_join` datetime DEFAULT CURRENT_TIMESTAMP,
  `last_seen` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `pos_x` float DEFAULT NULL,
  `pos_y` float DEFAULT NULL,
  `pos_z` float DEFAULT NULL,
  `rotation_yaw` float DEFAULT NULL,
  `stance` tinyint DEFAULT '0',
  `weapon` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `inventory` text COLLATE utf8mb4_unicode_ci,
  `is_alive` tinyint DEFAULT '1',
  `bank` int NOT NULL DEFAULT '0',
  `last_server_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`player_uid`,`server_id`)
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
) ENGINE=InnoDB AUTO_INCREMENT=2565 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `security_events`
--

/*!40000 ALTER TABLE `security_events` DISABLE KEYS */;
/*!40000 ALTER TABLE `security_events` ENABLE KEYS */;

--
-- Table structure for table `transactions`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `transactions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `player_uid` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `server_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'dev-01',
  `type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `amount` int NOT NULL,
  `balance_after` int NOT NULL,
  `details` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `timestamp` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_player` (`player_uid`,`server_id`),
  KEY `idx_timestamp` (`timestamp`)
) ENGINE=InnoDB AUTO_INCREMENT=4859 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `transactions`
--

/*!40000 ALTER TABLE `transactions` DISABLE KEYS */;
/*!40000 ALTER TABLE `transactions` ENABLE KEYS */;

--
-- Dumping routines for database 'wastelandez'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-04-28 23:51:54

-- ============================================================
-- SYNTHETIC SEED DATA - deliberately fake, see the 0.7.1 fixture
-- for why a fixture never carries real player data.
--
-- NOTE THE SHAPE: this schema predates hives, so `players` is keyed
-- (player_uid, server_id) and money lives PER SERVER. One player here
-- has a row on one server only, which is the case that can be converted.
-- ============================================================
INSERT INTO `players` (player_uid, server_id, display_name, money, bank, faction, inventory, pos_x, pos_y, pos_z, is_alive) VALUES
  ('TESTFIX-OLD-0001', 'dev-01', 'Old Alpha', 4242, 8484, 'US',  '[{"p":"rifle"}]', 100.5, 20.0, 300.25, 1),
  ('TESTFIX-OLD-0002', 'dev-01', 'Old Bravo',  777,    0, 'FIA', '',                  50.0, 10.0, 150.00, 1);

INSERT INTO `transactions` (player_uid, server_id, type, amount, balance_after, details) VALUES
  ('TESTFIX-OLD-0001', 'dev-01', 'atm_deposit', -100, 4142, 'fixture');

INSERT INTO `player_stats_daily` (player_uid, server_id, stat_date, kills, deaths) VALUES
  ('TESTFIX-OLD-0001', 'dev-01', '2026-04-01', 5, 2);
