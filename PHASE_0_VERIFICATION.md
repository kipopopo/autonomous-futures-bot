# Phase 0 Verification — Pure Domain Slice

**Status:** Domain slice GREEN; Phase 0 overall remains in progress.
**Execution mode:** Local Windows project environment only.
**Safety boundary:** No exchange credentials, authenticated client, order endpoint, database service, VPS deployment, OpenCode request, or frontend scaffold was used.

## Delivered in this slice

- `OrderIntent` contract with UTC-only timestamps and no final quantity/leverage authority.
- `RiskDecision` contract with strict Decimal accounting fields.
- `StrategySpec` contract with bounded `5m`/`15m` universe, approved feature names, causal `shift >= 1`, and non-executable expressions.
- Deterministic duplicate-position and one-global-position guard.
- Monotonic automatic runtime risk transitions: `NORMAL -> THROTTLED -> HALTED -> EMERGENCY_FLAT`.
- Guarded resume evidence model requiring reconciliation, incident resolution, fresh data, healthy risk, and operator approval.
- Deterministic risk sizing slice covering risk budget, cost buffer, effective notional cap, and minimum-notional rejection.
- Pytest discovery expanded from `research/` to `research/` plus `tests/`, with `src/` and `research/` on the test path.

## TDD evidence

### RED

```text
pytest tests/unit -q
2 collection errors
ModuleNotFoundError: No module named 'autonomous_futures'
```

The failure occurred before the domain implementation existed.

### GREEN

```text
pytest tests/unit -q
8 passed

pytest tests/unit/test_risk_state.py -q
6 passed
```

## Final quality gates

```text
pytest -q
18 passed in 2.55s

ruff check src tests research
All checks passed!

ruff format --check src tests research
13 files already formatted

mypy src
Success: no issues found in 6 source files

python -m compileall -q src tests research
exit 0

uv lock --check
Resolved 67 packages

git diff --check
exit 0
```

A repository secret-pattern scan found no credential-like patterns in the tracked development files.

## Not yet complete

The following remain outside this slice and must not be inferred as complete:

- PostgreSQL schema/migrations and persistence;
- FastAPI API/dashboard vertical slice;
- immutable dataset manifests and data-quality services;
- full feature catalog and event-driven backtester;
- OpenCode provider validation or LLM runtime calls;
- research scheduler and candidate registry;
- paper broker, order manager, reconciler, and failure drills;
- frontend/Magic UI scaffold;
- Kainode application deployment;
- Binance demo or live adapter;
- any authenticated order or live trading capability.
