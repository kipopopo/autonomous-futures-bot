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
- Collector commit `ec1116d6d39625ee3b54e7a91aaa8216af3d0b97` passed exact-head Actions `37469520310` (tests, Ruff, formatting, strict types, compile). The first approved one-shot collection stopped on `DataQualityError` at `/fapi/v1/fundingRate` after **2 GET attempts total**: one `/fapi/v1/exchangeInfo`, one funding request; no retry. The ignored local scope retains only the typed exchange-filter snapshot and failure audit; no kline/funding/mark Parquet, registry, or bundle was produced. The snapshot readback reports venue minimum notionals BTCUSDT=50, ETHUSDT=20, SOLUSDT=5 USDT (hash `bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb`); sizing remains fail-closed under the project’s 5-USDT constraint. The exact funding validation cause was not retained.
- The user renewed authorization for **one** further attempt with the same endpoints, symbols, time bounds, 1,800-GET ceiling, no retries, and local-only output. Collector changes now preserve the first failed root, write the second attempt to a fresh ignored root, and record a bounded single-line `DataQualityError` detail in its local audit. Affected tests passed **48 in 3.46s**; whole-tree Ruff, native/Linux mypy, lock, changed-file compilation, diff and secret scans passed. The renewed attempt has **not** started; exact-head CI for these changes must pass first.

## Data and safety boundary

The legacy immutable-data tree contains BTCUSDT, ETHUSDT, and SOLUSDT kline manifests but no verified funding/mark-price artifact or root bundle/registry. The approved new scope contains one read-back-verified exchange-filter snapshot and a failed audit after the first funding request; no market bars, derivative artifact, registry, or bundle exists. Current-market and complete derivative provenance are **UNAVAILABLE**. No provider/VPS/testnet/live/order operation occurred; synthetic test artifacts were not represented as collected market data.

No candidate was promoted or admitted. Testnet/live authority and orders remain disabled. Research003 remains rejected. This implementation does not establish untouched/current-market holdout, operational reconciliation, legal/account/capital/kill-switch approvals, or production readiness.

## Pending publication

Funding-bound follow-up `92c6e6e20b3802a5bdf95aa342afb3329aed1784` and bounded collector `ec1116d6d39625ee3b54e7a91aaa8216af3d0b97` are published and CI-verified. The first collection failed closed after two requests; preserve its partial audit/snapshot. The user has authorized one further attempt under the same exact scope; attempt 2 must use a fresh local root, retain no-retry behavior, and wait for exact-head CI on the diagnostic/audit change before any GET.
