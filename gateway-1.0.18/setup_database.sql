-- ============================================================
-- WastelandZ Gateway — Database Schema (THE single source of truth)
-- ============================================================
-- THIS FILE DEFINES THE WHOLE SCHEMA, AND IT IS APPLIED ON EVERY
-- GATEWAY START — on a brand-new database and on a decade-old one
-- alike. There is no second place where a table is defined.
--
-- WHY IT WORKS THAT WAY. The schema used to live in TWO places: this
-- file for fresh installs, and migrations/*.sql for upgrades. The two
-- drifted, exactly as that arrangement always eventually does:
-- player_marker_prefs ended up utf8mb4_unicode_ci on a fresh install
-- and utf8mb4_0900_ai_ci on an upgraded one, because a migration
-- omitted a COLLATE clause and inherited the server default instead.
-- The result was a hard `ERROR 1267 Illegal mix of collations` on any
-- join between players and player_marker_prefs — a query that passes
-- on a developer's fresh database and fails on every existing server.
--
-- One file, applied to both, makes that class of bug impossible rather
-- than merely unlikely. Numbered migrations still exist, but they now
-- carry DATA transformations only — never table definitions.
--
-- THEREFORE, THE RULES FOR EDITING THIS FILE:
--   1. Every statement MUST be idempotent. It runs again on every boot.
--      Tables: CREATE TABLE IF NOT EXISTS.
--      Columns / keys on existing tables: the guarded-ALTER pattern in
--      the SCHEMA UPGRADES section at the bottom.
--   2. Every table MUST name its COLLATE explicitly. Inheriting the
--      server default is what caused the drift described above, and the
--      default differs between MySQL 5.7 and 8.0.
--   3. NOTHING here may DROP or DELETE. Removing something is a
--      separate, numbered, destructive migration that an admin opts in
--      to. This file must always be safe to run unattended.
--
-- HIVE-SHARED MODEL
--   Player-associated data (money, bank, inventory, faction, stats,
--   recovery, marker prefs) is shared across the whole hive — one
--   profile per player, identical on every server. Only world context
--   (position on a specific map, alive state, placed objects) is
--   per-server. See docs/HIVE_SHARED_PLAN.md.
--
-- Usage (the gateway does this for you; this is for a manual run):
--   mysql -u wastelandz -p wastelandz < setup_database.sql
--
-- The database and the 'wastelandz' login are created in the setup
-- guide ("Create the database" step). This script builds TABLES ONLY
-- and holds NO usernames or passwords.
--
-- There is deliberately no `USE` statement: the database is selected by
-- the connection, so this file works against a database an admin has
-- named something other than 'wastelandz'.
-- ============================================================

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
  -- SOFT DELETE for the stale-account policy. NULL = active.
  -- A purge marks this and stops; removing rows is a separate, deliberate,
  -- opt-in step over rows already marked. A date-driven hard DELETE across
  -- money, bank, gear, garages and bases is a data-loss machine the first
  -- time a clock, a timezone or a last_seen regression is wrong - and this
  -- file's own rule is that the unattended path never destroys data.
  deleted_at        DATETIME     DEFAULT NULL,
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
  -- The boot session that last WROTE this row. Lets a load tell "you played
  -- here earlier this run" from "this server has restarted since you left",
  -- which nothing could distinguish before. Only ever written by a SAVE, so
  -- repeated loads during one arrival cannot disturb it - the property that
  -- arrival_grace exists to work around. See PLAYER_GEAR_STATE_CARD.md S8.
  boot_session_id    VARCHAR(64)  DEFAULT NULL,
  first_join         DATETIME     DEFAULT CURRENT_TIMESTAMP,  -- first seen ON THIS SERVER
  last_seen          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  -- hive_id IS in the key. It is on the row either way, but leaving it out
  -- let two hives that share a server_id string collide on one row - and
  -- server_id is an admin-chosen string, so "dev-01" in two hives is not
  -- exotic. The collision landed on position and is_alive.
  PRIMARY KEY (player_uid, hive_id, server_id)
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
  -- hive_id IS in the key. Without it two hives sharing a server_id string
  -- collided, and because this table is written with ON DUPLICATE KEY UPDATE
  -- the collision was SILENT AND CUMULATIVE: kills, deaths, playtime and
  -- money were summed across both hives into one row, which then kept
  -- whichever hive inserted it first. Widening a key can only SPLIT rows,
  -- never merge them, so correcting it loses nothing.
  PRIMARY KEY (player_uid, hive_id, server_id, stat_date),
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
-- more than one server's gear no matter how it was read.
--
-- THE POINT OF THIS TABLE: a new player-owned feature is a NEW
-- NAMESPACE STRING - not a new table, not a migration, not a gateway
-- release. The gateway holds NO list of valid namespaces; it validates
-- the SHAPE of the name only (<=32 chars, alnum/_/-, see
-- _valid_namespace) and stores the payload without ever parsing it.
-- Perks, payments, night-vision settings, gun settings and stored
-- vehicles are all just labels an admin never has to hear about.
--
-- THE PAYLOAD IS OPAQUE. The gateway never reads inside it. That is
-- what keeps every access a primary-key point lookup: three or four
-- B-tree page reads, microseconds, and NOT slower as the table grows.
-- NEVER add a query that looks inside payload (no JSON_EXTRACT in a
-- WHERE, no LIKE over payload) - that converts a point lookup into a
-- full scan and is the single change that would make this design slow.
--
-- WRITE RULE, ABSOLUTE: a server writes only rows whose server_id is
-- its own (or '@hive'). Every data-loss hazard in this area came from
-- one server overwriting another's value; that class is impossible by
-- construction here rather than merely guarded against.
--
-- THE KEY IS THE SCOPE. Five scopes, all first-class, all expressed by
-- the key rather than by branching code:
--   hive-wide      share_group '@hive'                scope_map ''
--   gear set       share_group 'ALPHA'..'ZULU'        scope_map ''
--   vehicle set    share_group from GARAGE_SHARE_GROUP scope_map ''
--   this server    share_group '@private:<server_id>' scope_map ''
--   per map        any of the above                   scope_map '<map>'
--
-- scope_map is BLANK for everything that is not map-scoped, which is
-- gear, perks, payments and most settings. Gear is deliberately NOT
-- per-map: the same mods on a different map in the same hive and the
-- same group are the same gear. map_name below is a separate,
-- INFORMATIONAL column ("last written on GM_Arland") so a per-map
-- namespace and the support breadcrumb never fight over one field.
--
-- format_ver is per ROW, so each namespace evolves its payload
-- independently - 'perks' can be at v4 while 'inventory' is still v1.
-- ============================================================
CREATE TABLE IF NOT EXISTS player_data (
  player_uid   VARCHAR(64)  NOT NULL,
  hive_id      VARCHAR(64)  NOT NULL DEFAULT 'default',
  share_group  VARCHAR(32)  NOT NULL DEFAULT 'ALPHA',
  namespace    VARCHAR(32)  NOT NULL,            -- 'inventory' | 'garage' | future
  scope_map    VARCHAR(64)  NOT NULL DEFAULT '', -- '' = not map-scoped (the norm)
  server_id    VARCHAR(64)  NOT NULL,            -- informational: last writer
  map_name     VARCHAR(64)  NOT NULL DEFAULT '', -- informational: last written on
  payload      MEDIUMTEXT   NOT NULL,   -- NOT json: MySQL normalises a JSON
                                        -- column (space after every colon, keys
                                        -- sorted) and the mod parses this by hand,
                                        -- whitespace- and order-sensitive.
  format_ver   INT          NOT NULL DEFAULT 1,
  -- Is the character who owns THIS state dead? 0 = alive (the default, so an
  -- upgrade marks nobody dead), 1 = died and has not respawned into this gear
  -- set yet.
  --
  -- PER NAMESPACE ON PURPOSE, and that is the model rather than a compromise:
  -- the mod sets it on 'inventory' because gear is forfeit on death, and
  -- NEVER on 'garage', because a car parked before you died is still yours
  -- afterwards. settings, perks and anything future are untouched.
  --
  -- The gateway stores this and never interprets it. The MOD decides which
  -- namespaces death touches.
  --
  -- WHY IT LIVES HERE. is_alive is on player_sessions, keyed by SERVER, and
  -- the load answers is_alive = 1 when the server being joined has no row.
  -- So death on one server was invisible to the next and cross-server gear
  -- restore handed the pre-death loadout back. Death is a property of the
  -- character and its gear, so it is stored at the gear's scope.
  owner_dead   TINYINT      NOT NULL DEFAULT 0,
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
  -- 256 chars = 1024 bytes under utf8mb4, well inside InnoDB's 3072-byte
  -- index limit.
  PRIMARY KEY (player_uid, hive_id, share_group, namespace, scope_map)
  --
  -- DELIBERATELY NO SECONDARY INDEXES. Every query the gateway issues
  -- against this table begins `player_uid = ? AND hive_id = ?`, so the
  -- primary key serves all of them as a leftmost prefix. The previous
  -- idx_owner (player_uid, hive_id) was an exact duplicate of that
  -- prefix, and idx_ns / idx_last_writer were never referenced by any
  -- endpoint. Three redundant index writes on every gear save is a real
  -- cost for no read benefit. If a support or dashboard query later
  -- needs to search by server_id, add the index then - it is one
  -- additive line.
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- hive_data - THE SAME IDEA, FOR THINGS THAT ARE NOT A PLAYER
-- ============================================================
-- player_data answers "what does this person own". This answers "what
-- does this hive know" - anything belonging to the community rather
-- than to one profile: supporter tiers, an announcement, seasonal
-- state, a Discord guild's settings.
--
-- WHY A SEPARATE TABLE AND NOT A SENTINEL PLAYER. Storing it in
-- player_data under a fake uid like '@hive' works on day one and costs
-- forever after: every "list the players" query, every leaderboard,
-- every export has to learn to skip that row, and the one that forgets
-- shows a fake player to an admin. A NOT NULL player_uid should mean
-- there is a player.
--
-- SAME CONTRACT AS player_data, deliberately: an opaque payload the
-- gateway never parses, a namespace that is shape-checked but never
-- enumerated, and a per-row format_ver. A new kind of hive-level data
-- therefore costs no schema change, no migration and no admin action -
-- the property player data already has.
--
--   scope   ''            not scoped (the norm)
--           '<map>'       per map
--           '<guild_id>'  per Discord guild, or any other partition
--                         the caller decides on
--
-- server_id is NOT in the key: hive data belongs to the hive, so two
-- servers writing one namespace mean one row. The column records the
-- last writer, for support only.
-- ============================================================
CREATE TABLE IF NOT EXISTS hive_data (
  hive_id      VARCHAR(64)  NOT NULL DEFAULT 'default',
  namespace    VARCHAR(32)  NOT NULL,            -- 'supporters' | 'announce' | future
  scope        VARCHAR(64)  NOT NULL DEFAULT '', -- '' = not scoped (the norm)
  server_id    VARCHAR(64)  NOT NULL,            -- informational: last writer
  payload      MEDIUMTEXT   NOT NULL,   -- opaque, same reasoning as player_data
  format_ver   INT          NOT NULL DEFAULT 1,
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (hive_id, namespace, scope)
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
-- SCHEMA UPGRADES — bring an OLDER database up to the definitions above
-- ============================================================
-- Everything above is CREATE TABLE IF NOT EXISTS, which by design does
-- NOTHING to a table that already exists. So a database created by an
-- older release keeps its old shape unless it is altered here.
--
-- This is that section. It is where "fresh install" and "upgrade" are
-- made to converge, and the harness test diffs the two to prove it.
--
-- EVERY STATEMENT HERE MUST BE:
--   * GUARDED   — check information_schema first, so a re-run is a no-op.
--                 ADD COLUMN IF NOT EXISTS is not portable before MySQL
--                 8.0.29, hence the prepared-statement pattern.
--   * ADDITIVE  — never DROP, never DELETE, never TRUNCATE. This file
--                 runs unattended on every boot; it must never be the
--                 thing that loses an admin's data. Removals are
--                 separate, numbered, destructive migrations that an
--                 admin opts in to.
--
-- A guard that names the WRONG TABLE is worse than no guard: it always
-- evaluates false and the ALTER fires every time. That exact bug shipped
-- once — a migration checked `players` for columns that live on
-- `player_sessions`, so it added three permanently-dead columns to
-- `players` on every install. Check the guard names the same table the
-- ALTER does.
-- ============================================================

-- ---- players.arrival_grace (one-shot cross-server arrival flag) ------
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'players' AND COLUMN_NAME = 'arrival_grace');
SET @ddl = IF(@c = 0,
    'ALTER TABLE players ADD COLUMN arrival_grace TINYINT NOT NULL DEFAULT 0',
    'SELECT "players.arrival_grace present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- player_sessions.hive_id ----------------------------------------
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_sessions' AND COLUMN_NAME = 'hive_id');
SET @ddl = IF(@c = 0,
    'ALTER TABLE player_sessions ADD COLUMN hive_id VARCHAR(64) NOT NULL DEFAULT ''default''',
    'SELECT "player_sessions.hive_id present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- hf_placements.base_id (groups parts into one player base) -------
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'hf_placements' AND COLUMN_NAME = 'base_id');
SET @ddl = IF(@c = 0,
    'ALTER TABLE hf_placements ADD COLUMN base_id BIGINT DEFAULT NULL',
    'SELECT "hf_placements.base_id present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- hf_placements.meta (per-part state: damage, flags, future) ------
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'hf_placements' AND COLUMN_NAME = 'meta');
SET @ddl = IF(@c = 0,
    'ALTER TABLE hf_placements ADD COLUMN meta JSON DEFAULT NULL',
    'SELECT "hf_placements.meta present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- player_marker_prefs collation ----------------------------------
-- THE DRIFT THIS WHOLE FILE EXISTS TO PREVENT, and the one instance of
-- it that reached real servers. An older release created this table with
-- no COLLATE clause, so it inherited the server default —
-- utf8mb4_0900_ai_ci on MySQL 8.0. Every other table names
-- utf8mb4_unicode_ci explicitly. The mismatch is a hard
-- `ERROR 1267 Illegal mix of collations` on any join between
-- player_marker_prefs and players: a query that passes on a fresh
-- database and fails on every upgraded one.
--
-- CONVERT TO rewrites the table but preserves every row. It is not
-- destructive and needs no flag. A COUNT of 0 (wrong collation absent,
-- or table absent) makes it a no-op.
SET @c = (SELECT COUNT(*) FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_marker_prefs'
             AND TABLE_COLLATION <> 'utf8mb4_unicode_ci');
SET @ddl = IF(@c > 0,
    'ALTER TABLE player_marker_prefs CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci',
    'SELECT "player_marker_prefs collation correct" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- hive_id on the tables that predate hives ------------------------
-- A database old enough to predate the hive model has these tables
-- ALREADY, so CREATE TABLE IF NOT EXISTS skips them and they keep their
-- old shape. Both columns below are QUERIED - the leaderboard filters
-- player_stats_daily on hive_id, and transactions is read by hive
-- everywhere - so without these an old database starts cleanly and then
-- fails at runtime with "Unknown column 'hive_id'".
--
-- Found by upgrading the OLDEST surviving backup and diffing the result
-- against a fresh install, which is the only way this class of gap shows
-- up: every one of them is a table that already existed.

SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_stats_daily' AND COLUMN_NAME = 'hive_id');
SET @ddl = IF(@c = 0,
    'ALTER TABLE player_stats_daily ADD COLUMN hive_id VARCHAR(64) NOT NULL DEFAULT ''default''',
    'SELECT "player_stats_daily.hive_id present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'transactions' AND COLUMN_NAME = 'hive_id');
SET @ddl = IF(@c = 0,
    'ALTER TABLE transactions ADD COLUMN hive_id VARCHAR(64) NOT NULL DEFAULT ''default''',
    'SELECT "transactions.hive_id present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- later stat counters --------------------------------------------
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_stats_daily' AND COLUMN_NAME = 'hvt_kills');
SET @ddl = IF(@c = 0,
    'ALTER TABLE player_stats_daily ADD COLUMN hvt_kills INT DEFAULT 0',
    'SELECT "player_stats_daily.hvt_kills present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_stats_daily' AND COLUMN_NAME = 'missions_completed');
SET @ddl = IF(@c = 0,
    'ALTER TABLE player_stats_daily ADD COLUMN missions_completed INT DEFAULT 0',
    'SELECT "player_stats_daily.missions_completed present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- players.weapon widened 255 -> 256 -------------------------------
-- Widening only. A prefab path that fits in 255 fits in 256, so no value
-- can be truncated by this.
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'players' AND COLUMN_NAME = 'weapon'
             AND CHARACTER_MAXIMUM_LENGTH < 256);
SET @ddl = IF(@c > 0,
    'ALTER TABLE players MODIFY weapon VARCHAR(256) DEFAULT NULL',
    'SELECT "players.weapon already 256" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- the index that goes with player_stats_daily.hive_id -------------
-- Guarded by NAME. An index that already exists under this name is left
-- alone rather than replaced: rebuilding one would mean dropping it, and
-- nothing in this file is allowed to drop anything.
SET @c = (SELECT COUNT(*) FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_stats_daily'
             AND INDEX_NAME = 'idx_player_hive');
SET @ddl = IF(@c = 0,
    'ALTER TABLE player_stats_daily ADD INDEX idx_player_hive (player_uid, hive_id)',
    'SELECT "player_stats_daily.idx_player_hive present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ============================================================
-- GATEWAY 0.9 ADDITIONS (2026-08-28)
-- ============================================================
-- All four are ADD COLUMN with an information_schema guard, so they are
-- additive, idempotent and safe to run unattended on every boot - the
-- rule this whole section lives by.
--
-- The two PRIMARY KEY corrections that ship alongside these are NOT here
-- and cannot be: a re-key is DROP PRIMARY KEY, and nothing in this file
-- is allowed to drop anything. They live in migration 0090, which an
-- admin opts into and which takes a backup first.

-- ---- player_data.owner_dead (death at gear-set scope) ----------------
-- 0 = alive. Every existing row gets the default, so the upgrade marks
-- NOBODY dead - which is the required behaviour, not a happy accident.
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_data' AND COLUMN_NAME = 'owner_dead');
SET @ddl = IF(@c = 0,
    'ALTER TABLE player_data ADD COLUMN owner_dead TINYINT NOT NULL DEFAULT 0',
    'SELECT "player_data.owner_dead present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- player_sessions.boot_session_id (which run wrote this row) ------
-- NULL on every existing row, and NULL reads as "unknown, assume the
-- server has restarted" - the forgiving direction, matching
-- HFServerSession.HasRestartedSince() which already treats an empty id
-- that way. No backfill needed or wanted.
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_sessions' AND COLUMN_NAME = 'boot_session_id');
SET @ddl = IF(@c = 0,
    'ALTER TABLE player_sessions ADD COLUMN boot_session_id VARCHAR(64) DEFAULT NULL',
    'SELECT "player_sessions.boot_session_id present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- player_sessions.first_join (first seen ON THIS SERVER) ----------
-- Existing rows get CURRENT_TIMESTAMP, so for a database that predates
-- this column "first join" reads as the upgrade date rather than the
-- true first visit. That is unavoidable - the information was never
-- recorded - and it is honest going forward. players.first_join already
-- carries the hive-level answer and is not affected.
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_sessions' AND COLUMN_NAME = 'first_join');
SET @ddl = IF(@c = 0,
    'ALTER TABLE player_sessions ADD COLUMN first_join DATETIME DEFAULT CURRENT_TIMESTAMP',
    'SELECT "player_sessions.first_join present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- players.deleted_at (soft delete for the stale-account policy) ---
-- NULL = active. Nothing writes this yet; the purge job and what
-- deletion MEANS for a player's base, stored vehicles and outstanding
-- money are policy that still needs its own pass. The column is the
-- cheap part.
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'players' AND COLUMN_NAME = 'deleted_at');
SET @ddl = IF(@c = 0,
    'ALTER TABLE players ADD COLUMN deleted_at DATETIME DEFAULT NULL',
    'SELECT "players.deleted_at present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ============================================================
-- POSITION IS SCOPED PER REALM AND PER MAP  (2026-08-29)
-- ============================================================
-- Gear is keyed per realm on player_data.share_group. Position was keyed
-- (player_uid, hive_id, server_id) only, so switching gear set kept the old
-- position, and map_name - though present as a COLUMN - was outside the key,
-- so only ONE position survived per server. Play Arland and your Eden spot
-- was overwritten.
--
-- Third instance of a finding already made twice: keys that do not match the
-- scope model. Widening a key can only SPLIT rows, never merge, so this is
-- non-lossy. Every existing row keeps its position under its own map_name
-- and a defaulted ALPHA realm.
--
-- ORDER MATTERS, and it is the reason these three steps are written out
-- separately rather than folded together:
--   1. normalise NULL map_name  (a 0.7.1 database has map_name DEFAULT NULL,
--      and those rows would fail step 2 on a server with strict mode on)
--   2. make map_name NOT NULL   (a PRIMARY KEY column cannot be nullable)
--   3. add share_group
-- The key widening itself is migration 0092 - see the note at the end.

-- ---- 1. normalise NULL map_name BEFORE it becomes NOT NULL -----------
-- Unconditional and idempotent: on a re-run there is nothing left to update.
UPDATE player_sessions SET map_name = '' WHERE map_name IS NULL;

-- ---- 2. player_sessions.map_name -> NOT NULL -------------------------
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_sessions' AND COLUMN_NAME = 'map_name'
             AND IS_NULLABLE = 'YES');
SET @ddl = IF(@c = 1,
    'ALTER TABLE player_sessions MODIFY map_name VARCHAR(64) NOT NULL DEFAULT ''''',
    'SELECT "player_sessions.map_name already NOT NULL" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- 3. player_sessions.share_group (which realm this position is in) --
-- DEFAULT 'ALPHA' matches player_data.share_group and the ALPHA fallback the
-- gateway and mod both use, so an upgraded row lands in the realm its owner
-- was already playing.
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_sessions' AND COLUMN_NAME = 'share_group');
SET @ddl = IF(@c = 0,
    'ALTER TABLE player_sessions ADD COLUMN share_group VARCHAR(32) NOT NULL DEFAULT ''ALPHA''',
    'SELECT "player_sessions.share_group present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- player_sessions.weapon (the weapon that was in their HANDS) -----
-- Owner decision 2026-08-30: the held weapon belongs with the body state -
-- beside position, yaw and stance - and NOT on `players`.
--
-- WHY IT MOVED. players.weapon is HIVE scoped: one value for the whole
-- account. Gear is REALM scoped and position is realm+map scoped, so a
-- player holding an AK in ALPHA and an M249 in BRAVO had the second
-- overwrite the first. Swapping back restored a weapon their ALPHA loadout
-- did not contain, the client could not equip what they did not own, and
-- they spawned empty-handed.
--
-- Here it inherits the realm+map key from 0092, so each realm remembers what
-- that realm's character was holding.
--
-- players.weapon is left in place and DEPRECATED - still written by older
-- mods, no longer read by this gateway. Dropping a column an older build may
-- still write is how a rollback loses data, so it stays.
SET @c = (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'player_sessions' AND COLUMN_NAME = 'weapon');
SET @ddl = IF(@c = 0,
    'ALTER TABLE player_sessions ADD COLUMN weapon VARCHAR(256) DEFAULT NULL',
    'SELECT "player_sessions.weapon present" AS msg');
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- ---- the key widening itself lives in migration 0092 -----------------
-- NOT HERE, and the gateway enforces that: this file is applied on EVERY
-- start, so it must be additive only. A PRIMARY KEY cannot be changed in
-- place - MySQL needs DROP PRIMARY KEY - and the schema guard matches the
-- verb, refusing to start if it appears here. That guard is correct and
-- was left alone. See migrations/0092_position_scope_by_realm_and_map.sql.
