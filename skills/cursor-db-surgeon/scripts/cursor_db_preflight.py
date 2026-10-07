#!/usr/bin/env python3
"""cursor_db_preflight.py — Pre-flight safety check before any DB write.
Delegates DB access to cursor_db_core."""
import os, sys, shutil
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cursor-db-core", "scripts"))
from cursor_db_core import db_path, check_cursor_not_running


def main():
    dbp = db_path()
    print(f"=== Cursor DB Pre-flight Check ===\n")
    print(f"DB path: {dbp}\n")
    ok = True

    if not os.path.exists(dbp):
        print(f"FAIL: DB not found at {dbp}")
        sys.exit(1)
    size_gb = os.path.getsize(dbp) / (1024**3)
    print(f"OK:   DB found ({size_gb:.2f} GB)")

    if not check_cursor_not_running(dbp):
        ok = False
    else:
        print("OK:   Cursor appears to be closed.")

    wal_path = dbp + "-wal"
    if os.path.exists(wal_path):
        wal_size = os.path.getsize(wal_path)
        if wal_size > 100 * 1024 * 1024:
            print(f"WARN: WAL is large ({wal_size / 1048576:.1f} MB)")
        else:
            print(f"OK:   WAL exists ({wal_size / 1024:.1f} KB)")
    else:
        print("OK:   No WAL file.")

    if ok:
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup_path = f"{dbp}.backup.{ts}"
        print(f"      Creating backup: {backup_path}")
        try:
            shutil.copy2(dbp, backup_path)
            print(f"OK:   Backup created ({os.path.getsize(backup_path) / (1024**3):.2f} GB)")
        except Exception as e:
            print(f"FAIL: Backup failed: {e}")
            ok = False

    print()
    if ok:
        print("=== ALL CHECKS PASSED — safe to proceed ===")
    else:
        print("=== CHECKS FAILED — do NOT proceed ===")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
