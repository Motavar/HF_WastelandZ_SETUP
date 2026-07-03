# Missions — how they work on your server

Missions in Wasteland-Z are built **in-game** with the admin tools — you never
hand-write mission files. You author a scene once, chain it into a mission
flow, and the server's mission pool spawns it automatically on a schedule you
control.

This folder ships the one thing that DOES need to be installed by hand: the
five **seed reward templates** that missions hand out (loot crates and a
flyable helicopter).

## One-time setup: install the reward templates

Copy the `rewards/` folder into your server profile:

```
missions/rewards/   →   <profile>/hf_wastelandz/missions/rewards/
```

`<profile>` is wherever your dedicated server's `-profile=` flag points.
Restart the server (or, in-game: F8 → MISSIONS → REWARDS → RELOAD).

| Template | What players get |
|---|---|
| `weapons_crate` | Sniper rifles + suppressed AKs with magazines. |
| `rockets_crate` | RPG-7s and LAWs with rockets. |
| `explosives_crate` | Grenades, smoke, C-4, mines. |
| `huey_gunship` | A UH-1H gunship — spawns locked, damaged and out of fuel; players fight for it, repair it, and fly it home. |
| `heli_repair_kit` | Wrench + medical supplies to fix up the Huey. |

You can adjust the contents by editing the JSON files, then RELOAD.

## How the pieces fit together

- A **reward** is what players get — a crate of loot or a vehicle.
- An **event** is a scene placed in the world — enemies, props, and markers
  showing where vehicles, loot, and reinforcements appear.
- A **mission** is a flow that strings events and logic together —
  e.g. *spawn the outpost → wait until all AI are dead → spawn the
  weapons crate → mission complete*.
- The **mission pool** is the auto-spawner. Put missions into its
  SMALL / MEDIUM / LARGE rotations and it keeps them cycling on a
  per-size schedule, away from players, with cooldowns.

## Authoring your first mission (in-game, ~10 minutes)

Everything happens in the admin menu: **F8 → MISSIONS**.

1. **Build the scene.** EVENTS panel: type a name, NEW EVENT. Walk to the
   location, open Zeus, and place your enemies, cover, and props — the first
   thing you place becomes the scene's anchor. Use the DROP buttons
   (VEH / LOOT / PATROL / WAVE) to mark where the vehicle, loot crate,
   patrols, and reinforcements go — each marker points the way YOU are
   facing when you drop it. SAVE EVENT.
2. **Build the flow.** MISSION EDITOR panel: add your event from the library,
   then add logic steps — `WAIT_UNTIL_AI_DEAD`, `SPAWN_REWARD` with a reward
   name (e.g. `weapons_crate`), `MISSION_COMPLETE`. SAVE MISSION.
3. **Test it.** RUNTIME panel: spawn the mission by name, play it through.
4. **Put it on rotation.** MISSION POOL panel: select the mission and
   ADD → POOL under the size you want. PAUSE / RESUME per size or all at
   once, whenever you like.

## Where mission files live on your server

```
<profile>/hf_wastelandz/missions/
├── rewards/            ← the templates from this folder (+ any you add)
├── events/             ← saved scenes        (*.event.json)
├── templates/          ← saved missions      (*.mission.json)
├── <MapName>/spots/    ← per-map spawn points
└── active_pool.json    ← auto-spawner settings (created on first boot)
```

Everything except `rewards/` is created and managed by the in-game tools —
you don't need to touch these files. If you want to fine-tune the spawn
cadence, `active_pool.json` can be edited by hand (per-size intervals in
seconds, plus a master `enabled` switch); the server re-reads it on restart.
