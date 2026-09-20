"""The gateway edits an admin's config.py. It must never damage it.

WHAT THIS GUARDS. Two paths write to config.py on the same start:

    ensure_config_defaults()      appends settings this build expects
    retire_legacy_config_keys()   deletes settings this build no longer reads

The second one is the only code in the gateway that DELETES from a file the
admin wrote, so the whole of this suite exists because of it.

THE FAULTS IT LOCKS OUT, all found by writing these cases:

  LINE ENDINGS FLIPPING BETWEEN OPERATING SYSTEMS. The autofill appended with
  the platform default and read without newline="", so reading turned CRLF into
  LF and writing on Windows turned it back. A Linux admin's LF config.py flipped
  to CRLF simply by being touched by a Windows gateway, and the reverse on the
  other side. Nothing breaks - Python does not care - but a file that rewrites
  itself when nobody asked is a file nobody trusts. Both paths now pass
  newline="" on every read and write, which disables translation in BOTH
  directions.

  A BACKUP DESTROYING AN EARLIER BACKUP. The name carries a second-resolution
  timestamp and was opened "w". Two starts inside one second collided and the
  second truncated the first - and what it destroyed could be the only copy of
  what the admin had before any of this ran. Now opened "x" (exclusive create)
  with a walk to a free name.

  TWO BACKUPS PER BOOT. Each path took its own, leaving near-identical litter
  beside config.py. They now share one.

  SPLITTING A LINE PYTHON CONSIDERS WHOLE. str.splitlines() also breaks on form
  feed, vertical tab and the Unicode separators, none of which end a line in
  Python source. A form feed is legal in a .py file.

HOW IT TESTS. The functions are extracted from gateway.py by AST and executed
in a sandbox, so this exercises the SHIPPED SOURCE rather than a copy that can
drift away from it. Nothing imports gateway.py and nothing starts.

Safe to run anywhere. It needs no config.py and no database - every case runs
against a temporary file - so unlike the other suites this one also runs from
the downloaded kit.

    python tests/test_config_maintenance.py
"""
import ast
import io
import os
import re
import sys
import tempfile
import types
from datetime import datetime

GW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GW = os.path.join(GW_DIR, "gateway.py")

if not os.path.exists(GW):
    raise SystemExit("\n  gateway.py not found next to this tests/ folder:\n    " + GW_DIR + "\n")

SRC = io.open(GW, encoding="utf-8", newline="").read()
TREE = ast.parse(SRC)

WANTED = ["_config_eol", "_config_lines", "_backup_config_once",
          "ensure_config_defaults", "retire_legacy_config_keys"]

_pieces = []
for _name in WANTED:
    _node = next((n for n in TREE.body
                  if isinstance(n, ast.FunctionDef) and n.name == _name), None)
    if _node is None:
        raise SystemExit(f"\n  {_name}() not found in gateway.py — has it been renamed?\n")
    _pieces.append(ast.get_source_segment(SRC, _node))
