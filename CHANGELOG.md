# Changelog

## [1.0.0] - 2026-10-07

### Added

- **cursor-db-core**: Shared Python foundation — `db_path()`, `connect_readonly()`, `connect_readwrite()`, `check_cursor_not_running()`, `import_raw_store()`, `jload()`, timestamp helpers
- **cursor-db-inspector**: Read-only inspection — schema reference, namespace registry, entity summaries, 20 SQL cookbook queries, 12-subcommand CLI script
- **cursor-db-surgeon**: Write operations — session import, workspace move with trigger-based pinning, folder rename recovery, orphan cleanup, pre-flight safety checks
- **cursor-session-export**: Full-fidelity 3-format export — raw_store (lossless), AgentLog v0.2.0 (11 event types), ASI v1 (19 part kinds), recursive subagent export, idempotency via content hashing, verify command, bundle script
- Cross-platform DB path detection (macOS, Linux, Windows)
- `__file__`-relative `sys.path` resolution for portable plugin installation
- Dual manifests: `.cursor-plugin/plugin.json` (Cursor) + `plugin.json` (Agent Plugin standard)
- `package.json` for npm registry distribution
- Full compliance with [agentskills.io specification](https://agentskills.io/specification)
