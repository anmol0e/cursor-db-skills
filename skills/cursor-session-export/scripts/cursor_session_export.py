#!/usr/bin/env python3
"""
cursor_session_export.py — Full-fidelity Cursor session exporter.

Exports Cursor AI sessions from state.vscdb to three portable formats:
  1. raw_store   — complete, untouched source data model (every row, every field)
  2. AgentLog    — v0.2.0 structured event timeline (published open standard)
  3. normalized  — ASI v1 convenience view (parts-based)

Design principle: SOURCE-DRIVEN, COMPLETE, FORMAT-AGNOSTIC.
The exporter is driven by Cursor's data model. It dumps EVERY cursorDiskKV row
related to a session and EVERY field of every row, verbatim. It never cherry-picks.
Unknown/future Cursor fields export automatically via raw_store.
The structured views (AgentLog, normalized) are derived, best-effort, lossy hints.
raw_store is the truth.

DB connection and path detection delegate to cursor-db-inspector for the canonical
implementation. This script embeds a minimal cross-platform path resolver for
standalone use.

Usage:
  python3 cursor_session_export.py --list [N]
  python3 cursor_session_export.py --list --search "keyword" --after DATE --min-messages N
  python3 cursor_session_export.py --export <composerId> [--outdir DIR]
  python3 cursor_session_export.py --export <composerId> --no-recursive --no-asi
  python3 cursor_session_export.py --verify <file.asi.json>

Defaults: recursive ON, verify-after-export ON, all 3 output formats ON.
"""
import sqlite3, json, sys, os, argparse, datetime, hashlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cursor-db-core", "scripts"))
from cursor_db_core import connect_readonly as open_db, jload, epoch_to_iso as iso, epoch_to_short as iso_short

__version__ = "4.0.0"

KNOWN_BUBBLE_TYPES = {1: "user", 2: "assistant"}
VALUE_LINKED_NAMESPACES = ["agentKv", "checkpointId"]


# ─── Listing with filters ────────────────────────────────────────────────────

def list_sessions(c, n=30, search=None, after=None, before=None, workspace=None, min_messages=None):
    rows = c.execute(
        "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
    ).fetchall()

    sessions = []
    for key, val in rows:
        env = jload(val)
        if not isinstance(env, dict):
            continue
        cid = key.split(":", 1)[1]
        name = env.get("name") or "(untitled)"
        updated = env.get("lastUpdatedAt")
        msgs = len(env.get("fullConversationHeadersOnly") or [])
        ws = env.get("workspaceIdentifier") or ""

        if search and search.lower() not in name.lower():
            continue
        if after and updated and updated < after:
            continue
        if before and updated and updated > before:
            continue
        if workspace and workspace not in str(ws):
            continue
        if min_messages and msgs < min_messages:
            continue

        sessions.append((cid, name, updated, msgs, ws))

    sessions.sort(key=lambda x: x[2] or 0, reverse=True)
    sessions = sessions[:n]

    print(f"{'composerId':38} {'msgs':>5}  {'updated':19}  name")
    print("-" * 110)
    for cid, name, upd, msgs, ws in sessions:
        print(f"{cid:38} {msgs:>5}  {iso_short(upd):19}  {name[:50]}")


# ─── raw_store: COMPLETE source data model (the truth) ────────────────────────

def collect_raw_store(c, cid, value_scan=True):
    """Collect EVERY row related to this composer across ALL tables, verbatim."""
    store = {}
    seen = set()

    def add(key, raw, namespace=None):
        if key in seen:
            return
        seen.add(key)
        ns = namespace or key.split(":", 1)[0]
        store.setdefault(ns, {})[key] = jload(raw)

    KEY_PREFIXES = [
        f"composerData:{cid}",
        f"bubbleId:{cid}:",
        f"ofsContent:{cid}:",
        f"codeBlockPartialInlineDiffFates:{cid}:",
        f"composerVirtualRowHeights:{cid}",
        f"inlineDiff:{cid}:",
        f"checkpointId:{cid}:",
    ]
    for prefix in KEY_PREFIXES:
        try:
            for (key, val) in c.execute(
                "SELECT key, value FROM cursorDiskKV WHERE key LIKE ?", (f"{prefix}%",)
            ):
                add(key, val)
        except Exception as e:
            print(f"  WARN: scan for {prefix}* failed: {e}", file=sys.stderr)

    try:
        row = c.execute("SELECT key, value FROM cursorDiskKV WHERE key=?", (f"composerData:{cid}",)).fetchone()
        if row:
            add(row[0], row[1])
    except Exception:
        pass

    if value_scan:
        for ns in VALUE_LINKED_NAMESPACES:
            try:
                for (key, val) in c.execute(
                    "SELECT key, value FROM cursorDiskKV WHERE key LIKE ? AND value LIKE ?",
                    (f"{ns}:%", f"%{cid}%"),
                ):
                    add(key, val)
            except Exception as e:
                print(f"  WARN: value-scan for {ns} failed: {e}", file=sys.stderr)

    try:
        hrow = c.execute(
            "SELECT composerId, workspaceId, createdAt, lastUpdatedAt, isArchived, "
            "isSubagent, recency, checkpointAt, value, subagentTypeName "
            "FROM composerHeaders WHERE composerId=?",
            (cid,)
        ).fetchone()
        if hrow:
            header_val = {
                "composerId": hrow[0], "workspaceId": hrow[1],
                "createdAt": hrow[2], "lastUpdatedAt": hrow[3],
                "isArchived": hrow[4], "isSubagent": hrow[5],
                "recency": hrow[6], "checkpointAt": hrow[7],
                "subagentTypeName": hrow[9],
            }
            if hrow[8]:
                header_val["value"] = jload(hrow[8])
            store.setdefault("composerHeaders", {})[f"composerHeaders:{cid}"] = header_val
    except Exception as e:
        print(f"  WARN: composerHeaders fetch failed: {e}", file=sys.stderr)

    try:
        item_rows = c.execute(
            "SELECT key, value FROM ItemTable WHERE key LIKE ?", (f"%{cid}%",)
        ).fetchall()
        for key, val in item_rows:
            add(key, val, namespace="ItemTable")
    except Exception as e:
        print(f"  WARN: ItemTable scan failed: {e}", file=sys.stderr)

    counts = {ns: len(rows) for ns, rows in store.items()}
    return store, counts


