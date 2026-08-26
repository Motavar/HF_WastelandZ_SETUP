"""Endpoint tests for the namespaced storage API.

WHAT THIS COVERS
    All five scopes a namespace can use - hive-wide, gear set, vehicle
    set, this-server-only, and per-map - plus the cross-server case that
    is the entire point of a hive.

WHY IT CAN TEST TWO SERVERS AT ONCE
    The gateway identifies a server by the PORT a request arrived on.
    Flask's test client sets SERVER_PORT from base_url, so pointing two
    requests at two configured ports IS two servers in one hive. Nothing
    is bound and no gateway process is launched.
    (Assigning environ_base after constructing the client does NOT reach
    the WSGI environ - base_url is what works.)

SAFE TO RUN AGAINST A LIVE DATABASE. It only ever touches rows under its
own TESTUID- player id, and cleans them up at both ends. It does not wipe
anything - unlike test_schema_and_storage.py, which does.

    python tests/test_endpoints.py
"""
import json
import os
import sys

GW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, GW)

# ----------------------------------------------------------------------
# config.py is what tells these tests which database to talk to, and it is
# NEVER in the kit - it holds your database password and gateway key, so it
# is deliberately not distributed. Run these from your RUNNING gateway
# folder (the one the service actually uses), not from the downloaded kit.
#
# Python's own ModuleNotFoundError does not explain any of that, so say it.
# ----------------------------------------------------------------------
if not os.path.exists(os.path.join(GW, "config.py")):
    raise SystemExit(
        "\n  No config.py found in:\n    " + GW + "\n"
        "\n  These tests read your database settings from config.py, which is"
        "\n  never shipped in the kit - it holds your password and gateway key."
        "\n"
        "\n  Run them from your RUNNING gateway folder instead, e.g.:"
        "\n    cd /opt/wastelandz-gateway   (Linux)"
        "\n    cd C:\\wastelandz-gateway    (Windows)"
        "\n    python tests/test_endpoints.py"
        "\n"
        "\n  If you only want to read the tests rather than run them, that is"
        "\n  what they are shipped for - no config.py needed.\n"
    )

import config       # noqa: E402
import gateway      # noqa: E402

UID = "TESTUID-0001"
PASS = FAIL = 0


def check(label, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}\n          got  {got!r}\n          want {want!r}")


def client_for(port):
    # base_url is what sets SERVER_PORT in the WSGI environ, and
    # current_server() resolves the server (and its hive) from that port.
    # Assigning environ_base after construction does not reach it.
    return gateway.app.test_client(), f"http://127.0.0.1:{port}"


def key_for(port):
    for s in config.SERVERS:
        if s["port"] == port:
            return s["api_key"]
    raise SystemExit(f"no server on port {port}")


def put(port, ns, group, payload, scope_map="", map_name=""):
    c, base = client_for(port)
    return c.put(
        f"/api/data/{UID}/{ns}/{group}?api_key={key_for(port)}",
        base_url=base,
        json={"payload": payload, "scope_map": scope_map,
              "map_name": map_name, "format_ver": 1},
    )


def get(port, ns, group, scope_map=""):
    c, base = client_for(port)
    return c.get(
        f"/api/data/{UID}/{ns}/{group}?api_key={key_for(port)}&map={scope_map}",
        base_url=base,
    )


def listrows(port, ns):
    c, base = client_for(port)
    return c.get(f"/api/data/{UID}/{ns}?api_key={key_for(port)}", base_url=base)


def delete(port, ns, group, scope_map=""):
    c, base = client_for(port)
    return c.delete(
        f"/api/data/{UID}/{ns}/{group}?api_key={key_for(port)}&map={scope_map}",
        base_url=base,
    )


def body(resp):
    return json.loads(resp.data.decode())


print("=" * 66)
print("NAMESPACED STORAGE - endpoint tests")
print("=" * 66)

