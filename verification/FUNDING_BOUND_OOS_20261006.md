# Funding-bound OOS research implementation — 2026-10-06

## Scope

Offline implementation only. Funding cash settlements now propagate through cached simulation, window evidence, walk-forward aggregation, persisted qualification and the Phase 250/253/autonomous research loaders. Longs debit positive funding payments; shorts receive the opposite signed cash flow. New qualification paths require funding mode `settled`, a verified funding artifact slice bound to bundle/registry/manifest/artifact hashes, and aligned funding timestamps. Cached evaluation windows copy pandas frames on ingress and return deep copies so callers cannot mutate retained evidence.

Autonomous-base synthetic windows now fail closed before research outputs are created. Offline exploration reports missing or unverified inputs as unavailable instead of writing an empty “completed” result; when a verified bundle is supplied, its loader checks the exact kline path and funding artifact. Phase 250 and Phase 253 also load windows through verified kline and funding artifact paths.

## Verification

- Earlier related locked regression sets passed (**511 tests in 51.09s**; verified exploration-loader subset **13 in 6.88s**). They were not a full-suite result.
- Exact-head Actions for `5faeec63dc604642db8cffd34e4feb5b6d61e3b5` failed: **34 failed, 5,110 passed, 1 skipped, 2 warnings in 925.78s**. Failures exposed synthetic catalogs with unavailable funding references, legacy qualification fixtures without v2 funding bindings, and an `_OpenPosition` constructor compatibility regression.
- Follow-up fixes use complete persisted **synthetic-only** catalog components in CLI/scheduler fixtures, bind v2 qualification fixtures, retain the prior default for `funding_payment`, and block HTTP redirects in the unsigned public transport.
- After those fixes, the affected integration/CLI/scheduler/challenger/provenance set passed **38 tests in 184.90s**; affected unit/data/funding/qualification/registration set passed **50 tests in 7.32s**.
- Ruff passed and **714 files** are formatted; native/Linux mypy passed for **359 source files**; `uv lock --check`, changed-file `py_compile`, added-line secret scan, and `git diff --check` passed. Windows full-tree `compileall` could not create `__pycache__` entries for pre-existing overlong `research_lab` module/test filenames; the exact-SHA Linux compile gate remains authoritative.
- Published follow-up `92c6e6e20b3802a5bdf95aa342afb3329aed1784` passed exact-head Actions `37462630995`: **5,145 passed, 1 skipped, 2 warnings in 904.44s**; Ruff, formatting, strict types, and Linux compile also passed. The synthetic catalog remains test plumbing only, not genuine market provenance.
- Collector commit `ec1116d6d39625ee3b54e7a91aaa8216af3d0b97` passed exact-head Actions `37469520310` (tests, Ruff, formatting, strict types, compile). The approved one-shot collection then stopped on `DataQualityError` at `/fapi/v1/fundingRate` after **2 GET attempts total**: one `/fapi/v1/exchangeInfo`, one funding request; no retry. The ignored local scope retains only the exchange-filter snapshot and failure audit; no kline/funding/mark Parquet, registry, or bundle was produced. The audit records only the failure type, so the exact validation cause is unavailable without another approved attempt. Do not retry or send further GETs under the closed no-retry authorization.

## Data and safety boundary

The local immutable-data tree contains kline Parquet/manifests, including BTCUSDT, ETHUSDT, and SOLUSDT 5m datasets with 378,211 rows each from 2023-01-01 through the last open time 2026-08-06T05:30:00Z. The inspected local tree has no persisted funding or mark-price derivative artifacts and no root bundle/registry files, so current-market or complete derivative provenance is **UNAVAILABLE**. No exchange/provider request or VPS operation was made; synthetic test artifacts were not represented as collected market data.

No candidate was promoted or admitted. Testnet/live authority and orders remain disabled. Research003 remains rejected. This implementation does not establish untouched/current-market holdout, operational reconciliation, legal/account/capital/kill-switch approvals, or production readiness.

## Pending publication

Funding-bound follow-up `92c6e6e20b3802a5bdf95aa342afb3329aed1784` and bounded collector `ec1116d6d39625ee3b54e7a91aaa8216af3d0b97` are published and CI-verified. Collection was attempted once and failed closed at the funding endpoint after two requests; preserve the partial local audit/snapshot. A further collection requires renewed explicit approval and a corrected, tested scope before any new GET.
