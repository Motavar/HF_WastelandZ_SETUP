# Wasteland-Z — Releases

What to run, what each release needed, and how to move between them.

**The mod updates itself.** Reforger downloads it from the Workshop every time your
server starts, so you are always on the current release and there is nothing to
install. **The gateway is the part you host**, and it is the part that can fall
behind. That is what this file is for.

---

## What you should be running right now

| | Version | Where |
|---|---|---|
| **Mod** | **1.0.16** | Workshop — automatic, nothing to do |
| **Gateway** | **0.7.1** | `gateway/` on the `main` branch of this repo |
| **Game server** | **Arma Reforger 1.8.0.10** or newer | SteamCMD |
| **Database** | 9 tables, from `gateway/setup_database.sql` | you run it once, by hand |

Check your gateway by looking at the first line it prints on start:

```
  WastelandZ Gateway v0.7.1
```

If it says anything else, see the table below.

> **A newer gateway is not better.** `0.9.0` exists on the `beta` branch and pairs
> with an unreleased mod build. Run it against mod 1.0.16 and gear keeps saving —
> which is exactly the trap. Starting 0.9.0 copies your gear into its new table
> once; that copy then sits still while players keep writing the old column. Update
> the mod later and gear **appears to roll back** to the day you started 0.9.0.
> Stay on 0.7.1 until the release notes here say otherwise.
>
> **When the next release does land, update the mod FIRST, then the gateway.** The
> order is not symmetric: mod-first fails visibly and recovers, gateway-first looks
> fine and drifts.

---

## Version history

Newest first. "Gateway" is the minimum that release needs.

| Date | Mod | Gateway | What it needed from you |
|---|---|---|---|
| *unreleased* | *next* | **0.9.0** | In testing on the `beta` branch. Not on the Workshop. Do not install. **Mod first, then gateway.** |
| 2026-08-26 | 1.0.16 | **0.7.1** | **Security update — re-download the gateway.** See below. |
| 2026-08-21 | **1.0.16** | 0.7.1 | Nothing. Towing keybinds returned (B sling, R heli start), loose props re-seat. |
| 2026-08-16 | 1.0.15 | 0.7.1 | **Arma Reforger 1.8.0.10.** The server does not start on older builds. |
| 2026-08-14 | 1.0.15 | 0.7.1 | Nothing. |
| 2026-08-09 | — | 0.7.1 | Nothing. Reward and vehicle-trunk loot pools became per-map. |
| 2026-07-16 | — | **0.7.1** | **Critical patch.** Replace `gateway.py`. Admin `/money` drops were not written to the database and vanished on restart. |
| 2026-07-16 | — | 0.7.0 | Nothing. Weight/speed dial, realtime stamina tuning. |
| 2026-07-04 | **1.0.0** | 0.7.0 | First public release. |
| 2026-06-30 | — | **0.7.0** | Hive-shared schema. |

---

## 2026-08-26 — Security update, gateway 0.7.1

**Re-download the gateway even though the version number has not changed.**

A server configured with an **empty** or **placeholder** `api_key` authenticated
every anonymous request. `check_auth` reads the `api_key` parameter with a default
of `""`, so a configured key of `""` matched a caller who sent no key at all — and
answered them. That reaches your economy database, and nothing in the log said so.

It was reachable from a `config.py` with no `SERVERS` list and no `API_KEY`.
Placeholder keys are now refused for the same reason: `CHANGE_ME_*` is published in
this kit's own `config.example.py`, so running on one is running on a key anybody
can read.

The gateway now refuses to start and names the offending servers, and refuses the
request as well, so neither path can be missed.

**The version stays 0.7.1 on purpose.** The mod checks it for exact equality;
calling this 0.7.2 would print `GATEWAY VERSION MISMATCH` on your console every 60
seconds and warn your admins in game, for a gateway that is correct.

**What to do:** follow the five-step update on the setup site's **Update Gateway**
tab. Your `config.py` is untouched. If your gateway refuses to start afterwards
and names a server, that server's key was one of the bad ones — generate a real
one:

```
python -c "import secrets; print(secrets.token_hex(32))"
```

Put it in `config.py` under `SERVERS`, and the **same** value in that server's
`HFWastelandZ_secrets.conf` (`API_KEY` line).

---

## 2026-08-21 — Mod 1.0.16

No gateway change, no database change, no config change.

Towing and slinging keybinds ship and are rebindable in **Options → Controls** — `B`
for the sling from the pilot seat, `R` for the instant helicopter start. Locked
mission rewards refuse tow and sling. The heli tow menu is engine-off only. Loose
props re-seat server-side instead of falling through the world.

---

## 2026-08-16 — Arma Reforger 1.8.0.10 required

**The server does not start on an older game build**, and there is no
older-compatible build of the mod to fall back to.

1.8.0.10 removed 137 script API members with **no deprecation cycle** — the
published deprecation list was byte-identical to the previous version's, so nothing
warned in advance. Three of those removals sat in mod code paths.

Update the game server with SteamCMD and restart. See the **Upgrade** tab.

---

## 2026-07-16 — Critical patch, gateway 0.7.1

Admin `/money` drops were not written to the database and vanished on the next
restart. Everything else kept working, which is why it was easy to miss.

Replace `gateway.py` and restart. No schema change.

---

## 2026-06-30 — Gateway 0.7.0, hive-shared schema

Money, bank and gear became shared across every server pointing at the same
database with the same `HIVE_ID`.

On this schema a hive shares **all three** — there is no setting that shares money
but keeps gear separate. So every server in a hive should run the **same mod set**:
gear is stored as item references, and an item whose mod is missing on the
destination cannot be restored there.

Splitting gear into groups while keeping one bank is what the next release adds.

---

## How to upgrade the gateway

One procedure, every release, whether it changed one file or twenty. It is on the
setup site under **Update Gateway**, and it is the same five steps every time:

**1. Stop the gateway and back up the whole folder**

The whole folder, not just `gateway.py` — any file in the kit can change. Put the
extra `config.py` copy **outside** the folder you are about to overwrite.

**2. Update the reference kit**

`git pull` in your clone, or download the ZIP and unpack it over the same folder.

**3. Copy the gateway files across**

`cp -r /opt/wastelandz/gateway/. /opt/wastelandz-gateway/` on Linux,
`xcopy /E /Y D:\wastelandz\gateway D:\wastelandz-gateway\` on Windows.

There is no `config.py` in the repo, so nothing can overwrite yours.

**4. Install requirements**

`pip install -r requirements.txt`. Every time, no exceptions — it does nothing when
nothing is new, and skipping it is how an upgrade half-lands.

**5. Restart and check**

You want `status: ok` from `/api/ping` and the version banner naming the version you
just installed.

---

## Branches

| Branch | Channel | Gateway | Who it is for |
|---|---|---|---|
| `main` | **Production** | 0.7.1 | Everyone running a live server |
| `beta` | **Test** | 0.9.0 | Testing the next release, never on a live server |

Both keep the kit at the same path — `gateway/` — so the setup and update steps are
identical. Only the clone differs:

```
git clone https://github.com/Motavar/HF_WastelandZ_SETUP.git            # production
git clone -b beta https://github.com/Motavar/HF_WastelandZ_SETUP.git    # beta
```

**Documentation for an older release** is the repo at that release's tag. The docs
as they stood at 1.0.16 are at
`https://github.com/Motavar/HF_WastelandZ_SETUP/blob/v1.0.16/index.html`, and the
kit that shipped with it is `gateway/` on the same tag.
