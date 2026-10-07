# Cursor DB Inspector — Full Field Reference

## composerData — Session Envelope (all fields)

Key: `composerData:<composerId>` · Version: `_v: 18` (as of Cursor ~Oct 2026; increments across releases)

### Identity & Status

| Field | Type | Description |
|-------|------|-------------|
| `_v` | int | Schema version (18) |
| `composerId` | string (UUID) | Session identifier |
| `name` | string | Display title |
| `status` | string | `completed` \| `aborted` \| `active` |
| `createdAt` | int (epoch ms) | Session creation time |
| `lastUpdatedAt` | int (epoch ms) | Last activity time |
| `unfinishedRunAt` | int (epoch ms) | Timestamp of in-progress run |
| `conversationCheckpointLastUpdatedAt` | int (epoch ms) | Last checkpoint time |
| `chatGenerationUUID` | string (UUID) | Current generation request ID |
| `latestChatGenerationUUID` | string (UUID) | Most recent generation ID |

### Mode & Model

| Field | Type | Description |
|-------|------|-------------|
| `unifiedMode` | string | `agent` \| `edit` \| `ask` |
| `forceMode` | string | `edit` etc. |
| `isAgentic` | boolean | Whether session uses agentic flow |
| `isNAL` | boolean | New Agent Loop flag |
| `modelConfig.modelName` | string | e.g. `claude-opus-4-6`, `auto-smart` |
| `modelConfig.maxMode` | boolean | Max context mode enabled |
| `modelConfig.selectedModels[]` | array | `{modelId, parameters[]}` |
| `activeCustomMode` | string \| null | Custom mode if active |
| `committedCustomMode` | string \| null | Committed custom mode |
| `pendingExitedCustomMode` | string \| null | Pending exit from custom mode |

### Context & Tokens

| Field | Type | Description |
|-------|------|-------------|
| `contextUsagePercent` | float | e.g. 3.43 — % of context window used |
| `contextTokensUsed` | int | e.g. 34,304 |
| `contextTokenLimit` | int | e.g. 1,000,000 |
| `promptTokenBreakdown.totalUsedTokens` | int | Total tokens consumed |
| `promptTokenBreakdown.maxTokens` | int | Maximum allowed |
| `promptTokenBreakdown.categories[]` | array | `{id, label, estimatedTokens}` |
| `conversationState` | string | Base64-encoded encrypted state blob |
| `speculativeSummarizationEncryptionKey` | string | Base64 encryption key |
| `blobEncryptionKey` | string | Base64 key for content blobs |

Token category IDs (as of ~Oct 2026): `system_prompt`, `tools`, `rules`, `skills`, `mcp`, `subagents`, `summarized_conversation`, `conversation`.

### Conversation Structure

| Field | Type | Description |
|-------|------|-------------|
| `fullConversationHeadersOnly[]` | array | Ordered bubble refs: `{bubbleId, type, grouping{isRenderable, hasText, textPreview, toolDisplayComputed}, contentHeightHint, createdAt}` |
| `conversationMap` | object | Conversation state mapping |
| `generatingBubbleIds[]` | array | Currently-streaming bubble IDs |
| `hasChangedContext` | boolean | Whether context was modified |
| `hasUnreadMessages` | boolean | Unread indicator |
| `lastReadAtMs` | int (epoch ms) | Last user view |

### Files & Git

| Field | Type | Description |
|-------|------|-------------|
| `originalFileStates` | object | Pre-edit file contents keyed by URI |
| `newlyCreatedFiles[]` | array | Files created during session |
| `newlyCreatedFolders[]` | array | Folders created during session |
| `totalLinesAdded` | int | Aggregate lines added |
| `totalLinesRemoved` | int | Aggregate lines removed |
| `addedFiles` | int | Count of new files |
| `removedFiles` | int | Count of deleted files |
| `trackedGitRepos[]` | array | Git repos tracked by this session |

### Subagent Hierarchy

| Field | Type | Description |
|-------|------|-------------|
| `subComposerIds[]` | array | Legacy child session IDs |
| `subagentComposerIds[]` | array | Current subagent child IDs |
| `subagentInfo` | object \| null | Present on children — links to parent |
| `isBestOfNParent` | boolean | Parent of best-of-N evaluation |
| `isBestOfNSubcomposer` | boolean | One candidate in best-of-N |

### Worktree & Plan

| Field | Type | Description |
|-------|------|-------------|
| `isCreatingWorktree` | boolean | Worktree creation in progress |
| `isApplyingWorktree` | boolean | Changes being applied |
| `isUndoingWorktree` | boolean | Undo in progress |
| `applied` | boolean | Changes applied |
| `pendingCreateWorktree` | boolean | Pending worktree creation |
| `worktreeStartedReadOnly` | boolean | Started read-only |
| `todos[]` | array | Plan items |
| `isSpec` | boolean | Spec session |
| `isProject` | boolean | Project session |
| `isDraft` | boolean | Draft session |
| `queueItems[]` | array | Queued follow-up actions |

