# Starter Missions

A small, working set of example missions you can drop onto your server to see
the mission system run. Copy them in, restart, and the server will load them.

## How to enable them

Copy the contents of this `missions/` folder into your server profile's
`missions/` tree (`$profile:missions/`):

```
cp -r missions/templates/*  <profile>/missions/templates/
cp -r missions/triggers/*   <profile>/missions/triggers/
```

Then restart the server. The boot log should show lines like:

```
[HF][ADMIN] MissionRegistry: loaded N templates ...
[HF][ADMIN] TriggerEngine:  loaded N triggers ...
```

## What's here

```
missions/
  templates/
    _index.json                    manifest of templates the server loads
    cache/easy_cache_starter.json  a simple loot-cache mission
    outpost/medium_outpost_starter.json  a small outpost mission
  triggers/
    _index.json                    manifest of triggers the server evaluates
    server_uptime_warmup.json      no missions spawn in the first 5 minutes after boot
    cache_cadence.json             keeps 1 cache mission active, min 10 min gap
```

## Customizing

The two starter templates ship with empty `ai_prefabs` (an empty string means
"skip — don't spawn AI"). To make them spawn enemies, edit those entries to point
at a real group prefab from your map — for example a
`Prefabs/Groups/<faction>/Group_<faction>_RifleSquad.et` resource path.

The easiest way to build missions is the in-game editor:

1. Enter Game Master as an admin.
2. `/mission new CACHE`
3. Place your AI groups and props.
4. `/mission save`

The template is written to `<profile>/missions/templates/cache/<name>.json` with
the prefab paths filled in from what you placed.
