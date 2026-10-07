#!/usr/bin/env python3
"""
cursor_db_core.py — Shared foundation for all Cursor DB skills.

This is the SINGLE source of truth for:
  - Cross-platform DB path detection
  - Read-only and read-write DB connections
  - Cursor-not-running check
  - Session import logic (raw_store.json → state.vscdb)
  - Write connection boilerplate

Every other script in the cursor-db-inspector, cursor-db-surgeon, and
cursor-session-export skills imports from this module instead of
reimplementing these primitives.

Install location: Alongside sibling skills in the cursor-db-skills suite.
Import from sibling: sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "cursor-db-core", "scripts"))

No external dependencies — stdlib only.
"""
import sqlite3
import json
import os
import platform
import subprocess
import sys
import datetime


__version__ = "1.0.0"


# ─── DB Path Detection (single source of truth) ──────────────────────────────

def db_path():
    """Cross-platform state.vscdb path.

    | OS      | Path                                                              |
    |---------|-------------------------------------------------------------------|
    | macOS   | ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb |
    | Linux   | ~/.config/Cursor/User/globalStorage/state.vscdb                   |
    | Windows | %APPDATA%/Cursor/User/globalStorage/state.vscdb                   |
    """
    s = platform.system()
    if s == "Darwin":
        return os.path.expanduser(
            "~/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
        )
    elif s == "Windows":
        return os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "Cursor", "User", "globalStorage", "state.vscdb",
        )
    return os.path.expanduser(
        "~/.config/Cursor/User/globalStorage/state.vscdb"
    )


# ─── DB Connections ───────────────────────────────────────────────────────────

def connect_readonly(path=None):
    """Open state.vscdb read-only + immutable. Zero mutation risk.
    Safe to call while Cursor is running."""
    p = path or db_path()
    if not os.path.exists(p):
        sys.exit(f"DB not found: {p}")
    return sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)


