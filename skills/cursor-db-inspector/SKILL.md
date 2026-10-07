---
name: cursor-db-inspector
description: >-
  Inspect, query, audit, and navigate Cursor's state.vscdb database.
  Read-only operations against composerHeaders, cursorDiskKV, and ItemTable.
  Use when asked to find sessions, count messages, check workspace assignments,
  inspect bubble fields, audit database size, list namespaces, examine entity
  structures, find orphaned sessions, or understand the Cursor data model.
  Trigger: "inspect cursor db", "find session", "how many messages",
  "which workspace", "db size", "cursor data model", "bubble fields",
  "namespace distribution", "session count", "audit db".
compatibility: "Requires Python 3.9+ and access to Cursor's state.vscdb SQLite database."
license: MIT
---

# Cursor DB Inspector

Read-only inspection of Cursor's `state.vscdb` SQLite database.

**Primary tool:** `python3 scripts/cursor_db_inspect.py <subcommand>`

**Fallback:** Copy-paste SQL from the cookbook below into `sqlite3`.

## Safety

ALL operations open the DB read-only. Zero mutation risk.

```
file:<DB_PATH>?mode=ro&immutable=1
```

## Connection

### DB paths

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` |
| Linux | `~/.config/Cursor/User/globalStorage/state.vscdb` |
| Windows | `%APPDATA%\Cursor\User\globalStorage\state.vscdb` |

### Shell

```bash
DB="$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
sqlite3 "file:${DB}?mode=ro&immutable=1" "<SQL>"
```

### Python

```python
import sqlite3, os, platform
def db_path():
    s = platform.system()
    if s == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb")
    elif s == "Windows":
        return os.path.join(os.environ.get("APPDATA", "~"), "Cursor/User/globalStorage/state.vscdb")
    return os.path.expanduser("~/.config/Cursor/User/globalStorage/state.vscdb")

conn = sqlite3.connect(f"file:{db_path()}?mode=ro&immutable=1", uri=True)
```

## Schema (3 core tables)

Cursor ships with 3 tables. A 4th (`lost_and_found`) may appear after corruption recovery or VACUUM — it is not present on fresh installs.

```sql
CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB);
-- auto-index: sqlite_autoindex_cursorDiskKV_1 on key

CREATE TABLE composerHeaders (
  composerId TEXT PRIMARY KEY,
  workspaceId TEXT,
  createdAt INTEGER,
  lastUpdatedAt INTEGER,
  isArchived INTEGER,
  isSubagent INTEGER,
  recency INTEGER,
  checkpointAt INTEGER,
  value TEXT,
  subagentTypeName TEXT
);
-- idx_composerHeaders_0 on (workspaceId, isSubagent, isArchived, recency)
-- idx_composerHeaders_1 on (recency, composerId)

CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB);

-- Recovery table — may not exist on fresh installs
CREATE TABLE lost_and_found (rootpgno INTEGER, pgno INTEGER, nfield INTEGER,
  id INTEGER, c0, c1);
