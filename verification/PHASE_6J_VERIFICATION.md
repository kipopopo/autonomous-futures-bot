# Phase 6J Verification — refreshed data-scope preflight

## Result

Phase 6J is a read-only preflight for a refreshed immutable evidence scope after
four executable cohorts failed qualification against the bounded Phase 6D
bundle. It intentionally does not mix new observations into the old bundle and
does not run another candidate retry.

The current verified bundle remains historical and bounded. A separate tail
collection/build is required before any new strategy qualification.

## Workspace and source

```text
local HEAD:       a42f02a81fd4ea15ef90787fa97c39faa456a4f6
origin/main:      a42f02a81fd4ea15ef90787fa97c39faa456a4f6
source:           unsigned Binance USDⓈ-M public REST
symbols:          BTCUSDT, ETHUSDT, SOLUSDT
authenticated:    false
```

No credentials, signed requests, order endpoint, exchange client, scheduler,
API/UI runtime, or paper process was used or started.

## Existing coverage

Read-only Kainode inspection of persisted Parquet artifacts found:

```text
5m canonical tail:   2026-08-06 05:30:00Z
15m canonical tail:  2026-08-06 05:15:00Z
5m rows/symbol:      378,211
15m rows/symbol:     126,070
```

The existing Phase 6D bundle remains:

```text
bundle range:        2023-10-31T08:00:00Z → 2023-11-10T03:40:00Z
bundle hash:         ffb21166b9dd55cfeab657f261a546f91a9f19b5cbc89f88ef37bd6991d833f8
registry hash:       596d7370b99462bc5d9153e2264267d18b7cf457b85ef0d45f9ce83bfb23e8f0
```

Historical derivative artifacts in the Phase 6D bundle remain limited to the
same pre-outage research range and were not rewritten.

## Public endpoint preflight

The unsigned public Binance server-time endpoint returned a current server
observation during the probe:

```text
serverTime: 1786421499004
```

Bounded `limit=3` probes succeeded for every required symbol on:

```text
/fapi/v1/klines?interval=5m
/fapi/v1/markPriceKlines?interval=5m
/fapi/v1/fundingRate
```

The observed responses were parsed only as endpoint reachability evidence. No
payload was persisted as a canonical artifact in this phase.

## Scope decision

A post-tail refresh is technically available, but the old bundle cannot be
extended in place because its immutable range, registry binding, derivative
coverage, and bundle hash would change. The next collection slice must:

1. derive an explicit UTC half-open range beginning after the last verified
   contiguous 5m/15m tail;
2. clamp the end to fully closed public bars;
3. collect 5m, 15m, mark-price, and funding data for all three symbols;
4. validate gaps and range boundaries without interpolation or forward-fill;
5. persist new immutable artifacts and manifests under a new ignored root;
6. build a new registry and DatasetBundle with fresh content hashes; and
7. run artifact readback/integrity verification before any new candidate.

No values were inferred across the historical outage, and no new bundle was
claimed from this preflight.

## Safety state

```text
data_source="cached_only" for research consumers
exchange_access=false in repository contracts
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

This phase proves endpoint reachability and identifies a possible refresh
scope only. It does not prove complete historical ingestion, data quality of a
future tail, profitability, qualification, paper readiness, or live readiness.

Recommended runtime for the next bounded immutable collection slice:
`gpt-5.6-luna` via `openai-codex`, `Medium` effort.
