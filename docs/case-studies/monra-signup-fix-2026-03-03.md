# Engram Case Study — March 3, 2026

## Engram Recovered 20 Minutes of Context in 30 Seconds

**Project:** Monra — fintech payment infrastructure (Solana wallet creation)
**Task:** Debug broken signup flow, fix validation error, deploy fix
**Session length:** ~15 minutes from report to deployed fix
**Key finding:** Engram recovered exact CLI commands and confirmed unmerged feature branch history instantly

---

## Background

User reported signup was broken: 401 errors, 2FA issues, session lost on page refresh. We needed to tail AWS CloudWatch logs for the `createUser` Lambda functions — but the function names and exact commands weren't documented anywhere except in past Claude Code sessions.

---

## What Engram Found

### Query 1: Find the log commands
```bash
engram search "aws logs tail"
# → 20 results — found exact commands from sessions on Feb 5 and Feb 25
```

**Result:** Instantly recovered:
```bash
aws logs tail /aws/lambda/api-createUser --follow --since 5m
aws logs tail /aws/lambda/management-createUser --follow --since 5m
```

Without Engram, we'd need to browse the AWS Console or guess Lambda function naming conventions across 6+ microservices.

### Query 2: Find what happened to user_type
```bash
engram search "user_type"
# → 20 results — showed full implementation history from Feb 25
```

**Result:** Confirmed `user_type` and `business_name` were implemented on `feat/enable-business-accounts` branch (session `30f688ae`, Feb 25) but never merged to `main`. The database migration ran (columns exist), the frontend was updated, but the backend validators stayed on the feature branch.

### Query 3: Confirm the error existed before
```bash
engram search "user_type should not exist"
# → 14 results — showed this was a known gap in the plan
```

**Result:** Found a session note from Feb 25: *"What's NOT yet implemented: NO database migration - fields not in schema, may not exist in..."* — proving this was a known incomplete merge, not a new regression.

---

## Time Impact

| Step | With Engram | Without Engram |
|------|------------|----------------|
| Find Lambda log group names | ~10s (1 search) | 5-10 min (AWS Console) |
| Get exact `aws logs tail` commands | ~10s (reused from history) | 3 min (construct manually) |
| Confirm feature was previously built | ~10s (1 search) | ~10-15 min (check branches, git log) |
| **Total context recovery** | **~30s** (measured) | **~20 min** (estimated) |

> *The 30s "With Engram" time was measured from the actual session. The ~20 min "Without" estimate is based on manual AWS Console browsing and git archaeology — no control run was performed.*

---

## Resolution Timeline

```
00:00  User reports signup broken
00:30  Engram finds past log commands → tailing starts
03:00  Logs captured: "property user_type should not exist"
04:00  Root cause: backend schema missing user_type (never merged from feature branch)
05:00  Engram confirms feature existed on unmerged branch
08:00  4 files fixed across api-gateway and management-service, committed
10:00  Management service deployed to AWS
15:00  API gateway deployed — full fix live
```

---

## The Fix

4 files, 24 lines added:

| File | Change |
|------|--------|
| `api-gateway/src/validators.ts` | Added `user_type` + `business_name` to `CreateUserValidator` |
| `api-gateway/src/management/createUser.ts` | Pass both fields to management Lambda |
| `management-service/src/user/schemas.ts` | Added to `CreateUserParams` |
| `management-service/src/lib/types.ts` | Added to `DBUser` type |

The database already had both columns (migration 12 ran on Feb 25). The `createUser` function already spread `...userInsert` into the insert call. Only the validation layer was blocking.

---

## Key Insight

Engram's value here wasn't code search — it was **session context recovery**. The critical information (Lambda function names, CLI commands, branch decisions) existed only in past Claude Code conversations. Without Engram, this knowledge would have been lost entirely, requiring manual AWS Console browsing and git archaeology to reconstruct.

The 30-second context recovery vs estimated ~20-minute manual reconstruction represents an **estimated ~40x speedup** on the discovery phase alone.

*— Aleksa, Engram author*
