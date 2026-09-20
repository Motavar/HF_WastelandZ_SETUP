-- ============================================================
-- Migration 0093 - carry the held weapon onto the session row
-- Created 2026-08-30.
--
-- ADDITIVE AND NON-DESTRUCTIVE. No flag, no backup gate, no chance of being
-- held. It copies a value; it deletes nothing and drops nothing. Deliberately
-- NOT claiming @auto-apply-nonlossy, because that opt-in exists for
-- migrations that must USE a destructive verb - this one does not use one at
-- all and the runner will apply it unattended on its own.
--
-- WHY. players.weapon is HIVE scoped: one value for the whole account. Gear is
-- REALM scoped and, since 0092, position is realm+map scoped. So a player
-- holding an AK in ALPHA and an M249 in BRAVO had the second overwrite the
-- first; swapping back restored a weapon their ALPHA loadout did not contain,
-- the client could not equip what they did not own, and they spawned
-- empty-handed. player_sessions.weapon (added in setup_database.sql, which
-- runs first on every start) inherits the realm+map key and fixes that.
--
-- WHAT THIS DOES. Seeds the new column from the old one so nobody loses the
-- weapon they were holding on upgrade day.
--
-- ⚠ THE SEED IS APPROXIMATE AND THAT IS ACCEPTED. The old column held ONE
-- weapon for the whole account, so every realm row gets the same value - most
-- likely correct for the realm they were last playing and possibly wrong for
-- the others. That is harmless by design: the mod now VERIFIES the weapon is
-- actually present in the restored loadout before equipping it, and silently
-- declines if it is not. A wrong seed costs nothing; a NULL would cost every
-- upgrading player the weapon in their hands.
--
-- IDEMPOTENT. Guarded on s.weapon IS NULL, so a re-run touches nothing and it
-- can never overwrite a value written since by the new code path.
--
-- players.weapon is left in place and DEPRECATED - no longer read by the
-- gateway, still written by older mods. Dropping a column an older build may
-- still write is how a rollback loses data, so it stays.
-- ============================================================

UPDATE player_sessions s
  JOIN players p
    ON p.player_uid = s.player_uid
   AND p.hive_id    = s.hive_id
   SET s.weapon = p.weapon
 WHERE s.weapon IS NULL
   AND p.weapon IS NOT NULL
   AND p.weapon <> '';
