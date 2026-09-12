# Paper Daemon Circuit-Breaker Persistence Verification — 2026-09-12

## Status

**DEPLOYED AND VERIFIED.** A first controlled restart exposed a
shutdown-ordering gap; the sidecar correction was then deployed and verified
through a second controlled paper-service restart.

## Finding

The Phase 259 daemon created a new `HardenedSharedMarginAccount` with an
in-memory `NORMAL` state on every process start. Its STARTING and clean-shutdown
health checkpoints also wrote `NORMAL` unconditionally. A restart could
therefore clear a prior `HALTED` state before the operator supplied complete
resume evidence.

## Minimal fix

- Restore the prior `circuit_breaker_status` from `paper-daemon-health.json`
  before warmup and feed processing.
- Persist the breaker state independently in atomic
  `paper-circuit-breaker-state.json`, and treat that sidecar as authoritative.
- Preserve valid `NORMAL`, `THROTTLED`, `HALTED`, and `EMERGENCY_FLAT` account
  states.
- Treat missing/unknown/malformed checkpoint evidence as `HALTED`.
- Derive heartbeat, STARTING, and SHUTDOWN_CLEAN health status from the current
  account state instead of hardcoding `NORMAL`.
- No automatic resume path was added; `request_resume` still requires complete
  operator-approved evidence.

The first restart showed why the sidecar is required: the old running process
wrote a hardcoded `NORMAL` health checkpoint during graceful shutdown before
the new process could restore `THROTTLED`. The sidecar remains untouched by
that old shutdown path.

## Verification evidence

- Phase 259 daemon + mock regression: **16 passed**.
- Canonical locked suite: **2,193 passed in 602.82s**.
- `uv run --locked python -m py_compile scripts/run_phase_259_live_paper_daemon.py`: **PASS**.
- Ruff check: **PASS**.
- Ruff format check: **PASS**.
- Mypy: **PASS**.
- `uv lock --check`: **PASS**.
- `git diff --check`: **PASS**.
- Remote runtime source SHA-256 matched the committed daemon source: **PASS**.

## Pre-restart read-only evidence

Before the first controlled restart, the paper daemon checkpoint reported `RUNNING`, a fresh
heartbeat, one active `BTCUSDT` paper position, circuit breaker `THROTTLED`,
zero reconnects, zero submitted orders, `execution_authority=false`,
live activation disabled, and paper activation enabled. The read-only SQLite
ledger integrity check passed and matched the single active position.

After that first restart, the process changed PID and the ledger/position
remained intact, but the health checkpoint incorrectly reported `NORMAL`.
This was the observed shutdown-ordering failure; no order was submitted.

After sidecar seeding and the second controlled restart, readback passed:

- paper service active/running with a changed PID;
- health and sidecar breaker state both `THROTTLED`;
- one `BTCUSDT` `SHORT` position preserved with matching side/quantity/entry;
- SQLite `query_only=1`, `integrity_check=ok`, 161 opens, 160 closes, one
  active position state;
- zero submitted orders, `execution_authority=false`, and live activation
  disabled.

No resume request, position mutation, scheduler restart, testnet action, or
live order was performed during this fix.

## Operational boundary

The paper-service-only restart is complete and verified. The autonomous
scheduler was not restarted, no resume request was issued, and the paper
breaker remains `THROTTLED`; no testnet/live action was performed.
