# Phase 7F Verification — explicit local paper observation capture

## Decision

Phase 7F adds one manual/caller-driven CLI that captures an already-defined paper observation. It composes existing local SQLite ledger, read-only observation calculation, and SQLite observation journal; it does not execute a paper cycle or access a market/exchange/network source.

## Delivered

`src/autonomous_futures/paper/observation_cli.py` provides:

```text
python -m autonomous_futures.paper.observation_cli \
  --ledger-path <caller-path> \
  --observation-path <caller-path> \
  --candidate-id <bound-id> \
  --candidate-artifact-hash <bound-hash> \
  --starting-equity <explicit-decimal> \
  --previous-peak-equity <explicit-decimal> \
  --marks-path <local-json-symbol-to-decimal> \
  --observed-at <explicit-UTC-timestamp>
```

The CLI:

1. Loads only the caller-selected SQLite ledger.
2. Validates explicit local marks, Decimal equity inputs, and UTC timestamp.
3. Computes the existing read-only `PaperObservation`.
4. Appends the result to the caller-selected observation SQLite journal.
5. Emits canonical JSON with `status="captured"`.

Invalid local input emits stable `{"error_code":"invalid_input","status":"error"}` and exits `2`.

## TDD evidence

```text
RED: ModuleNotFoundError: autonomous_futures.paper.observation_cli
GREEN: tests/unit/test_paper_observation_cli.py — 1 passed
related paper tests: 34 passed
```

The end-to-end focused test uses real temporary SQLite files, a local JSON mark file, explicit time/equity/marks, a fully costed open row, and verifies the persisted snapshot. It also proves the command reports all authority flags false.

## Verification

```text
full locked suite: 522 passed
Ruff:              passed
Ruff format:       passed
Mypy:              129 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

No clock/default data path, scheduler, recurring loop, candidate discovery, market-data loader, exchange client, credential, order router, paper activation, testnet, or live path was added. This command can only persist an explicitly computed local observation; `paper_activation`, `execution_authority`, and `exchange_access` remain false.