### Capabilities & UI

| Field | Type | Description |
|-------|------|-------------|
| `capabilities[]` | array | `{type(int), data}` — enabled capabilities |
| `capabilityContexts[]` | array | Capability context data |
| `context` | object | Full user context object (files, selections, rules, etc.) |
| `codeBlockData` | object | Rendered code block metadata |
| `isFileListExpanded` | boolean | File list panel state |
| `canvasPillCollapsed` | boolean | Canvas pill UI state |
| `browserChipManuallyEnabled` | boolean | Browser chip on |
| `browserChipManuallyDisabled` | boolean | Browser chip off |
| `isQueueExpanded` | boolean | Queue panel state |
| `usageData` | object | Usage tracking data |

Capability type enums observed (non-exhaustive; new values may appear): 15 (tools), 16, 19, 23, 24, 32, 33.

### Miscellaneous

| Field | Type | Description |
|-------|------|-------------|
| `hasLoaded` | boolean | Session loaded flag |
| `richText` | string | Rich text content |
| `text` | string | Plain text content |
| `allAttachedFileCodeChunksUris[]` | array | URIs of attached file code chunks |
| `gitHubPromptDismissed` | boolean | GitHub prompt state |
| `planModeSuggestionUsed` | boolean | Plan mode suggestion state |
| `debugModeSuggestionUsed` | boolean | Debug mode suggestion state |
| `stopHookLoopCount` | int | Hook loop stop counter |
| `isContinuationInProgress` | boolean | Continuation flag |
| `isSpecSubagentDone` | boolean | Spec subagent completion |
| `workspaceIdentifier` | object | `{id, uri?}` |
| `subtitle` | string | Last message preview (truncated) |
| `filesChangedCount` | int | Files modified count |

---

## bubbleId — Message Entity (86+ fields as of Oct 2026; grows with Cursor updates)

Key: `bubbleId:<composerId>:<bubbleId>` · Version: `_v: 3` (as of ~Oct 2026) · Types: `1` (user), `2` (assistant/tool)

### Core Identity (always present on all bubbles)

| Field | Type | Description |
|-------|------|-------------|
| `_v` | int | Schema version (3) |
| `type` | int | 1=user, 2=assistant/tool |
| `bubbleId` | string (UUID) | Message identifier |
| `createdAt` | string (ISO 8601) | Creation timestamp |
| `conversationState` | string | Encrypted state snapshot (base64, `~` prefix) |
| `text` | string | Plain text content |
| `richText` | string | ProseMirror JSON (rare — user bubbles only) |
| `unifiedMode` | int | 2=agent |
| `tokenCount.inputTokens` | int | Input tokens consumed |
| `tokenCount.outputTokens` | int | Output tokens generated |
| `isAgentic` | boolean | Agentic mode flag |
| `requestId` | string | Generation request ID |

### Timing (assistant bubbles)

| Field | Type | Freq | Description |
|-------|------|------|-------------|
| `startedAtMs` | int (epoch ms) | common | Generation started |
| `completedAtMs` | int (epoch ms) | common | Generation completed |
| `turnDurationMs` | int | rare | Full turn duration (turn-summary bubbles) |

### Thinking / Reasoning

| Field | Type | Freq | Description |
|-------|------|------|-------------|
| `thinking` | string | rare | Raw thinking/reasoning text |
| `thinkingStyle` | int | rare | Thinking mode configuration |
| `thinkingDurationMs` | int | rare | Time in thinking phase |
| `allThinkingBlocks` | array | always* | All thinking blocks (empty if none) |

### Code

| Field | Type | Freq | Description |
|-------|------|------|-------------|
| `codeBlocks` | array | common | Generated code blocks |
| `suggestedCodeBlocks` | array | always* | Suggested code changes (empty if none) |

### Tool Execution

| Field | Type | Freq | Description |
|-------|------|------|-------------|
| `toolFormerData` | object | common | Tool call envelope (see below) |
| `capabilityType` | int | common | 15=builtin, 30=MCP, 22=other (non-exhaustive; new values may appear) |
| `toolResults` | array | always* | Tool result data |
| `supportedTools` | array | always* | Available tools list |
| `mcpDescriptors` | array | always* | MCP server descriptors |

### Context & References

