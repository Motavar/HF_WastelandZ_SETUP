# Wasteland-Z — Server Setup

> ### 📖 [Read the setup guide](https://motavar.github.io/HF_WastelandZ_SETUP/)
> The full step-by-step as a web page — Windows and Linux, pick your tab.
>
> ### ⬇ [Download the kit (ZIP)](https://github.com/Motavar/HF_WastelandZ_SETUP/archive/refs/heads/main.zip)
> Everything in this repo in one file. No git or GitHub account needed.

**(EXPERIMENTAL DOCUMENTATION - UNTESTED)** — written with AI assistance; the
information may not be correct. As a server admin you use this kit at your own
risk. The full disclaimer is shown when you open the guide.

## Branches

| Branch | Channel | Gateway | For |
|---|---|---|---|
| **`main`** | **Production** | **0.7.1** | Everyone running a live server. This is what you want. |
| `beta` | Test | 0.9.4 | Testing the next release. **Never on a live server.** |

Both keep the kit at the same path, `gateway/`, so the setup and update steps are
identical on either. Only the clone differs:

```
git clone https://github.com/Motavar/HF_WastelandZ_SETUP.git            # production
git clone -b beta https://github.com/Motavar/HF_WastelandZ_SETUP.git    # beta
```

> **A newer gateway is not better.** Gateway `0.9.4` on `beta` pairs with an
> unreleased mod build. Run it against mod 1.0.16 and gear keeps saving — which is
> the trap. Starting 0.9.4 copies your gear into its new table once; that copy then
> goes stale while players carry on writing the old one. Update the mod later and
> gear **appears to roll back** to the day you started 0.9.4.

See **[RELEASES.md](RELEASES.md)** for the version history and how to upgrade.

> ## 🚨 SECURITY UPDATE — re-download the gateway (2026-08-26)
>
> **Update even though the version number has not changed.** A server configured
> with an **empty** or **placeholder** `api_key` authenticated every anonymous
> request — `check_auth` defaults a missing `api_key` parameter to `""`, so a
> configured key of `""` matched a caller who sent none. That reaches your economy
> database, with nothing in the log to say so.
>
> Reachable from a `config.py` with no `SERVERS` list and no `API_KEY`. Placeholder
> keys are refused too: `CHANGE_ME_*` is published in this kit's own
> `config.example.py`, so running on one is running on a key anybody can read.
>
> **What to do:** replace `gateway.py` from this repo's `gateway/` folder and
> restart. Your `config.py` is untouched. If the gateway then refuses to start and
> names a server, that server's key was one of the bad ones — generate a real one
> with `python -c "import secrets; print(secrets.token_hex(32))"`, put it in
> `config.py` under `SERVERS`, and the same value in that server's
> `HFWastelandZ_secrets.conf`.
>
> The version stays **0.7.1** on purpose: the mod checks it for exact equality, so
> a bumped number would print `GATEWAY VERSION MISMATCH` every 60 seconds for a
> gateway that is correct.

## What is this?

