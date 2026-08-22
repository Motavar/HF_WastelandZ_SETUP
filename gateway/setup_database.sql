-- ============================================================
-- WastelandZ Gateway — Database Setup (Hive-Shared schema)
-- ============================================================
-- Run this script to create the database and all tables.
--
-- Usage:
--   mysql -u root -p < setup_database.sql
--
-- HIVE-SHARED MODEL
--   Player-associated data (money, bank, inventory, faction, stats,
--   recovery, marker prefs) is shared across the whole hive — one
--   profile per player, identical on every server. Only world context
--   (position on a specific map, alive state, placed objects) is
--   per-server. See docs/HIVE_SHARED_PLAN.md.
--
--   This is the launch schema. It is a structural redesign vs the old
--   per-(player,server) model; apply it on a FRESH database (pre-launch,
--   no data to migrate).
-- ============================================================

-- The database and the 'wastelandz' login are created in the setup guide
-- ("Create the database" step). This script builds TABLES ONLY and holds
-- NO usernames or passwords. Run it logged in as the wastelandz user:
--   mysql -u wastelandz -p wastelandz < setup_database.sql
USE wastelandz;

-- ============================================================
-- PLAYERS table — the SHARED player profile.
-- One row per player per hive. Money, bank, inventory, faction and
-- the /recover-independent identity follow the player to every server
-- in the hive. Keyed by (player_uid, hive_id) so multiple hives can
-- share one database without colliding.
-- `current_server_id` records where the player is right now — used to
-- reject stale saves from a server the player just left (anti-clobber).
-- ============================================================
CREATE TABLE IF NOT EXISTS players (
  player_uid        VARCHAR(64)  NOT NULL,            -- Steam ID or Reforger UID
  hive_id           VARCHAR(64)  NOT NULL DEFAULT 'default',
  display_name      VARCHAR(128) DEFAULT '',
  money             INT          NOT NULL DEFAULT 0,  -- wallet (shared)
  bank              INT          NOT NULL DEFAULT 0,  -- bank   (shared)
  faction           VARCHAR(16)  DEFAULT 'GREEN',
  weapon            VARCHAR(256) DEFAULT NULL,        -- active weapon prefab (shared gear)
  inventory         TEXT         DEFAULT NULL,        -- shared inventory (JSON)
  current_server_id VARCHAR(64)  DEFAULT NULL,        -- server that currently owns the player
  arrival_grace     TINYINT      NOT NULL DEFAULT 0,  -- one-shot cross-server arrival flag
  first_join        DATETIME     DEFAULT CURRENT_TIMESTAMP,
  last_seen         DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (player_uid, hive_id)
) ENGINE=InnoDB;