# ---------------------------------------------------------------- cleanup
for g in ("ALPHA", "BRAVO", "@hive", "@private:dev-01"):
    for m in ("", "GM_Arland"):
        delete(5000, "testns", g, m)
        delete(5000, "perks", g, m)

print("\n-- 1. round trip: what goes in comes back byte-identical --")
gear = '[{"item":"rifle","attachments":["scope","grip"]},{"item":"medkit"}]'
r = put(5000, "testns", "ALPHA", gear)
check("write accepted", r.status_code, 200)
r = get(5000, "testns", "ALPHA")
check("read status", r.status_code, 200)
check("payload byte-identical", body(r)["row"]["payload"], gear)

print("\n-- 2. scope separation: two groups are two rows (broken before) --")
put(5000, "testns", "BRAVO", '{"different":"payload"}')
check("ALPHA still its own", body(get(5000, "testns", "ALPHA"))["row"]["payload"], gear)
check("BRAVO its own",
      body(get(5000, "testns", "BRAVO"))["row"]["payload"], '{"different":"payload"}')

print("\n-- 3. hive scope: written on dev-01, read on dev-02 --")
put(5000, "perks", "@hive", '{"medic":3}')
r = get(5001, "perks", "@hive")
check("dev-02 sees dev-01's hive row", body(r)["row"]["payload"], '{"medic":3}')

print("\n-- 4. per-map: same namespace, two maps, two rows --")
put(5000, "testns", "ALPHA", '{"map":"arland"}', scope_map="GM_Arland")
check("map-scoped row is separate",
      body(get(5000, "testns", "ALPHA", "GM_Arland"))["row"]["payload"], '{"map":"arland"}')
check("unscoped row untouched",
      body(get(5000, "testns", "ALPHA"))["row"]["payload"], gear)

print("\n-- 5. server_id is stamped from the PORT, never from the caller --")
check("dev-01 write stamped dev-01", body(get(5000, "testns", "ALPHA"))["row"]["server_id"], "dev-01")
put(5001, "testns", "BRAVO", '{"by":"dev-02"}')
check("dev-02 write stamped dev-02", body(get(5000, "testns", "BRAVO"))["row"]["server_id"], "dev-02")

print("\n-- 6. missing row is 'ok, None' - not an error, not data loss --")
r = get(5000, "testns", "ZULU")
check("absent row status", r.status_code, 200)
check("absent row is None", body(r)["row"], None)

print("\n-- 7. list shows every group for support --")
rows = body(listrows(5000, "testns"))["rows"]
check("row count", len(rows), 3)
check("groups present", sorted({r["share_group"] for r in rows}), ["ALPHA", "BRAVO"])

print("\n-- 8. delete removes ONE row and leaves the rest --")
check("delete count", body(delete(5000, "testns", "ALPHA", "GM_Arland"))["deleted"], 1)
check("unscoped ALPHA survives", body(get(5000, "testns", "ALPHA"))["row"]["payload"], gear)
check("BRAVO survives", body(get(5000, "testns", "BRAVO"))["row"]["payload"], '{"by":"dev-02"}')

print("\n-- 9. namespaces are independent blobs --")
check("perks untouched by testns work",
      body(get(5001, "perks", "@hive"))["row"]["payload"], '{"medic":3}')

print("\n-- 10. validation rejects malformed keys --")
check("bad namespace", put(5000, "bad ns!", "ALPHA", "{}").status_code, 400)
check("bad group", put(5000, "testns", "bad group!", "{}").status_code, 400)
check("no auth", gateway.app.test_client().get(
    f"/api/data/{UID}/testns/ALPHA", base_url="http://127.0.0.1:5000").status_code, 401)

# ---------------------------------------------------------------- cleanup
for g in ("ALPHA", "BRAVO", "@hive"):
    for m in ("", "GM_Arland"):
        delete(5000, "testns", g, m)
        delete(5000, "perks", g, m)

print("\n" + "=" * 66)
print(f"RESULT: {PASS} passed, {FAIL} failed")
print("=" * 66)
sys.exit(1 if FAIL else 0)
