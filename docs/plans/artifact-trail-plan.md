# Artifact Trail: JSONL State Diff & Timeline Reconstruction

## Status: Phase 1 Complete — Awaiting Review

---

## Task Overview

Build an artifact trail system that reconstructs a timeline of file mutations from Claude Code session JSONL data.

---

## Phase 1: Discovery Findings (COMPLETE)

### JSONL Entry Types

| Type | Count (sample) | Purpose |
|------|----------------|---------|
| `progress` | 913 | Hook events, bash output streaming, agent progress |
| `assistant` | 612 | Claude's responses (contains `tool_use` blocks) |
| `user` | 310 | User messages + `tool_result` blocks |
| `file-history-snapshot` | 57 | File backup tracking with versioned snapshots |
| `queue-operation` | 39 | Internal queue management |
| `summary` | 4 | Conversation compression summaries |

### Tool Call Structures

#### WRITE — Full content available
```json
{
  "type": "tool_use",
  "id": "toolu_01EePt...",
  "name": "Write",
  "input": {
    "file_path": "/path/to/file.json",
    "content": "<FULL FILE CONTENT>"
  }
}
```
- Result: `"File created successfully at: /path/to/file.json"`
- **Full file content IS in the payload**

#### EDIT — Before/after diff available
```json
{
  "type": "tool_use",
  "id": "toolu_015rUY...",
  "name": "Edit",
  "input": {
    "replace_all": false,
    "file_path": "/path/to/SessionRoutes.ts",
    "old_string": "<EXACT TEXT BEING REPLACED>",
    "new_string": "<REPLACEMENT TEXT>"
  }
}
```
- Result: `"The file /path/to/file.ts has been updated successfully."`
- **Both before and after available as `old_string`/`new_string`**

#### BASH — Command + stdout/stderr captured
```json
{
  "type": "tool_use",
  "id": "toolu_012TYh...",
  "name": "Bash",
  "input": {
    "command": "npm test",
    "description": "Run test suite"
  }
}
```
- Success result: stdout in `content` field
- Error result: `"Exit code N\n<stderr>"` with `is_error: true`
- File-modifying commands detectable by parsing `command` string

#### READ — Full content in result
```json
{
  "type": "tool_use",
  "id": "toolu_018VRU...",
  "name": "Read",
  "input": { "file_path": "/path/to/file.md" }
}
```
- Result: Full file content with line numbers (`"     1→..."`)

### file-history-snapshot — Versioned File Backups

Claude Code maintains versioned file backups at `~/.claude/file-history/<session_id>/`:

```json
{
  "type": "file-history-snapshot",
  "messageId": "89b78dfd-...",
  "isSnapshotUpdate": true,
  "snapshot": {
    "timestamp": "2026-02-02T22:25:45.813Z",
    "trackedFileBackups": {
      "clawdbot/src/chat.ts": {
        "backupFileName": "415bad4e2529bbb0@v4",
        "version": 4,
        "backupTime": "2026-02-02T23:25:23.682Z"
      }
    }
  }
}
```

- Backup files are **full file content** snapshots
- `backupFileName: None` means file was **created new**
- 148 sessions have backup directories, up to 130 backup files per session
- Versioned: `@v1`, `@v2`, `@v3` — each before a modification

### Wrapper Structure (every JSONL line)

```json
{
  "parentUuid": "6e191fca-...",
  "isSidechain": false,
  "cwd": "/home/.../development",
  "sessionId": "f3536b6c-...",
  "version": "2.1.22",
  "gitBranch": "feat/semantic-search",
  "type": "assistant",
  "uuid": "25bd5e1f-...",
  "timestamp": "2026-02-02T22:18:02.318Z",
  "toolUseResult": "...",
  "sourceToolAssistantUUID": "..."
}
```

### Data Availability Matrix

| Data | Available? | Source |
|------|-----------|--------|
| File path | Yes | `input.file_path` in tool_use |
| Timestamp | Yes | Wrapper `timestamp` field |
| Full content on Write | Yes | `input.content` |
| Before/After on Edit | Yes | `old_string` / `new_string` |
| Bash command | Yes | `input.command` |
| Bash exit code | Partial | Parse `"Exit code N"` from content string |
| Bash stdout/stderr | Yes | `content` field in tool_result |
| File hash before | No (but backup files exist) | `~/.claude/file-history/` |
| File hash after | No | Would need to hash content or read next backup version |
| Git branch | Yes | Wrapper `gitBranch` field |

---

## Phase 2: State Diff Reconstruction (PENDING)

Build `engram/artifact_trail.py`:

- Parse raw JSONL (not Engram's indexed SQLite) for maximum fidelity
- Dataclass: `ArtifactEvent(sequence, timestamp, tool_type, file_path, old_content, new_content, command, exit_code, stdout, description)`
- Handle: Write, Edit, Read, Bash, Glob, Grep
- Detect file-modifying bash commands: `mv`, `cp`, `rm`, `sed`, `pip install`, `git`, etc.
- Cross-reference `file-history-snapshot` entries for backup version tracking
- Use `tool_use_id` to match tool_use → tool_result pairs

### Key Design Decision
Parse from **raw JSONL** (not Engram SQLite) because:
- JSONL has full `input` payloads (old_string/new_string, file content)
- Engram's `messages` table only stores `content` (the result text), not the tool inputs
- file-history-snapshot entries aren't indexed by Engram at all

## Phase 3: CLI Visualization (PENDING)

Add `engram trail <session_id>` CLI command:
```
#001 [00:30] READ   validators.ts
#002 [00:45] READ   createUser.ts
#003 [01:20] EDIT   validators.ts  (+6 lines: user_type validation)
#004 [01:35] EDIT   createUser.ts  (+2 lines: pass fields to Lambda)
#005 [02:10] BASH   npm test       → exit 0
#006 [03:00] BASH   cdk deploy     → exit 0
```

### Constraints
- Add to existing engram package structure
- Follow session_db.py patterns
- Tests in `tests/test_artifact_trail.py`
