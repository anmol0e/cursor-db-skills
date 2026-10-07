#!/usr/bin/env python3
"""cursor_db_inspect.py — Read-only inspection of Cursor's state.vscdb.

Usage:
  python3 cursor_db_inspect.py sessions [--workspace PATH] [--search KEYWORD] [--limit N]
  python3 cursor_db_inspect.py session <composerId>
  python3 cursor_db_inspect.py bubbles <composerId> [--limit N]
  python3 cursor_db_inspect.py bubble <composerId> <bubbleId>
  python3 cursor_db_inspect.py bubble-fields <composerId>
  python3 cursor_db_inspect.py namespaces
  python3 cursor_db_inspect.py workspaces
  python3 cursor_db_inspect.py tools <composerId>
  python3 cursor_db_inspect.py subagents <composerId>
  python3 cursor_db_inspect.py stats
  python3 cursor_db_inspect.py audit
  python3 cursor_db_inspect.py query "<SQL>"

All operations are read-only. Delegates DB access to cursor_db_core.
"""
import json, sys, os
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cursor-db-core", "scripts"))
from cursor_db_core import connect_readonly, jload, epoch_to_iso


def cmd_sessions(args):
    conn = connect_readonly()
    where = ["isSubagent = 0"]
    params = []
    if "--workspace" in args:
        idx = args.index("--workspace")
        where.append("json_extract(value,'$.agentLocation.environment.uri.fsPath') LIKE ?")
        params.append(f"%{args[idx + 1]}%")
    if "--search" in args:
        idx = args.index("--search")
        where.append("json_extract(value,'$.name') LIKE ?")
        params.append(f"%{args[idx + 1]}%")
    limit = 20
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    sql = f"""
        SELECT composerId, workspaceId,
          json_extract(value,'$.name') as name,
          datetime(createdAt/1000,'unixepoch') as created,
          datetime(lastUpdatedAt/1000,'unixepoch') as updated,
          json_extract(value,'$.agentLocation.environment.uri.fsPath') as ws_path
        FROM composerHeaders
        WHERE {' AND '.join(where)}
        ORDER BY recency DESC LIMIT ?
    """
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    print(f"{'composerId':<38} {'workspace':<35} {'name':<40} {'updated'}")
    print("-" * 140)
    for r in rows:
        cid, wsid, name, created, updated, ws_path = r
        print(f"{cid:<38} {(ws_path or wsid or '')[:34]:<35} {(name or '')[:39]:<40} {updated or ''}")
    print(f"\n{len(rows)} sessions")


def cmd_session(args):
    cid = args[0]
    conn = connect_readonly()
    row = conn.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (f"composerData:{cid}",)).fetchone()
    if not row:
        sys.exit(f"No composerData for {cid}")
    d = jload(row[0])
    hdr = conn.execute("SELECT * FROM composerHeaders WHERE composerId = ?", (cid,)).fetchone()
    bubble_count = conn.execute("SELECT COUNT(*) FROM cursorDiskKV WHERE key LIKE ?", (f"bubbleId:{cid}:%",)).fetchone()[0]
    sub_count = len(d.get("subagentComposerIds") or [])
    print(f"Session: {cid}")
    print(f"  Name:       {d.get('name', '')}")
    print(f"  Status:     {d.get('status', '')}")
    print(f"  Mode:       {d.get('unifiedMode', '')}")
    print(f"  Model:      {(d.get('modelConfig') or {}).get('modelName', '')}")
    print(f"  Created:    {epoch_to_iso(d.get('createdAt'))}")
    print(f"  Updated:    {epoch_to_iso(d.get('lastUpdatedAt'))}")
    print(f"  Messages:   {bubble_count}")
    print(f"  Subagents:  {sub_count}")
    print(f"  Lines +/-:  +{d.get('totalLinesAdded', 0)} -{d.get('totalLinesRemoved', 0)}")
    print(f"  Files:      {d.get('filesChangedCount', 0)} changed")
    ctx = d.get("contextUsagePercent", 0)
    used = d.get("contextTokensUsed", 0)
    lim = d.get("contextTokenLimit", 0)
    print(f"  Context:    {ctx:.1f}% ({used:,}/{lim:,} tokens)")
    if hdr:
        print(f"  Workspace:  {hdr[1]}")
        print(f"  Archived:   {bool(hdr[4])}")
        print(f"  IsSubagent: {bool(hdr[5])}")
        if hdr[9]:
            print(f"  SubagentType: {hdr[9]}")
    val = jload(hdr[8]) if hdr and hdr[8] else {}
    loc = (val.get("agentLocation") or {}).get("environment", {}).get("uri", {})
    if loc.get("fsPath"):
        print(f"  Location:   {loc['fsPath']}")
    si = val.get("subagentInfo")
    if si:
        print(f"  Parent:     {si.get('parentComposerId', '')}")
        print(f"  Root:       {si.get('rootParentConversationId', '')}")
        print(f"  SpawnType:  {si.get('subagentTypeName', '')}")


