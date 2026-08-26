# Gateway tests

Two suites. One is safe to run anywhere; the other wipes a database.

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
