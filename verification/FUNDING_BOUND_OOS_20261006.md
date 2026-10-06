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
- A scope-pinned, no-retry collector is under local verification. Its no-network preflight plans **1,774 fixed GETs** and reserves **26** for funding pagination under the **1,800** hard cap. Collector/derivative and related data-foundation tests passed **46 in 3.10s**; Ruff formatted **721 files**, native/Linux mypy passed **360 source files**, and lock, changed-file compilation, diff and secret-scan gates passed. **No exchange request has been made**, and the collection output root is still absent. Exact-SHA Actions for this collector are pending.

## Data and safety boundary

The local immutable-data tree contains kline Parquet/manifests, including BTCUSDT, ETHUSDT, and SOLUSDT 5m datasets with 378,211 rows each from 2023-01-01 through the last open time 2026-08-06T05:30:00Z. The inspected local tree has no persisted funding or mark-price derivative artifacts and no root bundle/registry files, so current-market or complete derivative provenance is **UNAVAILABLE**. No exchange/provider request or VPS operation was made; synthetic test artifacts were not represented as collected market data.

No candidate was promoted or admitted. Testnet/live authority and orders remain disabled. Research003 remains rejected. This implementation does not establish untouched/current-market holdout, operational reconciliation, legal/account/capital/kill-switch approvals, or production readiness.

## Pending publication

Funding-bound follow-up `92c6e6e20b3802a5bdf95aa342afb3329aed1784` is published and CI-verified. The bounded collector is still local and uncommitted; after its exact-SHA quality run, only then execute the approved GETs, read back every bundle component, record the actual count/hashes, and keep all payload artifacts local and ignored by Git.
