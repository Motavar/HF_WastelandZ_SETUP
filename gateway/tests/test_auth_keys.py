"""A key nobody chose must never authenticate anybody.

THE HOLE THIS CLOSES. check_auth() compares the caller's key against the
server's configured one:

    key = request.args.get("api_key", "")     # "" when none is sent
    if key == api_key:                        # "" == "" -> True

so a server whose configured api_key was "" authenticated EVERY anonymous
request - the economy database open to anyone who found the port, with
nothing in the log to suggest anything was wrong.

It was reachable. The legacy single-server fallback in _resolve_servers()
builds its key from getattr(config, "API_KEY", ""), so a config with
neither a SERVERS list nor an API_KEY produced exactly that.

A placeholder is refused for a different reason: those strings are
published in config.example.py and on the setup site, so running on one is
running on a key an attacker already has.

Safe to run against a live database - it only reads, and the two ports it
invents are never bound.

    python tests/test_auth_keys.py
"""
import os
import sys

GW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, GW)

if not os.path.exists(os.path.join(GW, "config.py")):
    raise SystemExit(
        "\n  No config.py found in:\n    " + GW + "\n"
        "\n  Run this from your RUNNING gateway folder, not the downloaded kit."
        "\n  config.py holds your database password and is never shipped.\n"
    )

import gateway  # noqa: E402

PASS = FAIL = 0


def check(label, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}: got {got!r}, want {want!r}")


def main():
    print("=" * 68)
    print(" EMPTY / PLACEHOLDER KEY MUST NEVER AUTHENTICATE")
    print("=" * 68)

    print("\n-- the classifier --")
    for bad in ("", "   ", None, "CHANGE_ME_UNIQUE_KEY_1",
                "CHANGE_ME_TO_A_RANDOM_STRING", "your_key_here",
                "example", "PLACEHOLDER", "todo"):
        check(f"rejected: {bad!r}", gateway._key_is_usable(bad), False)
    for good in ("4853567256d91d9d7aaae53ba6453bfcc0b7cf2d8596c7027bb11c83d6e0676c",
                 "a-perfectly-fine-key-nobody-published"):
        check(f"accepted: {good[:24]}...", gateway._key_is_usable(good), True)

    # A port whose configured key is "" - exactly what the legacy fallback
    # produced from a config with no SERVERS and no API_KEY.
    print("\n-- the live request path, with a server whose key is EMPTY --")
    gateway.SERVERS_BY_PORT[5999] = {
        "server_id": "hole-test", "port": 5999, "host": "127.0.0.1",
        "api_key": "", "hive_id": "default",
    }
    c = gateway.app.test_client()
    base = "http://127.0.0.1:5999"

    check("no api_key at all is REJECTED",
          c.get("/api/players", base_url=base).status_code, 401)
    check("empty api_key is REJECTED",
          c.get("/api/players?api_key=", base_url=base).status_code, 401)
    check("wrong api_key is REJECTED",
          c.get("/api/players?api_key=anything", base_url=base).status_code, 401)

    print("\n-- and with a PLACEHOLDER key --")
    gateway.SERVERS_BY_PORT[5999]["api_key"] = "CHANGE_ME_UNIQUE_KEY_1"
    check("the published example key is REJECTED",
          c.get("/api/players?api_key=CHANGE_ME_UNIQUE_KEY_1",
                base_url=base).status_code, 401)

    print("\n-- a real key still works (auth is not broken) --")
    real_srv = gateway.SERVERS[0]
    real_base = f"http://127.0.0.1:{real_srv['port']}"
    check("correct key on a real server is ACCEPTED",
          c.get(f"/api/players?api_key={real_srv['api_key']}",
                base_url=real_base).status_code, 200)
    check("wrong key on a real server is REJECTED",
          c.get("/api/players?api_key=wrong", base_url=real_base).status_code, 401)

    print("\n-- startup validation names the offenders --")
    bad = gateway._validate_keys([
        {"server_id": "a", "port": 1, "api_key": ""},
        {"server_id": "b", "port": 2, "api_key": "CHANGE_ME_UNIQUE_KEY_1"},
        {"server_id": "c", "port": 3, "api_key": real_srv["api_key"]},
    ])
    check("two of three flagged", sorted(s["server_id"] for s in bad), ["a", "b"])

    print("\n-- this gateway's OWN config passes --")
    check("no server in config.py has an unusable key",
          [s["server_id"] for s in gateway._validate_keys(gateway.SERVERS)], [])

    del gateway.SERVERS_BY_PORT[5999]

    print("\n" + "=" * 68)
    print(f" RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