# ─── AgentLog v0.2.0 generation ───────────────────────────────────────────────

def _parse_args(s):
    if isinstance(s, (dict, list)):
        return s
    if isinstance(s, str) and s.strip():
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return s
    return s


def _tool_formers(b):
    out = []
    tf = b.get("toolFormerData")
    if isinstance(tf, dict):
        out.append(tf)
    elif isinstance(tf, list):
        out.extend(x for x in tf if isinstance(x, dict))
    for x in (b.get("toolResults") or []):
        if isinstance(x, dict):
            out.append(x)
    return out


def _agentlog_status(s):
    mapping = {"completed": "success", "error": "error", "cancelled": "cancelled"}
    return mapping.get(s, "success")


def bubble_to_agentlog_events(bid, b, seq):
    """Convert a single Cursor bubble into AgentLog v0.2.0 events."""
    events = []
    btype = b.get("type")
    role = KNOWN_BUBBLE_TYPES.get(btype)
    if role is None:
        return events

    ts = iso(b.get("createdAt"))
    base_ts = ts or datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    duration = b.get("turnDurationMs")
    token_count = b.get("tokenCount") or {}

    cursor_props = {}
    meta_fields = [
        "_v", "capabilities", "capabilityContexts", "capabilityType",
        "conversationState", "requestId", "isAgentic", "isRefunded",
        "isSimulatedMsg", "simulatedMessageMetadata", "simulatedMsgReason",
        "isPlanExecution", "planTitle", "planUri", "modelInfo",
        "contextWindowStatusAtCreation", "supportedTools", "cursorCommands",
        "cursorCommandsExplicitlySet", "unifiedMode", "uiElementPicked",
        "projectLayouts", "workspaceUris", "existedPreviousTerminalCommand",
        "existedSubsequentTerminalCommand", "thinkingStyle", "thinkingDurationMs",
        "serverBubbleId", "mcpDescriptors", "context",
    ]
    for f in meta_fields:
        v = b.get(f)
        if v is not None and v != [] and v != {} and v is not False:
            cursor_props[f"cursor:{f}"] = v

    def eid():
        return f"{bid}-{len(events)}"

    # reasoning
    thinking = b.get("thinking")
    if isinstance(thinking, dict) and thinking.get("text"):
        events.append({
            "type": "reasoning", "id": eid(), "timestamp": base_ts,
            "durationMs": b.get("thinkingDurationMs"),
            "intent": thinking["text"][:200] if len(thinking.get("text", "")) > 200 else thinking["text"],
            "rationale": thinking["text"], "alternatives": [],
            "properties": {"cursor:signature": thinking.get("signature")} if thinking.get("signature") else {},
        })

    all_thinking = b.get("allThinkingBlocks")
    if isinstance(all_thinking, list):
        for i, block in enumerate(all_thinking):
            if isinstance(block, dict) and block.get("text") and block != thinking:
                events.append({
                    "type": "reasoning", "id": eid(), "timestamp": base_ts,
                    "intent": block["text"][:200], "rationale": block["text"],
                    "alternatives": [], "properties": {"cursor:blockIndex": i},
                })

    # message
    text = b.get("text") or ""
    if text or role == "user":
        msg_event = {
            "type": "message", "id": eid(), "timestamp": base_ts,
            "durationMs": duration, "role": role, "content": text,
            "tokenUsage": {
                "inputTokens": token_count.get("inputTokens", 0),
                "outputTokens": token_count.get("outputTokens", 0),
                "cacheReadTokens": None, "cacheWriteTokens": None,
            } if token_count else None,
            "properties": cursor_props,
        }
        if b.get("images"):
            msg_event["properties"]["cursor:images"] = b["images"]
        if b.get("richText"):
            msg_event["properties"]["cursor:richText"] = b["richText"]
        events.append(msg_event)

    # toolCall
    for tf in _tool_formers(b):
        call_id = tf.get("toolCallId") or tf.get("toolCallID") or tf.get("modelCallId") or bid
        name = tf.get("name") or "unknown_tool"
        params = _parse_args(tf.get("params") or tf.get("rawArgs") or "")
        result = tf.get("result")
        if result is None and isinstance(tf.get("additionalData"), dict):
            result = tf["additionalData"].get("result")
        output = result if isinstance(result, str) else json.dumps(result, default=str) if result else None
        status = tf.get("status") or "completed"
        events.append({
            "type": "toolCall", "id": eid(), "timestamp": base_ts, "parentId": None,
            "name": name,
            "input": params if isinstance(params, dict) else {"raw": params},
            "output": output, "status": _agentlog_status(status), "summary": None,
            "properties": {"cursor:callId": call_id},
        })

    # fileOperation from gitDiffs
    for diff in (b.get("gitDiffs") or []):
        if isinstance(diff, dict):
            events.append({
                "type": "fileOperation", "id": eid(), "timestamp": base_ts,
                "operation": "edit",
                "path": diff.get("path") or diff.get("filePath") or "",
                "diff": diff.get("diff") or diff.get("content") or json.dumps(diff),
                "linesAdded": diff.get("linesAdded"), "linesRemoved": diff.get("linesRemoved"),
                "properties": {},
            })
        elif isinstance(diff, str):
            events.append({
                "type": "fileOperation", "id": eid(), "timestamp": base_ts,
                "operation": "edit", "path": "", "diff": diff, "properties": {},
            })

    # fileOperation from humanChanges / attachedHumanChanges / assistantSuggestedDiffs
    for field_name in ("humanChanges", "attachedHumanChanges", "assistantSuggestedDiffs"):
        changes = b.get(field_name)
        if isinstance(changes, list):
            for ch in changes:
                if isinstance(ch, dict):
                    events.append({
                        "type": "fileOperation", "id": eid(), "timestamp": base_ts,
                        "operation": "edit",
                        "path": ch.get("path") or ch.get("filePath") or ch.get("uri") or "",
                        "diff": ch.get("diff") or ch.get("content") or json.dumps(ch),
                        "properties": {"cursor:source": field_name},
                    })

    # fileOperation from deletedFiles
    for f in (b.get("deletedFiles") or []):
        path = f if isinstance(f, str) else (f.get("path") if isinstance(f, dict) else str(f))
        events.append({
            "type": "fileOperation", "id": eid(), "timestamp": base_ts,
            "operation": "delete", "path": path, "properties": {},
        })

    # fileOperation from suggestedCodeBlocks / codeBlocks
    for field_name in ("suggestedCodeBlocks", "codeBlocks"):
        for cb in (b.get(field_name) or []):
            if isinstance(cb, dict):
                events.append({
                    "type": "fileOperation", "id": eid(), "timestamp": base_ts,
                    "operation": "edit",
                    "path": cb.get("uri") or cb.get("relativeWorkspacePath") or cb.get("filePath") or "",
                    "diff": cb.get("code") or cb.get("content") or cb.get("text") or "",
                    "properties": {
                        "cursor:source": field_name,
                        "cursor:language": cb.get("languageId") or cb.get("language"),
                    },
                })

    # terminalCommand from consoleLogs
    for log in (b.get("consoleLogs") or []):
        if isinstance(log, dict):
            events.append({
                "type": "terminalCommand", "id": eid(), "timestamp": base_ts,
                "command": log.get("command") or log.get("input") or "",
                "cwd": log.get("cwd"),
                "stdout": log.get("output") or log.get("stdout") or log.get("text") or "",
                "stderr": log.get("stderr"), "exitCode": log.get("exitCode"),
                "properties": {},
            })
        elif isinstance(log, str):
            events.append({
                "type": "terminalCommand", "id": eid(), "timestamp": base_ts,
                "command": "", "stdout": log, "properties": {},
            })

    # terminalCommand from interpreterResults
    for ir in (b.get("interpreterResults") or []):
        if isinstance(ir, dict):
            events.append({
                "type": "terminalCommand", "id": eid(), "timestamp": base_ts,
                "command": ir.get("command") or ir.get("code") or "",
                "stdout": ir.get("output") or ir.get("result") or "",
                "exitCode": ir.get("exitCode"),
                "properties": {"cursor:source": "interpreterResults"},
            })

    # search events
    for ws in (b.get("aiWebSearchResults") or []):
        if isinstance(ws, dict):
            events.append({
                "type": "search", "id": eid(), "timestamp": base_ts,
                "tool": "WebSearch",
                "query": ws.get("query") or ws.get("title") or "",
                "resultCount": len(ws.get("results", [])) if isinstance(ws.get("results"), list) else None,
                "topResults": [r.get("title", "") for r in ws.get("results", [])[:5]] if isinstance(ws.get("results"), list) else [],
                "properties": {"cursor:fullResult": ws},
            })
        elif isinstance(ws, str):
            events.append({
                "type": "search", "id": eid(), "timestamp": base_ts,
                "tool": "WebSearch", "query": ws, "properties": {},
            })

    for cs in (b.get("codebaseContextChunks") or []):
        if isinstance(cs, dict):
            events.append({
                "type": "search", "id": eid(), "timestamp": base_ts,
                "tool": "CodebaseSearch",
                "query": cs.get("query") or cs.get("path") or "",
                "resultCount": 1, "properties": {"cursor:chunk": cs},
            })

    for field_name in ("webReferences", "docsReferences"):
        for ref in (b.get(field_name) or []):
            if isinstance(ref, dict):
                events.append({
                    "type": "search", "id": eid(), "timestamp": base_ts,
                    "tool": "DocsReference" if "docs" in field_name else "WebReference",
                    "query": ref.get("title") or ref.get("url") or ref.get("query") or "",
                    "properties": {"cursor:ref": ref},
                })

    # contextLoad
    context_sources = [
        ("attachedCodeChunks", "file"), ("attachedFolders", "codebase"),
        ("attachedFoldersNew", "codebase"), ("attachedFoldersListDirResults", "codebase"),
        ("attachedFileCodeChunksMetadataOnly", "file"), ("contextPieces", "custom"),
        ("knowledgeItems", "memory"), ("documentationSelections", "rag"),
        ("relevantFiles", "codebase"), ("recentlyViewedFiles", "file"),
        ("externalLinks", "web"), ("notepads", "memory"),
        ("pastChats", "memory"), ("summarizedComposers", "memory"),
        ("cursorRules", "file"),
    ]
    for field_name, source in context_sources:
        items = b.get(field_name)
        if not items or items == []:
            continue
        item_count = len(items) if isinstance(items, list) else 1
        events.append({
            "type": "contextLoad", "id": eid(), "timestamp": base_ts,
            "source": source, "query": field_name, "itemCount": item_count,
            "tokenCount": None, "reason": None,
            "properties": {"cursor:source": field_name, "cursor:data": items},
        })

    # plan
    todos = b.get("todos")
    if todos and isinstance(todos, list) and len(todos) > 0:
        steps = []
        for t in todos:
            if isinstance(t, dict):
                steps.append({
                    "id": t.get("id") or str(len(steps)),
                    "description": t.get("content") or t.get("text") or t.get("title") or "",
                    "status": t.get("status") or "pending", "dependsOn": [],
                })
        events.append({
            "type": "plan", "id": eid(), "timestamp": base_ts,
            "title": "Session TODOs", "steps": steps, "status": "active",
            "properties": {},
        })

    # error
    error_details = b.get("errorDetails")
    if error_details:
        if isinstance(error_details, dict):
            events.append({
                "type": "error", "id": eid(), "timestamp": base_ts,
                "message": error_details.get("message") or error_details.get("error") or json.dumps(error_details),
                "code": error_details.get("code"), "recovery": None, "resolved": False,
                "properties": {"cursor:errorDetails": error_details},
            })
        elif isinstance(error_details, str):
            events.append({
                "type": "error", "id": eid(), "timestamp": base_ts,
                "message": error_details, "resolved": False, "properties": {},
            })

    for lint_field in ("lints", "multiFileLinterErrors"):
        lints = b.get(lint_field)
        if isinstance(lints, list) and lints:
            events.append({
                "type": "error", "id": eid(), "timestamp": base_ts,
                "message": f"{len(lints)} linter errors", "code": None,
                "category": "validation", "recovery": None, "resolved": False,
                "properties": {"cursor:source": lint_field, "cursor:lints": lints},
            })

    # handoff
    spawn_id = b.get("subagentSpawnTaskToolCallId")
    if spawn_id:
        events.append({
            "type": "handoff", "id": eid(), "timestamp": base_ts,
            "fromAgent": "cursor", "toAgent": "subagent",
            "reason": f"Spawned via tool call {spawn_id}",
            "status": "initiated",
            "properties": {"cursor:toolCallId": spawn_id},
        })

    # checkpoint
    checkpoint_id = b.get("checkpointId")
    if checkpoint_id:
        events.append({
            "type": "checkpoint", "id": eid(), "timestamp": base_ts,
            "checkpointType": "snapshot", "label": None,
            "reference": checkpoint_id if isinstance(checkpoint_id, str) else json.dumps(checkpoint_id),
            "restorable": True, "properties": {},
        })

    return events


