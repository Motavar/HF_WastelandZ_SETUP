# Wasteland-Z — Gateway Releases

What to run, which gateway each mod version needs, and where to download it.

**The mod updates itself.** Reforger downloads it from the Workshop every time your
server starts. **The gateway is the part you host**, and it is the part that can
fall behind. That is what this file is for.

> ⚠ **You are reading the `beta` branch.** It carries the next release. For the
> live kit, switch to [`main`](https://github.com/Motavar/HF_WastelandZ_SETUP/tree/main).

---

## Which gateway do I need?

The mod checks the gateway version **for exact equality** at startup. A mismatch
prints `GATEWAY VERSION MISMATCH` on the server console and warns admins in game.
It does **not** stop the server — so a mismatch is a silent fault, not a clean
refusal. Match the table.

| Your mod | Gateway | Folder in this repo | Download |
|---|---|---|---|
| **1.0.18** *(next release)* | **0.9.6** | [`gateway/`](https://github.com/Motavar/HF_WastelandZ_SETUP/tree/beta/gateway) | [browse](https://github.com/Motavar/HF_WastelandZ_SETUP/tree/beta/gateway) · [whole kit (ZIP)](https://github.com/Motavar/HF_WastelandZ_SETUP/archive/refs/heads/beta.zip) |
| **1.0.16** *(on the Workshop now)* | **0.7.1** | [`gateway-0.7.1/`](https://github.com/Motavar/HF_WastelandZ_SETUP/tree/beta/gateway-0.7.1) | [browse](https://github.com/Motavar/HF_WastelandZ_SETUP/tree/beta/gateway-0.7.1) · [whole kit (ZIP)](https://github.com/Motavar/HF_WastelandZ_SETUP/archive/refs/heads/main.zip) |

**We keep the current gateway plus the two before it.** Older revisions stay in git
history and in the version table below, but are not shipped as folders.

Check what you are running — the gateway prints it on the first line at start:

```
  WastelandZ Gateway v0.9.6
```

---

## ⚠ Moving to 0.9.6

**Back up the database before the first start.**

```
mysqldump -u <user> -p wastelandz > wastelandz-backup-before-0.9.6.sql
```

The gateway applies its own migrations on first start — **you never run SQL by
hand** — but once the database has been upgraded, **an older gateway refuses to
start against it.** That is deliberate, so a downgraded gateway can never write a
format it does not understand. Rolling back to 0.7.1 afterwards means restoring
that backup.

**Order:** stop the server and the gateway → back up → update the gateway → update
the mod → start the gateway **on its own** and let it finish migrating → start the
game server.

**Both halves, or neither.** 0.9.6 with mod 1.0.16 stops gear saving. 1.0.18 with
gateway 0.7.1 does the same, because 1.0.18 calls endpoints 0.7.1 never served.

---

## Gateway version history

Newest first. Versions marked **shipped** were published in this kit; the rest ran
on the beta channel only.

| Version | Date | Status | What it changed |
|---|---|---|---|
| **0.9.6** | 2026-09-07 | beta | Oversize loadouts arrive in parts and write as one row. |
| 0.9.5 | 2026-09-05 | beta | `DB_POOL_SIZE` retired for `DB_POOL_SIZE_v2`, default 32. |
| 0.9.4 | 2026-08-31 | beta | Every save records which run of which server wrote it. |
| 0.9.3 | 2026-08-30 | beta | An absent weapon field no longer overwrites a stored one. |
| 0.9.2 | 2026-08-29 | beta | Position, stance and yaw keyed per realm and per map. |
| 0.9.1 | 2026-08-29 | beta | — |
| 0.9.0 | 2026-08-28 | beta | Namespaced player storage, keyed by scope. |
| 0.8.0 | 2026-08-24 | beta | **Hive v2** — `player_data`, auto-migrations, optional `waitress`. |
| **0.7.1** | 2026-07-17 | **shipped** | World-map marker toggles. Re-released 2026-08-26 as a security fix, version deliberately unchanged. |
| 0.7.2 | 2026-07-17 | withdrawn | Reverted to 0.7.1 — see below. |
| **0.7.0** | 2026-06-30 | **shipped** | Hive-shared, multi-server. |
| 0.6.0 | 2026-06-29 | — | — |
| 0.5.0 | 2026-06-06 | — | — |
| 0.4.0 | 2026-05-08 | — | — |
| 0.3.0 | 2026-02-25 | — | — |

> **Why 0.7.2 was withdrawn.** The 2026-08-26 security fix changed behaviour but
> kept the number, because the mod checks the version for exact equality — a bump
> would have printed `GATEWAY VERSION MISMATCH` every 60 seconds for a gateway that
> was correct.

---

## 0.9.6 — 2026-09-07

A loadout over roughly 8,000 characters could not be sent in one request. The mod
now splits it and the gateway buffers the parts, writing **one row when the last
one lands**. An incomplete batch writes nothing and the stored row stands, so a
dropped part costs a retry rather than a loadout.

No schema change. A body with no chunk fields takes exactly the 0.9.5 path.

## 0.9.5 — 2026-09-05

`DB_POOL_SIZE` is replaced by `DB_POOL_SIZE_v2`, default 32. The gateway deletes
the old line from your `config.py` on first start after taking a timestamped
backup. Nothing for you to edit.

Ten connections was correct while the development HTTP server throttled by failing.
With `waitress` delivering real concurrency it meant HTTP 503s, and a 503 on a save
is a lost write.

## 0.8.0 — 2026-08-24 — Hive v2

**The release that changes the database.** Player storage moved from a single
`players.inventory` value to `player_data` — one row per player, hive, realm and
namespace — which is what lets one account hold different gear on different groups
of servers.

- A server may write only its own scope; anything else is refused `403`.
- `hive_servers` / `hive_share_groups` publish each server's map, realms and real
  addon list, so a mod mismatch is visible before it costs anyone their gear.
- `players.arrival_grace` fixes gear loss when moving between servers.
- Migrations apply on start and are recorded in `schema_migrations`, so an update
  cannot run twice. Destructive ones need `--allow-destructive` **and** a
  successful dump first.
- Optional `waitress` HTTP server, auto-detected. Running three or more servers
  through one gateway: lower `HTTP_THREADS` by hand.

## 0.7.1 — security re-release, 2026-08-26

**Re-download the gateway even though the version number did not change.**

A server configured with an empty or placeholder `api_key` authenticated every
anonymous request: `check_auth` read the parameter with a default of `""`, so a
configured key of `""` matched a caller who sent no key at all. That reaches the
economy database, and nothing in the log said so.

The gateway now refuses to start and names the offending servers, and refuses the
request as well, so neither path can be missed. Generate a real key with:

```
python -c "import secrets; print(secrets.token_hex(32))"
```

Put it in `config.py` under `SERVERS`, and the **same** value in that server's
`HFWastelandZ_secrets.conf` (`API_KEY` line).

---

By **Motavar** · [Wasteland-Z.com](https://wasteland-z.com) · [HeavyForge.com](https://heavyforge.com)
