# Phase 6A Verification

## Scope

Materialized immutable local **kline-only** collections from the already cached,
public raw CSVs. Generated artifacts live under the ignored
`research/immutable-data/` root and are deliberately not committed as binary
research data.

| Interval | Collection hash | Rows per BTCUSDT/ETHUSDT/SOLUSDT |
|---|---|---:|
| 5m | `0c1cf42fd3dc962a104de51f9c28978997299bb38a7c08cdc14893f362572bf7` | 378,211 |
| 15m | `a659c69d32c2eb2d271616d19cdd8b60aa896a3044a6af7a7dd957d9222895ed` | 126,070 |

Each collection was built by the existing `build_kline_collection(...)` path
using code version `c55221f` and the locked `uv.lock` SHA-256. Both manifests
and all six canonical parquet files were reread through project verification
readers after materialization.

## Safety and limitation

This is cached, public kline evidence only. It does not create a dataset
registry or complete `DatasetBundle`, because the source cache lacks required
mark-price and exchange-filter components. No candidate, OOS aggregation,
qualification, promotion, paper activation, provider/exchange call, or order
path was added.

## Delivery

`.gitignore` excludes `research/immutable-data/` so the 72MB generated
artifact set cannot be accidentally committed. Existing raw CSV provenance is
unchanged.
