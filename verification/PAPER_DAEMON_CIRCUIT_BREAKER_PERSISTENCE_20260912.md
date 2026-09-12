# Paper Daemon Circuit-Breaker Persistence Verification — 2026-09-12

## Status

**IMPLEMENTED AND LOCALLY VERIFIED.** Remote source staging and the controlled
paper-service restart remain separate operational steps.

## Finding

The Phase 259 daemon created a new `HardenedSharedMarginAccount` with an
in-memory `NORMAL` state on every process start. Its STARTING and clean-shutdown
health checkpoints also wrote `NORMAL` unconditionally. A restart could
therefore clear a prior `HALTED` state before the operator supplied complete
resume evidence.

## Minimal fix

- Restore the prior `circuit_breaker_status` from `paper-daemon-health.json`
  before warmup and feed processing.
- Preserve valid `NORMAL`, `THROTTLED`, `HALTED`, and `EMERGENCY_FLAT` account
  states.
- Treat missing/unknown/malformed checkpoint evidence as `HALTED`.
- Derive heartbeat, STARTING, and SHUTDOWN_CLEAN health status from the current
  account state instead of hardcoding `NORMAL`.
- No automatic resume path was added; `request_resume` still requires complete
  operator-approved evidence.

## Verification evidence

- Phase 259 daemon + mock/stress regression: **28 passed**.
- Canonical locked suite: **2,192 passed in 598.33s**.
- `uv run --locked python -m py_compile scripts/run_phase_259_live_paper_daemon.py`: **PASS**.
- Ruff check: **PASS**.
- Ruff format check: **PASS**.
- Mypy: **PASS**.
- `uv lock --check`: **PASS**.
- `git diff --check`: **PASS**.

## Pre-restart read-only evidence

At review time, the paper daemon checkpoint reported `RUNNING`, a fresh
heartbeat, one active `BTCUSDT` paper position, circuit breaker `THROTTLED`,
zero reconnects, zero submitted orders, `execution_authority=false`,
live activation disabled, and paper activation enabled. The read-only SQLite
ledger integrity check passed and matched the single active position.

No resume request, position mutation, scheduler restart, testnet action, or
live order was performed during this fix.

## Operational boundary

The next permitted action is a code-only source update followed by a controlled
**paper-service-only** restart. The restart must be read back for PID, health
checkpoint, position continuity, breaker-state continuity, ledger integrity,
and zero-order/live-disabled invariants. The autonomous scheduler remains
untouched.
