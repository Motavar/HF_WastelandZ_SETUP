# Config files

## The server creates its own configs — you do not have to

**On its first start, Wasteland-Z writes a complete, ready-to-run set of
config files** into your server profile's `hf_wastelandz/configs/` folder,
each pre-filled with the current default values. You can boot the server with
**zero** config files present and it will generate everything, then edit the
generated files in place. This is the recommended path — the files the server
writes always match the version of the mod you are running, so there is no
chance of a stale hand-copied file drifting out of sync.

**Auto-created on first start (do not copy these from the kit unless you want
to pre-tune before the first boot):**

- `HFWastelandZ_server.conf` — master settings
- `HFWastelandZ_secrets.conf` — API-key file (written with a **placeholder** —
  you must edit it, see below)
- `HFWastelandZ_admins.conf` — staff roster (written **empty** — you must add
  yourself, see below)
- `HFWastelandZ_blacklist.conf`, `HFWastelandZ_command_tiers.conf`,
  `HFWastelandZ_loadouts.conf`
- `HFWastelandZ_town_tiers.conf`, `HFWastelandZ_loot_spawn_filter.conf`,
  `HFWastelandZ_item_catalog.conf`, `HFWastelandZ_vehicle_spawn.conf`
- `HFWastelandZ_server_message.txt`
- Per-map files under `configs/map/<MapName>/` — towns, spawn points, loot
  pools, world loot, and the three store catalogs (gun / general / vehicle).
  These regenerate automatically for **whatever map you load**, so a new map
  is supported out of the box.

## The two files you must author yourself

Everything above works on defaults except these two — the server writes them,
but you have to fill them in before your server is usable:

1. **`HFWastelandZ_secrets.conf`** — the gateway API key. Generated with a
   placeholder; replace it with your real key (must match the gateway's
   `config.py`). See `HFWastelandZ_secrets.conf.example` for the key-generation
   command.
2. **`HFWastelandZ_admins.conf`** — generated empty, so nobody is an admin
   until you add your Steam64 ID. See `HFWastelandZ_admins.conf.example`.

## Why the kit still ships `.example` files

They are **reference and pre-tuning copies**, not required drop-ins. The
documentation for every setting lives **inside each file** — every key sits
under a comment explaining what it does, its default, its range, and its
gameplay impact. Read them to learn the options, or, if you want to prepare
settings before the first boot, remove `.example` from a file's name and place
it in `hf_wastelandz/configs/`.

> **Heads-up on drift:** because a hand-copied file is frozen at the moment you
> copied it, a kit `.example` can fall behind the mod's built-in defaults after
> an update. If you are not deliberately overriding a setting, prefer the
> file the server generated — it is always current. The server reads config
> files at start, so restart after any edit.

| File | What it configures |
|---|---|
| `HFWastelandZ_server.conf.example` | **The master settings file** — economy, loot density, vehicles, towns, spawn rules, map markers, HVT, resupply pricing, debug logging. Start here. |
| `HFWastelandZ_secrets.conf.example` | The gateway API key. The only file with a password in it — never share it. |
| `HFWastelandZ_admins.conf.example` | Staff roster — Steam64 ID → role (TRUSTED / MOD / ADMIN / OWNER). |
| `HFWastelandZ_blacklist.conf.example` | Banned players. |
| `HFWastelandZ_command_tiers.conf.example` | Which role each chat/admin command requires. |
| `HFWastelandZ_loadouts.conf.example` | Faction starting loadouts — what a fresh spawn carries. |
| `HFWastelandZ_general_catalog.conf.example` | General-store catalog — items and prices. |
| `HFTownTiers.conf.example` | How many loot crates and vehicles a small / medium / large town gets. |
| `HFTowns_Arland.conf.example` | Per-map town list (names, positions, radii) — Arland. Other maps auto-generate on first boot as `HFTowns_<MapName>.conf`. |
| `HFLootPools_Arland.conf.example` | Per-map loot pool contents — what items spawn, with weights. |
| `HFLootFilter.conf.example` | Which building types can receive loot crates. |
