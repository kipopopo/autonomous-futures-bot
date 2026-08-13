# Complete Paper Runtime Implementation Plan

**Goal:** Complete a caller-driven, local-only paper runtime for the qualified candidate without creating exchange, network, testnet, live, scheduler, or persistent activation authority.

**Authorization:** A human caller injects one explicit approval for every `open` or `close` action. Each approval binds a unique approval ID, candidate ID/hash, trade ID, action, and caller-supplied UTC expiry. It is consumed only by an appended durable ledger event, so an ID cannot replay after restart.

**Safety invariants:**

```text
paper_activation     false (no persistent activation switch)
execution_authority  false (no external order authority)
exchange_access      false (structurally impossible)
network access       absent
```

A successful action means only that a local, deterministic simulated ledger event was appended after explicit human approval.

## Vertical delivery slices

1. **Approval contract and durable binding**
   - Add a strict one-shot paper-action approval model.
   - Add optional `approval_id` to append-only ledger events using an additive SQLite migration.
   - Runtime-generated opens/closes require the ID; legacy rows remain auditable but cannot prove approval.
   - Reject an already-recorded approval ID before write.

2. **Single explicit open action**
   - New minimal `paper/runtime.py` composes: request + approval + evidence + injected SQLite ledger + caller UTC time.
   - Reuse `evaluate_paper_safety`, fill math, ledger validation, and SQLite writer.
   - It writes one adverse-fill open event with paired entry fee/slippage accounting only when all bindings pass.
   - No price loading, clocks, signal generation, discovery, thread, loop, or scheduler.

3. **Single explicit close action**
   - Caller supplies close mark and UTC time plus a separate approval.
   - Runtime verifies durable matching open state and creates one deterministic close accounting event.
   - Existing ledger invariants prevent duplicate/invalid lifecycle transitions.

4. **Runtime safety proof**
   - End-to-end real temporary-SQLite tests: unapproved/no-evidence/replayed/expired/mismatched requests write zero rows.
   - Prove long and short local lifecycle, restart rehydration, reconciliation, and every authority field remains false.
   - Audit imports: runtime modules must contain no exchange, HTTP, websocket, scheduler, subprocess, or market-data imports.

5. **Manual caller CLI (only after runtime API is verified)**
   - Thin argparse adapter accepts explicit local paths and all action/price/approval/evidence inputs.
   - No defaults, no credentials, no network, no automatic invocation.

6. **Verification and delivery**
   - RED→GREEN evidence per slice, paper-focused tests, canonical locked suite, Ruff/format/mypy/lock/diff, post-commit repeat, commit/push, HEAD/origin equality.

## Explicitly deferred

Testnet, live routing, credentials, exchange API, signal generation, market data, automatic execution, scheduling, persistent activation, dashboards, and remote deployment all require a separate design plus approval.
