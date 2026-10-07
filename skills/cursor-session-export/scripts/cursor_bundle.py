#!/usr/bin/env python3
"""
cursor_bundle.py — Create a self-contained bundle of exported Cursor sessions
with all referenced external files, plus an install script for the target machine.

For the import protocol used by the generated install.py, see cursor-db-surgeon.

Bundle structure:
  bundle/
  ├── sessions/              # .raw_store.json + .asi.jsonl + .agentlog.jsonl
  ├── files/                 # external files referenced by sessions
  ├── canvases/              # Cursor canvas files
  ├── skills/                # Cursor skills referenced
  ├── install.py             # Drop-in restore script
  └── manifest.json          # Bundle metadata + file map

Usage:
  python3 cursor_bundle.py --name "My-Bundle" --sessions ~/cursor_exports/*.raw_store.json
  python3 cursor_bundle.py --name "Project-X" --session-dir ~/cursor_exports/project_x/
"""
import json, os, sys, shutil, glob, argparse, datetime
from urllib.parse import unquote, urlparse


def extract_file_refs(raw_store):
    """Extract all external file paths referenced in a raw_store."""
    refs = set()

    for key in raw_store.get("ofsContent", {}):
        parts = key.split(":", 2)
        if len(parts) >= 3 and parts[2].startswith("file://"):
            path = unquote(urlparse(parts[2]).path)
            if path and os.path.exists(path):
                refs.add(path)

    for key, bubble in raw_store.get("bubbleId", {}).items():
        if not isinstance(bubble, dict):
            continue
        for ch in (bubble.get("attachedCodeChunks") or []):
            p = ch.get("absolutePath") or ch.get("relativeWorkspacePath")
            if p and os.path.isabs(p) and os.path.exists(p):
                refs.add(p)
        for cb in (bubble.get("suggestedCodeBlocks") or bubble.get("codeBlocks") or []):
            if isinstance(cb, dict):
                p = cb.get("uri") or cb.get("absolutePath")
                if p and p.startswith("file://"):
                    path = unquote(urlparse(p).path)
                    if os.path.exists(path):
                        refs.add(path)
                elif p and os.path.isabs(p) and os.path.exists(p):
                    refs.add(p)

    return refs


def classify_ref(path):
    if "/.cursor/skills/" in path:
        return "skills"
    if "/.cursor/projects/" in path and "/canvases/" in path:
        return "canvases"
    if "/.cursor/" in path:
        return "cursor_config"
    return "files"


