---
name: cursor-db-core
description: >-
  Shared Python foundation for the cursor-db skill suite (inspector, surgeon,
  session-export). Provides cross-platform DB path detection, read-only and
  read-write connections to Cursor's state.vscdb, Cursor-not-running safety
  check, JSON loading, timestamp helpers, and the canonical session import
  function. Other cursor-db skills import from this module's scripts/ directory.
  Not invoked directly — activated when any cursor-db skill needs shared
  database utilities.
compatibility: "Requires Python 3.9+ and access to Cursor's state.vscdb SQLite database."
license: MIT
---

# Cursor DB Core

Shared Python utilities for the `cursor-db-inspector`, `cursor-db-surgeon`, and `cursor-session-export` skills.

**This skill is not invoked directly.** It exists so that the shared module `scripts/cursor_db_core.py` is discoverable and resolvable by all skills in the suite.

## What it provides

| Function | Purpose |
|----------|---------|
| `db_path()` | Cross-platform state.vscdb path (macOS, Linux, Windows) |
| `connect_readonly(path?)` | Open DB read-only + immutable (safe while Cursor runs) |
| `connect_readwrite(path?)` | Open DB for writes (isolation_level=None, WAL, busy_timeout) |
| `check_cursor_not_running(path?)` | Verify Cursor is not locking the DB |
| `require_cursor_not_running(path?)` | Same, but exits on failure |
| `jload(raw)` | Safely parse JSON from cursorDiskKV (handles binary, None) |
| `epoch_to_iso(ms)` | Convert epoch milliseconds to ISO 8601 UTC |
| `epoch_to_short(ms)` | Convert epoch milliseconds to short local datetime |
| `import_raw_store(path, ...)` | Import a .raw_store.json file into state.vscdb |

## How other skills import it

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "cursor-db-core", "scripts"))
from cursor_db_core import connect_readonly, jload, epoch_to_iso
```

The `sys.path.insert` resolves relative to the script's own `__file__`, so it works regardless of where the skill suite is installed (user skills directory, plugin cache, or project skills).