```

For workspace pinning infrastructure (`zz_pinned_workspace` table + 3 triggers), see the `cursor-db-surgeon` skill — that is user-created, not part of Cursor's stock schema.

## Namespace Registry (cursorDiskKV)

Run `cursor_db_inspect.py namespaces` for live row counts and sizes.

| Namespace | Key Format | Description |
|-----------|-----------|-------------|
| `bubbleId` | `bubbleId:<cid>:<bid>` | Messages — 86+ JSON fields each (as of Oct 2026; grows with Cursor updates) |
| `agentKv` | `agentKv:blob:<sha256>` | Content-addressed agent runtime blobs |
| `composer.content` | `composer.content.<sha256>` | Content-addressed file source snapshots |
| `checkpointId` | `checkpointId:<cid>:<cpid>` | Workspace snapshots per turn (git diff format) |
| `ofsContent` | `ofsContent:<cid>:<fileUri>` | Original File State at session start |
| `composerData` | `composerData:<cid>` | Session envelopes — full conversation metadata |
| `codeBlockPartialInlineDiffFates` | `…:<cid>:<cbid>` | Accept/reject state per diff hunk |
| `inlineDiff` | `inlineDiff:<wsid>:<diffId>` | Editor inline diffs with original text |
| `composerVirtualRowHeights` | `…:<cid>` | UI scroll layout cache |
| `composerRootWriterDiagnostic` | `…:<cid>` | Agent checkpoint writer diagnostics |
| `cursorBlame` | `cursorBlame:<commitHash>` | AI attribution per commit |
| `composerDraft` | `composerDraft:<cid>` | Unsent message drafts |
| `bcCachedDetails` | `bcCachedDetails:<bcid>` | Cloud agent cached details (binary) |
| `mcp_oauth_registration_lock` | `mcp_oauth…::<url>` | MCP OAuth lock |

### Non-namespaced keys (no colon separator)

| Pattern | Description |
|---------|-------------|
| `composer.content.<sha256>` | Content-addressed file blobs |
| `composer.autoAccept.*` | Auto-accept tracking |
| `slashMenuItems/v7/local.glass.*` | Cached slash menus per workspace |
| `model-nudge.*` | Model upgrade nudge state |
| `composer.composerHeaders.migratedToTable` | Migration flag |

## Entity Summaries

Full field inventories with types, frequencies, and descriptions: see [reference.md](reference.md).

### composerData — Session Envelope (`_v: 18` as of Cursor ~Oct 2026)

Key: `composerData:<composerId>`. ~75+ fields grouped (grows with Cursor updates):

- **Identity**: `_v`, `composerId`, `name`, `status`(completed|aborted|active), `createdAt`, `lastUpdatedAt`, `unfinishedRunAt`, `conversationCheckpointLastUpdatedAt`, `chatGenerationUUID`, `latestChatGenerationUUID`
- **Mode/Model**: `unifiedMode`(agent|edit|ask), `forceMode`, `isAgentic`, `isNAL`, `modelConfig.{modelName, maxMode, selectedModels[]}`, `activeCustomMode`, `committedCustomMode`, `pendingExitedCustomMode`
- **Context/Tokens**: `contextUsagePercent`, `contextTokensUsed`, `contextTokenLimit`, `promptTokenBreakdown.categories[]{id,label,estimatedTokens}`, `conversationState`(encrypted base64), `speculativeSummarizationEncryptionKey`, `blobEncryptionKey`
- **Conversation**: `fullConversationHeadersOnly[]{bubbleId,type,grouping,contentHeightHint,createdAt}`, `conversationMap`, `generatingBubbleIds[]`, `hasChangedContext`, `hasUnreadMessages`, `lastReadAtMs`
- **Files/Git**: `originalFileStates`, `newlyCreatedFiles[]`, `newlyCreatedFolders[]`, `totalLinesAdded`, `totalLinesRemoved`, `addedFiles`, `removedFiles`, `trackedGitRepos[]`
- **Subagent**: `subComposerIds[]`, `subagentComposerIds[]`, `subagentInfo`, `isBestOfNParent`, `isBestOfNSubcomposer`
- **Worktree/Plan**: `isCreatingWorktree`, `isApplyingWorktree`, `isUndoingWorktree`, `applied`, `worktreeStartedReadOnly`, `todos[]`, `isSpec`, `isProject`, `isDraft`, `queueItems[]`, `pendingCreateWorktree`
- **Capabilities/UI**: `capabilities[]{type,data}`, `capabilityContexts[]`, `context`(full object), `codeBlockData`, `isFileListExpanded`, `canvasPillCollapsed`, `browserChipManuallyEnabled`, `browserChipManuallyDisabled`, `isQueueExpanded`, `usageData`
- **Misc**: `hasLoaded`, `richText`, `text`, `allAttachedFileCodeChunksUris[]`, `gitHubPromptDismissed`, `planModeSuggestionUsed`, `debugModeSuggestionUsed`, `stopHookLoopCount`, `isContinuationInProgress`, `isSpecSubagentDone`, `workspaceIdentifier`, `subtitle`, `filesChangedCount`

### bubbleId — Message (86+ fields as of Oct 2026, `_v: 3`)

Key: `bubbleId:<composerId>:<bubbleId>`. Types: `1`=user, `2`=assistant/tool.

- **Core (always present)**: `_v`, `type`, `bubbleId`, `createdAt`, `conversationState`, `text`, `unifiedMode`, `tokenCount.{inputTokens,outputTokens}`, `isAgentic`, `requestId`
- **Timing**: `startedAtMs`(common), `completedAtMs`(common), `turnDurationMs`(rare — turn-summary bubbles only)
- **Content**: `richText`(rare), `thinking`(rare), `thinkingStyle`(rare), `thinkingDurationMs`(rare), `allThinkingBlocks`, `codeBlocks`(common), `suggestedCodeBlocks`
- **Tools**: `toolFormerData`(common), `capabilityType`(common), `toolResults`, `supportedTools`, `mcpDescriptors`
- **Context**: `attachedCodeChunks`, `attachedFolders`, `codebaseContextChunks`, `contextPieces`, `relevantFiles`, `knowledgeItems`, `cursorRules`, `cursorCommands`, `notepads`, `pastChats`, `summarizedComposers`, `recentlyViewedFiles`, `externalLinks`, `documentationSelections`
- **Diffs**: `assistantSuggestedDiffs`, `gitDiffs`, `humanChanges`, `deletedFiles`, `diffHistories`, `fileDiffTrajectories`
- **Web/Docs**: `aiWebSearchResults`, `webReferences`, `docsReferences`, `images`
- **Errors**: `lints`, `approximateLintErrors`, `multiFileLinterErrors`, `consoleLogs`, `interpreterResults`
- **Git**: `commits`, `pullRequests`
- **Rare**: `agentMode`(rare), `modelInfo.modelName`(rare), `checkpointId`(rare), `serverBubbleId`(very rare), `isSimulatedMsg`(very rare), `simulatedMsgReason`(very rare; observed value: 3=task_resumption; enum may have other members), `simulatedMessageMetadata{title,taskId}`

### toolFormerData — Tool Call Envelope

Fields: `tool`(int), `toolIndex`, `modelCallId`, `toolCallId`, `status`(loading|completed), `rawArgs`, `name`, `params`(JSON), `result`, `additionalData.{status(success|cancelled), startedAtMs}`, `toolCallBinary`.

| capabilityType | Meaning |
|---------------:|---------|
| 15 | Built-in tool |
| 30 | MCP tool |
| 22 | Other |

Non-exhaustive; new capability types may appear in future Cursor versions.

Tool names (as of ~Oct 2026; names evolve across versions, e.g. `_v2` suffix may change): `run_terminal_command_v2`, `read_file_v2`, `edit_file_v2`, `update_current_step`, `ripgrep_raw_search`, `task_v2`, `glob_file_search`, `todo_write`, `ask_question`, `get_mcp_tools`, `create_plan`, `await`, `mcp-*`.

### composerHeaders.value — Sidebar Header

See [reference.md](reference.md) § composerHeaders.value for all fields.

Critical: `subagentInfo` on child sessions: `{subagentType(int), parentComposerId, rootParentConversationId, subagentTypeName, toolCallId, toolCallIdHistory[], conversationLengthAtSpawn, parentRequestId, rootParentRequestId, additionalData}`.

9 known subagent types (as of ~Oct 2026; non-exhaustive): `generalPurpose`, `explore`, `shell`, `browser-use`, `code-reviewer`, `side-chat`, `babysit-gitlab-mr`, `ci-investigator`, `cursor-guide`.

Run `cursor_db_inspect.py stats` for live distribution counts.

### Other Entities

| Entity | Key Format | Structure |
|--------|-----------|-----------|
| `checkpointId` | `checkpointId:<cid>:<cpid>` | `{nonExistentFilesVersion, files[]{uri, originalModelDiffWrtV0[]{original{startLineNumber,endLineNumberExclusive}, modified[]}}}` |
| `ofsContent` | `ofsContent:<cid>:<fileUri>` | Raw file source code string |
| `composer.content` | `composer.content.<sha256>` | Raw file source code string (content-addressed) |
| `agentKv` | `agentKv:blob:<sha256>` | Binary/protobuf blobs (content-addressed) |
| `inlineDiff` | `inlineDiff:<wsid>:<diffId>` | `{diffId, uri, originalTextLines[], generationUUID, composerMetadata.{composerId,codeblockId,toolCallId,composerGenerationID}, hideDecorations}` |
| `codeBlockPartialInlineDiffFates` | `…:<cid>:<cbid>` | `{fates[]{removedLines[],removedRange,addedLines[],addedRange,fate("accepted"\|"rejected")}}` |
| `composerRootWriterDiagnostic` | `…:<cid>` | `{version,previousRendererRootBlobIdHex,rendererRootBlobIdHex,throughWriterSequence,writers[]{reason,fields[]},writerInstanceId,writtenAtMs}` |
| `cursorBlame` | `cursorBlame:<commitHash>` | `{metrics.{commitHash,totalLinesAdded,totalLinesDeleted,agentLinesAdded,agentLinesDeleted,branchName,userEmail,rangeAnnotations[],commitSource},conversations[]{id,authorEmail},fetchedAt}` |
| `composerDraft` | `composerDraft:<cid>` | `{text, richText(ProseMirror JSON)}` |
| `bcCachedDetails` | `bcCachedDetails:<bcid>` | Binary/protobuf (cloud agent cache) |

## Relationships

```
composerHeaders ──1:1──► composerData:<cid>          (composerId)
composerData    ──1:N──► bubbleId:<cid>:<bid>         (composerId prefix)
composerHeaders ──N:1──► workspaceMetadata.entries    (workspaceId)
child header    ──N:1──► parent header                (subagentInfo.parentComposerId)
composerData    ──1:N──► composerHeaders (children)   (subagentComposerIds[])
bubbleId        ──1:1──► checkpointId:<cid>:<cpid>    (checkpointId field)
composerData    ──1:N──► ofsContent:<cid>:<uri>       (composerId prefix)
bubbleId        ──1:1──► codeBlockPartialInlineDiffFates (cid+cbid)
agentKv         ──N:M──► multiple namespaces          (SHA-256 content hash in values)
cursorBlame     ──N:M──► composerHeaders              (conversations[].id)
inlineDiff      ──scoped to workspaceId, not composerId
composer.content ──referenced by ofsContent values    (content-addressed)
```

## Ownership Model

| Store | External writes survive? | Notes |
|-------|:------------------------:|-------|
| `composerHeaders` | **No** | Cursor-owned: held in memory, rewritten on startup/shutdown |
| `cursorDiskKV` | **Yes** | Writes persist through restarts |
| `ItemTable` | Mixed | Most persist; `workspaceMetadata.entries` is Cursor-owned |
| `workspaceMetadata.entries` | **No** | Deleted entries reappear; edits reverted |
| `storage.json` | **No** | `backupWorkspaces` rewritten on exit |
| Workspace IDs | N/A | Opaque hashes — NOT computable. Read from DB, never fabricate. |

## Sidebar Grouping

The sidebar groups sessions by **three** fields. Only the third controls the displayed group:

| Location | Field | Controls sidebar? |
|----------|-------|:-----------------:|
| `composerHeaders` column | `workspaceId` | No (index/filter only) |
| `composerHeaders.value` JSON | `workspaceIdentifier` | No (bookkeeping) |
| `composerHeaders.value` JSON | `agentLocation.environment.uri` | **Yes** |

- Sessions without `agentLocation` fall back to unrelated buckets or "No Repo".
- A folder rename mints a new workspace ID — even case-only renames on case-insensitive FS.
- Stale `workspaceMetadata` entries show as phantom "No agents yet" groups — harmless, reappear if deleted.

## Cookbook: Common Queries

Run via script: `python3 scripts/cursor_db_inspect.py <subcmd>`

Or copy-paste SQL into sqlite3 (always use the read-only URI above).

### 1. List recent sessions

```sql
SELECT composerId, workspaceId, isSubagent, subagentTypeName,
  datetime(createdAt/1000,'unixepoch') as created,
  datetime(lastUpdatedAt/1000,'unixepoch') as updated
