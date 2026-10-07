---
name: cursor-session-export
description: >-
  Full-fidelity, source-driven export of Cursor AI sessions. Emits raw_store
  (complete source data model), AgentLog v0.2.0 (published open standard),
  and ASI v1 normalized view. Use when asked to export, archive, search,
  filter, or convert Cursor sessions to a portable format.
  Trigger: "export session", "archive cursor session", "cursor chat history",
  "AgentLog format", "ASI format", "search sessions", "list sessions".
compatibility: "Requires Python 3.9+ and access to Cursor's state.vscdb SQLite database."
license: MIT
---

# Cursor Session Export

Source-driven, full-fidelity export of Cursor AI sessions.

For data model knowledge (schema, entities, namespaces, relationships), see `cursor-db-inspector`.
For write operations (import, move, repair), see `cursor-db-surgeon`.

## Design Principle

The exporter is driven by **Cursor's data model**, NOT by what any consumer wants. It dumps **every cursorDiskKV row related to a session and every field of every row, verbatim**. Consequences:

- Nothing is silently dropped. Unknown/future Cursor fields export automatically.
- The exporter never needs editing when Cursor adds new fields or row types.
- A session in any state (in-progress, mid-agent-run, checkpointed) round-trips losslessly.

## When to Use

- "Export my Cursor session / chat history"
- "Archive a Cursor session in a portable format"
- "Search / filter my Cursor sessions"
- "Get a session into AgentLog format"

## Usage

### List sessions

```bash
python3 scripts/cursor_session_export.py --list [N]
```

### Search and filter

```bash
--list --search "keyword"
--list --after 2026-07-01 --before 2026-08-01
--list --workspace /path/to/project
--list --min-messages 50
```

### Export

```bash
python3 scripts/cursor_session_export.py --export <composerId>
```

### Options

```bash
--outdir DIR          # Output directory (default ~/cursor_exports)
--no-agentlog         # Skip AgentLog v0.2.0 generation
--no-normalized       # Skip ASI v1 normalized view
--no-value-scan       # Skip slower value-linked blob scan (agentKv)
```

### Verify

```bash
python3 scripts/cursor_session_export.py --verify <file.asi.json>
```

## Output Structure

Three files per session, each serving a different consumer:

```
~/cursor_exports/
├── <cid>.raw_store.json     # Complete Cursor data model (lossless)
├── <cid>.asi.jsonl          # ASI v1 normalized (one message per line)
└── <cid>.agentlog.jsonl     # AgentLog v0.2.0 (one event per line)
```

### `<cid>.raw_store.json` — Source of truth

```jsonc
{
  "format": "cursor_raw_store",
  "format_version": "1.0",
  "source": { "tool": "cursor", "completeness": "full", "row_counts": {...} },
  "raw_store": {
    "composerData":   { "composerData:<cid>": { /* full envelope */ } },
    "bubbleId":       { "bubbleId:<cid>:<bid>": { /* all fields */ } },
    "ofsContent":     { /* file snapshots */ },
    "agentKv":        { /* agent runtime state */ },
    "composerHeaders": { /* sidebar header data */ },
    "...":            { /* any other namespace */ }
  }
}
```

### `<cid>.asi.jsonl` — ASI v1 normalized

```jsonc
{"type":"session","asi_version":"1.0","session":{"id","title","model","workspace"}}
{"type":"message","id":"...","role":"user","parts":[{"kind":"text","text":"..."}]}
{"type":"message","id":"...","role":"assistant","parts":[{"kind":"reasoning",...},{"kind":"tool_call",...}]}
```

### `<cid>.agentlog.jsonl` — AgentLog v0.2.0

```jsonc
{"type":"session","specVersion":"0.2.0","id":"...","agent":{"name":"Cursor"},"metrics":{...}}
{"type":"message","id":"...","role":"user","content":"..."}
{"type":"toolCall","id":"...","name":"Edit","input":{...},"output":"...","status":"success"}
{"type":"fileOperation","id":"...","operation":"edit","path":"...","diff":"..."}
```

### Consumer routing

