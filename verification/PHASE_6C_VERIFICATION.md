# Phase 6C Verification — bounded public mark-price collector

## Scope

Added the minimum reusable production boundary for public mark-price collection:

```text
explicit [start_ms, end_ms_exclusive)
→ existing resumable kline backfill
→ strict complete-range validation
→ existing mark-price canonicalizer
→ existing immutable Parquet + manifest writer
```

The collector is unsigned/public-only and requires an explicit range. It has no
credentials, signed requests, order endpoints, promotion, paper activation, or
execution authority.

## TDD evidence

- RED: new collector test failed during collection because
  `autonomous_futures.data.derivative_collection` did not exist.
- GREEN: focused derivative/backfill/transport regression:

```text
19 passed in 1.59s
```

The test uses the actual 12-field Binance mark-price kline response shape,
resumable checkpoint path, canonical Parquet writer, and manifest writer.

## Historical outage boundary

The Kainode public collection established a shared five-bar Binance mark-price
outage for BTCUSDT, ETHUSDT, and SOLUSDT at:

```text
1699587600000 through 1699588800000
2023-11-10T03:40:00Z through 2023-11-10T04:00:00Z
```

Phase 6B therefore remains the valid bounded bundle boundary. The new collector
fails closed on a range containing missing bars; it does not interpolate,
forward-fill, or silently shorten a requested range.

## Safety boundary

This phase proves collector composition and immutable persistence only. It does
not prove historical completeness, alpha, qualification, profitability,
paper readiness, promotion, demo readiness, or live execution.
