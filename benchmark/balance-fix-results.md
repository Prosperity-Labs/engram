# Balance & Transaction Correctness Fix — Session Results

## Session Metadata
- **Date**: 2026-02-19
- **Duration**: ~1 session
- **Agent**: Claude Opus 4.6 via Claude Code CLI
- **Branch**: `fix/balance-transaction-correctness` (forked from main)
- **Repos**: monra-core, monra-web-app

## Engram Usage: NOT USED

**Engram searches were planned but not executed.** The agent went directly into
implementation using codebase exploration (file reads, grep, noodlbox) instead of
querying Engram for past session context.

### Why Engram Was Skipped
1. The plan itself contained sufficient context (exact line numbers, file paths, root cause analysis)
2. The agent had direct access to the codebase and could read files in real-time
3. No ambiguity in the implementation — the fixes were well-defined

### Planned Queries (Not Executed)
```bash
.venv/bin/engram search "balance transaction webhook" --limit 10
.venv/bin/engram search "transfer link handlers escrow" --limit 10
.venv/bin/engram search "alchemy webhook deposit" --limit 10
```

## Where Engram WOULD Have Helped

### 1. CDK Stack Lambda Definitions (HIGH VALUE)
The biggest unexpected problem was that `linkTransferBroadcastSuccess` and
`claimLinkBroadcastSuccess` Lambda functions existed on the feature branch but
NOT on main. Deploying from main's CDK stack **deleted** the running Lambdas.

An Engram query like `"linkTransferBroadcastSuccess CDK stack deploy"` would have
surfaced past sessions where these were added, alerting the agent that the CDK
stack also needed changes. This cost ~15 minutes of debugging + redeploy.

### 2. API Gateway Route Wiring (MEDIUM VALUE)
Similarly, the API gateway routes for broadcast-success endpoints were only on the
feature branch. Past session context about "how link transfer endpoints are wired"
would have flagged this dependency upfront instead of discovering it after
flow-service deploy.

### 3. Feature Branch vs Main Divergence (HIGH VALUE)
The plan noted that MonraTag transfer flow exists only in the feature branch, but
didn't fully account for all the infrastructure (CDK stacks, API gateway routes,
validators, schemas) that was also feature-branch-only. Engram sessions from
Feb 16-18 (escrow link transfer integration) would have provided this context.

## Task Results

### task-01: completeTransaction in linkTransferBroadcastSuccess
- **Status**: COMPLETED + DEPLOYED
- **Engram helped**: No (not used)
- **Without Engram**: No impact — change was straightforward (2 lines)

### task-02: completeTransaction in claimLinkBroadcastSuccess
- **Status**: COMPLETED + DEPLOYED
- **Engram helped**: No (not used)
- **Without Engram**: No impact — change was straightforward (4 lines)

### task-03: Frontend transaction direction classification
- **Status**: COMPLETED, pushed to branch
- **Engram helped**: No (not used)
- **Without Engram**: No impact — self-contained frontend change

### task-04: Balance reconciliation script
- **Status**: COMPLETED + DEPLOYED
- **Engram helped**: No (not used)
- **Potential value**: Past sessions about EVMClient usage, RPC URL SSM params,
  and the dual-write pattern (user_currency_balances + users.balance) would have
  saved exploration time. Took ~10 min of file reading to discover these patterns.

### task-05: Clean slate SQL
- **Status**: NOT EXECUTED (deferred until after verification testing)

## Unplanned Work (Discovered During Execution)

These tasks were NOT in the original plan but were required:

| Task | Time Spent | Engram Would Have Prevented? |
|------|-----------|------------------------------|
| Add types/schemas to main (types.ts, schemas.ts) | 10 min | YES — past sessions would show these were feature-branch-only |
| Add CDK Lambda definitions (flow-service-stack.ts) | 15 min | YES — past sessions would show CDK stack divergence |
| Add API gateway routes + handlers | 20 min | YES — past sessions would show full integration chain |
| Fix TypeScript fetch declaration | 5 min | No — tsconfig-specific issue |

## Key Finding

