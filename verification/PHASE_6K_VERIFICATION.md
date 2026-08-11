# Phase 6K Verification — bounded post-tail immutable collection

## Result

Phase 6K collected and persisted a new bounded post-tail data scope for
BTCUSDT, ETHUSDT, and SOLUSDT. The old Phase 6D bundle was not modified. New
kline, mark-price, funding, registry, and bundle artifacts were written under
an ignored immutable root on Kainode and reread through shared validators.

## Scope

```text
root:                 research/immutable-data/tail-20260811
symbols:              BTCUSDT, ETHUSDT, SOLUSDT
primary interval:     5m
context interval:     15m
5m range:             2026-08-06T05:35:00Z → 2026-08-11T04:15:00Z
15m range:            2026-08-06T05:30:00Z → 2026-08-11T04:15:00Z
mark range:           2026-08-06T05:35:00Z → 2026-08-11T04:15:00Z
funding coverage:     2026-08-06T05:30:00Z → 2026-08-11T04:15:00Z
```

The end boundary was clamped to the last fully closed public candle. No gap
was filled, inferred, forward-filled, or interpolated.

## Persisted row evidence

Per symbol:

```text
5m klines:            1,424
15m klines:           475
mark-price 5m:        1,424
funding events:       15
```

All three symbols returned the same bounded cadence/row shape. Kline, mark,
and funding manifests were independently read back with artifact hash
validation; each readback row count matched its persisted manifest.

## Manifest hashes

```text
BTCUSDT 5m:           ac981b6921f6f30ca60ad8df3eca45f83ae4420bdc803e4712a7b68c60ae62bc
BTCUSDT 15m:          b0ad035008fb60c389df5de74a324878168920a91604da6c46323827e677ba83
BTCUSDT mark:         610ac280bc8c7a3510456f36c72e443d653b6cfb578a3ca933e5ae2e969e7fe2
BTCUSDT funding:      7aafcc86422497de7ef9610d9b57bea3bee69be2e62a118a4f6ff37d6f66f35d

ETHUSDT 5m:           deb17bbaed5c216998420c5a25cb9de8bbcc05adab5b27ecc094be72c09136eb
ETHUSDT 15m:          4ec28f571cb0419e5fb1a1a5d0d54b0519c3c0a5b928567e2bd3ef5d64770446
ETHUSDT mark:         03e77c004052906a364f4cb129efc5ef45144e6c3de9f63a3a27a88d0316bc39
ETHUSDT funding:      ca273a23e5a9ae0852addc19017f586db8e6f8637eb222009c9cbf5fbd1fc7bc

SOLUSDT 5m:           d4f3c3e186b1b7e2f7fb9c901bf1e143971c3e27eb18e66ebc013d7bc319af4c
SOLUSDT 15m:          357853c82ccc8b5ffa9e4e9d4943ed870421fa9724f7cdd73c328f4e06bdb66c
SOLUSDT mark:         f80ac36838dbed572e89afa1875927e4b5fc9bc1d4460eeaed6a5942178a20fe
SOLUSDT funding:      25aa77828b77d928b91025d291569962d85def768f78c25265f14b2ec5a5fcfa
```

## Registry and bundle

```text
registry components:  13
registry hash:        b164c4dbe2a10dda92611eed1187662f8d5c30759eded24206bfd5d79ecc4ce6
bundle hash:          b69c5db0a0e3c628de905327dd24d9e510368bfe33a7a62221d1f13dd633f5ca
lock hash:            487a92cfe4abbc2ff06bc4ff6e1c1a80b5c981cc6982fa7462f995ca8aef0264
source commit:        7faa22524c63bcc54a12c1763e0bfc6bc6757220
```

The registry and DatasetBundle were built, persisted, and reread through the
shared hash-verifying readers. The bundle has the expected 13 components: four
per symbol plus one exchange-filter snapshot.

The exchange-filter component is the previously verified symbol-universe
snapshot (`bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb`).
It is metadata without a historical time range and was not rewritten. Its reuse
is explicit; it does not imply a new exchange-filter observation.

## Source and safety

```text
source:               unsigned Binance USDⓈ-M public REST
credentials:          none
signed requests:      none
order endpoints:      none
data_source:          cached_only for downstream research
exchange_access:      false in research contracts
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
```

This phase proves a bounded immutable post-tail dataset scope, not historical
completeness, current-market representativeness, profitability, qualification,
paper readiness, or live readiness. The next candidate evaluation must use the
new bundle as a fresh evidence generation and must not compare its metrics as
portable with the old Phase 6F–6I bundle without an explicit evidence reset.

Recommended runtime for the next bounded cached-only qualification slice:
`gpt-5.6-luna` via `openai-codex`, `Medium` effort.