| Consumer | Use file | Why |
|----------|----------|-----|
| Cursor importer | `.raw_store.json` | Write directly back to state.vscdb — see `cursor-db-surgeon` § Import Protocol |
| ASI-aware tools | `.asi.jsonl` | Typed parts, streaming-friendly, 19 part kinds |
| Ecosystem tools | `.agentlog.jsonl` | Published standard, widest compatibility |

## Field Coverage

`raw_store` captures 100% of all fields by design. The structured views map known fields explicitly:

### ASI v1 — 19 part kinds

| kind | Cursor fields |
|------|---------------|
| `text` | text, richText |
| `reasoning` | thinking, allThinkingBlocks |
| `tool_call` | toolFormerData, toolResults |
| `tool_result` | toolFormerData.result, toolResults[].result |
| `code` | suggestedCodeBlocks, codeBlocks |
| `file_context` | attachedCodeChunks |
| `image` | images |
| `diff` | gitDiffs, humanChanges, attachedHumanChanges, assistantSuggestedDiffs |
| `file_delete` | deletedFiles |
| `terminal` | consoleLogs, interpreterResults |
| `web_search` | aiWebSearchResults, webReferences |
| `codebase_search` | codebaseContextChunks |
| `docs_reference` | docsReferences, documentationSelections |
| `context_load` | attachedFolders*, relevantFiles, contextPieces, knowledgeItems, cursorRules, notepads, pastChats, summarizedComposers, externalLinks, recentlyViewedFiles |
| `plan` | todos |
| `error` | errorDetails, lints, multiFileLinterErrors |
| `commit` | commits |
| `pull_request` | pullRequests |
| `handoff` | subagentSpawnTaskToolCallId |
| `checkpoint` | checkpointId |

### AgentLog v0.2.0 — 11 event types

`message`, `toolCall`, `fileOperation`, `terminalCommand`, `search`, `reasoning`, `contextLoad`, `plan`, `error`, `handoff`, `checkpoint`.

Cursor-internal metadata is stored as `cursor:*` prefixed properties on events.

For the full list of bubble fields and their types, see `cursor-db-inspector` [reference.md](../cursor-db-inspector/reference.md) § bubbleId.

## Namespaces Captured

The broad `key LIKE '%<cid>%'` scan catches all key-linked namespaces automatically:

- `composerData` — session envelope
- `bubbleId` — messages
- `composerHeaders` — sidebar header
- `ofsContent` — file snapshots
- `codeBlockPartialInlineDiffFates` — diff accept/reject state
- `composerVirtualRowHeights` — UI layout
- `inlineDiff` — inline diff records

Plus optional value-scan (`--no-value-scan` to skip):

- `agentKv` — content-addressed agent runtime blobs
- `checkpointId` — workspace snapshots

For namespace key formats and entity structures, see `cursor-db-inspector` § Namespace Registry.

## Idempotency

Content-hashed via `~/cursor_exports/.export_manifest.json`. Re-exporting an unchanged session prints SKIP. Delete the manifest to force re-export.

## Safety & Performance

- DB opened read-only + immutable — zero risk to live Cursor data
- Never copies the DB; queries in place
- Immutable mode sidesteps WAL lock contention
- macOS only (hardcoded path in export script)
- Value-scan for agentKv is optional and slower (skip with `--no-value-scan`)

For DB paths on all platforms and connection methods, see `cursor-db-inspector` § Connection.

## Forward Compatibility: Handling New Cursor Fields

### Invariant

`raw_store` guarantees zero data loss regardless of Cursor schema changes. But the structured views (`normalized`, `agentlog`) are only as complete as their explicit mappings. **Novel content-bearing fields MUST be promoted to typed parts/events within one session of discovery** — otherwise the structured views silently regress while raw_store carries the truth.

### Detection mechanism

The script classifies every bubble field into one of three sets:

| Set | Constant | Meaning |
|-----|----------|---------|
| `HANDLED_BUBBLE_FIELDS` | Explicitly decomposed into ASI parts | Fully covered |
| `METADATA_FIELDS` | Cursor-internal state, not message content | Silently ignored (safe) |
| *(neither)* | **Novel field** — detected at export time | Needs promotion |

On export, the script computes `novel_fields = bubble_keys - HANDLED - METADATA`. If non-empty, it prints:
```
NOTE: 3 novel content fields found (preserved in raw): ['newField1', 'newField2', 'newField3']
```

