# Wasteland-Z — Server Setup

> ### 📖 [Read the setup guide](https://motavar.github.io/HF_WastelandZ_SETUP/)
> The full step-by-step as a web page — Windows and Linux, pick your tab.
>
> ### ⬇ [Download the kit (ZIP)](https://github.com/Motavar/HF_WastelandZ_SETUP/archive/refs/heads/main.zip)
> Everything in this repo in one file. No git or GitHub account needed.

**(EXPERIMENTAL DOCUMENTATION - UNTESTED)** — written with AI assistance; the
information may not be correct. As a server admin you use this kit at your own
risk. The full disclaimer is shown when you open the guide.

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
for Reforger.

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
| `gateway/setup_database.sql` | Builds every database table in one shot. |
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