def cmd_bubbles(args):
    cid = args[0]
    limit = 50
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    conn = connect_readonly()
    rows = conn.execute(
        "SELECT key, value FROM cursorDiskKV WHERE key LIKE ? ORDER BY ROWID LIMIT ?",
        (f"bubbleId:{cid}:%", limit),
    ).fetchall()
    print(f"{'#':<4} {'type':<5} {'bubbleId':<38} {'tool/text':<50} {'created'}")
    print("-" * 145)
    for i, (key, val) in enumerate(rows):
        d = jload(val)
        btype = "user" if d.get("type") == 1 else "asst"
        bid = d.get("bubbleId", "")
        tf = d.get("toolFormerData")
        if tf and isinstance(tf, dict) and tf.get("name"):
            preview = f"[{tf['name']}] {tf.get('additionalData', {}).get('status', '')}"
        else:
            preview = (d.get("text") or "")[:49]
        created = d.get("createdAt", "")[:19] if d.get("createdAt") else ""
        print(f"{i+1:<4} {btype:<5} {bid:<38} {preview:<50} {created}")
    print(f"\n{len(rows)} bubbles shown")


def cmd_bubble(args):
    cid, bid = args[0], args[1]
    conn = connect_readonly()
    row = conn.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (f"bubbleId:{cid}:{bid}",)).fetchone()
    if not row:
        sys.exit(f"Bubble not found: {cid}:{bid}")
    d = jload(row[0])
    non_empty = {k: v for k, v in d.items() if v is not None and v != [] and v != "" and v != 0 and v is not False and v != {}}
    print(json.dumps(non_empty, indent=2, ensure_ascii=False, default=str))


def cmd_bubble_fields(args):
    cid = args[0]
    conn = connect_readonly()
    rows = conn.execute("SELECT value FROM cursorDiskKV WHERE key LIKE ?", (f"bubbleId:{cid}:%",)).fetchall()
    all_keys = Counter()
    total = 0
    for (val,) in rows:
        d = jload(val)
        for k in d:
            all_keys[k] += 1
        total += 1
    print(f"{'Field':<45} {'Count':>6} {'%':>6}")
    print("-" * 60)
    for k, cnt in all_keys.most_common():
        print(f"{k:<45} {cnt:>6} {100*cnt/total:>5.0f}%")
    print(f"\n{len(all_keys)} distinct fields across {total} bubbles")


def cmd_namespaces(_args):
    conn = connect_readonly()
    rows = conn.execute("""
        SELECT SUBSTR(key,1,INSTR(key,':')-1) as prefix, COUNT(*) as cnt,
          ROUND(SUM(LENGTH(value))/1048576.0,2) as mb
        FROM cursorDiskKV WHERE key LIKE '%:%'
        GROUP BY prefix ORDER BY cnt DESC
    """).fetchall()
    print(f"{'Namespace':<40} {'Rows':>10} {'MB':>10}")
    print("-" * 65)
    for ns, cnt, mb in rows:
        print(f"{ns:<40} {cnt:>10,} {mb:>10,.2f}")


