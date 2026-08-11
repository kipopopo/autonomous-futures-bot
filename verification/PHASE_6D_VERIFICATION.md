# Phase 6D Verification — production collector bundle rebuild

## Result

The reusable `collect_mark_price_artifact(...)` boundary from Phase 6C was
executed on Kainode for all required symbols using unsigned Binance public REST
transport:

```text
BTCUSDT 5m: 2,828 rows
ETHUSDT 5m: 2,828 rows
SOLUSDT 5m: 2,828 rows
```

Scope:

```text
[start, end) =
2023-10-31T08:00:00Z → 2023-11-10T03:40:00Z
```

The end remains immediately before the verified shared five-bar public
mark-price outage. No gap values were fabricated.

## Persisted v2 bundle

| Item | Value |
|---|---|
| Host | Kainode `147.79.18.15` |
| Collector code | `4b76506` |
| Components | 13: 6 kline, 3 mark-price, 3 funding, 1 exchange-filter |
| Registry hash | `596d7370b99462bc5d9153e2264267d18b7cf457b85ef0d45f9ce83bfb23e8f0` |
| Bundle hash | `ffb21166b9dd55cfeab657f261a546f91a9f19b5cbc89f88ef37bd6991d833f8` |
| Artifact inspection | 13/13 verified |

The v2 assembly also corrected two stale metadata bindings discovered by the
read-only API verifier:

- exchange-filter registry content hash now binds to snapshot hash
  `bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb`;
- every kline/funding/mark registry entry now points to its manifest relative to
the v2 artifact root, not to the previous bundle root or directly to a parquet
file.

## Verification

Remote:

```text
collector: 3 symbols completed
bundle: 13 components verified
mark rows: [2828, 2828, 2828]
```

This phase proves public collection, persistence, registry binding, bundle
construction, and read-only artifact integrity. It does not prove historical
completeness beyond the bounded scope, strategy quality, qualification,
profitability, paper activation, promotion, or live execution.
