# Wasteland-Z — Server Setup

> ### 📖 [Read the setup guide](https://motavar.github.io/HF_WastelandZ_SETUP/)
> The full step-by-step as a web page — Windows and Linux, pick your tab.
>
> ### ⬇ [Download the kit (ZIP)](https://github.com/Motavar/HF_WastelandZ_SETUP/archive/refs/heads/main.zip)
> Everything in this repo in one file. No git or GitHub account needed.

**(EXPERIMENTAL DOCUMENTATION - UNTESTED)** — written with AI assistance; the
information may not be correct. As a server admin you use this kit at your own
risk. The full disclaimer is shown when you open the guide.

Everything an admin needs to stand up a **Wasteland-Z** dedicated server: the
game-server install kit with start/stop scripts, the gateway program, the
database schema, example configs, and the mission reward templates — with a
plain-English, step-by-step setup guide for **Windows and Linux**.

## What the guide covers

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