FROM composerHeaders
WHERE isSubagent = 0
ORDER BY recency DESC LIMIT 20;
```

### 2. List subagents for a parent

```sql
SELECT composerId, subagentTypeName,
  datetime(createdAt/1000,'unixepoch') as created
FROM composerHeaders
WHERE json_extract(value,'$.subagentInfo.parentComposerId') = '<PARENT_CID>'
ORDER BY createdAt;
```

### 3. Count messages per session

```sql
SELECT COUNT(*) as msg_count,
  SUM(CASE WHEN json_extract(value,'$.type')=1 THEN 1 ELSE 0 END) as user_msgs,
  SUM(CASE WHEN json_extract(value,'$.type')=2 THEN 1 ELSE 0 END) as asst_msgs
FROM cursorDiskKV
WHERE key LIKE 'bubbleId:<CID>:%';
```

### 4. Find sessions by workspace path

```sql
SELECT composerId,
  json_extract(value,'$.name') as name,
  json_extract(value,'$.agentLocation.environment.uri.fsPath') as path
FROM composerHeaders
WHERE json_extract(value,'$.agentLocation.environment.uri.fsPath') LIKE '%<PATH_FRAGMENT>%'
ORDER BY recency DESC;
```

### 5. Find sessions by name/keyword

```sql
SELECT composerId, json_extract(value,'$.name') as name,
  datetime(lastUpdatedAt/1000,'unixepoch') as updated
