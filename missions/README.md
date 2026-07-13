# Missions — example pack

Missions in Wasteland-Z are built **in-game** with the admin tools (F8 →
MISSIONS) — you don't hand-write these files. This folder ships a small set of
**working examples** so you can drop them onto your server, see how a real
mission is put together, and build your own the same way.

> Full walkthrough: open the setup guide and click the **Mission Setup** tab —
> <https://motavar.github.io/HF_WastelandZ_SETUP/>

## What's in here

```
missions/
├── rewards/      ← what missions hand out (loot crates)
├── events/       ← the scenes (AI + structures + markers), built in Zeus
└── templates/    ← the mission flows (logic that ties events + rewards together)
```

### Example missions

| Mission | Tier | What it shows |
|---|---|---|
| `Mission_outpost1` | EASY | Announce → secure an outpost (wait until all AI dead) → drop four loot crates → then unlock a Zeus-placed vehicle and spawn two more on completion. Demonstrates events, waiting for AI, multiple rewards, and setting vehicle options (lock at start, unlock at the end). |
| `Mission_hack1` | MEDIUM | Announce → hack a terminal (circle-hold countdown) under a mission timeout → drop three loot crates → complete. Demonstrates the hack objective and a timeout fail-safe. |

### Events

| Event | Used by |
|---|---|
| `outpost1` | `Mission_outpost1` |
| `hack1` | `Mission_hack1` |

### Rewards

| Reward | Kind |
|---|---|
| `Guns_Crate` | Loot crate |
| `Ammo_Crate` | Loot crate |
| `Explosives_Crate` | Loot crate |
| `Rocket_Crate` | Loot crate |

## Install

Copy the three folders into your server profile:

```
missions/rewards/     →   <profile>/hf_wastelandz/missions/rewards/
missions/events/      →   <profile>/hf_wastelandz/missions/events/
missions/templates/   →   <profile>/hf_wastelandz/missions/templates/
```

`<profile>` is wherever your dedicated server's `-profile` flag points. Include
the `_index.json` in each folder — it's the manifest the server reads.

Then in-game (as admin): **F8 → MISSIONS → REWARDS → RELOAD**, and reload the
event/mission lists from the same panel. The two example missions appear in the
MISSIONS list; LOAD one into the editor to inspect how its logic is wired, or
add it to the pool and start it.

## Notes

- **Tiers are EASY / MEDIUM / HARD.** A mission's tier decides which map spawn
  markers can host it and which pool timer runs it.
- These are examples to learn from and copy — edit them, or build fresh ones
  in-game. More examples get added over time, so check back.
- `spots/` (per-map spawn markers) and `active_pool.json` (pool timers) are
  **your server's own** settings and aren't shipped here — you place spawn
  markers and set pool timers on your own server.