def build_agentlog(raw_store, cid):
    env = (raw_store.get("composerData") or {}).get(f"composerData:{cid}") or {}
    bubbles = raw_store.get("bubbleId") or {}
    headers = env.get("fullConversationHeadersOnly") or []
    mc = env.get("modelConfig") or {}

    events = []
    all_commits = []
    all_prs = []

    for seq, h in enumerate(headers):
        bid = h.get("bubbleId")
        b = bubbles.get(f"bubbleId:{cid}:{bid}")
        if not isinstance(b, dict):
            continue
        events.extend(bubble_to_agentlog_events(bid, b, seq))
        for commit in (b.get("commits") or []):
            if isinstance(commit, dict):
                all_commits.append({"sha": commit.get("sha") or commit.get("hash") or "", "message": commit.get("message")})
        for pr in (b.get("pullRequests") or []):
            if isinstance(pr, dict):
                all_prs.append({"number": pr.get("number"), "title": pr.get("title"), "url": pr.get("url")})

    msg_count = sum(1 for e in events if e["type"] == "message")
    tool_count = sum(1 for e in events if e["type"] == "toolCall")
    file_paths = set(e["path"] for e in events if e["type"] == "fileOperation" and e.get("path"))
    tools_used = list(set(e["name"] for e in events if e["type"] == "toolCall"))

    start_time = iso(env.get("createdAt")) or datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    end_time = iso(env.get("lastUpdatedAt"))

    return {
        "specVersion": "0.2.0", "id": cid,
        "startTime": start_time, "endTime": end_time, "status": "completed",
        "agent": {
            "name": "Cursor", "version": None,
            "model": mc.get("modelName") or mc.get("model") or mc.get("modelId") or env.get("latestModelName"),
            "provider": mc.get("provider"), "properties": {},
        },
        "project": {
            "name": "",
            "workingDirectory": _workspace_to_path(env.get("workspaceIdentifier")),
            "repository": None, "branch": None, "properties": {},
        } if env.get("workspaceIdentifier") else None,
        "developer": None,
        "events": events,
        "metrics": {
            "messageCount": msg_count, "toolCallCount": tool_count,
            "filesTouchedCount": len(file_paths), "durationMinutes": None,
            "tokenUsage": None, "filesTouched": list(file_paths)[:100],
            "toolsUsed": tools_used[:50], "properties": {},
        },
        "relationships": {
            "commits": all_commits, "pullRequests": all_prs,
            "issues": [], "errors": [], "deployments": [],
            "parentSession": None, "childSessions": [], "properties": {},
        } if (all_commits or all_prs) else None,
        "properties": {
            "cursor:composerMode": env.get("unifiedMode") or env.get("forceMode"),
            "cursor:contextTokensUsed": env.get("contextTokensUsed"),
        },
    }