def connect_readwrite(path=None):
    """Open state.vscdb for writing. Cursor MUST be quit first.

    Uses isolation_level=None for manual transaction control (Python's sqlite3
    opens implicit transactions otherwise, and a later BEGIN IMMEDIATE fails
    with 'cannot start a transaction within a transaction').

    Sets busy_timeout and WAL journal mode.
    """
    p = path or db_path()
    if not os.path.exists(p):
        sys.exit(f"DB not found: {p}")
    conn = sqlite3.connect(p, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# ─── Safety Checks ───────────────────────────────────────────────────────────

def check_cursor_not_running(path=None):
    """Check if Cursor has the DB locked. Returns True if safe to proceed.

    On macOS/Linux, uses lsof. On Windows, prints a warning.
    """
    p = path or db_path()
    s = platform.system()
    if s in ("Darwin", "Linux"):
        try:
            result = subprocess.run(
                ["lsof", p], capture_output=True, text=True, timeout=10,
            )
            if result.stdout.strip():
                print("FAIL: Cursor is running (DB is locked).", file=sys.stderr)
                print("      Quit Cursor (Cmd+Q / Ctrl+Q) before proceeding.", file=sys.stderr)
                return False
        except FileNotFoundError:
            print("WARN: lsof not found. Cannot verify Cursor is closed.", file=sys.stderr)
        except subprocess.TimeoutExpired:
            print("WARN: lsof timed out.", file=sys.stderr)
    elif s == "Windows":
        print("WARN: Cannot auto-check on Windows. Ensure Cursor is quit.", file=sys.stderr)
    return True


def require_cursor_not_running(path=None):
    """Like check_cursor_not_running but exits on failure."""
    if not check_cursor_not_running(path):
        sys.exit(1)


# ─── JSON Loading ─────────────────────────────────────────────────────────────

def jload(raw):
    """Safely parse a value from cursorDiskKV. Handles JSON, binary, and None."""
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8", "replace")
        except Exception:
            import base64
            return {"__binary_base64__": base64.b64encode(bytes(raw)).decode()}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


# ─── Timestamp Helpers ────────────────────────────────────────────────────────

def epoch_to_iso(ms):
    """Convert epoch milliseconds to ISO 8601 UTC string."""
    if not ms:
        return None
    try:
        return datetime.datetime.fromtimestamp(
            ms / 1000, tz=datetime.timezone.utc
        ).isoformat()
    except (ValueError, OSError):
        return str(ms)


def epoch_to_short(ms):
    """Convert epoch milliseconds to short local datetime string."""
    if not ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(ms / 1000).isoformat(timespec="seconds")
    except (ValueError, OSError):
        return str(ms)


# ─── Session Import (single source of truth) ─────────────────────────────────

def import_raw_store(raw_store_path, db_path_override=None, make_head=True, dry_run=False):
    """Import a .raw_store.json file into Cursor's state.vscdb.

    This is the canonical import implementation. All scripts that need to import
    sessions should call this function.

    Args:
        raw_store_path: Path to .raw_store.json file
        db_path_override: Override the auto-detected DB path
        make_head: If True (default), register in composerHeaders for sidebar visibility.
                   If False, write-only (data on disk but not in sidebar).
        dry_run: If True, print what would be done without writing.

    Returns:
        The composerId of the imported session.

    Visibility levels (see cursor-db-surgeon § Import Protocol):
      Level 1 (write-only): composerData + bubbleId into cursorDiskKV only
      Level 2 (make-head):  also register in composerHeaders → sidebar visible
    """
    target = db_path_override or db_path()

    if not os.path.exists(target):
        sys.exit(f"ERROR: Target DB not found: {target}")

    with open(raw_store_path) as f:
        doc = json.load(f)

    if doc.get("format") != "cursor_raw_store":
        print(f"  WARNING: format is '{doc.get('format')}', expected 'cursor_raw_store'",
              file=sys.stderr)

    raw_store = doc["raw_store"]

    cd_keys = list(raw_store.get("composerData", {}).keys())
    if not cd_keys:
        sys.exit(f"ERROR: No composerData in {raw_store_path}")
    cid = cd_keys[0].split(":", 1)[1]

    total_rows = sum(len(entries) for ns, entries in raw_store.items() if ns != "composerHeaders")
    env = raw_store["composerData"][cd_keys[0]]
    name = env.get("name") or "(untitled)"
    bubble_count = len(raw_store.get("bubbleId", {}))

    if dry_run:
        print(f"  DRY RUN: {name}")
        print(f"    composerId: {cid}")
        print(f"    bubbles: {bubble_count}, total rows: {total_rows}")
        print(f"    make_head: {make_head}, target: {target}")
        return cid

    conn = connect_readwrite(target)

    conn.execute("BEGIN IMMEDIATE")
    try:
        rows_written = 0

        for namespace, entries in raw_store.items():
            if namespace == "composerHeaders":
                continue
            if namespace == "ItemTable":
                for key, val in entries.items():
                    serialized = json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val
                    conn.execute(
                        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                        (key, serialized),
                    )
                    rows_written += 1
                continue
            for key, val in entries.items():
                conn.execute(
                    "INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?, ?)",
                    (key, json.dumps(val, ensure_ascii=False)),
                )
                rows_written += 1

        if make_head:
            ch_data = raw_store.get("composerHeaders", {})
            ch_key = f"composerHeaders:{cid}"
            if ch_key in ch_data:
                header = ch_data[ch_key]
                conn.execute(
                    """INSERT OR REPLACE INTO composerHeaders
                    (composerId, workspaceId, createdAt, lastUpdatedAt, isArchived,
                     isSubagent, recency, checkpointAt, value, subagentTypeName)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cid,
                        header.get("workspaceId"),
                        header.get("createdAt"),
                        header.get("lastUpdatedAt"),
                        header.get("isArchived", 0),
                        header.get("isSubagent", 0),
                        header.get("recency"),
                        header.get("checkpointAt"),
                        json.dumps(header.get("value", {}), ensure_ascii=False)
                        if header.get("value") else None,
                        header.get("subagentTypeName"),
                    ),
                )
                rows_written += 1
            else:
                print(f"  NOTE: No composerHeaders in export — session may not appear in sidebar",
                      file=sys.stderr)

        conn.execute("COMMIT")
        print(f"  ✓ {name} — {rows_written} rows ({bubble_count} bubbles)")
        return cid

    except Exception as e:
        conn.execute("ROLLBACK")
        sys.exit(f"  ✗ ROLLBACK: {e}")
    finally:
        conn.close()
