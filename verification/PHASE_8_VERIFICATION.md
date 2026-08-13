# Phase 8 Verification — complete caller-driven paper runtime

## Authorized scope

The user authorized **complete paper runtime sahaja**. This phase creates a usable local simulated open/close lifecycle, not testnet or live trading.

```text
No exchange client
No network / HTTP / WebSocket
No credentials
No market-data loader
No signal generation
No scheduler or automatic loop
No persistent activation switch
No testnet / live route
```

## Delivered

### One-shot human approval

`PaperActionApproval` requires a unique caller-provided approval ID bound to:

```text
candidate ID + candidate artifact hash
trade ID
open or close action
UTC approval time + UTC expiry
```

The permission evaluator requires qualified, zero-OOS-liquidation evidence, matching candidate/trade/action binding, and an action time in `[approved_at, expires_at)`. It permits only a local simulated ledger action; all capability fields remain structurally false:

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

### Durable anti-replay evidence

Every runtime-written ledger event carries `approval_id`. SQLite migration is additive. `PaperLedger` rejects a previously-recorded approval ID during hydration or append, preventing replay across restart. Legacy rows remain readable/auditable but do not claim an approval.

### Local paper runtime

`PaperRuntime` accepts injected local `SqlitePaperLedger`, validated request/evidence/approval, explicit trade ID, explicit UTC time, and explicit exit mark on close.

```text
open:
  checks one-shot permission
  applies adverse fill
  writes paired entry fee + slippage cost

close:
  checks a separate one-shot approval
  requires matching durable open with complete entry costs
  applies adverse exit fill
  writes exact entry/exit fees, total slippage, gross P&L and net P&L
```

Invalid/expired/mismatched/replayed approval returns `blocked` without a write. An approved close with no durable open is blocked and does not create a ledger path.

### Manual CLI

`python -m autonomous_futures.paper.runtime_cli` is a thin explicit local adapter. It requires caller-supplied ledger path, request/evidence/approval JSON paths, action, trade ID, UTC action time, and exit mark for close. It has no default path, clock, candidate discovery, market lookup, automatic invocation, network, or activation path.

Malformed inputs return canonical:

```json
{"error_code":"invalid_input","status":"error"}
```

before any ledger write.

## TDD evidence

```text
RED: PaperActionApproval import missing
GREEN: typed UTC/expiry validation

RED: ledger did not retain/reject approval IDs
GREEN: durable approval column + replay protection + additive migration

RED: PaperRuntime module missing
GREEN: approved adverse-fill local open

RED: PaperRuntime.close missing
GREEN: approved separate-approval durable close accounting

RED: runtime_cli module missing
GREEN: explicit CLI open and close lifecycle
```

Failure drills prove zero new write for expired/replayed/mismatched approvals, invalid CLI input, and a close without a durable open.

## Verification

```text
paper runtime / approval focused tests: 26 passed
paper-focused suite:                    55 passed
locked full suite:                      542 passed
Ruff check:                             passed
Ruff format:                            passed
Mypy:                                   132 source files clean
uv lock --check:                        passed
git diff --check:                       passed
runtime import safety scan:             passed (no HTTP/network/WebSocket/scheduler imports)
```

## Safety status

The runtime is complete only as a caller-driven **local paper simulator**. It never grants external execution authority:

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

Testnet/live design, venue/legal/KYC confirmation, credentials, exchange integration, market input, signals, scheduling, automatic execution, dashboards, and deployment remain separate unapproved work.