-- ============================================================
-- PLAYER_SESSIONS table — PER-SERVER world context.
-- World state that only makes sense on the specific server/map the
-- player is on: position, stance, alive state, and the /recover token
-- (the vehicle was on that server's map). One row per (player, server).
-- ============================================================
CREATE TABLE IF NOT EXISTS player_sessions (
  player_uid         VARCHAR(64)  NOT NULL,
  server_id          VARCHAR(64)  NOT NULL,
  hive_id            VARCHAR(64)  NOT NULL DEFAULT 'default',
  map_name           VARCHAR(64)  DEFAULT NULL,
  pos_x              FLOAT        DEFAULT NULL,
  pos_y              FLOAT        DEFAULT NULL,
  pos_z              FLOAT        DEFAULT NULL,
  rotation_yaw       FLOAT        DEFAULT NULL,
  stance             TINYINT      DEFAULT 0,
  is_alive           TINYINT      DEFAULT 1,
  recover_veh_prefab VARCHAR(256) DEFAULT NULL,       -- vehicle to re-spawn via /recover
  recover_veh_class  VARCHAR(16)  DEFAULT NULL,       -- GROUND / HELI / PLANE / BOAT
  recover_session_id VARCHAR(64)  DEFAULT NULL,       -- server session the driver got in during
  last_seen          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (player_uid, server_id)
) ENGINE=InnoDB;

-- ============================================================
-- TRANSACTIONS table — audit trail for all money changes.
-- hive_id = which hive; server_id = where the transaction happened.
-- ============================================================
CREATE TABLE IF NOT EXISTS transactions (
  id             INT           AUTO_INCREMENT PRIMARY KEY,
  player_uid     VARCHAR(64)   NOT NULL,
  hive_id        VARCHAR(64)   NOT NULL DEFAULT 'default',
  server_id      VARCHAR(64)   NOT NULL DEFAULT 'dev-01',
  type           VARCHAR(32)   NOT NULL,    -- 'spawn_grant', 'purchase', 'sell', 'admin_give', 'kill_reward', etc.
  amount         INT           NOT NULL,    -- positive = earned, negative = spent
  balance_after  INT           NOT NULL,    -- wallet balance after this transaction
  details        VARCHAR(256)  DEFAULT '',
  timestamp      DATETIME      DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_player (player_uid, hive_id),
  INDEX idx_timestamp (timestamp)
) ENGINE=InnoDB;

-- ============================================================
-- PLAYER_STATS_DAILY table — one row per player per server per day.
-- Kept per-server (so you retain where activity happened); hive-wide
-- leaderboards aggregate a player's rows across all servers in the hive.
-- ============================================================
CREATE TABLE IF NOT EXISTS player_stats_daily (
  player_uid       VARCHAR(64)  NOT NULL,
  hive_id          VARCHAR(64)  NOT NULL DEFAULT 'default',
  server_id        VARCHAR(64)  NOT NULL,
  stat_date        DATE         NOT NULL,
  kills            INT          DEFAULT 0,
  deaths           INT          DEFAULT 0,
  playtime_seconds INT          DEFAULT 0,
  money_earned     INT          DEFAULT 0,
  money_spent      INT          DEFAULT 0,
  distance_traveled FLOAT       DEFAULT 0,
  longest_life_sec INT          DEFAULT 0,
  hvt_kills        INT          DEFAULT 0,
  missions_completed INT        DEFAULT 0,
  PRIMARY KEY (player_uid, server_id, stat_date),
  INDEX idx_date (stat_date),
  INDEX idx_player_hive (player_uid, hive_id)
) ENGINE=InnoDB;

-- ============================================================
-- SECURITY_EVENTS table — anti-cheat audit trail.
-- ============================================================
CREATE TABLE IF NOT EXISTS security_events (
  id             INT           AUTO_INCREMENT PRIMARY KEY,
  player_uid     VARCHAR(64)   NOT NULL,
  server_id      VARCHAR(64)   NOT NULL DEFAULT 'dev-01',
  hive_id        VARCHAR(64)   NOT NULL DEFAULT 'default',
  display_name   VARCHAR(128)  DEFAULT '',
  event_type     VARCHAR(64)   NOT NULL,    -- 'BLOCKED_VEST_WEIGHT', 'BLOCKED_ROOT_WEIGHT', etc.
  item_prefab    VARCHAR(256)  DEFAULT '',
  details        VARCHAR(512)  DEFAULT '',
  severity       VARCHAR(16)   DEFAULT 'WARN',  -- 'WARN', 'CRITICAL', 'BAN'
  timestamp      DATETIME      DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_player (player_uid),
  INDEX idx_server (server_id, hive_id),
  INDEX idx_severity (severity),
  INDEX idx_timestamp (timestamp)
) ENGINE=InnoDB;

-- ============================================================
-- BLACKLIST table — banned players (server, hive, or global).
-- Scope: 'server' = this server only, 'hive' = all servers in the
-- same hive, 'global' = all servers everywhere.
-- ============================================================
CREATE TABLE IF NOT EXISTS blacklist (
  id             INT           AUTO_INCREMENT PRIMARY KEY,
  player_uid     VARCHAR(64)   NOT NULL,
  display_name   VARCHAR(128)  DEFAULT '',
  scope          VARCHAR(16)   NOT NULL DEFAULT 'server',  -- 'server', 'hive', 'global'
  server_id      VARCHAR(64)   DEFAULT NULL,  -- NULL for hive/global scope
  hive_id        VARCHAR(64)   DEFAULT NULL,  -- NULL for global scope
  reason         VARCHAR(256)  DEFAULT '',
  banned_by      VARCHAR(128)  DEFAULT 'system',
  banned_at      DATETIME      DEFAULT CURRENT_TIMESTAMP,
  expires_at     DATETIME      DEFAULT NULL,  -- NULL = permanent
  is_active      TINYINT       DEFAULT 1,     -- 0 = unbanned
  INDEX idx_player (player_uid),
  INDEX idx_scope (scope, server_id, hive_id),
  INDEX idx_active (is_active, expires_at)
) ENGINE=InnoDB;

-- ============================================================
-- HF_PLACEMENTS table — admin-placed and player-built world fixtures
-- (HF Carry & Place System). World state — scoped PER SERVER so two
-- servers running the same map do not share each other's builds.
-- ============================================================
CREATE TABLE IF NOT EXISTS hf_placements (
  id             BIGINT        AUTO_INCREMENT PRIMARY KEY,
  hive_id        VARCHAR(64)   NOT NULL DEFAULT 'default',
  server_id      VARCHAR(64)   NOT NULL,
  map_name       VARCHAR(64)   NOT NULL,
  carry_class    TINYINT       NOT NULL,        -- mirrors EHFCarryClass; expect PLACE=2
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
  base_id        BIGINT        DEFAULT NULL,   -- groups parts into one player base
  meta           JSON          DEFAULT NULL,   -- per-part state: damage, flags, future
  INDEX idx_server_map (server_id, map_name),
  INDEX idx_owner (owner_uid),
  INDEX idx_active (is_active)
) ENGINE=InnoDB;

-- ============================================================
-- MONEY_DROPS table — DB-backed money pickup entities.
-- Session-only world state — boot-wipe by (server_id, map_name) on
-- server start. Hard DELETE on pickup/expiry.
-- ============================================================
CREATE TABLE IF NOT EXISTS money_drops (
  id            BIGINT       AUTO_INCREMENT PRIMARY KEY,
  hive_id       VARCHAR(64)  NOT NULL DEFAULT 'default',
  server_id     VARCHAR(64)  NOT NULL,
  map_name      VARCHAR(64)  NOT NULL,
  pos_x         FLOAT        NOT NULL,
  pos_y         FLOAT        NOT NULL,
  pos_z         FLOAT        NOT NULL,
  amount        INT          NOT NULL,
  drop_source   VARCHAR(16)  NOT NULL DEFAULT 'death',   -- 'death' | 'player_drop' | 'admin_money'
  dropper_uid   VARCHAR(64)  DEFAULT '',
  dropper_name  VARCHAR(128) DEFAULT '',
  created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
  expires_at    DATETIME     NOT NULL,
  INDEX idx_server_map (server_id, map_name),
  INDEX idx_expires (expires_at)
) ENGINE=InnoDB;

-- ============================================================
-- PLAYER_MARKER_PREFS table — per-player team-marker UI preferences.
-- Shared across the hive (keyed by player_uid + hive_id). A player's
-- marker picks follow them to every server in the hive.
-- ============================================================
CREATE TABLE IF NOT EXISTS player_marker_prefs (
  player_uid          VARCHAR(64) NOT NULL,
  hive_id             VARCHAR(64) NOT NULL DEFAULT 'default',
  icon_idx            INT         NOT NULL DEFAULT 4,
  icon_size_px        INT         NOT NULL DEFAULT 48,
  marker_range_m      INT         NOT NULL DEFAULT 5000,
  markers_enabled     TINYINT(1)  NOT NULL DEFAULT 1,
  names_enabled       TINYINT(1)  NOT NULL DEFAULT 1,
  group_only          TINYINT(1)  NOT NULL DEFAULT 0,
  auto_vehicle_swap   TINYINT(1)  NOT NULL DEFAULT 1,
  map_flags           INT         NOT NULL DEFAULT 7,
  updated_at          TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (player_uid, hive_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- PLAYER_DATA table - namespaced per-scope player state.
--
-- Replaces the single players.inventory value, which could not hold
-- more than one server's gear no matter how it was read. One row per
-- (player, hive, server, namespace); a new player-owned feature is a
-- new namespace string, NOT a new table and NOT a gateway release.
--
-- WRITE RULE, ABSOLUTE: a server writes only rows whose server_id is
-- its own (or '@hive'). Every data-loss hazard in this area came from
-- one server overwriting another's value; that class is impossible by
-- construction here rather than merely guarded against.
--
-- payload is JSON so MySQL validates it on write - a malformed
-- inventory is REJECTED and the previous good value survives.
--
-- share_group + map_name drive the read rule:
--   share_group = mine  OR  (server_id = me AND map_name = my map)
-- The map test stops a server that rotated to a new map (and a new mod
-- set) from restoring gear whose prefabs no longer resolve there.
-- ============================================================
CREATE TABLE IF NOT EXISTS player_data (
  player_uid   VARCHAR(64)  NOT NULL,
  hive_id      VARCHAR(64)  NOT NULL DEFAULT 'default',
  server_id    VARCHAR(64)  NOT NULL,            -- real server id, or '@hive'
  namespace    VARCHAR(32)  NOT NULL,            -- 'inventory' | 'garage' | future
  share_group  VARCHAR(32)  NOT NULL DEFAULT 'ALPHA',
  map_name     VARCHAR(64)  NOT NULL DEFAULT '', -- '' = matches any map (legacy rows)
  payload      JSON         NOT NULL,
  format_ver   INT          NOT NULL DEFAULT 1,
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (player_uid, hive_id, server_id, namespace),
  KEY idx_ns    (hive_id, namespace, share_group),
  KEY idx_owner (player_uid, hive_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- HIVE_SERVERS table - server registration + mod compliance.
--
-- Each server announces itself on startup (map, share groups, mod
-- version, full addon list) and refreshes on its existing ping, so
-- this costs no extra traffic.
--
-- WHY THE ADDON LIST MATTERS: gear is stored as prefab paths, and on a
-- server missing the owning addon the item silently fails to restore.
-- This lets an admin SEE the mod delta BEFORE putting a server into a
-- shared gear pool, rather than discovering it when a player's rifle
-- disappears.
-- ============================================================
CREATE TABLE IF NOT EXISTS hive_servers (
  hive_id         VARCHAR(64)  NOT NULL DEFAULT 'default',
  server_id       VARCHAR(64)  NOT NULL,
  display_name    VARCHAR(128),
  map_name        VARCHAR(64),
  gear_group      VARCHAR(32),
  garage_group    VARCHAR(32),
  mod_version     VARCHAR(32),
  addon_count     INT          NOT NULL DEFAULT 0,
  addon_hash      VARCHAR(64),                   -- one-compare match test
  addon_list      JSON,                          -- readable diff when they differ
  players_online  INT          NOT NULL DEFAULT 0,
  boot_session_id VARCHAR(64),
  started_at      DATETIME,
  last_seen       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (hive_id, server_id),
  KEY idx_group (hive_id, gear_group)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- HIVE_SHARE_GROUPS table - labels for the fixed A-Z gear pools.
-- At most 27 rows per hive (ALPHA..ZULU plus PRIVATE). The NAMES are a
-- closed vocabulary in the mod, never free text: matching between
-- servers must be exact, and a typo would split a pool silently.
-- ============================================================
CREATE TABLE IF NOT EXISTS hive_share_groups (
  hive_id     VARCHAR(64)  NOT NULL DEFAULT 'default',
  group_name  VARCHAR(32)  NOT NULL,
  description VARCHAR(255),
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                           ON UPDATE CURRENT_TIMESTAMP,
  updated_by  VARCHAR(64),
  PRIMARY KEY (hive_id, group_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- HF_BASES / HF_BASE_ACCESS - player base ownership and door access.
--
-- Access belongs to a BASE, not to each door: re-typing a code at every
-- door is miserable and an owner wants one place to change it.
--
-- access_code_hash IS A SECRET AND NEVER LEAVES THE SERVER. No list or
-- read endpoint may select it - Enfusion replicates component state to
-- clients, so a code that reached the mod could be read by every
-- player. Verification is a dedicated endpoint returning only a boolean.
--
-- TWO LOCKS, NOT ONE: access_mode decides who may open, last_touched_at
-- decides how long it lives, and locking never touches the second one.
-- An owner-keyed lock that also extended lifetime would be a denial
-- exploit - the lesson HFVehicleLockRegistry already paid for.
-- ============================================================
CREATE TABLE IF NOT EXISTS hf_bases (
  id                BIGINT       NOT NULL AUTO_INCREMENT,
  hive_id           VARCHAR(64)  NOT NULL DEFAULT 'default',
  server_id         VARCHAR(64)  NOT NULL,
  map_name          VARCHAR(64)  NOT NULL,
  owner_uid         VARCHAR(64)  NOT NULL,
  display_name      VARCHAR(64),
  access_mode       TINYINT      NOT NULL DEFAULT 0,  -- 0 owner, 1 code, 2 public
  access_code_hash  VARCHAR(128),                     -- NEVER returned to a client
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

-- ============================================================
-- SCHEMA_MIGRATIONS table - the migration ledger.
-- One row per applied migration. The gateway reads this on startup,
-- diffs it against migrations/*.sql, and applies only what is missing.
-- This is what makes "restart the gateway" a safe upgrade instruction:
-- a migration cannot run twice because the database itself records it.
-- Created automatically by migrate.py; included here so a fresh install
-- has the complete schema in one file.
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
  version          INT          NOT NULL,
  name             VARCHAR(128) NOT NULL,
  applied_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  gateway_version  VARCHAR(16),
  PRIMARY KEY (version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- Verify setup
-- ============================================================
SELECT 'WastelandZ database created successfully (hive-shared schema)!' AS status;
SHOW TABLES;
