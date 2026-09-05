# Gateway tests

Two suites. One is safe to run anywhere; the other wipes a database.

> **Run them from your RUNNING gateway folder**, not from the downloaded
> kit — `/opt/wastelandz-gateway` on Linux, `C:\wastelandz-gateway` on
> Windows.
>
> They read your database settings from `config.py`, and that file is
> **never shipped in the kit** because it holds your database password and
> gateway key. Run from the kit folder and both tests stop and say so,
> rather than failing with an unexplained import error.
>
> They are also shipped simply to be **read**. If you only want to see what
> is being claimed and how it is checked, no `config.py` is needed.

---

## `test_auth_keys.py` — safe

```
python tests/test_auth_keys.py
```

Proves a key nobody chose can never authenticate anybody.

`check_auth()` compares the caller's key against the configured one, and an
absent `api_key` parameter arrives as `""`. So a server configured with an
empty key made `"" == ""` true and **answered every anonymous request** —
the economy database open to anyone who found the port, with nothing in the
log to suggest a problem.

It was reachable: the legacy single-server fallback builds its key from
`getattr(config, "API_KEY", "")`, so a config with neither a `SERVERS` list
nor an `API_KEY` produced exactly that.

Placeholders are refused too. Those strings are published in
`config.example.py` and on the setup site, so running on one is running on a
key an attacker already has.

Read-only, and the ports it invents are never bound, so it is safe against a
live database. It also asserts that **this** gateway's own `config.py` passes.

---

## `test_config_maintenance.py` — safe, and needs no `config.py`

```
python tests/test_config_maintenance.py
```

The gateway **edits a file the admin wrote**. This is what says it may not
damage it.

Two paths write to `config.py` on the same start: `ensure_config_defaults()`
appends settings this build expects, and `retire_legacy_config_keys()` deletes
settings it no longer reads. The second is the only code in the gateway that
**deletes** from an admin's own file, and the whole suite exists because of it.

Every fault below was found by writing these cases, not by an admin losing
something:

- **Line endings flipping between operating systems.** The autofill appended
  with the platform default and read without `newline=""`, so reading turned
  CRLF into LF and writing on Windows turned it back. A Linux admin's LF
  `config.py` became CRLF simply by being touched by a Windows gateway, and the
  reverse on the other side. Nothing breaks — Python does not care — but a file
  that rewrites itself when nobody asked is a file nobody trusts.
- **A backup destroying an earlier backup.** The name carries a
  second-resolution timestamp and was opened `"w"`. Two starts inside one
  second collided and the second truncated the first — and what it destroyed
  could be the only copy of what the admin had before any of this ran.
- **Two backups per boot**, one from each path, left beside `config.py`.
- **Splitting a line Python considers whole.** `str.splitlines()` also breaks on
  form feed, vertical tab and the Unicode separators, none of which end a line
  in Python source. A form feed is legal in a `.py` file.

It also proves both **fail-closed** guards: neither path writes anything if the
result would not `ast.parse()`. A stale setting is harmless; a `config.py`
Python cannot read stops the gateway.

The functions are extracted from `gateway.py` by AST and run in a sandbox, so
the suite exercises the **shipped source** rather than a copy that can drift
away from it. Nothing imports `gateway.py` and nothing starts.

> Unlike the others, this one needs **no `config.py` and no database** — every
> case runs against a temporary file — so it also runs from the downloaded kit.

---

## `test_endpoints.py` — safe

```
python tests/test_endpoints.py
```

Exercises the namespaced storage API across all five scopes, including
the cross-server case that is the whole point of a hive.

Only ever touches rows under its own `TESTUID-` player id and cleans up
at both ends, so it is safe against a live database.

It tests two servers at once without launching anything: the gateway
identifies a server by the **port a request arrived on**, and Flask's
test client sets `SERVER_PORT` from `base_url`. Two ports = two servers
in one hive.

> Setting `environ_base` after constructing the test client does **not**
> reach the WSGI environ. `base_url` is what works. Worth knowing before
> spending an evening on a 401.

---

## `test_schema_and_storage.py` — WIPES THE DATABASE

```
python tests/test_schema_and_storage.py --i-know-this-wipes-the-db
```

**It drops every table in the database `config.py` points at.** Two
interlocks stand in the way:

1. The flag is required, so it cannot be run by reflex.
2. It refuses outright if `players` holds rows that are not fixture
   data — which is the mistake that actually costs something: running it
   deliberately, against the wrong database.

### What it proves, and why it exists

The schema used to be defined in **two places** — `setup_database.sql`
for a fresh install, and `migrations/*.sql` for an upgrade. Keeping two
definitions in agreement is a discipline, and disciplines lapse. This one
did:

`player_marker_prefs` was created **with** an explicit
`COLLATE utf8mb4_unicode_ci` by the schema file, and **without** one by
the migration — which therefore inherited the server default,
`utf8mb4_0900_ai_ci` on MySQL 8.0.

The visible consequence was a hard error on any join between that table
and `players`:

```
ERROR 1267 (HY000): Illegal mix of collations
  (utf8mb4_unicode_ci,IMPLICIT) and (utf8mb4_0900_ai_ci,IMPLICIT)
```

A query that **passes on a developer's fresh database and fails on every
server in the field.**

`setup_database.sql` is now the single source of the schema and is
applied on every start, so a fresh install and an upgrade execute the
same SQL. **This test is what keeps that true.** It builds a database
both ways and diffs `information_schema`.

> Any difference between the two is a defect, not a curiosity.

It also checks the things an admin would notice if they broke: money,
bank, ATM history and gear surviving the upgrade; the legacy
`players.inventory` column being kept as a rollback path; a restart
changing nothing; and a malformed legacy payload being skipped rather
than copied.

---

## `fixtures/published_0_7_1_schema.sql`

The schema of the **last published release** (gateway `0.7.1`, nine
tables, no `player_data`, no migration ledger), so the upgrade path is
tested against the shape real admins actually have rather than a
reconstruction of it.

Derived from a genuine pre-upgrade `mysqldump`, with **every `INSERT`
removed** — the real dump carried live player UIDs, display names and
balances, and a fixture must never carry anyone's data into a
repository. The seed rows at the bottom are synthetic and deliberately
awkward: one player with an empty inventory, one with invalid JSON, and
distinctive balances so a failure is obvious at a glance.
