# Case Study: SQL Query Analysis of 13,881 Artifacts
**Date:** 2026-02-22
**Context:** Running 5 analytical SQL queries against Engram's artifacts table

## Data Snapshot
| Type | Count |
|------|-------|
| command | 5,581 |
| file_read | 3,621 |
| error | 1,924 |
| file_write | 1,453 |
| file_create | 731 |
| api_call | 571 |
| **Total** | **13,881** |

Hottest file: `handlers.ts` — 133 reads, 67 edits across sessions.

---

## Finding 1: Read Loops — handlers.ts dominates
Session `5b6fa781` read `handlers.ts` **40 times**. Session `02f21e2b` read it
22 times AND read `webhook-processors.ts` 18 times AND `TransactionLifecycleService.ts`
11 times — one session burning 51 reads on 3 files.

**Diagnosis:** Classic compression-induced amnesia. The agent forgets it already
read the file and reads it again. `engram brief` prevents this by injecting
"you've already read these files, here's what's in them."

---

## Finding 2: Complexity Magnets — the real killers
The error/write ratio is the signal:
- `endpoints.ts` — 6 writes, **240 errors** (40:1 ratio)
- `schemas.ts` — 5 writes, **207 errors** (41:1 ratio)
- `validators.ts` — 10 writes, **254 errors** (25:1 ratio)

These aren't the most-edited files — they're the files where touching them
means the session goes sideways. "Don't touch without understanding the full contract."

---

## Finding 3: Time of Day Patterns
- **Most productive:** 3am (20%), 15:00 (20%), 19:00 (22%)
- **Most error-prone:** 21:00 (23% errors), 18-19:00 (20-21%)
- **14:00 busiest** (1,721 actions) but only 12% productive — peak activity, mediocre output

---

## Finding 4: Zero-Write Sessions — 38% produce nothing
72 out of 191 sessions (38%) have zero file writes.

Worst: session `1e28bfa0` — 187 actions, zero writes, 76 errors, 98 commands. All for nothing.

---

## Finding 5: Co-Change Patterns — implicit architecture
- `validators.ts` + `handlers.ts` + `schemas.ts` + `endpoints.ts` + `transfers.ts` — a **5-file cluster**. Touching one means touching all. That's the monra-core API contract surface — nobody documented it, Engram found it.
- `earnings.service.ts` + `earnings/page.tsx` — backend + frontend always co-edited
- `drops/[id]/page.tsx` + `EmbedCodeGenerator.tsx` — always together (5 sessions)

**The co-change patterns are architecture documentation that nobody wrote down.
The agent keeps discovering these relationships from scratch every session.**

---

## The Thesis Proven
The data already existed in session logs. The artifact extractor structured it.
Five SQL queries revealed architecture intelligence that no documentation captured.

This is behavior-derived architecture understanding — not static analysis, not
documentation, but what actually happens when engineers and agents work on the codebase.

---

*Engram v0.2.0 — February 2026*
*Case Study #2 of ongoing validation series*
