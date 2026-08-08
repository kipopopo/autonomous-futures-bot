# Phase 1o Verification — 15m Context Artifacts and Causal Bundle Expansion

**Status:** GREEN.
**Execution mode:** Local Windows project environment.
**Safety boundary:** Public unsigned market-data only; metadata/research artifacts only. No credentials, authenticated requests, order endpoint, execution authority, or live trading path.

## Contract delivered

`DatasetBundle` now binds, for every symbol:

- primary `5m` kline component with exact closed-bar coverage;
- context `15m` kline component whose coverage starts no later than the primary range and extends through the primary range;
- `5m` mark-price component;
- event-time funding-rate component;
- one exchange-filter snapshot covering the complete symbol universe.

The bundle records:

```text
primary_interval: 5m
context_interval: 15m
context_feature_policy: close_time_plus_1ms
```

The context policy is enforced by `context_bar_is_usable`: a 15m value becomes usable only at `context_open + 15m`, equivalent to the exchange candle close boundary (`close_time + 1ms`). It cannot be observed during the constituent 5m candles.

## TDD evidence

RED tests were added first for:

- complete 15m context binding;
- missing context component rejection;
- insufficient context coverage rejection;
- interval-aware primary/context lookup;
- pre-close context leakage rejection.

Initial focused run against the old implementation:

```text
3 failed, 3 passed
```

The failures demonstrated that the old bundle silently ignored 15m entries and did not expose the causality helper.

GREEN focused result:

```text
7 passed in 0.72s
```

## Real public dogfood

Real cached 5m kline slices plus public Binance unsigned 15m klines, mark-price klines, funding-rate events, and exchange filters were persisted to temporary immutable artifacts, registered, and bundled.

```text
symbols:
BTCUSDT, ETHUSDT, SOLUSDT

primary range:
2026-08-06T05:25:00Z
→ 2026-08-06T05:35:00Z exclusive

context interval:
15m

context feature policy:
close_time_plus_1ms

components:
13

registry_hash:
c17c5be978cb221e09a65f9f8651abcd795d84c4b559b9d7461ba5c2062656af

bundle_hash:
58fedc7964fb747d893c296ce21b329cfd2d47c792ed839473d0bad380622d10

exchange_filter_hash:
bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb

public transport:
9 requests
9 successes
0 failures

bundle persisted:
true
```

The 13 components are:

```text
3 symbols × (5m kline + 15m context + 5m mark price + funding rate)
+ 1 exchange-filter snapshot
```

## Files changed

- `src/autonomous_futures/data/bundle.py`
- `src/autonomous_futures/data/__init__.py`
- `tests/unit/test_bundle.py`

No temporary dogfood script or generated artifact remains in the repository.

## Final quality gates

```text
pytest -q
77 passed in 2.86s

ruff check
All checks passed!

ruff format --check
44 files already formatted

mypy src
Success: no issues found in 23 source files

uv lock --check
pass

compileall
pass

git diff --check
pass

secret scan
No findings
```