FROM composerHeaders
WHERE json_extract(value,'$.name') LIKE '%<KEYWORD>%'
ORDER BY recency DESC LIMIT 20;
```

### 6. Namespace distribution with sizes

```sql
SELECT SUBSTR(key,1,INSTR(key,':')-1) as prefix,
  COUNT(*) as cnt,
  ROUND(SUM(LENGTH(value))/1048576.0,2) as mb
FROM cursorDiskKV WHERE key LIKE '%:%'
GROUP BY prefix ORDER BY cnt DESC;
```

### 7. Bubble field frequency for a session

```sql
SELECT value FROM cursorDiskKV WHERE key LIKE 'bubbleId:<CID>:%';
-- Pipe output through: python3 -c "
-- import sys,json; from collections import Counter; ..."
-- (use the inspect script: cursor_db_inspect.py bubble-fields <CID>)
```

### 8. Inspect a specific bubble

```sql
SELECT value FROM cursorDiskKV WHERE key = 'bubbleId:<CID>:<BID>';
```

### 9. Check workspace assignment

```sql
SELECT composerId, workspaceId,
  json_extract(value,'$.workspaceIdentifier.id') as ws_ident,
  json_extract(value,'$.agentLocation.environment.id') as agent_loc_id,
  json_extract(value,'$.agentLocation.environment.uri.fsPath') as agent_loc_path