CODE = "\n\n".join(_pieces)

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok    {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def run(text, autofill, retired=("DB_POOL_SIZE",), predir=None):
    """Run both paths over a throwaway config.py and report what happened."""
    d = predir or tempfile.mkdtemp()
    path = os.path.join(d, "config.py")
    io.open(path, "w", encoding="utf-8", newline="").write(text)

    cfg = types.ModuleType("config")
    cfg.__file__ = path
    exec(compile(text, path, "exec"), cfg.__dict__)

    said = []
    sandbox = {
        "config": cfg, "re": re, "ast": ast, "os": os, "datetime": datetime,
        "CONFIG_AUTOFILL": list(autofill),
        "RETIRED_CONFIG_KEYS": list(retired),
        "_CONFIG_BACKUP": None,
        "print": lambda *a, **k: said.append(" ".join(str(x) for x in a)),
    }
    exec(CODE, sandbox)
    sandbox["ensure_config_defaults"]()
    sandbox["retire_legacy_config_keys"]()

    after = io.open(path, encoding="utf-8", newline="").read()
    backups = sorted(f for f in os.listdir(d) if ".bak-" in f)
    return after, backups, said, d


# One entry, shaped like a real one: the comment carries an embedded newline,
# which is what made the endings leak in the first place.
AUTOFILL = [("DB_POOL_SIZE_v2", 32,
             "Pooled MySQL connections. 32 is the connector's maximum.\n"
             "# Keep HTTP_THREADS x number_of_servers <= this.")]

HAS_TOP_LEVEL = re.compile(r"(?m)^DB_POOL_SIZE\s*=")


def main():
    print("=" * 68)
    print(" config.py maintenance — the gateway must not damage an admin's file")
    print("=" * 68)

    print("\n-- an LF file stays pure LF (a Linux config on a Windows gateway) --")
    text = "DB_HOST = 'x'\nDB_POOL_SIZE = 10\nHTTP_THREADS = 16\n"
    after, baks, said, d = run(text, AUTOFILL)
    check("no CR introduced anywhere", "\r" not in after, repr(after[-80:]))
    check("the new setting was added", "DB_POOL_SIZE_v2 = 32" in after)
    check("the retired setting is gone", not HAS_TOP_LEVEL.search(after))
    check("the result is valid Python", bool(ast.parse(after)))
    check("exactly one backup", len(baks) == 1, str(baks))
    check("the backup is the pristine original",
          io.open(os.path.join(d, baks[0]), encoding="utf-8", newline="").read() == text)

    print("\n-- a CRLF file stays pure CRLF (a Windows config on a Linux gateway) --")
    text = "DB_HOST = 'x'\r\nDB_POOL_SIZE = 10\r\nHTTP_THREADS = 16\r\n"
    after, baks, said, d = run(text, AUTOFILL)
    check("no bare LF introduced", "\n" not in after.replace("\r\n", ""), repr(after[-80:]))
    check("the new setting was added", "DB_POOL_SIZE_v2 = 32" in after)
    check("the retired setting is gone", not HAS_TOP_LEVEL.search(after))
    check("the result is valid Python", bool(ast.parse(after)))

    print("\n-- newlines inside the comment text follow the file too --")
    tail = after.split("HTTP_THREADS = 16\r\n", 1)[1]
    check("the appended block is all CRLF",
          "\n" not in tail.replace("\r\n", ""), repr(tail[:120]))

    print("\n-- a file with no trailing newline is not glued onto --")
    text = "DB_HOST = 'x'\nDB_POOL_SIZE = 10"
    after, baks, said, d = run(text, AUTOFILL)
    check("the result is valid Python", bool(ast.parse(after)))

    print("\n-- both paths share ONE backup --")
    text = "DB_HOST = 'x'\nDB_POOL_SIZE = 10\n"
    after, baks, said, d = run(text, AUTOFILL)
    check("one backup file, not two", len(baks) == 1, str(baks))
    named = [m.split("saved as")[-1].strip() for m in said if "saved as" in m]
    check("both paths name the same one", len(set(named)) == 1, str(named))

    print("\n-- an existing backup is NEVER overwritten --")
    d = tempfile.mkdtemp()
    decoy = os.path.join(d, "config.py.bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    io.open(decoy, "w", encoding="utf-8", newline="").write("AN EARLIER BACKUP")
    after, baks, said, d = run("DB_HOST = 'x'\nDB_POOL_SIZE = 10\n", AUTOFILL, predir=d)
    check("the earlier backup is intact",
          io.open(decoy, encoding="utf-8", newline="").read() == "AN EARLIER BACKUP")
    check("a free name was used instead", len(baks) == 2, str(baks))

    print("\n-- a form feed does not split a line Python considers whole --")
    text = "A = 1\n\fB = 2\nDB_POOL_SIZE = 10\n"
    check("the fixture really is valid Python", bool(ast.parse(text)))
    after, baks, said, d = run(text, AUTOFILL)
    check("the retired setting is still found and gone", not HAS_TOP_LEVEL.search(after))
    check("the form feed survives", "\f" in after)
    check("the result is valid Python", bool(ast.parse(after)))

    print("\n-- the name in a comment, a string or an indented block is left alone --")
    text = ("# DB_POOL_SIZE = 99 was the old setting\n"
            'NOTE = "DB_POOL_SIZE = 77"\n'
            "def f():\n"
            "    DB_POOL_SIZE = 5\n"
            "    return DB_POOL_SIZE\n"
            "DB_POOL_SIZE = 10\n")
    after, baks, said, d = run(text, AUTOFILL)
    check("the comment is kept", "# DB_POOL_SIZE = 99" in after)
    check("the string is kept", 'NOTE = "DB_POOL_SIZE = 77"' in after)
    check("the indented local is kept", "    DB_POOL_SIZE = 5" in after)
    check("only the top-level assignment went", not HAS_TOP_LEVEL.search(after))
    check("the result is valid Python", bool(ast.parse(after)))

    print("\n-- FAIL CLOSED: the retirement refuses a multi-line value --")
    text = "A = 1\nDB_POOL_SIZE = (\n    10\n)\nDB_POOL_SIZE_v2 = 32\n"
    after, baks, said, d = run(text, AUTOFILL)
    check("nothing was written", after == text, repr(after))
    check("no backup was taken", baks == [], str(baks))
    check("it said why", any("unparseable" in m for m in said), str(said))

    print("\n-- FAIL CLOSED: the autofill refuses to write a broken file --")

    class Unwritable:
        def __repr__(self):
            return "<<not python>>"

    text = "DB_HOST = 'x'\nDB_POOL_SIZE = 10\n"
    after, baks, said, d = run(text, [("BROKEN", Unwritable(), "x")], retired=())
    check("nothing was written", after == text, repr(after))
    check("no backup was taken", baks == [], str(baks))
    check("the admin was told what to add by hand",
          any("could NOT write" in m for m in said), str(said))

    print("\n-- nothing to do: the file is not touched at all --")
    text = "DB_HOST = 'x'\nDB_POOL_SIZE_v2 = 32\n"
    after, baks, said, d = run(text, AUTOFILL)
    check("byte-identical", after == text)
    check("no backup written", baks == [], str(baks))

    print("\n" + "=" * 68)
    print(f" RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