def create_bundle(name, session_files, outdir):
    bundle_dir = os.path.join(outdir, name)
    os.makedirs(bundle_dir, exist_ok=True)

    sessions_dir = os.path.join(bundle_dir, "sessions")
    files_dir = os.path.join(bundle_dir, "files")
    skills_dir = os.path.join(bundle_dir, "skills")
    canvases_dir = os.path.join(bundle_dir, "canvases")
    os.makedirs(sessions_dir, exist_ok=True)

    manifest = {
        "bundle_name": name,
        "created_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        "sessions": [],
        "external_files": [],
        "total_bubbles": 0,
    }

    all_refs = set()

    print(f"Creating bundle: {name}")
    print(f"  Output: {bundle_dir}")
    print()

    for sf in session_files:
        if not sf.endswith(".raw_store.json"):
            continue
        basename = os.path.basename(sf)
        cid = basename.replace(".raw_store.json", "")

        shutil.copy2(sf, os.path.join(sessions_dir, basename))
        for ext in (".asi.jsonl", ".agentlog.jsonl"):
            companion = sf.replace(".raw_store.json", ext)
            if os.path.exists(companion):
                shutil.copy2(companion, os.path.join(sessions_dir, os.path.basename(companion)))

        with open(sf) as f:
            doc = json.load(f)
        raw_store = doc.get("raw_store", {})

        env_key = list(raw_store.get("composerData", {}).keys())
        session_name = "(untitled)"
        if env_key:
            env = raw_store["composerData"][env_key[0]]
            session_name = env.get("name") or "(untitled)"

        bubble_count = len(raw_store.get("bubbleId", {}))
        manifest["total_bubbles"] += bubble_count

        refs = extract_file_refs(raw_store)
        all_refs.update(refs)

        manifest["sessions"].append({
            "composerId": cid, "name": session_name,
            "bubbles": bubble_count, "file": basename,
            "external_refs": len(refs),
        })
        print(f"  + {session_name[:50]} ({bubble_count} bubbles, {len(refs)} file refs)")

    print()
    print(f"  Bundling {len(all_refs)} external files...")

    home = os.path.expanduser("~")
    for ref_path in sorted(all_refs):
        category = classify_ref(ref_path)
        rel_path = ref_path[len(home) + 1:] if ref_path.startswith(home) else ref_path.lstrip("/")

        if category == "skills":
            dest_dir = skills_dir
        elif category == "canvases":
            dest_dir = canvases_dir
        else:
            dest_dir = files_dir

        dest = os.path.join(dest_dir, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        if os.path.isfile(ref_path):
            shutil.copy2(ref_path, dest)
        elif os.path.isdir(ref_path) and not os.path.exists(dest):
            shutil.copytree(ref_path, dest)

        manifest["external_files"].append({
            "source": ref_path,
            "bundle_path": os.path.relpath(dest, bundle_dir),
            "category": category,
        })

    # Bundle entire directories with 3+ referenced files
    dir_refs = set()
    for ref in all_refs:
        parent = os.path.dirname(ref)
        if parent != home and parent not in dir_refs:
            same_dir = [r for r in all_refs if os.path.dirname(r) == parent]
            if len(same_dir) >= 3:
                dir_refs.add(parent)

    for dir_path in dir_refs:
        rel = dir_path[len(home) + 1:] if dir_path.startswith(home) else dir_path.lstrip("/")
        dest = os.path.join(files_dir, rel)
        if not os.path.exists(dest):
            try:
                shutil.copytree(dir_path, dest, dirs_exist_ok=True)
                print(f"  + bundled dir: {rel}")
            except Exception as e:
                print(f"  WARN: couldn't bundle {rel}: {e}")

    install_script = os.path.join(bundle_dir, "install.py")
    with open(install_script, "w") as f:
        f.write(INSTALL_SCRIPT)
    os.chmod(install_script, 0o755)

    with open(os.path.join(bundle_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    bundle_size = sum(
        os.path.getsize(os.path.join(dp, fn))
        for dp, _, fns in os.walk(bundle_dir) for fn in fns
    )

    print()
    print(f"=== Bundle created: {bundle_dir} ===")
    print(f"  Sessions: {len(manifest['sessions'])}")
    print(f"  Total bubbles: {manifest['total_bubbles']}")
    print(f"  External files: {len(manifest['external_files'])}")
    print(f"  Bundle size: {bundle_size / (1024*1024):.1f} MB")
    print()
    print(f"To install on target:")
    print(f"  1. Copy bundle to target machine")
    print(f"  2. Quit Cursor on target")
    print(f"  3. python3 {name}/install.py")
    print(f"  4. Open Cursor")

    return bundle_dir


INSTALL_SCRIPT = '''#!/usr/bin/env python3
"""
install.py — Restore this session bundle into a Cursor installation.

For the full import protocol, pre-flight checks, and workspace assignment,
see the cursor-db-surgeon skill.

Cursor must be QUIT before running.

Usage:
  python3 install.py
  python3 install.py --dry-run
  python3 install.py --sessions-only
  python3 install.py --files-only
"""
import sqlite3, json, os, sys, shutil, platform, glob, subprocess


def _db_path():
    s = platform.system()
    if s == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb")
    elif s == "Windows":
        return os.path.join(os.environ.get("APPDATA", "~"), "Cursor", "User", "globalStorage", "state.vscdb")
    return os.path.expanduser("~/.config/Cursor/User/globalStorage/state.vscdb")


def _check_cursor_not_running():
    db = _db_path()
    try:
        result = subprocess.run(["lsof", db], capture_output=True, text=True, timeout=10)
        if result.stdout.strip():
            print("ERROR: Cursor is running. Quit Cursor first.")
            sys.exit(1)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def import_sessions(bundle_dir, dry_run=False):
    db = _db_path()
    if not os.path.exists(db):
        sys.exit(f"ERROR: Cursor DB not found at {db}")

    sessions_dir = os.path.join(bundle_dir, "sessions")
    files = sorted(glob.glob(os.path.join(sessions_dir, "*.raw_store.json")))

    if not files:
        print("No session files found in bundle/sessions/")
        return

    print(f"Importing {len(files)} sessions into {db}")
    if dry_run:
        print("(DRY RUN)")
        for f in files:
            with open(f) as fh:
                doc = json.load(fh)
            rs = doc.get("raw_store", {})
            cd_keys = list(rs.get("composerData", {}).keys())
            if cd_keys:
                env = rs["composerData"][cd_keys[0]]
                print(f"  {env.get('name', '?')}: {len(rs.get('bubbleId', {}))} bubbles")
        return

    conn = sqlite3.connect(db, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")

    success = 0
    for sf in files:
        with open(sf) as fh:
            doc = json.load(fh)
        raw_store = doc.get("raw_store", {})
        cd_keys = list(raw_store.get("composerData", {}).keys())
        if not cd_keys:
            continue
        cid = cd_keys[0].split(":", 1)[1]
        env = raw_store["composerData"][cd_keys[0]]

        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = 0
            for namespace, entries in raw_store.items():
                if namespace == "composerHeaders":
                    continue
                if namespace == "ItemTable":
                    for key, val in entries.items():
                        conn.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                                     (key, json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val))
                        rows += 1
                    continue
                for key, val in entries.items():
                    conn.execute("INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?, ?)",
                                 (key, json.dumps(val, ensure_ascii=False)))
                    rows += 1

            ch = raw_store.get("composerHeaders", {}).get(f"composerHeaders:{cid}")
            if ch:
                conn.execute("""INSERT OR REPLACE INTO composerHeaders
                    (composerId, workspaceId, createdAt, lastUpdatedAt, isArchived,
                     isSubagent, recency, checkpointAt, value, subagentTypeName)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (cid, ch.get("workspaceId"), ch.get("createdAt"), ch.get("lastUpdatedAt"),
                     ch.get("isArchived", 0), ch.get("isSubagent", 0), ch.get("recency"),
                     ch.get("checkpointAt"),
                     json.dumps(ch.get("value", {}), ensure_ascii=False) if ch.get("value") else None,
                     ch.get("subagentTypeName")))
                rows += 1

            conn.execute("COMMIT")
            print(f"  \\u2713 {env.get('name', '?')[:45]:45s} {rows} rows")
            success += 1
        except Exception as e:
            conn.execute("ROLLBACK")
            print(f"  \\u2717 {env.get('name', '?')[:45]:45s} ERROR: {e}")

    conn.close()
    print(f"\\nImported {success}/{len(files)} sessions")


def restore_files(bundle_dir, dry_run=False):
    manifest_path = os.path.join(bundle_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        print("No manifest.json — skipping file restoration")
        return

    with open(manifest_path) as f:
        manifest = json.load(f)

    restored = 0
    skipped = 0

    print(f"Restoring {len(manifest.get('external_files', []))} external files...")
    if dry_run:
        print("(DRY RUN)")

    for entry in manifest.get("external_files", []):
        source_path = entry["source"]
        bundle_path = os.path.join(bundle_dir, entry["bundle_path"])

        if not os.path.exists(bundle_path):
            continue
        if os.path.exists(source_path):
            skipped += 1
            continue
        if dry_run:
            print(f"  would restore: {source_path}")
            continue

        os.makedirs(os.path.dirname(source_path), exist_ok=True)
        if os.path.isfile(bundle_path):
            shutil.copy2(bundle_path, source_path)
        elif os.path.isdir(bundle_path):
            shutil.copytree(bundle_path, source_path, dirs_exist_ok=True)
        restored += 1

    print(f"  Restored: {restored}, Already existed (skipped): {skipped}")


if __name__ == "__main__":
    bundle_dir = os.path.dirname(os.path.abspath(__file__))
    dry_run = "--dry-run" in sys.argv
    sessions_only = "--sessions-only" in sys.argv
    files_only = "--files-only" in sys.argv

    print(f"=== Cursor Session Bundle Installer ===")
    print(f"Bundle: {os.path.basename(bundle_dir)}")
    print()

    if not dry_run:
        _check_cursor_not_running()

    if not files_only:
        import_sessions(bundle_dir, dry_run=dry_run)
        print()

    if not sessions_only:
        restore_files(bundle_dir, dry_run=dry_run)
        print()

    if not dry_run:
        print("Done! Open Cursor to see restored sessions.")
        print("For workspace reassignment, see cursor-db-surgeon.")
    else:
        print("Dry run complete. Remove --dry-run to execute.")
'''


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Create a drop-in Cursor session bundle")
    ap.add_argument("--name", required=True, help="Bundle name")
    ap.add_argument("--sessions", nargs="+", help="Session .raw_store.json files")
    ap.add_argument("--session-dir", help="Directory containing .raw_store.json files")
    ap.add_argument("--outdir", default=os.path.expanduser("~/cursor_bundles"))
    a = ap.parse_args()

    files = []
    if a.sessions:
        for pattern in a.sessions:
            files.extend(glob.glob(pattern))
    if a.session_dir:
        files.extend(glob.glob(os.path.join(a.session_dir, "*.raw_store.json")))

    files = sorted(set(f for f in files if f.endswith(".raw_store.json")))
    if not files:
        sys.exit("No .raw_store.json files found")

    create_bundle(a.name, files, a.outdir)