# ─── ASI v1 normalized view ───────────────────────────────────────────────────

def normalize_bubble(bid, b):
    role = KNOWN_BUBBLE_TYPES.get(b.get("type"), "assistant")
    parts = []

    # reasoning
    thinking = b.get("thinking")
    if isinstance(thinking, dict) and thinking.get("text"):
        parts.append({"kind": "reasoning", "text": thinking["text"], "signature": thinking.get("signature")})
    all_thinking = b.get("allThinkingBlocks")
    if isinstance(all_thinking, list):
        for block in all_thinking:
            if isinstance(block, dict) and block.get("text") and block != thinking:
                parts.append({"kind": "reasoning", "text": block["text"], "signature": block.get("signature")})

    # text
    text = b.get("text") or ""
    if text:
        parts.append({"kind": "text", "text": text})

    # tool_call / tool_result
    for tf in _tool_formers(b):
        call_id = tf.get("toolCallId") or tf.get("toolCallID") or tf.get("modelCallId") or bid
        name = tf.get("name") or "unknown_tool"
        parts.append({
            "kind": "tool_call", "call_id": call_id, "name": name,
            "arguments": _parse_args(tf.get("params") or tf.get("rawArgs") or ""),
            "status": tf.get("status"),
        })
        result = tf.get("result")
        if result is None and isinstance(tf.get("additionalData"), dict):
            result = tf["additionalData"].get("result")
        if result is not None or tf.get("status") in ("completed", "error"):
            out = result if isinstance(result, str) else json.dumps(result, default=str)
            parts.append({
                "kind": "tool_result", "call_id": call_id, "name": name,
                "output": out or "", "status": tf.get("status"),
                "is_error": (tf.get("status") == "error"),
            })

    # file_context
    for ch in (b.get("attachedCodeChunks") or []):
        if ch.get("lines"):
            parts.append({
                "kind": "file_context", "path": ch.get("relativeWorkspacePath"),
                "start_line": ch.get("startLineNumber"), "content": "\n".join(ch["lines"]),
            })

    # code
    for field_name in ("suggestedCodeBlocks", "codeBlocks"):
        for cb in (b.get(field_name) or []):
            if isinstance(cb, dict):
                content = cb.get("code") or cb.get("content") or cb.get("text")
                if content:
                    parts.append({
                        "kind": "code",
                        "language": cb.get("languageId") or cb.get("language"),
                        "path": cb.get("uri") or cb.get("relativeWorkspacePath"),
                        "content": content,
                    })

    # image
    for img in (b.get("images") or []):
        if isinstance(img, dict):
            parts.append({"kind": "image", "uri": img.get("path") or img.get("uri"), "data": img.get("data"), "mime": img.get("mimeType")})

    # diff
    for diff in (b.get("gitDiffs") or []):
        if isinstance(diff, dict):
            parts.append({
                "kind": "diff", "path": diff.get("path") or diff.get("filePath") or "",
                "content": diff.get("diff") or diff.get("content") or json.dumps(diff),
                "lines_added": diff.get("linesAdded"), "lines_removed": diff.get("linesRemoved"),
            })
        elif isinstance(diff, str):
            parts.append({"kind": "diff", "path": "", "content": diff})
    for field_name in ("humanChanges", "attachedHumanChanges", "assistantSuggestedDiffs"):
        for ch in (b.get(field_name) or []):
            if isinstance(ch, dict):
                parts.append({
                    "kind": "diff",
                    "path": ch.get("path") or ch.get("filePath") or ch.get("uri") or "",
                    "content": ch.get("diff") or ch.get("content") or json.dumps(ch),
                    "source": field_name,
                })

    # file_delete
    for f in (b.get("deletedFiles") or []):
        path = f if isinstance(f, str) else (f.get("path") if isinstance(f, dict) else str(f))
        parts.append({"kind": "file_delete", "path": path})

    # terminal
    for log in (b.get("consoleLogs") or []):
        if isinstance(log, dict):
            parts.append({
                "kind": "terminal",
                "command": log.get("command") or log.get("input") or "",
                "output": log.get("output") or log.get("stdout") or log.get("text") or "",
                "exit_code": log.get("exitCode"), "cwd": log.get("cwd"),
            })
        elif isinstance(log, str):
            parts.append({"kind": "terminal", "command": "", "output": log})
    for ir in (b.get("interpreterResults") or []):
        if isinstance(ir, dict):
            parts.append({
                "kind": "terminal",
                "command": ir.get("command") or ir.get("code") or "",
                "output": ir.get("output") or ir.get("result") or "",
                "exit_code": ir.get("exitCode"), "source": "interpreter",
            })

    # web_search
    for ws in (b.get("aiWebSearchResults") or []):
        if isinstance(ws, dict):
            parts.append({"kind": "web_search", "query": ws.get("query") or ws.get("title") or "", "results": ws.get("results") or []})
        elif isinstance(ws, str):
            parts.append({"kind": "web_search", "query": ws, "results": []})
    for ref in (b.get("webReferences") or []):
        if isinstance(ref, dict):
            parts.append({"kind": "web_search", "query": ref.get("title") or ref.get("url") or "", "url": ref.get("url"), "results": [ref]})

    # codebase_search
    for cs in (b.get("codebaseContextChunks") or []):
        if isinstance(cs, dict):
            parts.append({
                "kind": "codebase_search",
                "query": cs.get("query") or cs.get("path") or "",
                "path": cs.get("path") or cs.get("relativeWorkspacePath"),
                "content": cs.get("content") or ("\n".join(cs["lines"]) if cs.get("lines") else None),
            })

    # docs_reference
    for ref in (b.get("docsReferences") or []):
        if isinstance(ref, dict):
            parts.append({"kind": "docs_reference", "title": ref.get("title") or "", "url": ref.get("url"), "content": ref.get("content") or ref.get("snippet")})
    for sel in (b.get("documentationSelections") or []):
        if isinstance(sel, dict):
            parts.append({"kind": "docs_reference", "title": sel.get("title") or sel.get("name") or "", "url": sel.get("url"), "content": sel.get("content")})

    # context_load
    context_sources = [
        ("attachedFolders", "folder"), ("attachedFoldersNew", "folder"),
        ("attachedFoldersListDirResults", "folder"),
        ("attachedFileCodeChunksMetadataOnly", "file"), ("contextPieces", "custom"),
        ("knowledgeItems", "knowledge"), ("relevantFiles", "file"),
        ("recentlyViewedFiles", "file"), ("externalLinks", "web"),
        ("notepads", "notepad"), ("pastChats", "past_chat"),
        ("summarizedComposers", "past_chat"), ("cursorRules", "rules"),
    ]
    for field_name, source_type in context_sources:
        items = b.get(field_name)
        if items and items != []:
            parts.append({
                "kind": "context_load", "source": source_type, "field": field_name,
                "item_count": len(items) if isinstance(items, list) else 1, "data": items,
            })

    # plan
    todos = b.get("todos")
    if todos and isinstance(todos, list) and len(todos) > 0:
        steps = []
        for t in todos:
            if isinstance(t, dict):
                steps.append({
                    "id": t.get("id") or str(len(steps)),
                    "description": t.get("content") or t.get("text") or t.get("title") or "",
                    "status": t.get("status") or "pending",
                })
        parts.append({"kind": "plan", "title": "TODOs", "steps": steps})

    # error
    error_details = b.get("errorDetails")
    if error_details:
        if isinstance(error_details, dict):
            parts.append({"kind": "error", "message": error_details.get("message") or error_details.get("error") or json.dumps(error_details), "code": error_details.get("code")})
        elif isinstance(error_details, str):
            parts.append({"kind": "error", "message": error_details})
    for lint_field in ("lints", "multiFileLinterErrors"):
        lints = b.get(lint_field)
        if isinstance(lints, list) and lints:
            parts.append({"kind": "error", "message": f"{len(lints)} linter errors", "category": "lint", "source": lint_field, "data": lints})

    # commit
    for commit in (b.get("commits") or []):
        if isinstance(commit, dict):
            parts.append({"kind": "commit", "sha": commit.get("sha") or commit.get("hash") or "", "message": commit.get("message")})

    # pull_request
    for pr in (b.get("pullRequests") or []):
        if isinstance(pr, dict):
            parts.append({"kind": "pull_request", "number": pr.get("number"), "title": pr.get("title"), "url": pr.get("url")})

    # handoff
    spawn_id = b.get("subagentSpawnTaskToolCallId")
    if spawn_id:
        parts.append({"kind": "handoff", "to_agent": "subagent", "tool_call_id": spawn_id})

    # checkpoint
    checkpoint_id = b.get("checkpointId")
    if checkpoint_id:
        parts.append({"kind": "checkpoint", "reference": checkpoint_id if isinstance(checkpoint_id, str) else json.dumps(checkpoint_id)})

    tc = b.get("tokenCount") or {}
    return {
        "id": bid, "role": role, "created_at": iso(b.get("createdAt")),
        "tokens": {"input": tc.get("inputTokens", 0), "output": tc.get("outputTokens", 0)} if tc else None,
        "parts": parts,
    }


