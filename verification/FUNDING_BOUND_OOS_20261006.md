# Funding-bound OOS research implementation — 2026-10-06

## Scope

Offline implementation only. Funding cash settlements now propagate through cached simulation, window evidence, walk-forward aggregation, persisted qualification and the Phase 250/253/autonomous research loaders. Longs debit positive funding payments; shorts receive the opposite signed cash flow. New qualification paths require funding mode `settled`, a verified funding artifact slice bound to bundle/registry/manifest/artifact hashes, and aligned funding timestamps. Cached evaluation windows copy pandas frames on ingress and return deep copies so callers cannot mutate retained evidence.

Autonomous-base synthetic windows now fail closed before research outputs are created. Offline exploration reports missing or unverified inputs as unavailable instead of writing an empty “completed” result; when a verified bundle is supplied, its loader checks the exact kline path and funding artifact. Phase 250 and Phase 253 also load windows through verified kline and funding artifact paths.

## Verification

- Related locked regression set: **511 passed in 51.09s**.
- After adding the verified offline-exploration loader integration, the integration/exploration subset passed: **13 passed in 6.88s**.
- Ruff: passed; **719 files** already formatted.
- Native and Linux-targeted mypy: passed, **359 source files** each.
- `uv lock --check`, changed-file `compileall`, and `git diff --check`: passed.
- Temporary-catalog integration tests exercised the autonomous-cycle and Phase 250 production loaders with synthetic, explicitly test-only artifacts. They prove plumbing and hash/path checks, not real-market provenance or strategy quality.
- Full pytest suite and exact-head GitHub Actions have not yet been run for this working tree.

## Data and safety boundary

The local immutable-data tree contains kline Parquet/manifests, including BTCUSDT, ETHUSDT, and SOLUSDT 5m datasets with 378,211 rows each from 2023-01-01 through the last open time 2026-08-06T05:30:00Z. The inspected local tree has no persisted funding or mark-price derivative artifacts and no root bundle/registry files, so current-market or complete derivative provenance is **UNAVAILABLE**. No exchange/provider request or VPS operation was made; synthetic test artifacts were not represented as collected market data.

No candidate was promoted or admitted. Testnet/live authority and orders remain disabled. Research003 remains rejected. This implementation does not establish untouched/current-market holdout, operational reconciliation, legal/account/capital/kill-switch approvals, or production readiness.

## Pending publication

This report describes the local verification state before publication. Exact commit SHA and the exact-SHA Actions result must be recorded after push; no full-suite or CI success is claimed here.
