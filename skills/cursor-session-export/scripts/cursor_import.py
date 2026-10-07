#!/usr/bin/env python3
"""
cursor_import.py — Import raw_store.json into Cursor's state.vscdb.

Thin CLI wrapper around cursor_db_core.import_raw_store().
For the full import protocol, see cursor-db-surgeon.

Usage:
  python3 cursor_import.py <file.raw_store.json>
  python3 cursor_import.py <file.raw_store.json> --db /path/to/state.vscdb
  python3 cursor_import.py <file.raw_store.json> --write-only
  python3 cursor_import.py --batch ~/cursor_imports/
  python3 cursor_import.py --batch ~/cursor_imports/ --dry-run
"""
import sys, os, glob

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cursor-db-core", "scripts"))
from cursor_db_core import db_path, import_raw_store, require_cursor_not_running


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if "--help" in sys.argv or "-h" in sys.argv else 1)

    args = sys.argv[1:]
    db = None
    make_head = True
    dry_run = False
    batch_dir = None
    files = []

    i = 0
    while i < len(args):
        if args[i] == "--db":
            db = args[i + 1]; i += 2
        elif args[i] == "--write-only":
            make_head = False; i += 1
        elif args[i] == "--dry-run":
            dry_run = True; i += 1
        elif args[i] == "--batch":
            batch_dir = args[i + 1]; i += 2
        else:
            files.append(args[i]); i += 1

    if batch_dir:
        files = sorted(glob.glob(os.path.join(batch_dir, "*.raw_store.json")))

    if not files:
        print("No .raw_store.json files specified")
        sys.exit(1)

    target = db or db_path()
    print(f"Importing {len(files)} session(s) → {target}")
    if dry_run:
        print("(DRY RUN)")
    else:
        require_cursor_not_running(target)
    print()

    for f in files:
        try:
            import_raw_store(f, db_path_override=db, make_head=make_head, dry_run=dry_run)
        except SystemExit as e:
            print(f"  {e}")
        except Exception as e:
            print(f"  ERROR: {e}")

    print()
    print("Done. Open Cursor to verify sessions appear in the sidebar.")
    print("For workspace reassignment, see cursor-db-surgeon § Workspace Move Protocol.")