FROM composerHeaders WHERE composerId = '<CID>';
```

### 10. Database size breakdown

```sql
SELECT 'cursorDiskKV' as tbl, COUNT(*) as rows,
  ROUND(SUM(LENGTH(value))/1073741824.0,2) as gb FROM cursorDiskKV
UNION ALL
SELECT 'composerHeaders', COUNT(*),
  ROUND(SUM(LENGTH(value))/1073741824.0,2) FROM composerHeaders
UNION ALL
SELECT 'ItemTable', COUNT(*),
  ROUND(SUM(LENGTH(value))/1073741824.0,2) FROM ItemTable;
```

### 11. Workspaces with session counts

```sql
SELECT workspaceId, COUNT(*) as total,
  SUM(CASE WHEN isSubagent=1 THEN 1 ELSE 0 END) as subagents,
  SUM(CASE WHEN isSubagent=0 THEN 1 ELSE 0 END) as parents
FROM composerHeaders GROUP BY workspaceId ORDER BY total DESC;
```

### 12. Orphaned composerData (no composerHeaders)

```sql
SELECT SUBSTR(key,15) as cid FROM cursorDiskKV
WHERE key LIKE 'composerData:%'
AND SUBSTR(key,15) NOT IN (SELECT composerId FROM composerHeaders);
```

### 13. Sessions with most subagents

```sql
SELECT composerId, json_extract(value,'$.name') as name,
  json_array_length(json_extract(c.value,'$.subagentComposerIds')) as sub_cnt
FROM cursorDiskKV c
WHERE key LIKE 'composerData:%'
AND json_array_length(json_extract(c.value,'$.subagentComposerIds')) > 0
ORDER BY sub_cnt DESC LIMIT 10;
```

### 14. Tool call distribution for a session

```sql
SELECT json_extract(value,'$.toolFormerData.name') as tool,
  COUNT(*) as cnt
FROM cursorDiskKV
WHERE key LIKE 'bubbleId:<CID>:%'
AND json_extract(value,'$.toolFormerData.name') IS NOT NULL
GROUP BY tool ORDER BY cnt DESC;
```

### 15. Token usage across sessions

```sql
SELECT json_extract(value,'$.contextTokensUsed') as used,
  json_extract(value,'$.contextTokenLimit') as lim,
  json_extract(value,'$.name') as name
FROM cursorDiskKV
WHERE key LIKE 'composerData:%'
AND json_extract(value,'$.contextTokensUsed') > 0
ORDER BY CAST(json_extract(value,'$.contextTokensUsed') AS INTEGER) DESC
LIMIT 10;
```

### 16. Recently active sessions

```sql
SELECT composerId, json_extract(value,'$.name') as name,
  datetime(lastUpdatedAt/1000,'unixepoch') as updated, workspaceId
