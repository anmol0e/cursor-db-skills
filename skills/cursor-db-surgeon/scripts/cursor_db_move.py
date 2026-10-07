#!/usr/bin/env python3
"""cursor_db_move.py — Move sessions between workspaces.
Delegates DB access to cursor_db_core."""
import json, sys, os, argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "cursor-db-core", "scripts"))
from cursor_db_core import db_path, connect_readwrite


def build_identifier_json(wsid, path):
    return json.dumps({
        "id": wsid,
        "uri": {"$mid": 1, "fsPath": path, "external": f"file://{path}", "path": path, "scheme": "file"},
    }, ensure_ascii=False)


def build_agent_location_json(wsid, path):
    return json.dumps({
        "type": "local",
        "environment": {
            "id": wsid,
            "uri": {"$mid": 1, "fsPath": path, "external": f"file://{path}", "path": path, "scheme": "file"},
        },
        "status": "active",
    }, ensure_ascii=False)


def find_subagents(conn, parent_cids):
    all_cids = set()
    queue = list(parent_cids)
    while queue:
        cid = queue.pop(0)
        rows = conn.execute(
            "SELECT composerId FROM composerHeaders "
            "WHERE json_extract(value,'$.subagentInfo.parentComposerId') = ?",
            (cid,),
        ).fetchall()
        for (child_cid,) in rows:
            if child_cid not in all_cids:
                all_cids.add(child_cid)
                queue.append(child_cid)
    return all_cids


def main():
    parser = argparse.ArgumentParser(description="Move Cursor sessions between workspaces")
    parser.add_argument("--sessions", required=True, help="Comma-separated composerIds")
    parser.add_argument("--target-workspace-id", required=True)
    parser.add_argument("--target-path", required=True, help="Absolute path to project folder")
    parser.add_argument("--include-subagents", action="store_true")
    parser.add_argument("--db", help="Override DB path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    session_cids = set(args.sessions.split(","))
    wsid = args.target_workspace_id
    path = args.target_path

    conn = connect_readwrite(args.db)

    if args.include_subagents:
        subs = find_subagents(conn, session_cids)
        print(f"Found {len(subs)} subagents to include")
        session_cids.update(subs)

    ident_json = build_identifier_json(wsid, path)
    loc_json = build_agent_location_json(wsid, path)

    print(f"Moving {len(session_cids)} sessions to workspace {wsid}")
    print(f"  Path: {path}")

    if args.dry_run:
        print("\n[DRY RUN] Would move:")
        for cid in sorted(session_cids):
            print(f"  {cid}")
        conn.close()
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        for cid in session_cids:
            conn.execute(
                "INSERT OR REPLACE INTO zz_pinned_workspace "
                "(composerId, workspaceId, identifierJson, agentLocationJson) VALUES (?, ?, ?, ?)",
                (cid, wsid, ident_json, loc_json),
            )
            conn.execute("UPDATE composerHeaders SET workspaceId = ? WHERE composerId = ?", (wsid, cid))
            conn.execute(
                "UPDATE composerHeaders SET value = json_set("
                "  json_set(value, '$.workspaceIdentifier', json(?)),"
                "  '$.agentLocation', json(?)) WHERE composerId = ?",
                (ident_json, loc_json, cid),
            )
        conn.execute("COMMIT")
        print(f"\n✓ Moved {len(session_cids)} sessions. Restart Cursor to see changes.")
    except Exception as e:
        conn.execute("ROLLBACK")
        sys.exit(f"✗ ROLLBACK: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
