#!/usr/bin/env python3
"""cursor_db_pin.py — Install, verify, or drop workspace pinning triggers.
Delegates DB access to cursor_db_core.

Usage:
  python3 cursor_db_pin.py install
  python3 cursor_db_pin.py verify
  python3 cursor_db_pin.py drop
  python3 cursor_db_pin.py list
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cursor-db-core", "scripts"))
from cursor_db_core import db_path, connect_readonly, connect_readwrite


TRIGGER_ON_UPDATE_WS = """
CREATE TRIGGER IF NOT EXISTS zz_pin_workspace_on_update
AFTER UPDATE OF workspaceId ON composerHeaders FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM zz_pinned_workspace p
              WHERE p.composerId = NEW.composerId AND p.workspaceId <> NEW.workspaceId)
BEGIN
    UPDATE composerHeaders SET workspaceId = (
      SELECT workspaceId FROM zz_pinned_workspace WHERE composerId = NEW.composerId
    ) WHERE composerId = NEW.composerId;
END;"""

TRIGGER_ON_INSERT = """
CREATE TRIGGER IF NOT EXISTS zz_pin_workspace_on_insert
AFTER INSERT ON composerHeaders FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM zz_pinned_workspace p
              WHERE p.composerId = NEW.composerId AND p.workspaceId <> NEW.workspaceId)
BEGIN
    UPDATE composerHeaders SET workspaceId = (
      SELECT workspaceId FROM zz_pinned_workspace WHERE composerId = NEW.composerId
    ) WHERE composerId = NEW.composerId;
END;"""

TRIGGER_ON_UPDATE_VALUE = """
CREATE TRIGGER IF NOT EXISTS zz_pin_location_on_update
AFTER UPDATE OF value ON composerHeaders FOR EACH ROW
WHEN NEW.value IS NOT NULL
 AND EXISTS (SELECT 1 FROM zz_pinned_workspace p
   WHERE p.composerId = NEW.composerId
   AND (IFNULL(json_extract(NEW.value,'$.agentLocation.environment.id'),'')<>p.workspaceId
    OR IFNULL(json_extract(NEW.value,'$.workspaceIdentifier.id'),'')<>p.workspaceId))
BEGIN
    UPDATE composerHeaders SET value = json_set(
      json_set(value,'$.workspaceIdentifier',
        json((SELECT identifierJson FROM zz_pinned_workspace WHERE composerId=NEW.composerId))),
      '$.agentLocation',
      json((SELECT agentLocationJson FROM zz_pinned_workspace WHERE composerId=NEW.composerId))
    ) WHERE composerId = NEW.composerId;
END;"""


def cmd_install(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zz_pinned_workspace (
            composerId TEXT PRIMARY KEY, workspaceId TEXT NOT NULL,
            identifierJson TEXT NOT NULL, agentLocationJson TEXT NOT NULL)
    """)
    conn.execute(TRIGGER_ON_UPDATE_WS)
    conn.execute(TRIGGER_ON_INSERT)
    conn.execute(TRIGGER_ON_UPDATE_VALUE)
    print("✓ Installed zz_pinned_workspace table + 3 triggers")
    cmd_verify(connect_readonly())


def cmd_verify(conn):
    triggers = {t[0] for t in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'zz_%'"
    ).fetchall()}
    expected = {"zz_pin_workspace_on_update", "zz_pin_workspace_on_insert", "zz_pin_location_on_update"}
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='zz_pinned_workspace'"
    ).fetchall()

    print("=== Pinning Infrastructure ===")
    print(f"  Table zz_pinned_workspace: {'EXISTS' if table else 'MISSING'}")
    for t in sorted(expected):
        print(f"  Trigger {t}: {'EXISTS' if t in triggers else 'MISSING'}")

    if table:
        cnt = conn.execute("SELECT COUNT(*) FROM zz_pinned_workspace").fetchone()[0]
        print(f"  Pinned sessions: {cnt}")

    if (expected - triggers) or not table:
        print(f"\n✗ Incomplete — run 'install' to fix")
    else:
        print(f"\n✓ All infrastructure present")


def cmd_drop(conn):
    conn.execute("DROP TRIGGER IF EXISTS zz_pin_workspace_on_update")
    conn.execute("DROP TRIGGER IF EXISTS zz_pin_workspace_on_insert")
    conn.execute("DROP TRIGGER IF EXISTS zz_pin_location_on_update")
    conn.execute("DROP TABLE IF EXISTS zz_pinned_workspace")
    print("✓ Dropped all pinning infrastructure")


def cmd_list(conn):
    try:
        rows = conn.execute(
            "SELECT p.composerId, p.workspaceId, "
            "json_extract(p.agentLocationJson,'$.environment.uri.fsPath') as path "
            "FROM zz_pinned_workspace p"
        ).fetchall()
    except Exception:
        print("No zz_pinned_workspace table. Run 'install' first.")
        return
    print(f"{'composerId':<38} {'workspaceId':<38} {'path'}")
    print("-" * 120)
    for cid, wsid, path in rows:
        print(f"{cid:<38} {wsid:<38} {path or ''}")
    print(f"\n{len(rows)} pinned sessions")


COMMANDS = {"install": True, "verify": False, "drop": True, "list": False}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: cursor_db_pin.py <install|verify|drop|list> [--db PATH]")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        sys.exit(f"Unknown: {cmd}. Use: {', '.join(COMMANDS)}")

    dbp = db_path()
    if "--db" in sys.argv:
        dbp = sys.argv[sys.argv.index("--db") + 1]

    if not os.path.exists(dbp):
        sys.exit(f"DB not found: {dbp}")

    needs_write = COMMANDS[cmd]
    conn = connect_readwrite(dbp) if needs_write else connect_readonly(dbp)

    {"install": cmd_install, "verify": cmd_verify, "drop": cmd_drop, "list": cmd_list}[cmd](conn)
    conn.close()
