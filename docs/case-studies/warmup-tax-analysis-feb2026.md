# Warm-Up Tax Analysis — Feb 2026

Dataset: 180+ sessions, 13,881 artifacts, 8 projects.

## Thesis

The agent spends 54 messages finding code before doing anything useful. Context injection should attack this warm-up tax, not file-specific error warnings.

## Finding 1: Messages-to-First-Edit

Median **54 messages** before first Edit/Write. 93% of sessions need 10+ exploration messages first.

```
Distribution:
    0-  2:    1 (   1%)
    3-  5:    1 (   1%)
    6- 10:    9 (   7%)
   11- 20:    7 (   6%)
   21- 50:   38 (  31%)
   51-999:   65 (  54%)
```

By project:
```
  monra-app                  avg=102.2  sessions=19
  development                avg= 75.2  sessions=31
  personal-knowledge-graph   avg= 64.8  sessions=12
  monra-app/monra-core       avg= 50.4  sessions=16
  music-nft-platform         avg= 47.1  sessions=19
  stakecommit                avg= 33.8  sessions=4
```

## Finding 2: First 10 Messages Are 76% Exploration

```
  Bash                   124 (29.0%)  [explore]
  Read                    99 (23.1%)  [explore]
  Glob                    73 (17.1%)  [explore]
  Task                    33 ( 7.7%)
  Grep                    29 ( 6.8%)  [explore]
  Edit                     7 ( 1.6%)  [mutate]
  Write                    5 ( 1.2%)  [mutate]
```

First 10 messages: **76% exploration, 3% mutation.**
After message 10: **72% exploration, 18% mutation.**

Exploration never really stops — it just gets diluted by actual work.

## Finding 3: Cross-Session Rediscovery — 18%

- 490 of 2,791 file reads are files the agent already explored in a prior session
- 55% of sessions re-explore files from earlier sessions
- These are reads that last-session or search-based injection would eliminate

## Finding 4: Predictable Errors — Only 14%

- 1,785 total errors, only 251 were repeat errors on files with prior error history
- Most errors are novel, not repeats
- File-specific error hook would only help 14% of the time

Top recurring error targets are Edit failures (non-unique old_string) on heavily-modified files.

## What This Means for Context Injection

| Injection Type | Addressable Waste | Impact |
|---|---|---|
| Last-session continuation | 54-message warm-up, 18% rediscovery | High |
| Search-based injection | 76% exploration in first 10 messages | High |
| File error warnings | 14% of errors | Low |

The warm-up tax is the real problem. The agent spends 76% of its first 10 messages on exploration — Glob, Grep, Read, Bash — just finding code. Injecting "here's what you explored last time" or "here's what's relevant to your query" attacks this directly.

File-specific error warnings (the original v0.4.0 spec) address a real but small problem. The warm-up killer addresses the problem every developer feels every session.
