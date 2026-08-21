# Phase 52 Verification — XRPUSDT immutable cached-data bundle

## Scope

Phase 52 collects a bounded XRPUSDT research scope on Kainode through unsigned public Binance REST endpoints, canonicalizes it, and builds immutable manifests, registry, and bundle evidence.

```text
No credentials
No authenticated endpoint
No order
No scheduler
No live execution
```

## Collection scope

```text
symbol: XRPUSDT
primary interval: 5m
context interval: 15m
range: 2026-05-23T08:45:00Z → 2026-08-21T08:45:00Z
source: https://fapi.binance.com public REST
```

## Collected artifacts on Kainode

```text
5m klines:       25,920 rows
15m klines:       8,640 rows
5m mark price:   25,920 rows
funding events:     270 rows
exchange filters:     1 XRPUSDT snapshot
bundle components:     5
```

Remote artifact root:

```text
/var/lib/autonomous-futures/research/xrpusdt-90d
```

## Immutable identities

```text
registry_hash: 71d929b8ba2f9996b47e20fe4cf17e83576ec3c533abde28c5d62f9e93872d7d
bundle_hash:   68f2962b8a4aef3f8c0fd301b01e3043afce89f4686aeb9c0017046e3fad6ded
5m manifest:   a9e876c9812ae4d75d10eb4136d8aa881133578b90242d6b15f645099b9fa726
15m manifest:  6f47b36350af8751c0c66006a1b5c8238315f13a520eea55f8fa47e53ebdc19c
mark manifest: f029850c8093cea5f64a5b1e5dd40c11d76aebbd7e29d58e886876e1879b29e1
filters hash:  4036a9269ec487e7046e70a79082f2528df64622aa2efe4ebcdaf5c02d768a0b
funding hash:  369e0cbede47b497500b63bb4e9543eba823f620ac3b32c8a9177031738cb0de
```

## Read-back verification

```text
bundle read/verify:       passed
registry read/verify:     passed
5m Parquet canonical read: passed
15m Parquet canonical read: passed
manifest row counts:      matched
bundle component count:   5
temporary files:          0
```

The temporary collector was removed after execution. Market-data binaries remain on Kainode and were not added to Git.

## Boundaries

This is a bounded 90-day research bundle, not complete historical coverage. XRPUSDT candidate qualification, walk-forward evidence, paper eligibility, and live activation remain unavailable until the cached-only research pipeline evaluates this exact bundle.

```text
paper_activation=false
execution_authority=false
read_only_exchange_access=true
live_order_enabled=false
new_order_actions_allowed=false
```