def cmd_workspaces(_args):
    conn = connect_readonly()
    rows = conn.execute("""
        SELECT workspaceId, COUNT(*) as total,
          SUM(CASE WHEN isSubagent=1 THEN 1 ELSE 0 END) as subs,
          SUM(CASE WHEN isSubagent=0 THEN 1 ELSE 0 END) as parents,
          MIN(createdAt) as oldest, MAX(lastUpdatedAt) as newest
        FROM composerHeaders GROUP BY workspaceId ORDER BY total DESC
    """).fetchall()
    print(f"{'workspaceId':<38} {'total':>6} {'parents':>8} {'subs':>6} {'newest'}")
    print("-" * 90)
    for wsid, total, subs, parents, oldest, newest in rows:
        print(f"{wsid:<38} {total:>6} {parents:>8} {subs:>6} {epoch_to_iso(newest) or ''}")


def cmd_tools(args):
    cid = args[0]
    conn = connect_readonly()
    rows = conn.execute("""
        SELECT json_extract(value,'$.toolFormerData.name') as tool, COUNT(*) as cnt
        FROM cursorDiskKV WHERE key LIKE ? AND json_extract(value,'$.toolFormerData.name') IS NOT NULL
        GROUP BY tool ORDER BY cnt DESC
    """, (f"bubbleId:{cid}:%",)).fetchall()
    print(f"{'Tool':<45} {'Count':>6}")
    print("-" * 55)
    for tool, cnt in rows:
        print(f"{tool:<45} {cnt:>6}")


def cmd_subagents(args):
    cid = args[0]
    conn = connect_readonly()
    rows = conn.execute("""
        SELECT composerId, subagentTypeName,
          datetime(createdAt/1000,'unixepoch') as created,
          datetime(lastUpdatedAt/1000,'unixepoch') as updated,
          json_extract(value,'$.name') as name
        FROM composerHeaders
        WHERE json_extract(value,'$.subagentInfo.parentComposerId') = ?
        ORDER BY createdAt
    """, (cid,)).fetchall()
    print(f"{'composerId':<38} {'type':<20} {'name':<40} {'created'}")
    print("-" * 120)
    for r in rows:
        cid2, stype, created, updated, name = r
        print(f"{cid2:<38} {stype or '':<20} {(name or '')[:39]:<40} {created or ''}")
    print(f"\n{len(rows)} subagents")


