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
- Collector commit `ec1116d6d39625ee3b54e7a91aaa8216af3d0b97` passed exact-head Actions `37469520310`. Attempt 1 stopped on `DataQualityError` at `/fapi/v1/fundingRate` after 2 GETs (one exchangeInfo, one funding), with no retry; its audit retained only the type. The user authorized one fresh attempt with the identical endpoints, symbols, range, 1,800 cap, no retries, and local-only output.
- The diagnostic collector update `0ae137e319828d20ee173181afd68aa18aee839f` passed exact-head Actions `37478800227` (tests, Ruff, format, strict types, compile). Attempt 2 also stopped after 2 GETs (one exchangeInfo, one funding); audit detail: `invalid decimal in markPrice: ''`. Both ignored roots retain only an exchange-filter snapshot and failure audit; neither has market bars, funding/mark Parquet, registry, or bundle. At the end of attempt 2, no further GETs were authorized by the then-current approval. Do not coerce or substitute an empty funding mark price without an explicitly approved policy.
- The typed snapshot readback reports venue minimum notionals BTCUSDT=50, ETHUSDT=20, SOLUSDT=5 USDT (hash `bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb`); sizing remains fail-closed against the project's 5-USDT constraint. Affected local tests passed 48; whole-tree Ruff, native/Linux mypy, lock, changed-file compilation, diff and secret scans passed.

## Data and safety boundary

The legacy immutable-data tree contains BTCUSDT, ETHUSDT, and SOLUSDT kline manifests but no verified funding/mark-price artifact or root bundle/registry. Both approved collection attempt roots contain only a read-back-verified exchange-filter snapshot and failed audit; no market bars, derivative artifacts, registry, or bundle exists. Current-market and complete derivative provenance are **UNAVAILABLE**. No provider/VPS/testnet/live/order operation occurred; synthetic test artifacts were not represented as collected market data.

No candidate was promoted or admitted. Testnet/live authority and orders remain disabled. Research003 remains rejected. This implementation does not establish untouched/current-market holdout, operational reconciliation, legal/account/capital/kill-switch approvals, or production readiness.

## Current approved public-data follow-up — 2026-10-07 (pre-attempt)

The user has now explicitly approved exactly one third local-only collection attempt under the same unsigned endpoints, symbols, historical half-open range, 1,800-GET ceiling, no-retry/stop-on-first-error rule, and ignored local output. For a funding row whose `markPrice` is empty only, the approved fallback is the OPEN from the 5m `/fapi/v1/markPriceKlines` candle whose timestamp exactly equals `fundingTime`; no nearest candle, close, interpolation, or forward fill is permitted.

The implementation collects and verifies mark-price artifacts before funding history, writes per-row source labels and the fallback mark-manifest hash into funding schema v2, and verifies that hash, timestamp, and exact OPEN again when loading a verified funding slice. Focused market-data regressions passed (**50 passed**); Ruff lint/format, native and Linux mypy (**360 source files**), lock, changed-file compilation, and diff checks passed. Exact-SHA CI is still required before the single approved collection; attempt 3 has not made any GET yet. Its fresh ignored output root is `research/immutable-data/approved-public-20261006-attempt3/`.

## Pending publication

Funding-bound follow-up `92c6e6e20b3802a5bdf95aa342afb3329aed1784`, bounded collector `ec1116d6d39625ee3b54e7a91aaa8216af3d0b97`, and diagnostic update `0ae137e319828d20ee173181afd68aa18aee839f` are published and CI-verified. Preserve both failed attempt roots unchanged. The new one-shot attempt 3 and its exact-timestamp fallback are explicitly approved, but remain gated on exact-SHA CI; no additional attempt or fallback policy is authorized beyond that scope.
