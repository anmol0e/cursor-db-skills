---
name: cursor-db-surgeon
description: >-
  Import, export, move, repair, and pin Cursor sessions in state.vscdb.
  Write operations including session import, workspace reassignment,
  sidebar pinning, and orphan cleanup. Use when asked to move sessions
  between workspaces, import exported sessions, pin sessions to a workspace,
  repair sidebar grouping, fix workspace assignment after folder rename,
  or clean up orphaned data.
  Trigger: "move session", "import session", "pin workspace",
  "fix sidebar", "reassign workspace", "folder renamed",
  "import raw_store", "clean orphans".
compatibility: "Requires Python 3.9+ and write access to Cursor's state.vscdb. Cursor must be quit before write operations."
license: MIT
---

# Cursor DB Surgeon

Write operations on Cursor's `state.vscdb`. **Every write requires the pre-flight check.**

For read-only inspection, use the `cursor-db-inspector` skill instead.

## Pre-flight (MANDATORY before any write)

```bash
python3 scripts/cursor_db_preflight.py
```

This checks: Cursor not running, DB exists, backup taken. **Do not skip.**

### Manual pre-flight

```bash
# 1. Verify Cursor is NOT running
lsof ~/Library/Application\ Support/Cursor/User/globalStorage/state.vscdb* 2>/dev/null
# Must return nothing. If output appears → Cmd+Q Cursor first.

# 2. Backup
DB="$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
cp "$DB" "$DB.backup.$(date +%Y%m%dT%H%M%S)"
```

### DB paths

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` |
| Linux | `~/.config/Cursor/User/globalStorage/state.vscdb` |
| Windows | `%APPDATA%\Cursor\User\globalStorage\state.vscdb` |

### Python connection for writes

```python
import sqlite3
conn = sqlite3.connect(DB_PATH, isolation_level=None)  # manual transactions
conn.execute("PRAGMA busy_timeout = 30000")
conn.execute("PRAGMA journal_mode = WAL")
```

**Critical:** Use `isolation_level=None`. Python's sqlite3 opens implicit transactions otherwise, and a later `BEGIN IMMEDIATE` fails with "cannot start a transaction within a transaction."

**Never** run `PRAGMA wal_checkpoint(TRUNCATE)` on this multi-GB database — it stalls indefinitely.

## Ownership Model

| Store | External writes survive? |
|-------|:------------------------:|
| `cursorDiskKV` | **Yes** |
| `composerHeaders` | **No** — Cursor-owned, held in memory, rewritten on startup/shutdown |
| `ItemTable` (most keys) | **Yes** |
| `workspaceMetadata.entries` | **No** — Cursor-owned, deleted entries reappear |

**Consequence:** Writing to `composerHeaders` requires the trigger-based pinning approach (§ Pinning) or will be silently reverted.

## Import Protocol

Import sessions from `.raw_store.json` files (produced by `cursor-session-export`).

### 3-level visibility model

| Level | What to write | Result |
|-------|---------------|--------|
| **1. Write-only** | `composerData:<cid>` + `bubbleId:<cid>:*` into cursorDiskKV | On disk, NOT in sidebar |
| **2. Make-head** | Also register in `composerHeaders` table | **Visible in sidebar** |
| **3. Make-current** | Also set `selectedComposerIds` in workspace state | **Opens as active session** |

### Import script

```bash
# Single session
python3 ../cursor-session-export/scripts/cursor_import.py <file.raw_store.json>

