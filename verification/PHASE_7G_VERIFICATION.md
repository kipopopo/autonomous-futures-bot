# Phase 7G Verification — read-only paper observation inspection

## Decision

Phase 7G adds the smallest next paper-safe boundary: a caller-invoked CLI that reads the latest persisted observation for one exact candidate ID/artifact-hash binding. It does not calculate a snapshot, append anything, load a trade ledger, read marks, use a clock, start a loop, or authorize paper activity.

## Delivered

`src/autonomous_futures/paper/observation_inspect_cli.py` provides:

```text
python -m autonomous_futures.paper.observation_inspect_cli \
  --observation-path <caller-path> \
  --candidate-id <bound-id> \
  --candidate-artifact-hash <bound-hash>
```

The command restores typed snapshots through the existing SQLite observation reader and emits the newest sequence-row as canonical JSON:

```text
status="available"
```

A valid empty journal/binding returns:

```text
status="unavailable"
```

Invalid local input returns stable JSON with `status="error"`, `error_code="invalid_input"`, and exit code `2`.

## TDD evidence

```text
RED: ModuleNotFoundError: autonomous_futures.paper.observation_inspect_cli
GREEN: tests/unit/test_paper_observation_inspect_cli.py — 1 passed
related paper tests: 35 passed
```

The focused test writes two real append-only snapshots under the same candidate binding, invokes the CLI, verifies it returns the latest row with all authority flags false, then re-reads the journal to prove the count remains unchanged.

## Verification

```text
full locked suite: 523 passed
Ruff:              passed
Ruff format:       passed
Mypy:              130 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

No snapshot capture, ledger loading, mark input, calculation, persistence write, scheduler, runtime loop, exchange/network client, credential, testnet/live route, activation, or execution authority was introduced. The read model exposes the existing explicit false fields unchanged.
