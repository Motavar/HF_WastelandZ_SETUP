# Wasteland-Z — Server Setup

> ### 📖 [Read the setup guide](https://motavar.github.io/HF_WastelandZ_SETUP/)
> The full step-by-step as a web page — pick your mod version, pick Windows or
> Linux, and follow the numbered steps.
>
> ### ⬇ [Download the kit (ZIP)](https://github.com/Motavar/HF_WastelandZ_SETUP/archive/refs/heads/main.zip)
> Everything in this repo in one file. No git or GitHub account needed.

**(EXPERIMENTAL DOCUMENTATION - UNTESTED)** — written with AI assistance; the
information may not be correct. As a server admin you use this kit at your own
risk. The full disclaimer is shown when you open the guide.

## Which gateway do I need?

**The mod updates itself** from the Reforger Workshop every time your server
starts. **The gateway is the part you host**, and it has to match the mod.

| Your mod | Needs gateway | Folder in this repo |
|---|---|---|
| **1.0.18** | **0.9.6** | [`gateway-1.0.18/`](gateway-1.0.18) |
| **1.0.16** | **0.7.1** | [`gateway-1.0.16/`](gateway-1.0.16) |

Not sure which you have? Your server console prints it on start as
`[HF] WastelandZ <version>`.

> ⚠ **Mod 1.0.16 and gateway 0.7.1 are what the Workshop serves today.** The
> 1.0.18 kit is here and ready, but the mod is not on the Workshop yet — until
> it is, **stay on 1.0.16 / 0.7.1.**

> ⚠ **The two halves are not interchangeable.** The mod checks the gateway
> version at startup. On a mismatch it prints `GATEWAY VERSION MISMATCH` every
> 60 seconds **and keeps running anyway**, while saves fail. It is a warning,
> not a stop — so the console is the only place it shows. Update both in the
> same sitting.

**Moving to 1.0.18 changes the database.** Back up before you start the new
gateway for the first time — once the database is upgraded, an older gateway
refuses to start against it, so the dump is the only way back:

```
mysqldump -u <user> -p wastelandz > wz-backup-before-0.9.6.sql
```

The gateway applies its own migrations on start. **You never run SQL by hand.**

See [`RELEASES.md`](RELEASES.md) for the version history, and the
**Upgrade the Mod + Gateway** tab of the guide for the step-by-step.

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

## ⚠ One setting you must not skip

Your `server1.json` needs this block inside `"game"`, and the example configs
in this kit already ship it:

```json
"missionHeader": {
  "m_sName": "WASTELAND Z",
  "m_eSaveTypes": 0,
  "m_bIsSavingEnabled": false
}
```

With the game's own saving **on**, the engine restores a saved copy of the
world on start and Wasteland-Z then builds the world again on top of it — so
you get **two of everything**. The symptom admins report first is **every town
listed twice**; stores, markers and map circles double the same way.

Nothing is lost by turning it off. Money, bank, gear, position and vehicles all
live in your MySQL database through the gateway.

## What the guide covers

# 🟢 [Open the guide → ( START HERE )](https://motavar.github.io/HF_WastelandZ_SETUP/)

(Linux users: the guide's Step 1 clones this repo straight onto the server —
no ZIP needed.)

- **New — Server Setup:** SteamCMD, the Reforger dedicated server, MySQL,
  Python, the gateway, and the ready-made `server1.json`.
- **Upgrade the Mod + Gateway:** the two halves that move together, with the
  backup step, the migration, and how to check it worked.
- **Upgrade the Game (Steam):** updating Arma Reforger itself.
- **Server Administration, Hives & Gear, Mission Setup, Troubleshooting.**

## What's in this repo

| Folder / file | What it is |
|---|---|
| `index.html` | The step-by-step setup guide (open it in a browser). |
| `gateway-1.0.18/` | Gateway **0.9.6** — for mod 1.0.18. Includes `migrate.py`, the pending migrations and the test suite. |
| `gateway-1.0.16/` | Gateway **0.7.1** — for mod 1.0.16, the current Workshop release. |
| `RELEASES.md` | Version history and which gateway each mod needs. |
| `gateway-1.0.18/setup_database.sql` | Every database table, defined in one file. **The gateway applies it on every start**, so you never run SQL by hand. It only ever adds — running it again changes nothing. |
| `gateway-1.0.18/migrate.py` | Applies the schema on start, then any pending data change. Records what it applied so nothing runs twice, and refuses to remove anything unless you deliberately pass `--allow-destructive`. |
| `gateway-1.0.18/tests/` | The tests we run against the gateway, shipped so you can run them yourself. ⚠ One of them **wipes** the database it is pointed at — read [`gateway-1.0.18/tests/README.md`](gateway-1.0.18/tests/README.md) first. |
| `*/config.example.py` | Settings template — copy to `config.py` and fill in. Your `config.py` is never in this repo, so an update cannot overwrite it. |
| `*/start_gateway.bat` | Windows one-click start. |
| `configs/` | Example server settings (loot, vehicles, towns, admins, loadouts…). [`configs/README.md`](configs/README.md) lists each file; every setting is documented inside its file. |
| `missions/` | Reward templates for the mission system + a guide to authoring missions in-game. |
| `server/` | Game-server kit: SteamCMD install script, example `server1.json`, start/stop batch files with auto-restart loop. |

## Requirements

- A Windows or Linux machine that stays on. The guide installs everything
  else: the Reforger dedicated server downloads via SteamCMD (no Steam
  account needed), the **Wasteland-Z** mod auto-downloads from the Reforger
  Workshop on first server start, and it walks through **Python 3.12+**
  and **MySQL 8**.

## The guide as a web page

The guide is published with GitHub Pages at
**<https://motavar.github.io/HF_WastelandZ_SETUP/>**. Running a fork? Enable it
on yours: **Settings → Pages → Deploy from a branch → `main` / `/ (root)`** —
live at `https://<your-username>.github.io/HF_WastelandZ_SETUP/` after a
minute.

---

By **Motavar** · [Wasteland-Z.com](https://wasteland-z.com) · [HeavyForge.com](https://heavyforge.com) · [Motavar@Judgement.net](mailto:Motavar@Judgement.net)
