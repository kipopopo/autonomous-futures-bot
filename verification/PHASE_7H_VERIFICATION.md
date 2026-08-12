# Phase 7H Verification — fail-closed paper observation binding validation

## Decision

Phase 7H closes a read-only trust-boundary defect: the observation inspector previously passed raw candidate ID/hash strings directly to SQLite, so malformed bindings could be reported as ordinary `unavailable` state. The fix adds one shared typed binding contract and applies it before either paper-observation CLI touches local storage.

## Delivered

`PaperObservationBinding` in `src/autonomous_futures/paper/observation.py` centralizes the exact existing observation binding rules:

```text
candidate_id:            cand-… canonical form
candidate_artifact_hash: lowercase SHA-256 hex, 64 characters
```

Both local CLIs now validate through it before any SQLite read/load:

```text
observation_cli          capture path
observation_inspect_cli  read-only inspection path
```

Malformed bindings return the existing stable `invalid_input` error with exit code `2`; valid but empty bindings continue to return `status="unavailable"`.

## TDD evidence

```text
RED: malformed candidate ID/hash returned status="unavailable", exit 0
GREEN: focused inspection/capture/observation tests — 6 passed
related paper tests: 36 passed
```

The regression test calls the real inspection CLI with a temporary SQLite path and malformed candidate binding, asserting stable error JSON and zero ambiguity with genuine empty evidence.

## Verification

```text
full locked suite: 524 passed
Ruff:              passed
Ruff format:       passed
Mypy:              130 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

No ledger schema, observation schema, journal write behavior, scheduler, runtime loop, market/exchange/network client, credential, activation, testnet, or live path was changed. Existing `paper_activation`, `execution_authority`, and `exchange_access` fields remain false.