| Field | Type | Description |
|-------|------|-------------|
| `attachedCodeChunks` | array | File code chunks attached to context |
| `attachedFileCodeChunksMetadataOnly` | array | Metadata-only file refs |
| `attachedFolders` | array | Attached folder paths |
| `attachedFoldersNew` | array | New format folder attachments |
| `attachedFoldersListDirResults` | array | Directory listing results |
| `codebaseContextChunks` | array | Codebase search results |
| `contextPieces` | array | Arbitrary context fragments |
| `relevantFiles` | array | Agent-selected relevant files |
| `knowledgeItems` | array | Knowledge base items |
| `documentationSelections` | array | Selected documentation |
| `externalLinks` | array | External URL references |
| `cursorRules` | array | Active Cursor rules |
| `cursorCommands` | array | Available slash commands |
| `cursorCommandsExplicitlySet` | boolean | Whether commands explicitly set |
| `notepads` | array | Notepad references |
| `pastChats` | array | Referenced past conversations |
| `pastChatsExplicitlySet` | boolean | Whether past chats explicitly set |
| `summarizedComposers` | array | Summarized prior sessions |
| `recentlyViewedFiles` | array | Recently viewed files |
| `recentLocationsHistory` | array | Editor location history |

### Diffs & File Operations

| Field | Type | Description |
|-------|------|-------------|
| `assistantSuggestedDiffs` | array | AI-proposed diffs |
| `gitDiffs` | array | Git diff snapshots |
| `humanChanges` | array | Human-made changes |
| `attachedHumanChanges` | boolean | Whether human changes attached |
| `diffHistories` | array | Diff history log |
| `diffsSinceLastApply` | array | Accumulated diffs since apply |
| `fileDiffTrajectories` | array | File change trajectories |
| `diffsForCompressingFiles` | array | Compression diffs |
| `deletedFiles` | array | Files deleted during session |
| `editTrailContexts` | array | Edit trail context data |

### Web, Docs & Search

| Field | Type | Description |
|-------|------|-------------|
| `aiWebSearchResults` | array | AI web search results |
| `webReferences` | array | Web page references |
| `docsReferences` | array | Documentation references |
| `images` | array | Image attachments |

### Errors & Diagnostics

| Field | Type | Description |
|-------|------|-------------|
| `lints` | array | Lint diagnostic results |
| `approximateLintErrors` | array | Approximate lint errors |
| `multiFileLinterErrors` | array | Multi-file linter errors |
| `consoleLogs` | array | Console/terminal output |
| `interpreterResults` | array | Code interpreter results |

### Git Integration

| Field | Type | Description |
|-------|------|-------------|
| `commits` | array | Commit references |
| `pullRequests` | array | PR references |

### Plan, Capabilities & UI

| Field | Type | Description |
|-------|------|-------------|
| `todos` | array | Plan/todo items |
| `capabilities` | array | Enabled capabilities |
| `capabilityContexts` | array | Capability context data |
| `projectLayouts` | array | Project layout data |
| `workspaceUris` | array | Workspace URIs |
| `uiElementPicked` | array | UI elements selected by user |
| `userResponsesToSuggestedCodeBlocks` | array | Accept/reject of code blocks |

### Boolean Flags

| Field | Type | Description |
|-------|------|-------------|
| `existedSubsequentTerminalCommand` | boolean | Terminal command followed |
| `existedPreviousTerminalCommand` | boolean | Terminal command preceded |
| `isRefunded` | boolean | Tokens refunded |

### User Bubble Context Object (type=1 only)

Present on user bubbles. Contains all user-attached context:

| Field | Type |
|-------|------|
| `context.composers` | array — referenced composer sessions |
| `context.selectedCommits` | array — selected git commits |
| `context.selectedPullRequests` | array — selected PRs |
| `context.selectedImages` | array — attached images |
| `context.selectedDocuments` | array — attached documents |
| `context.selectedVideos` | array — attached videos |
| `context.folderSelections` | array — selected folders |
| `context.fileSelections` | array — selected files |
| `context.terminalFiles` | array — terminal file references |
| `context.selections` | array — editor selections |
| `context.terminalSelections` | array — terminal selections |
| `context.selectedDocs` | array — documentation selections |
| `context.externalLinks` | array — external URLs |
| `context.cursorRules` | array — `{filename, slashSubject{kind, slashSubjectKey, syncEligible}}` |
| `context.cursorCommands` | array — slash commands |
| `context.gitPRDiffSelections` | array — PR diff selections |
| `context.subagentSelections` | array — subagent references |
| `context.browserSelections` | array — browser tab selections |
| `context.extraContext` | array — additional context |
| `context.mentions` | object — maps each type above to position data (dict or array) |

### Rare / Special Fields