def cmd_stats(_args):
    conn = connect_readonly()
    counts = {}
    for tbl in ["cursorDiskKV", "composerHeaders", "ItemTable", "lost_and_found"]:
        try:
            counts[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception:
            counts[tbl] = "N/A"
    ch = conn.execute("""
        SELECT COUNT(*),
          SUM(CASE WHEN isSubagent=1 THEN 1 ELSE 0 END),
          SUM(CASE WHEN isSubagent=0 OR isSubagent IS NULL THEN 1 ELSE 0 END),
          SUM(CASE WHEN isArchived=1 THEN 1 ELSE 0 END),
          COUNT(DISTINCT workspaceId)
        FROM composerHeaders
    """).fetchone()
    print("=== Table Row Counts ===")
    for t, c in counts.items():
        print(f"  {t:<30} {c:>12,}" if isinstance(c, int) else f"  {t:<30} {c:>12}")
    print(f"\n=== Session Stats ===")
    print(f"  Total sessions:    {ch[0]:>8,}")
    print(f"  Subagents:         {ch[1]:>8,}")
    print(f"  Parents:           {ch[2]:>8,}")
    print(f"  Archived:          {ch[3]:>8,}")
    print(f"  Workspaces:        {ch[4]:>8,}")
    types = conn.execute("""
        SELECT subagentTypeName, COUNT(*) FROM composerHeaders
        WHERE subagentTypeName IS NOT NULL AND subagentTypeName != ''
        GROUP BY subagentTypeName ORDER BY COUNT(*) DESC
    """).fetchall()
    print(f"\n=== Subagent Types ===")
    for name, cnt in types:
        print(f"  {name:<25} {cnt:>6,}")
    page_info = conn.execute("SELECT page_count, page_size FROM pragma_page_count, pragma_page_size").fetchone()
    if page_info:
        gb = page_info[0] * page_info[1] / (1024**3)
        print(f"\n=== DB Size ===")
        print(f"  Pages: {page_info[0]:,}  Page size: {page_info[1]}  Total: {gb:.2f} GB")


def cmd_audit(_args):
    conn = connect_readonly()
    print("=== Orphan Check ===")
    orphan_cd = conn.execute("""
        SELECT COUNT(*) FROM cursorDiskKV WHERE key LIKE 'composerData:%'
        AND SUBSTR(key,15) NOT IN (SELECT composerId FROM composerHeaders)
    """).fetchone()[0]
    print(f"  composerData without composerHeaders: {orphan_cd}")
    total_ch = conn.execute("SELECT COUNT(*) FROM composerHeaders").fetchone()[0]
    total_cd = conn.execute("SELECT COUNT(*) FROM cursorDiskKV WHERE key LIKE 'composerData:%'").fetchone()[0]
    print(f"  composerHeaders rows: {total_ch}")
    print(f"  composerData rows:    {total_cd}")
    print(f"  Difference:           {abs(total_ch - total_cd)}")
    try:
        pinned = conn.execute("SELECT COUNT(*) FROM zz_pinned_workspace").fetchone()[0]
    except Exception:
        pinned = "N/A (table not present)"
    print(f"\n=== Pinning ===")
    print(f"  Pinned sessions: {pinned}")
    triggers = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'zz_%'"
    ).fetchall()
    print(f"  Triggers: {', '.join(t[0] for t in triggers) if triggers else 'NONE'}")
    print(f"\n=== Namespace Sizes ===")
    ns_rows = conn.execute("""
        SELECT SUBSTR(key,1,INSTR(key,':')-1) as ns, COUNT(*) as cnt,
          ROUND(SUM(LENGTH(value))/1073741824.0,2) as gb
        FROM cursorDiskKV WHERE key LIKE '%:%'
        GROUP BY ns ORDER BY gb DESC
    """).fetchall()
    for ns, cnt, gb in ns_rows:
        print(f"  {ns:<40} {cnt:>10,} rows  {gb:>8.2f} GB")


def cmd_query(args):
    sql = args[0]
    conn = connect_readonly()
    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()
        if cur.description:
            headers = [d[0] for d in cur.description]
            print("\t".join(headers))
            print("-" * (len(headers) * 20))
        for row in rows:
            print("\t".join(str(c) if c is not None else "" for c in row))
        print(f"\n{len(rows)} rows")
    except Exception as e:
        sys.exit(f"Query error: {e}")


COMMANDS = {
    "sessions": (cmd_sessions, "List recent parent sessions"),
    "session": (cmd_session, "Show session details"),
    "bubbles": (cmd_bubbles, "List bubbles in a session"),
    "bubble": (cmd_bubble, "Show a single bubble (non-empty fields as JSON)"),
    "bubble-fields": (cmd_bubble_fields, "Field frequency for all bubbles in a session"),
    "namespaces": (cmd_namespaces, "cursorDiskKV namespace distribution"),
    "workspaces": (cmd_workspaces, "Workspace session counts"),
    "tools": (cmd_tools, "Tool call distribution for a session"),
    "subagents": (cmd_subagents, "List subagents of a parent session"),
    "stats": (cmd_stats, "Database statistics"),
    "audit": (cmd_audit, "Audit: orphans, pinning, sizes"),
    "query": (cmd_query, "Run arbitrary read-only SQL"),
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: cursor_db_inspect.py <command> [args]\n\nCommands:")
        for name, (_, desc) in COMMANDS.items():
            print(f"  {name:<20} {desc}")
        sys.exit(0)
    cmd_name = sys.argv[1]
    if cmd_name not in COMMANDS:
        sys.exit(f"Unknown command: {cmd_name}. Use --help for list.")
    COMMANDS[cmd_name][0](sys.argv[2:])
