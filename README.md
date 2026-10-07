# Cursor DB Skills

Inspect, query, export, import, move, and repair Cursor AI sessions in `state.vscdb`.

Four complementary skills for working with Cursor's SQLite session database — usable from **Cursor**, **Claude Code**, **Gemini CLI**, and any host supporting the [Agent Skills](https://agentskills.io) open standard.

## Skills

| Skill | What it does |
|-------|-------------|
| **cursor-db-core** | Shared Python utilities: cross-platform DB path, read-only/read-write connections, safety checks, session import |
| **cursor-db-inspector** | Read-only inspection: schema, entities, namespaces, relationships, 20 pre-built SQL queries, live stats |
| **cursor-db-surgeon** | Write operations: import sessions, move between workspaces, pin sidebar grouping, orphan cleanup |
| **cursor-session-export** | Full-fidelity export to 3 formats: raw_store (lossless), AgentLog v0.2.0, ASI v1 normalized |

## Install

### Cursor — From GitHub Repository

In Cursor: **Customize → From GitHub Repository** → enter:

```
anmol0e/cursor-db-skills
```

### Cursor Marketplace

*(Pending review — submit at [cursor.com/marketplace/publish](https://cursor.com/marketplace/publish))*

### npx (any agent)

```bash
npx skills add anmol0e/cursor-db-skills
npx skills add anmol0e/cursor-db-skills --agent cursor
npx skills add anmol0e/cursor-db-skills --agent claude-code --agent gemini-cli
```

### Claude Code

```bash
/plugin marketplace add anmol0e/cursor-db-skills
```

### Gemini CLI

```bash
gemini skills install https://github.com/anmol0e/cursor-db-skills.git --path skills
```

### Manual

```bash
git clone https://github.com/anmol0e/cursor-db-skills.git
# Copy skills/ into your agent's skill directory:
cp -r cursor-db-skills/skills/* ~/.cursor/skills/
# Or for Claude Code:
cp -r cursor-db-skills/skills/* ~/.claude/skills/
```

## Quick Start

### Inspect your database

```
> How many sessions do I have? What's the database size?
```

The agent activates `cursor-db-inspector` and runs:

```bash
python3 scripts/cursor_db_inspect.py stats
```

### Export a session

```
> Export my latest session to AgentLog format
```

The agent activates `cursor-session-export` and runs:

```bash
python3 scripts/cursor_session_export.py --list 5
python3 scripts/cursor_session_export.py --export <composerId>
```

### Move sessions to a different workspace

```
> Move all sessions from the old project folder to the new one
```

The agent activates `cursor-db-surgeon` and follows the workspace move protocol with pre-flight safety checks.

## Requirements

- **Python 3.9+** (stdlib only — no pip installs needed)
- **Cursor installed** (the skills query Cursor's `state.vscdb` SQLite database)
- **macOS, Linux, or Windows** (cross-platform DB path detection)

## How It Works

The skills form a layered architecture:

```
cursor-db-core          ← shared Python module (DB access, safety checks)
  ├── cursor-db-inspector   ← read-only queries (imports from core)
  ├── cursor-db-surgeon     ← write operations (imports from core)
  └── cursor-session-export ← export to 3 formats (imports from core)
```

Each skill's scripts resolve `cursor-db-core` using `__file__`-relative paths, so they work regardless of install location (user skills, project skills, plugin cache, or any agent's skill directory).

## Output Formats (Export)

| File | Format | Use case |
|------|--------|----------|
| `<cid>.raw_store.json` | Complete Cursor data model | Lossless Cursor-to-Cursor migration |
| `<cid>.agentlog.jsonl` | AgentLog v0.2.0 | Ecosystem tools, analytics |
| `<cid>.asi.jsonl` | ASI v1 normalized | Typed parts, streaming-friendly |

## Contributing

Issues and PRs welcome. Please:

1. Test changes against a real `state.vscdb` before submitting
2. Ensure all scripts run with Python 3.9+ stdlib only (no external dependencies)
3. Keep SKILL.md files under 500 lines
4. Use relative paths — no hardcoded `~/.cursor/skills/` references

## License

[MIT](LICENSE)
