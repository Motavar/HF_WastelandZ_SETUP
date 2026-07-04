# Config files

The documentation for every setting is **inside each file** — every key sits
under a comment explaining what it does, its default, its range, and the
gameplay impact. Open any file in a text editor and read the block above the
key you want to change.

**To use one:** remove `.example` from the name and place it in your server
profile's `hf_wastelandz/configs/` folder (created on the server's first
start). The server reads config files at start — restart after editing.
Wasteland-Z writes starter copies of most of these on first boot; the kit
versions exist so you can prepare or reset them.

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