**[Arma Reforger](https://reforger.armaplatform.com/)** is Bohemia
Interactive's military simulation game (PC and Xbox), built on the Enfusion
engine — the platform that succeeds Arma 3. Anyone can host a dedicated
server, and mods install themselves: when a player joins a modded server, the
game downloads its mods automatically from the built-in Workshop.

**[Wasteland-Z](https://wasteland-z.com/)** is a hardcore PVP open-world mod
for Arma Reforger, by **Heavy Forge, Inc.** The world after the Z — the
outbreak ended, the cities emptied, and what survived now scavenges, fights,
and trades for what's left. Town-based scarcity loot, missions, gun / general
/ vehicle stores, a server-authoritative money economy with ATM banking,
three-faction PVP, and a cross-server hive: the same money, bank and gear on
every server in a cluster. It runs on top of any Game Master scenario, on any
map. The gameplay concept honors the A3 Wasteland lineage, rebuilt ground-up
for Reforger. It's published on the
**[Reforger Workshop](https://reforger.armaplatform.com/workshop/68A616565DECAB19)**
(mod ID `68A616565DECAB19`) — this kit already pre-lists it in every server
config, so it downloads and loads automatically.

**This repo is the server side.** It exists for admins who want to **host** a
Wasteland-Z server: the step-by-step setup guide, the gateway program (the
bridge between game servers and the MySQL database holding player money and
gear), the database schema, example configs, and start/stop scripts for
Windows and Linux.

**Just want to play?** You need nothing from here — find a Wasteland-Z server
in the Reforger server browser and join. The mod installs itself.

## What the guide covers

# 🟢 [Open the guide → ( START HERE )](https://motavar.github.io/HF_WastelandZ_SETUP/)

(Linux users: the guide's Step 1 clones this repo straight onto the server —
no ZIP needed.)

- **Part 1 — Install the game server:** SteamCMD, downloading the Arma
  Reforger dedicated server, and the ready-made `server1.json` (Wasteland-Z
  pre-listed in `mods`).
- **Part 2 — Database & gateway:** install MySQL + Python, create the
  database, configure and start the gateway, firewall, connect your game
  server.
- **Part 3 — Run, monitor & stop:** one `start_all.bat` starts everything,
  each piece in its own labeled window — close a window to stop just that
  piece. Auto-restart loop, start-on-boot, health checks, backups.
- **Part 4 — Multi-server:** run 2–3 game servers on one machine against one
  database (shared money/gear hive), with the ports table and per-server keys.

## What's in this repo

| Folder / file | What it is |
|---|---|
| `index.html` | The step-by-step setup guide (open it in a browser). |
| `gateway/` | The gateway program — copy this folder to your server and run it. |
| `gateway/setup_database.sql` | Every database table, defined in one file. **The gateway applies it on every start**, so you never run SQL by hand and there is no separate first-time step. It only ever adds — running it again changes nothing, which is what makes a fresh install and an upgraded one end up identical. |
| `gateway/migrate.py` | Applies the schema on start, then any pending data change. Records what it applied so nothing runs twice, and refuses to remove anything unless you deliberately pass `--allow-destructive`. |
| `gateway/tests/` | The tests we run against the gateway, shipped so you can run them yourself. ⚠ One of them **wipes** the database it is pointed at — read [`gateway/tests/README.md`](gateway/tests/README.md) first. |
| `gateway/config.example.py` | Settings template — copy to `config.py` and fill in. |
| `gateway/start_gateway.bat` | Windows one-click start. |
| `configs/` | Example server settings (loot, vehicles, towns, admins, loadouts…). [`configs/README.md`](configs/README.md) lists each file; every setting is documented inside its file. |
| `missions/` | Reward templates for the mission system + a guide to authoring missions in-game. |
| `server/` | Game-server kit: SteamCMD install script, example `server1.json`, start/stop batch files with auto-restart loop. |

## Requirements

- A Windows or Linux machine that stays on. The guide installs everything
  else: the Reforger dedicated server downloads via SteamCMD (no Steam
  account needed), the **Wasteland-Z** mod auto-downloads from the Reforger
  Workshop on first server start, and Part 2 walks through **Python 3.12+**
  and **MySQL 8**.

## The guide as a web page

The guide is published with GitHub Pages at
**<https://motavar.github.io/HF_WastelandZ_SETUP/>**. Running a fork? Enable it
on yours: **Settings → Pages → Deploy from a branch → `main` / `/ (root)`** —
live at `https://<your-username>.github.io/HF_WastelandZ_SETUP/` after a
minute.

---

By **Motavar** · [Wasteland-Z.com](https://wasteland-z.com) · [HeavyForge.com](https://heavyforge.com) · [Motavar@Judgement.net](mailto:Motavar@Judgement.net)