**The plan was incomplete.** It identified the handler-level code changes correctly
but missed the infrastructure layer (CDK stacks, API gateway, types, schemas) that
was also needed. This is exactly the kind of gap that Engram session history would
fill — past sessions about "deploying link transfer features" would reveal the full
dependency chain.

**Estimated time saved if Engram had been used**: 30-45 minutes (avoiding the
CDK deletion incident and discovering API gateway needs upfront).

## Commits on Branch

### monra-core (3 commits)
1. `ae5864f` — fix: Complete transaction status transitions and add balance reconciliation
2. `4465933` — fix: Add linkTransferBroadcastSuccess and claimLinkBroadcastSuccess Lambda definitions
3. `3ba6c26` — feat: Add API gateway routes for link transfer broadcast success handlers

### monra-web-app (1 commit)
1. `bffd47c` — fix: Correct transaction direction classification in dashboard

## Deployment Status
- flow-service: DEPLOYED (dev)
- api-gateway: DEPLOYED (dev)
- monra-web-app: NOT DEPLOYED (branch pushed, needs frontend deploy)

## Post-Session Engram Queries (Retroactive Validation)

Ran Engram searches at end of session to validate what WOULD have been found:

### Query: `"balance fix attribution"` (3 results)
1. **Feb 7 session** — Balance correct but transaction amount stale; mentions
   `attributeTransaction` needing `destinationAmount`. Directly relevant to
   balance/transaction interaction patterns.
2. **This session** (Feb 19) — The plan itself being written.
3. **Feb 17 session** — Commit history showing the escrow integration branch.

### Query: `"transfer link handlers escrow"` (5 results)
1. **Feb 17 session** — "No webhook handler for escrow deposits" + "Handlers use
   legacy balance check, no escrow_lock/escrow_release transactions". This is
   EXACTLY the gap we hit — would have alerted us to missing infrastructure.
2. **Feb 16 session** — "TransactionType includes transfer_link_created and
   transfer_link_claimed but NOT escrow_lock, escrow_release, escrow_refund".
   Shows the naming confusion between plan and implementation.
3. **Feb 17 session** — "Wire linkTransferBroadcastSuccess end-to-end" listed as
   pending phase. This is the work we did today — Engram would have shown it was
   already planned with specific file lists.
4. **This session** — Branch commit history.
5. **Feb 11 session** — Full escrow flow: "TransactionLifecycleService creates
   escrow_lock transaction... Web3-service generates approve and makeDeposit
   encoded calls and creates link_transfers row."

### Query: `"CDK stack Lambda linkTransferBroadcastSuccess deploy"` (3 results)
- Only this session's results. No prior CDK deployment context existed in Engram
  for these specific Lambdas. Confirms: the CDK deletion incident was genuinely
  novel — but the Feb 17 "Wire end-to-end" plan WOULD have listed the CDK files
  if that session had been more thoroughly captured.

## Conclusions

### Most Relevant Past Sessions
1. **Feb 16-17** (escrow link transfer integration planning) — HIGH relevance.
   Would have revealed the full dependency chain (handlers + types + schemas +
   CDK + API gateway) and prevented 30+ min of unplanned work.
2. **Feb 7** (balance/transaction attribution fix) — MEDIUM relevance.
   Shows the `attributeTransaction` pattern and balance correctness patterns.
3. **Feb 11** (escrow flow architecture) — MEDIUM relevance.
   Full flow description including TransactionLifecycleService and web3-service
   interaction patterns.

### Honest Assessment
- **For the planned tasks (1-4)**: Engram would have saved ~10 min max. The plan
  had enough detail and the agent could read files directly.
- **For the unplanned infrastructure work**: Engram would have saved ~30-45 min
  by surfacing the CDK/API gateway dependency chain BEFORE deployment.
- **Net value**: Engram's highest value is in **surfacing implicit dependencies**
  — things the plan doesn't mention because the planner didn't know about them.
  The Feb 17 "Wire end-to-end" session plan would have been the single most
  valuable result.

## Next Steps
1. Create PRs for both repos
2. Test verification protocol (deposit, link transfer, claim, reconciliation)
3. Run task-05 (clean slate SQL) after verification passes
4. Deploy frontend