def build_normalized(raw_store, cid):
    env = (raw_store.get("composerData") or {}).get(f"composerData:{cid}") or {}
    bubbles = raw_store.get("bubbleId") or {}
    headers = env.get("fullConversationHeadersOnly") or []
    mc = env.get("modelConfig") or {}

    messages = []
    for h in headers:
        bid = h.get("bubbleId")
        b = bubbles.get(f"bubbleId:{cid}:{bid}")
        if isinstance(b, dict):
            messages.append(normalize_bubble(bid, b))

    return {
        "session": {
            "id": cid, "title": env.get("name"),
            "created_at": iso(env.get("createdAt")), "updated_at": iso(env.get("lastUpdatedAt")),
            "model": mc.get("modelName") or mc.get("model") or mc.get("modelId"),
            "workspace": env.get("workspaceIdentifier"),
            "cwd": _workspace_to_path(env.get("workspaceIdentifier")),
        },
        "messages": messages,
    }


def _workspace_to_path(wid):
    if isinstance(wid, str) and wid.startswith("file://"):
        from urllib.parse import unquote, urlparse
        return unquote(urlparse(wid).path)
    return None


# ─── Export assembly ──────────────────────────────────────────────────────────

def content_hash(cid, raw_store):
    h = hashlib.sha256()
    h.update(cid.encode())
    h.update(json.dumps(raw_store, separators=(",", ":"), sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def load_manifest(outdir):
    path = os.path.join(outdir, ".export_manifest.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_manifest(outdir, manifest):
    path = os.path.join(outdir, ".export_manifest.json")
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)


def export(c, cid, outdir, want_agentlog=True, want_normalized=True, value_scan=True):
    raw_store, counts = collect_raw_store(c, cid, value_scan=value_scan)
    env_key = f"composerData:{cid}"
    if env_key not in (raw_store.get("composerData") or {}):
        sys.exit(f"ERROR: no composerData for {cid}")

    env = raw_store["composerData"][env_key]
    headers = env.get("fullConversationHeadersOnly") or []
    print(f"Session: {env.get('name') or '(untitled)'} ({len(headers)} bubbles)")
    print(f"  Raw store: {counts}")

    os.makedirs(outdir, exist_ok=True)
    manifest = load_manifest(outdir)
    chash = content_hash(cid, raw_store)

    if manifest.get(cid, {}).get("hash") == chash:
        print(f"  SKIP: already exported with identical content (hash={chash})")
        return

    exported_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    written = []

    # 1. raw_store.json
    raw_file = os.path.join(outdir, f"{cid}.raw_store.json")
    raw_doc = {
        "format": "cursor_raw_store", "format_version": "1.0",
        "source": {
            "tool": "cursor", "schema": "cursorDiskKV",
            "exported_at": exported_at,
            "exporter": f"cursor_session_export.py@{__version__}",
            "completeness": "full", "row_counts": counts,
        },
        "raw_store": raw_store,
    }
    with open(raw_file, "w") as f:
        json.dump(raw_doc, f, indent=2, default=str, ensure_ascii=False)
    written.append(raw_file)

    # 2. asi.jsonl
    if want_normalized:
        norm = build_normalized(raw_store, cid)
        asi_file = os.path.join(outdir, f"{cid}.asi.jsonl")
        with open(asi_file, "w") as f:
            f.write(json.dumps({
                "asi_version": "1.0", "type": "session", "session": norm["session"],
                "exported_at": exported_at, "exporter": f"cursor_session_export.py@{__version__}",
            }, default=str, ensure_ascii=False) + "\n")
            for msg in norm["messages"]:
                f.write(json.dumps({"type": "message", **msg}, default=str, ensure_ascii=False) + "\n")
        written.append(asi_file)

    # 3. agentlog.jsonl
    if want_agentlog:
        al = build_agentlog(raw_store, cid)
        al_file = os.path.join(outdir, f"{cid}.agentlog.jsonl")
        with open(al_file, "w") as f:
            envelope = {k: v for k, v in al.items() if k != "events"}
            envelope["type"] = "session"
            f.write(json.dumps(envelope, default=str, ensure_ascii=False) + "\n")
            for event in al["events"]:
                f.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")
        written.append(al_file)

    manifest[cid] = {
        "hash": chash, "files": [os.path.basename(p) for p in written],
        "title": env.get("name"), "exported_at": exported_at, "row_counts": counts,
    }
    save_manifest(outdir, manifest)

    for fp in written:
        print(f"  Wrote: {fp}")
    if want_agentlog:
        print(f"  AgentLog: {al['metrics']['messageCount']} messages, "
              f"{al['metrics']['toolCallCount']} tool calls, "
              f"{al['metrics']['filesTouchedCount']} files, "
              f"{len(al['events'])} total events")
    print(f"  Hash: {chash} (re-export will skip if unchanged)")


# ─── Verify ───────────────────────────────────────────────────────────────────

def verify(path):
    errs = []

    if path.endswith(".raw_store.json"):
        with open(path) as f:
            doc = json.load(f)
        if doc.get("format") != "cursor_raw_store":
            errs.append("missing or wrong format field")
        rs = doc.get("raw_store")
        if not isinstance(rs, dict) or "composerData" not in rs:
            errs.append("raw_store missing or has no composerData")
        n_bubbles = len(rs.get("bubbleId", {})) if isinstance(rs, dict) else 0
        if errs:
            print("INVALID:\n  " + "\n  ".join(errs))
            sys.exit(1)
        print(f"OK [raw_store]: namespaces={list(rs.keys())}; {n_bubbles} bubble rows; "
              f"completeness={doc.get('source', {}).get('completeness')}")

    elif path.endswith(".asi.jsonl"):
        with open(path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        if not lines:
            errs.append("empty file")
        else:
            header = lines[0]
            if header.get("type") != "session":
                errs.append("first line must be type=session")
            if not str(header.get("asi_version", "")).startswith("1."):
                errs.append("bad asi_version")
            messages = [l for l in lines[1:] if l.get("type") == "message"]
            seen_calls = set()
            for m in messages:
                for p in m.get("parts", []):
                    if p.get("kind") == "tool_call":
                        seen_calls.add(p.get("call_id"))
                    if p.get("kind") == "tool_result" and p.get("call_id") not in seen_calls:
                        errs.append(f"orphan tool_result call_id={p.get('call_id')}")
        if errs:
            print("INVALID:\n  " + "\n  ".join(errs[:20]))
            sys.exit(1)
        print(f"OK [asi]: {len(messages)} messages; tool_calls={len(seen_calls)}; "
              f"session={header.get('session', {}).get('title')}")

    elif path.endswith(".agentlog.jsonl"):
        with open(path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        if not lines:
            errs.append("empty file")
        else:
            header = lines[0]
            if header.get("type") != "session":
                errs.append("first line must be type=session")
            if header.get("specVersion") != "0.2.0":
                errs.append(f"specVersion={header.get('specVersion')}, expected 0.2.0")
            events = lines[1:]
            from collections import Counter
            etypes = Counter(e.get("type") for e in events)
        if errs:
            print("INVALID:\n  " + "\n  ".join(errs[:20]))
            sys.exit(1)
        print(f"OK [agentlog]: {len(events)} events; types={dict(etypes)}; session={header.get('id')}")

    else:
        with open(path) as f:
            asi = json.load(f)
        if not str(asi.get("asi_version", "")).startswith("1."):
            errs.append("bad asi_version")
        rs = asi.get("raw_store")
        if not isinstance(rs, dict) or "composerData" not in rs:
            errs.append("raw_store missing or has no composerData")
        if errs:
            print("INVALID:\n  " + "\n  ".join(errs[:20]))
            sys.exit(1)
        n_bubbles = len(rs.get("bubbleId", {})) if isinstance(rs, dict) else 0
        print(f"OK [legacy]: raw_store namespaces={list(rs.keys())}; {n_bubbles} bubble rows")


# ─── Recursive subagent discovery ─────────────────────────────────────────────

def find_subagents(c, parent_cid):
    rows = c.execute(
        "SELECT composerId, value FROM composerHeaders WHERE isSubagent=1"
    ).fetchall()
    children = []
    for cid, val in rows:
        if not val:
            continue
        try:
            v = json.loads(val)
        except (json.JSONDecodeError, TypeError):
            continue
        si = v.get("subagentInfo")
        if isinstance(si, dict) and si.get("parentComposerId") == parent_cid:
            children.append({
                "composerId": cid, "name": v.get("name"),
                "subagentType": si.get("subagentTypeName") or si.get("subagentType"),
                "toolCallId": si.get("toolCallId"),
            })
    return children


def export_recursive(c, cid, outdir, want_agentlog=True, want_normalized=True, value_scan=True, depth=0, max_depth=10):
    indent = "  " * depth
    if depth > max_depth:
        print(f"{indent}  MAX DEPTH ({max_depth}) reached, stopping recursion")
        return

    export(c, cid, outdir, want_agentlog=want_agentlog,
           want_normalized=want_normalized, value_scan=value_scan)

    children = find_subagents(c, cid)
    if children:
        print(f"{indent}  ↳ {len(children)} subagents found")
        for child in children:
            child_cid = child["composerId"]
            child_name = child["name"] or "(untitled)"
            child_type = child["subagentType"] or "unknown"
            print(f"{indent}  ↳ [{child_type}] {child_name} ({child_cid})")
            export_recursive(c, child_cid, outdir,
                             want_agentlog=want_agentlog,
                             want_normalized=want_normalized,
                             value_scan=value_scan,
                             depth=depth + 1, max_depth=max_depth)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_date_ms(s):
    try:
        dt = datetime.datetime.fromisoformat(s)
        return int(dt.timestamp() * 1000)
    except ValueError:
        sys.exit(f"ERROR: invalid date format '{s}' — use YYYY-MM-DD or ISO")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Cursor session exporter (raw_store + AgentLog v0.2.0 + ASI v1)")
    ap.add_argument("--list", nargs="?", const=30, type=int, metavar="N")
    ap.add_argument("--export", metavar="COMPOSER_ID")
    ap.add_argument("--recursive", action="store_true", default=True)
    ap.add_argument("--no-recursive", action="store_true")
    ap.add_argument("--outdir", default=os.path.expanduser("~/cursor_exports"))
    ap.add_argument("--search", help="Filter by name substring")
    ap.add_argument("--after", help="Filter: updated after date (YYYY-MM-DD)")
    ap.add_argument("--before", help="Filter: updated before date (YYYY-MM-DD)")
    ap.add_argument("--workspace", help="Filter by workspace path")
    ap.add_argument("--min-messages", type=int, help="Filter: minimum message count")
    ap.add_argument("--no-agentlog", action="store_true")
    ap.add_argument("--no-asi", action="store_true")
    ap.add_argument("--no-value-scan", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--verify", metavar="FILE")
    a = ap.parse_args()

    if a.verify:
        verify(a.verify)
        sys.exit(0)

    c = open_db()
    try:
        if a.list is not None:
            after_ms = parse_date_ms(a.after) if a.after else None
            before_ms = parse_date_ms(a.before) if a.before else None
            list_sessions(c, a.list, search=a.search, after=after_ms,
                          before=before_ms, workspace=a.workspace,
                          min_messages=a.min_messages)
        elif a.export:
            recursive = not a.no_recursive
            if recursive:
                export_recursive(c, a.export, a.outdir,
                                 want_agentlog=not a.no_agentlog,
                                 want_normalized=not a.no_asi,
                                 value_scan=not a.no_value_scan)
            else:
                export(c, a.export, a.outdir,
                       want_agentlog=not a.no_agentlog,
                       want_normalized=not a.no_asi,
                       value_scan=not a.no_value_scan)

            if not a.no_verify:
                print("\n  Verifying exports...")
                import glob as g
                for pattern in ("*.raw_store.json", "*.asi.jsonl", "*.agentlog.jsonl"):
                    for fp in sorted(g.glob(os.path.join(a.outdir, f"{a.export}{pattern[1:]}"))):
                        try:
                            verify(fp)
                        except SystemExit:
                            pass
        else:
            ap.print_help()
    finally:
        c.close()
