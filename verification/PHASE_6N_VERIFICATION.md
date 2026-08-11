# Phase 6N Verification — longer immutable cached-data scope

## Result

Phase 6N built a new immutable DatasetBundle with a materially longer scope than
Phase 6K/6M. The prior pre-gap bundle and the five-day post-tail bundle were not
modified. All required components were persisted, read back through the shared
hash-verifying readers, and bound into a fresh registry and bundle.

This phase is data-foundation evidence only. No candidate qualification,
promotion, paper activation, scheduler, authenticated client, or order endpoint
was started.

## Scope

```text
root:                 research/immutable-data/scope-20260701-20260811
symbols:              BTCUSDT, ETHUSDT, SOLUSDT
primary interval:     5m
context interval:     15m
range:                2026-07-01T00:00:00Z → 2026-08-11T04:15:00Z
```

The end boundary is the last fully closed public candle captured in the
previous verified tail. The new root is separate from
`research/immutable-data/tail-20260811`; no prior artifact was extended in
place. The requested three-year mark-price attempt was abandoned after a
bounded HTTP 408 timeout on an oversized request; its partial root was removed
and was not used as evidence. The successful scope uses bounded public pages.

## Persisted rows

Per symbol:

```text
5m klines:            11,859
15m klines:            3,953
mark-price 5m:        11,859
funding events:          124
```

Each kline artifact was read back with its raw/canonical row counts matching.
Derivative manifest `rows` values matched the persisted Parquet readback. The
three symbols had identical cadence and range shape; no gaps were filled,
interpolated, or forward-filled.

## Registry and bundle

```text
registry components:  13
registry hash:        2daa004bb64582bc76338fb75ac6e09608213d85346deacd10cbd5b5c2b075bd
bundle hash:          ea3a4145f0a1950d4d1ecafc870accda043115714663026ccafbb423096a6a93
lock hash:            487a92cfe4abbc2ff06bc4ff6e1c1a80b5c981cc6982fa7462f995ca8aef0264
```

Component manifest hashes:

```text
BTCUSDT 5m:           b7351a305f8a08db9def011520b35e8ef1b3a54c57d045673775522e1e050ed8
BTCUSDT 15m:          0ba596e0e0f337c01ee18c57c1024174b388eab0e13cd511f716dc44c94d4611
BTCUSDT mark:         e0bce7394dc121fb572d10bf3ab7a3a6ceaddc80fd5cd09ca304c714d71dc9db
BTCUSDT funding:      c9d7b0b30ef68b2890536d60171cd3a3af46406f8f6f283fc45c744ef166f46e
ETHUSDT 5m:           dcc3333fd93fe8fe1c7077bbdf752262a77dce8151d1969f9b31ffec0ab974b5
ETHUSDT 15m:          e5d290e7406a3c363aa31ef9b88002e5bc898519c3e1235f4bc82c4534d3e0f7
ETHUSDT mark:         f0b6446e3421b8725e6a306ffdc490f3885071c8640f6a0c79749ab9a3aa2341
ETHUSDT funding:      6664eb87c999f7420195377ba0cf9201e68deed7f73e2ca9c17744ca6645127d
SOLUSDT 5m:           fea6d177c3931f2f6034be0ee0f5b37fe4bfbdbc2da6c0e22afdec8dd9bb6652
SOLUSDT 15m:          0aec5135ea08fc64e372de878c4910a75f7fce04323c947d79313840fb50319e
SOLUSDT mark:         c3e2b4f825b21375f310df7c600ec5798faa642281218d0c48a92353d37502e1
SOLUSDT funding:      6f0d1a2944d6afa78f7964802b29a891ec0a8d157afab9d68f7973e83a1c6735
exchange filters:     bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb
```

The exchange-filter snapshot is intentionally reused metadata, not a fresh
historical observation. Its symbol universe and schema match the new bundle.

## Source and safety

```text
source:               unsigned Binance USDⓈ-M public REST plus verified cache
credentials:          none
signed requests:      none
order endpoints:      none
data_source:          cached_only for downstream research
exchange_access:      false in research contracts
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
```

## Decision

The longer immutable scope is available for a fresh qualification evidence
reset. The next slice may evaluate one explicitly bound candidate against this
bundle; it must not reuse Phase 6M aggregation or qualification evidence. No
profitability or qualification claim is made by Phase 6N itself.

Source code baseline: `de56198`. Recommended runtime remains
`gpt-5.6-luna` via `openai-codex`, `Medium` effort.