# Batch
for f in ~/cursor_imports/*.raw_store.json; do
    python3 ../cursor-session-export/scripts/cursor_import.py "$f"
done
```

### Import SQL (Level 2 — make-head)

```sql
-- Write cursorDiskKV rows (composerData, bubbleId, ofsContent, etc.)
INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?, ?);

-- Register in composerHeaders (sidebar visibility)
INSERT OR REPLACE INTO composerHeaders
  (composerId, workspaceId, createdAt, lastUpdatedAt, isArchived,
   isSubagent, recency, checkpointAt, value, subagentTypeName)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
```

`INSERT OR REPLACE` is idempotent — re-importing overwrites, no duplicates.

### Subagent import order

Import **root sessions first**, then subagents. Subagents with `isSubagent=1` appear nested under their parent in the sidebar (via `subagentInfo.parentComposerId`), not as top-level entries.

## Workspace Move Protocol (Pinning)

Moving sessions between workspaces requires the trigger-based approach because `composerHeaders` is Cursor-owned.

### How sidebar grouping works

The sidebar groups by `agentLocation.environment.uri` — **NOT** by `workspaceId`. Three sessions with the same `workspaceId` but different `agentLocation` values land in different sidebar groups.

Three fields must be consistent:

| Field | Location | Controls sidebar? |
|-------|----------|:-----------------:|
| `workspaceId` | composerHeaders column | No (index/filter) |
| `workspaceIdentifier` | composerHeaders.value JSON | No (bookkeeping) |
| `agentLocation` | composerHeaders.value JSON | **Yes** |

### Step 1: Read the target workspace ID

Workspace IDs are opaque hashes — **never fabricate them**. Read from DB:

```sql
-- From workspaceMetadata.entries
SELECT value FROM ItemTable WHERE key = 'workspaceMetadata.entries';
-- Parse JSON → find entry with matching folderUri or configPath → use its workspaceId

-- Or from the newest session in that workspace
SELECT workspaceId FROM composerHeaders
WHERE json_extract(value,'$.agentLocation.environment.uri.fsPath') LIKE '%<PATH>%'
ORDER BY lastUpdatedAt DESC LIMIT 1;
```

### Step 2: Install pinning triggers (if not present)

```bash
python3 scripts/cursor_db_pin.py install
```

Or manually:

```sql
-- Check if triggers exist
SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'zz_%';

-- Create pin table (if missing)
CREATE TABLE IF NOT EXISTS zz_pinned_workspace (
    composerId        TEXT PRIMARY KEY,
    workspaceId       TEXT NOT NULL,
    identifierJson    TEXT NOT NULL,
    agentLocationJson TEXT NOT NULL
);

-- Create all 3 triggers (see cursor-db-inspector SKILL.md § Schema for full DDL)
```

### Step 3: Move sessions

```bash
python3 scripts/cursor_db_move.py \
  --sessions <CID1>,<CID2>,... \
  --target-workspace-id <WSID> \
  --target-path "/abs/path/to/project" \
  --include-subagents
```

Or manually:

```sql
-- Build the JSON payloads
-- identifierJson:
-- {"id":"<WSID>","uri":{"$mid":1,"fsPath":"<PATH>","external":"file://<PATH>","path":"<PATH>","scheme":"file"}}

-- agentLocationJson:
-- {"type":"local","environment":{"id":"<WSID>","uri":{"$mid":1,"fsPath":"<PATH>","external":"file://<PATH>","path":"<PATH>","scheme":"file"}},"status":"active"}

-- Seed the pin table
INSERT OR REPLACE INTO zz_pinned_workspace
  (composerId, workspaceId, identifierJson, agentLocationJson)
VALUES (?, ?, ?, ?);

-- Stamp composerHeaders (triggers will enforce on restart)
UPDATE composerHeaders SET workspaceId = '<WSID>' WHERE composerId = '<CID>';
UPDATE composerHeaders SET value = json_set(
  json_set(value, '$.workspaceIdentifier', json('<identifierJson>')),
  '$.agentLocation', json('<agentLocationJson>'))
WHERE composerId = '<CID>';
```

### Step 4: Include subagents

```sql
-- Find all subagents
SELECT composerId FROM composerHeaders
WHERE json_extract(value,'$.subagentInfo.parentComposerId') = '<PARENT_CID>';

-- Pin each subagent with the same workspace target
INSERT OR REPLACE INTO zz_pinned_workspace ...  -- same target for each
```

### Step 5: Restart Cursor and verify

Quit and reopen Cursor. Sessions appear in the target workspace's sidebar group.

```sql
-- Verify post-restart
SELECT composerId, workspaceId,
  json_extract(value,'$.agentLocation.environment.id') as loc_id
FROM composerHeaders WHERE composerId IN ('<CID1>','<CID2>');
-- workspaceId and loc_id must match the target
```

## Folder Rename Recovery

When a project folder is renamed, all sessions point at the old path. Cursor mints a fresh workspace ID for the new path.

### Procedure

1. **Open the renamed folder in Cursor** once — this mints the real workspace ID for the new path.

2. **Read the new workspace ID:**
```sql
SELECT workspaceId FROM composerHeaders
WHERE json_extract(value,'$.agentLocation.environment.uri.fsPath') = '<NEW_PATH>'
ORDER BY lastUpdatedAt DESC LIMIT 1;
```

3. **Find stranded sessions:**
```sql
SELECT composerId FROM composerHeaders
WHERE json_extract(value,'$.agentLocation.environment.uri.fsPath') = '<OLD_PATH>'
   OR json_extract(value,'$.agentLocation.environment.uri.fsPath') IS NULL;
```

4. **Pin and stamp** all stranded sessions to the new workspace ID (follow § Move Protocol above).

5. **Restart Cursor.**

**Case sensitivity:** A case-only rename (e.g. `oncall-agent` → `Oncall-Agent`) creates a new workspace ID even on case-insensitive macOS. The old sessions remain stranded.

**Stale entries:** `workspaceMetadata.entries` may show phantom groups for old paths — "No agents yet". These are harmless and reappear if deleted (Cursor-owned).

## Orphan Cleanup

### Find orphans

```sql
-- composerData without composerHeaders
SELECT SUBSTR(key,15) as cid FROM cursorDiskKV
WHERE key LIKE 'composerData:%'
AND SUBSTR(key,15) NOT IN (SELECT composerId FROM composerHeaders);

-- bubbleId for sessions that no longer exist in composerData
SELECT DISTINCT SUBSTR(key,10,36) as cid FROM cursorDiskKV
WHERE key LIKE 'bubbleId:%'
AND SUBSTR(key,10,36) NOT IN (
  SELECT SUBSTR(key,15) FROM cursorDiskKV WHERE key LIKE 'composerData:%'
);

-- ofsContent for deleted sessions
SELECT DISTINCT SUBSTR(key,12,36) as cid FROM cursorDiskKV
WHERE key LIKE 'ofsContent:%'
AND SUBSTR(key,12,36) NOT IN (
  SELECT SUBSTR(key,15) FROM cursorDiskKV WHERE key LIKE 'composerData:%'
);

-- Stale composerVirtualRowHeights
SELECT SUBSTR(key,28) as cid FROM cursorDiskKV
WHERE key LIKE 'composerVirtualRowHeights:%'
AND SUBSTR(key,28) NOT IN (
  SELECT SUBSTR(key,15) FROM cursorDiskKV WHERE key LIKE 'composerData:%'
);
```

### Remove orphans (DESTRUCTIVE — backup first)

```sql
-- Delete orphaned bubbles for a specific session
DELETE FROM cursorDiskKV WHERE key LIKE 'bubbleId:<ORPHAN_CID>:%';

-- Delete orphaned composerData
DELETE FROM cursorDiskKV WHERE key = 'composerData:<ORPHAN_CID>';

-- Delete orphaned ofsContent
DELETE FROM cursorDiskKV WHERE key LIKE 'ofsContent:<ORPHAN_CID>:%';

-- Delete orphaned checkpoints
DELETE FROM cursorDiskKV WHERE key LIKE 'checkpointId:<ORPHAN_CID>:%';
```

## Trigger Management

### Install

```bash
python3 scripts/cursor_db_pin.py install
```

### Verify triggers are active

```sql
SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'zz_%';
-- Must return 3 triggers: zz_pin_workspace_on_update, zz_pin_workspace_on_insert, zz_pin_location_on_update
```

### Drop triggers (to uninstall)

```sql
DROP TRIGGER IF EXISTS zz_pin_workspace_on_update;
DROP TRIGGER IF EXISTS zz_pin_workspace_on_insert;
DROP TRIGGER IF EXISTS zz_pin_location_on_update;
DROP TABLE IF EXISTS zz_pinned_workspace;
```

**Note:** A Cursor upgrade that recreates `composerHeaders` drops the triggers. Re-apply after upgrade.

## Behavioral Notes

- `storage.json` → `backupWorkspaces` decides what Cursor restores. Cursor-owned, edits unreliable.
- Sessions without `agentLocation` fall back to unrelated sidebar buckets or "No Repo".
- Stale `workspaceMetadata` entries render as phantom "No agents yet" groups — harmless.
- Workspace IDs are opaque hashes, not computable. Always read from DB.
- `PRAGMA recursive_triggers` is OFF by default. Cursor doesn't enable it. Trigger UPDATEs don't loop.