### Protocol: detect → classify → implement → verify

#### 1. Classify

Determine if the field is **content-bearing** or **metadata**.

- Content-bearing → needs a new ASI part kind + AgentLog event mapping
- Metadata → add to `METADATA_FIELDS` set in the script

**Heuristic:** if removing the field would lose information a human reviewing the transcript would notice, it's content-bearing.

For the complete field inventory to compare against, see `cursor-db-inspector` [reference.md](../cursor-db-inspector/reference.md) § bubbleId.

#### 2. Implement (content-bearing fields)

Three locations in `cursor_session_export.py` must be updated together:

**a) ASI normalized view — add part kind in `normalize_bubble()`:**

```python
for item in (b.get("newField") or []):
    if isinstance(item, dict):
        parts.append({
            "kind": "new_kind_name",
            "key_field": item.get("relevantKey") or "",
        })
```

**b) AgentLog events — add event mapping in `bubble_to_agentlog_events()`:**

```python
for item in (b.get("newField") or []):
    if isinstance(item, dict):
        events.append({
            "type": "closest_agentlog_event_type",
            "id": eid(),
            "timestamp": base_ts,
            "properties": {"cursor:source": "newField"},
        })
```

If no existing AgentLog event type fits, use `properties` on the parent message event:
```python
msg_event["properties"]["cursor:newField"] = b["newField"]
```

**c) Field set registration — move from novel to handled:**

```python
HANDLED_BUBBLE_FIELDS = {
    ...,
    "newField",  # added YYYY-MM-DD
}
```

#### 3. Update documentation

In this SKILL.md, update the **Field Coverage** table:
- Add a row to the `kind` table mapping the new kind to its Cursor field(s)

#### 4. Verify and re-export

```bash
python3 scripts/cursor_session_export.py --export <composerId>
python3 scripts/cursor_session_export.py --verify <output.asi.json>
```

Confirm:
- No novel fields reported for the promoted field
- `--verify` passes
- Part kind appears in the normalized message's `parts[]`

Then re-export all previously exported sessions:
```bash
rm ~/cursor_exports/.export_manifest.json
python3 scripts/cursor_session_export.py --export <each composerId>
```

### Version policy

- Adding a new part kind → **minor** bump (e.g., 3.0.0 → 3.1.0)
- Changing an existing part kind's schema → **major** bump
- Adding to `METADATA_FIELDS` → **patch** bump

### Why this matters

Without this protocol, the exporter develops "structured rot": raw_store stays complete but the normalized/AgentLog views gradually cover a smaller percentage of actual content as Cursor evolves. The detection mechanism makes this rot visible immediately.

## Scripts

| Script | Lines | Purpose |
|--------|------:|---------|
| `cursor_session_export.py` | 1,366 | Main exporter — list, search, export, verify |
| `cursor_bundle.py` | 446 | Bundle multiple exports for transfer |
| `cursor_import.py` | 207 | Import raw_store.json into another Cursor installation |

For the import protocol (pre-flight, 3-level visibility, subagent ordering, workspace binding), see `cursor-db-surgeon` § Import Protocol.

## Cross-references

This skill handles **export only**. For data model knowledge and write operations, use the companion skills:

| Need | Skill | Section |
|------|-------|---------|
| Schema DDL, entity fields, relationships | `cursor-db-inspector` | Schema, Entity Summaries, Relationships |
| DB paths, connection methods | `cursor-db-inspector` | Connection |
| Namespace key formats, entity structures | `cursor-db-inspector` | Namespace Registry, reference.md |
| Sidebar grouping rules | `cursor-db-inspector` | Sidebar Grouping |
| Ownership model (which writes persist) | `cursor-db-inspector` | Ownership Model |
| Import sessions to another machine | `cursor-db-surgeon` | Import Protocol |
| Move sessions between workspaces | `cursor-db-surgeon` | Workspace Move Protocol |
| Folder rename recovery | `cursor-db-surgeon` | Folder Rename Recovery |
| Pinning triggers (install, verify, drop) | `cursor-db-surgeon` | Trigger Management |
| Pre-flight safety check for writes | `cursor-db-surgeon` | Pre-flight |