| Field | Type | Freq | Description |
|-------|------|------|-------------|
| `agentMode` | int | rare | 1=agent mode (user bubbles) |
| `modelInfo.modelName` | string | rare | Model used (user bubbles) |
| `checkpointId` | string (UUID) | rare | Checkpoint reference (user bubbles) |
| `isPlanExecution` | boolean | rare | Plan execution flag |
| `contextWindowStatusAtCreation` | object | rare | `{percentageRemaining, percentageRemainingFloat, tokensUsed, tokenLimit}` |
| `serverBubbleId` | string (UUID) | very rare | Server-assigned ID (simulated messages) |
| `isSimulatedMsg` | boolean | very rare | Injected system message |
| `simulatedMsgReason` | int | very rare | Observed value: 3=task resumption; enum may have other members |
| `simulatedMessageMetadata` | object | very rare | `{title, taskId}` |

---

## composerHeaders.value — Sidebar Header Envelope

### All Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"head"` |
| `composerId` | string (UUID) | Session ID |
| `name` | string | Display name |
| `lastUpdatedAt` | int (epoch ms) | Last update |
| `unfinishedRunAt` | int (epoch ms) | Active run timestamp |
| `conversationCheckpointLastUpdatedAt` | int | Last checkpoint |
| `createdAt` | int (epoch ms) | Creation time |
| `unifiedMode` | string | `agent` \| `edit` \| `ask` |
| `forceMode` | string | e.g. `edit` |
| `hasUnreadMessages` | boolean | Unread indicator |
| `contextUsagePercent` | float | Context window usage % |
| `totalLinesAdded` | int | Lines added |
| `totalLinesRemoved` | int | Lines removed |
| `filesChangedCount` | int | Files modified |
| `subtitle` | string | Last message preview |
| `hasBlockingPendingActions` | boolean | Blocking actions pending |
| `hasPendingPlan` | boolean | Plan pending |
| `isDraft` | boolean | Draft session |
| `isWorktree` | boolean | Worktree session |
| `worktreeStartedReadOnly` | boolean | Read-only worktree |
| `isSpec` | boolean | Spec session |
| `isProject` | boolean | Project session |
| `isBestOfNSubcomposer` | boolean | Best-of-N candidate |
| `numSubComposers` | int | Child agent count |
| `referencedPlans[]` | array | Plan IDs |
| `trackedGitRepos[]` | array | `{repoPath, branches[{branchName, lastInteractionAt}]}` |

### Workspace & Location

| Field | Type | Description |
|-------|------|-------------|
| `workspaceIdentifier.id` | string | Workspace hash ID |
| `workspaceIdentifier.uri` | object | `{$mid, fsPath, external, path, scheme}` |
| `agentLocation.type` | string | `local` or `cloud` |
| `agentLocation.environment.id` | string | Workspace ID |
| `agentLocation.environment.uri` | object | Full URI — **THE sidebar grouping key** |
| `agentLocation.status` | string | `active` |
| `agentLocationHistory[]` | array | `{id, timestamp, destination{type}, location{type,environment,status}, reason(created\|moved)}` |

### subagentInfo (child sessions only)

| Field | Type | Description |
|-------|------|-------------|
| `subagentType` | int | Agent type enum |
| `parentComposerId` | string (UUID) | Parent session ID |
| `rootParentConversationId` | string (UUID) | Root ancestor |
| `subagentTypeName` | string | e.g. `generalPurpose`, `explore`, `browser-use` |
| `toolCallId` | string | Tool call that spawned this agent |
| `toolCallIdHistory[]` | array | History of tool call IDs |
| `conversationLengthAtSpawn` | int | Parent conversation length at spawn |
| `parentRequestId` | string (UUID) | Parent's generation request ID |
| `rootParentRequestId` | string (UUID) | Root ancestor's request ID |
| `additionalData` | object | Extra metadata |

---

## toolFormerData — Tool Call Envelope

| Field | Type | Description |
|-------|------|-------------|
| `tool` | int | Tool type enum (15=capability) |
| `toolIndex` | int | Index within tool call batch |
| `modelCallId` | string | Model invocation ID |
| `toolCallId` | string | Unique ID (e.g. `toolu_bdrk_...`) |
| `status` | string | `loading` \| `completed` |
| `rawArgs` | string | Raw argument string |
| `name` | string | Tool name |
| `params` | string (JSON) | Tool parameters |
| `result` | string | Execution result (when completed) |
| `additionalData.status` | string | `success` \| `cancelled` |
| `additionalData.startedAtMs` | int | Execution start time |
| `toolCallBinary` | string | Binary-encoded call data |

### Known Tool Names (as of ~Oct 2026; names evolve across versions)

Run `cursor_db_inspect.py tools <CID>` for live distribution in a specific session.

| Tool |
|------|
| `run_terminal_command_v2` |
| `read_file_v2` |
| `edit_file_v2` |
| `update_current_step` |
| `ripgrep_raw_search` |
| `task_v2` |
| `glob_file_search` |
| `todo_write` |
| `ask_question` |
| `get_mcp_tools` |
| `mcp-<ServerName>-<method>` |
| `create_plan` |
| `await` |
