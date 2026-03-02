# LOOPWRIGHT — AGENT CONTEXT TRANSFER
# Read this before touching any file. This is the full state of the build.

## What You Are Building

Loopwright: autonomous CI/CD with self-correcting agents.
Three repos. One SQLite file shared between all of them.

Engram (Python) — memory layer — ~/Desktop/development/engram
OpenClaw (Node.js) — observability layer — ~/Desktop/development/openclaw
Loopwright (TypeScript/Bun) — orchestration brain — ~/Desktop/development/loopwright

## Current Build State

### Engram — STABLE, do not break
- session_db.py: 46 tests passing. Schema has worktrees, checkpoints, correction_cycles tables.
- correction_brief.py: NEW. Generates correction-aware briefs with prior cycle history.
- mcp_server.py: NEW. NL search MCP. One known bug fixed (NoneType sort line 95).
- hooks: UserPromptSubmit fires on every Claude Code message, injects brief automatically.
- sessions.db: 13K+ real artifacts. Do not delete. Do not modify schema without migration.

### OpenClaw — STABLE, do not break
- Dashboard at :8789, fully working, 675 real events
- events.jsonl: append-only, do not rewrite
- Replay: fully working in browser
- Missing (do not build yet): programmatic spawner, idle detection, registry

### Loopwright — ACTIVE BUILD, this is where you work
Files that exist and pass tests (26 tests, 91 expects):
- src/db.ts — schema + 4 query methods for correction_cycles
- src/watchdog.ts — idle/finish detection, AGENT_IDLE/AGENT_FINISHED events
- src/spawner.ts — Bun.spawn() wrapper, AgentRegistry Map, AGENT_STARTED events
- src/test-runner.ts — delta file detection, scoped pytest/bun test, error parsing
- src/correction-writer.ts — TestResult → correction_cycles table
- src/corrector.ts — reads errors, builds brief, calls spawner
- src/loop.ts — orchestrates up to 3 cycles, writes final status to worktrees

## Your Exact Task Right Now

Four fixes needed before the loop runs end to end on a real task.
Do them in this order. Run bun test after each fix.

### Fix 1: src/test-runner.ts — venv pytest path
Add this helper:
```typescript
function detectPytestBin(worktreePath: string): string {
  // Check 1: worktree local venv
  const local = join(worktreePath, '.venv/bin/pytest');
  if (existsSync(local)) return local;

  // Check 2: walk up to parent repo (worktrees share parent .venv)
  // worktrees have a .git FILE (not dir) pointing to parent
  const gitFile = join(worktreePath, '.git');
  if (existsSync(gitFile) && statSync(gitFile).isFile()) {
    const content = readFileSync(gitFile, 'utf8'); // "gitdir: ../../.git/worktrees/..."
    const parentRepo = resolve(worktreePath, content.replace('gitdir:', '').trim(), '../../..');
    const parentVenv = join(parentRepo, '.venv/bin/pytest');
    if (existsSync(parentVenv)) return parentVenv;
  }

  // Fallback
  return 'pytest';
}
```
Use detectPytestBin(worktreePath) in runTests() when framework === 'pytest'.

### Fix 2: src/loop.ts — CLAUDE.md injection + output logging
After worktree creation (around line 198), before agent spawn:
```typescript
const claudeMd = `# Task\n${taskPrompt}\n\n## Instructions\n- Make the changes described above\n- Run tests to verify: \`pytest tests/\`\n- Commit your changes when tests pass\n`;
writeFileSync(join(worktreePath, 'CLAUDE.md'), claudeMd);
```

In runAgentAndWait(), after agent exits, add:
```typescript
const lastStdout = stdout.slice(-500);
const lastStderr = stderr.slice(-500);
console.log('[loop] agent stdout tail:', lastStdout);
console.log('[loop] agent stderr tail:', lastStderr);
```

### Fix 3: src/spawner.ts — prepend .venv/bin to PATH
In spawnAgent(), before Bun.spawn():
```typescript
const venvBin = join(worktreePath, '.venv/bin');
const envPath = existsSync(venvBin)
  ? `${venvBin}:${process.env.PATH}`
  : process.env.PATH;
// Pass envPath as PATH in spawn env
```

### Fix 4: Verify everything works
```bash
cd ~/Desktop/development/loopwright
bun test  # must show 38 tests passing

bun run src/loop.ts \
  "Add a format_cycle_summary function to correction_brief.py that takes a correction_cycles row and returns a human-readable string summary" \
  ~/Desktop/development/engram \
  sessions.db \
  main
```

Watch dashboard at http://localhost:8790
Expected sequence: running → spawn → test → checkpoint OR correct → passed/escalated
Check engram worktree has actual file changes after agent runs.

## How sessions.db Is Shared

Path: ~/.config/engram/sessions.db
Loopwright reads it via src/db.ts (bun:sqlite)
Engram reads/writes via session_db.py (Python sqlite3)
Same file. Both sides. No API needed.

## How Inter-Agent Memory Works

sessions.db = persistent store (everything that ever happened)
CLAUDE.md in worktree = the envelope (context for the next agent)

Flow:
1. Agent works → Engram captures artifacts to sessions.db via hooks
2. Watchdog detects AGENT_FINISHED
3. Test runner fires on delta files
4. On fail: corrector reads sessions.db, builds brief, writes to CLAUDE.md
5. New agent spawns, reads CLAUDE.md — knows what failed and why
6. Repeat max 3 cycles then escalate

## Rules

- Never modify sessions.db schema without a migration script
- Never rewrite events.jsonl
- Always run bun test before committing
- All new Loopwright files: zero external dependencies, Bun-only
- CLAUDE.md in worktrees is ephemeral — written by loop, read by agent, disposable
- Do not touch OpenClaw files unless explicitly asked

## File Locations

```
~/.config/engram/sessions.db          ← shared SQLite, do not delete
~/Desktop/development/engram/          ← Engram repo
~/Desktop/development/openclaw/        ← OpenClaw repo
~/Desktop/development/loopwright/      ← Loopwright repo (you work here)
~/Desktop/development/loopwright/src/  ← all TypeScript source
```

## If Something Breaks

1. Run bun test first — find which test fails
2. Check sessions.db schema with: sqlite3 ~/.config/engram/sessions.db ".schema"
3. Check dashboard at :8789 for live event stream
4. Last resort: git log --oneline -10 to see recent changes

## When You Are Done

The loop ran successfully on engram repo. Dashboard showed the full sequence.
Agent made real file changes. Tests passed. Checkpoint was written.
Output: paste the full dashboard sequence + what the agent changed.
