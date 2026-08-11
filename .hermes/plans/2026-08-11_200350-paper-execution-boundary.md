# Paper Execution Boundary Design Plan

> **For Hermes:** This is a design-only plan. Do not implement until the user explicitly authorizes execution of this plan.

**Goal:** Define the smallest paper-only execution boundary that can consume the qualified ADX-gated RSI evidence without enabling live/testnet orders or mutating research qualification state.

**Architecture:** Keep research artifacts, paper simulation/execution, and live routing as separate modules and state namespaces. Paper execution will use explicit caller-supplied prices/signals and injected persistence, with hard safety locks and no exchange/network imports. Activation remains a separate human-approved transition after implementation and verification.

**Tech Stack:** Existing Python 3.11/uv project, Pydantic domain contracts, Decimal accounting, existing test suite, no new dependency.

---

## Current facts and non-goals

- Qualified evidence: `cand-scope-rsi-adx-001` from Phase 6S.
- Qualification is evidence only; it is not promotion or paper activation.
- Phase 0 explicitly lists paper broker, order manager, reconciler, and failure drills as incomplete.
- Existing `research_observation_*` modules are audit-only and must not be reused as an executor.
- No exchange client, authenticated request, WebSocket, order endpoint, scheduler, or live/testnet path is part of this plan.
- No candidate artifact or qualification artifact is mutated by paper code.

## Proposed minimum boundary

1. A paper-only fill/accounting component accepts explicit mark prices, direction, quantity, fee rate, and slippage configuration.
2. A paper position ledger is injected, not constructed by the executor; restart hydration and duplicate-open protection are required before activation.
3. A hard safety gate verifies the candidate is explicitly paper-authorized by a later approved transition, while defaulting to blocked.
4. Every open/close event carries strategy ID, symbol, side, quantity, fill, fees, slippage, net P&L, and an explicit reason.
5. A read-only observation snapshot derives realized P&L, fees, slippage, open exposure, equity, peak, and drawdown from durable state.
6. A reconciliation check compares runtime positions with durable open rows and blocks on drift.
7. Paper observation remains disabled until a separate activation decision is explicitly recorded and verified.

## Implementation sequence (future execution phase)

### Task 1: Freeze the paper safety contract

**Likely files:**
- Modify: `src/autonomous_futures/domain/contracts.py`
- Test: `tests/unit/test_paper_contracts.py`

Define typed paper-only state and safety locks. RED-test that default state is
blocked, live/testnet authority is impossible, symbols are bounded to the
qualified candidate universe, and invalid prices/quantities/fees are rejected.
Do not add lifecycle mutation yet.

### Task 2: Implement deterministic paper fills

**Likely files:**
- Create: `src/autonomous_futures/paper/fills.py`
- Test: `tests/unit/test_paper_fills.py`

Reuse Decimal conventions from `src/autonomous_futures/research/trade_simulation.py`.
Cover adverse LONG/SHORT entry and exit fills, both fees, slippage, net P&L,
invalid inputs, and no network imports. Use explicit prices only.

### Task 3: Add injected paper ledger and restart recovery

**Likely files:**
- Create: `src/autonomous_futures/paper/ledger.py`
- Create or modify: existing persistence module only after locating the actual
  durable storage contract
- Test: `tests/unit/test_paper_ledger.py`
- Test: one temporary-file integration test using the real writer/reader

Cover one open position per symbol/strategy, duplicate-open rejection, close
persistence, restart hydration, and source/runtime state consistency. Preserve
historical rows; never repair drift by deletion.

### Task 4: Add hard safety gate and explicit activation seam

**Likely files:**
- Create: `src/autonomous_futures/paper/safety.py`
- Test: `tests/unit/test_paper_safety.py`

Require explicit paper authorization, qualified evidence binding, zero
liquidations in OOS evidence, and fixed `exchange_access=false`. Default to
blocked. The seam must not promote candidates or grant live/testnet authority.

### Task 5: Add reconciliation and observation snapshot

**Likely files:**
- Create: `src/autonomous_futures/paper/observation.py`
- Create: `src/autonomous_futures/paper/reconciliation.py`
- Tests: focused unit tests plus one real temporary persistence integration test

Derive realized P&L/fees/slippage from durable closed trades, open exposure from
owned positions, and drawdown from persisted peak equity. Reject missing net P&L,
non-finite values, negative exposure/costs, duplicate opens, and runtime/ledger
drift. Keep snapshots append-only and observational.

### Task 6: Paper-only orchestration hook (not activation)

**Likely files:**
- Create: `src/autonomous_futures/paper/engine.py`
- Test: `tests/unit/test_paper_engine.py`

Accept explicit cached signal/price inputs and injected ledger/safety/logger.
With no authorized candidate, return a blocked/no-op result and perform no
writes. With authorization, process only paper fills; never import live routers,
exchange SDKs, network clients, or schedulers.

### Task 7: Verification and human activation review

Before any activation code path is enabled:

- Run focused RED→GREEN tests for every task.
- Run `unset PYTHONPATH PYTHONHOME VIRTUAL_ENV; uv run --locked pytest -q`.
- Run Ruff, format, mypy, lock, diff, and import/safety scans.
- Run a temporary real-ledger verifier and delete it.
- Review representative LONG/SHORT lifecycle traces.
- Confirm no authenticated exchange path or live/testnet route exists.
- Write a new `verification/PHASE_<id>_VERIFICATION.md` report.
- Commit/push only after the user explicitly authorizes the implementation phase.
- Keep `paper_activation=false` until a separate human approval after the
  implementation and observation prerequisites pass.

## Risks and guardrails

- **Research/paper coupling:** prevent imports from paper into research and keep
  candidate artifacts immutable.
- **Restart duplication:** hydrate durable open rows before accepting signals.
- **Accounting drift:** derive observation values from the durable ledger, not
  only in-memory state.
- **False readiness:** qualified evidence must never imply paper activation.
- **Network creep:** reject any paper module importing exchange/network clients.
- **Model scope:** this plan is design-only under Terra + Medium; implementation
  should receive a separate model-tier decision because it crosses paper
  execution and safety architecture.

## Acceptance gate

The plan is complete only when the future implementation has deterministic
paper-only accounting, restart-safe durable state, fail-closed safety gates,
reconciliation, observational snapshots, zero live/testnet authority, and fresh
post-commit locked verification. No paper process may start before that gate and
explicit human activation approval.