FROM composerHeaders WHERE isSubagent=0
ORDER BY lastUpdatedAt DESC LIMIT 10;
```

### 17. Models used

```sql
SELECT DISTINCT json_extract(value,'$.modelConfig.modelName') as model
FROM cursorDiskKV WHERE key LIKE 'composerData:%'
AND json_extract(value,'$.modelConfig.modelName') IS NOT NULL
ORDER BY model;
```

### 18. File operation stats for a session

```sql
SELECT json_extract(value,'$.totalLinesAdded') as added,
  json_extract(value,'$.totalLinesRemoved') as removed,
  json_extract(value,'$.addedFiles') as new_files,
  json_extract(value,'$.removedFiles') as del_files,
  json_array_length(json_extract(value,'$.newlyCreatedFiles')) as created
FROM cursorDiskKV WHERE key = 'composerData:<CID>';
```

### 19. Find sessions with specific tool usage

```sql
SELECT DISTINCT SUBSTR(key,10,36) as cid FROM cursorDiskKV
WHERE key LIKE 'bubbleId:%'
AND json_extract(value,'$.toolFormerData.name') = '<TOOL_NAME>'
LIMIT 20;
```

### 20. Content by namespace

```sql
SELECT SUBSTR(key,1,INSTR(key,':')-1) as ns,
  COUNT(*) as rows, ROUND(SUM(LENGTH(value))/1048576.0,2) as mb
FROM cursorDiskKV WHERE key LIKE '%:%'
GROUP BY ns ORDER BY mb DESC;
```

## ItemTable Registry

Run `cursor_db_inspect.py query "SELECT ..."` for live key counts and sizes.

| Category | Description |
|----------|-------------|
| `agentData.*` | Agent environment cache, slash menu items |
| `workbench.*` | VS Code workbench state |
| `glass.*` | Glass UI state (tabs, file views, branch recency) |
| `cursor/*` | Tab state, file view state per workspace |
| `src.vs.platform…applicationUser` | VS Code reactive storage |
| `__$__targetStorageMarker` | Storage migration marker |
| `mcpOAuth.*` | MCP OAuth tokens and registration |
| `branchMetadata.*` | PR URLs per branch per repo |
| `secret://*` | Extension secrets |
| `cursor.plugins.*` | Plugin installation tracking |

### Notable Singletons

| Key | Description |
|-----|-------------|
| `workbench.experiments.statsigBootstrap` | Feature flag bootstrap |
| `conversationClassificationScoredConversations` | Conversation scoring |
| `cursorai/serverConfig` | Server config cache |
| `composer.planRegistry` | Plan registry with URIs |
| `glass.localAgentProjects.v1` | Local agent projects |
| `history.recentlyOpenedPathsList` | Recent paths |
| `browserAutomation.history` | Browser URL history |
| `terminal.history.entries.commands` | Terminal command history |
| `workspaceMetadata.entries` | Workspace registry (Cursor-owned) |
| `cloudAgentRepository.agents.*` | Cloud agent repository |
| `cursorAuth/accessToken` | Auth token |
| `mcp.sharedOAuthFanoutEvent.*` | MCP OAuth event fanout |

## DB Configuration

Run `cursor_db_inspect.py stats` for live page count, DB size, and session counts.

| Parameter | Value |
|-----------|-------|
| Page size | 4,096 bytes |
| Journal mode | WAL |
| Auto-vacuum | 2 (incremental) |
| Synchronous | 2 (FULL) |
| Encryption | SEE cccrypt256 (AES-256) |
| FTS5 | Enabled |
| Threadsafe | 2 (multi-thread) |
| Recursive triggers | ON by default (compile option) |
| Session extension | Enabled |
| `state.vscdb.options.json` | `{"useWAL": true}` |

### Structural Constants

| Fact | Value |
|------|-------|
| Bubble types | 1 (user), 2 (assistant/tool) |
| Bubble field count | 86+ as of Oct 2026; grows with Cursor updates |
| Token breakdown categories (as of ~Oct 2026) | system_prompt, tools, rules, skills, mcp, subagents, summarized_conversation, conversation |
| Capability type enums (non-exhaustive) | 15 (tools), 16, 19, 23, 24, 32, 33 |

Run `cursor_db_inspect.py stats` for all live counts (sessions, workspaces, subagent distribution, DB size).
Run query 17 (`Models used`) to discover available models.
