# Immutable Bundle Refresh — 2026-09-12

## Decision

A fresh complete immutable research bundle was **PUBLISHED and VERIFIED** on
the remote research worker. It is available for downstream cached-only learner
or derivative research. No candidate, candidate registry, paper ledger,
scheduler, service, testnet, live account, or order state was changed.

## Scope

```text
root:                 research/immutable-data/scope-20260912
symbols:              BTCUSDT, ETHUSDT, SOLUSDT
primary interval:     5m
context interval:     15m
primary range:        [2026-07-01T00:00:00Z, 2026-08-06T05:30:00Z)
context range:        [2026-06-30T23:45:00Z, 2026-08-06T05:30:00Z)
source commit:        eff95edfda2a1ba714c91141cbf017c3b7eccd5e
lock hash:            sha256:487a92cfe4abbc2ff06bc4ff6e1c1a80b5c981cc6982fa7462f995ca8aef0264
```

The 5m and 15m artifacts are contiguous slices of the verified canonical
inputs. No raw CSV was fabricated, interpolated, forward-filled, or used to
bridge a gap. Mark-price and funding artifacts were collected through the
existing unsigned public adapters; exchange filters were freshly read and
parsed through the existing snapshot contract.

## Persisted rows

| Component | BTCUSDT | ETHUSDT | SOLUSDT |
|---|---:|---:|---:|
| 5m kline | 10,434 | 10,434 | 10,434 |
| 15m context | 3,479 | 3,479 | 3,479 |
| 5m mark price | 10,434 | 10,434 | 10,434 |
| funding events | 109 | 109 | 109 |

The bundle contains the expected `13` components: four per symbol plus one
exchange-filter snapshot.

## Content identities

```text
registry hash:        ee83e82abbbb0b9f47bf6a87f4577d4689bf6b72b5ed4ac3cf1f8c7f0b7ddba8
bundle hash:          108b5ce688f2c5389ceb60fb1a265d1db313bba184f9dcd4bf0e8541bb4abdaa
exchange-filter hash: bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb
```

### Component manifest hashes

| Symbol | 5m kline | 15m context | 5m mark price | Funding |
|---|---|---|---|---|
| BTCUSDT | `8a0c5abedeaf7aa5aaa7a54c2a00ccba45f45978c8b87d41cc31d915f0f73ce3` | `522ee6ad5531d96a7a2168243db1f0da1fc7409e896e717e48f8a16eaa18bd81` | `d4a8c7e838374f79a4a4cc928b65b3e213c7ed103063830877c53b6a4e1cfb55` | `373f5abfb748dcbb82e38fdf82de8ad4393d0d1a110c1e5d2673999ade192393` |
| ETHUSDT | `1e88e01b69c86ee01ae6920377779785f1096ef8fb9b6bd34b8991f12336b852` | `7b3e4441296328b79288cdb34c48c4dfcce0b7cc232d6023af7139b271847534` | `ba81de9be4144408d3ac54159ea399ec1269f48df3059cdc0c42ace12c4927f9` | `e04056761d01a91c00d80d79d2c406e867aff441787bb2b3bf4d1bf1a520a57f` |
| SOLUSDT | `fc90a0e361c0b933a48b2b04e80ab3746dbc53c1db07461d1cb2d4b05bb8a03d` | `fd42026c831ee0406a013151710e691090bc142918f963aec33a807316b6674c` | `7bd60d59d0fb701ca14af5bc7cbf723d4ad335c2ef7029c9ab124cf65689c1ce` | `79fbe3469f346cdc4760b84dfdb562918c8a2f933a54ff0c560b26760fa76a48` |
```

## Collection and readback

```text
public requests:
  server time:        1
  exchange info:      1
  mark price:         7 per symbol
  funding rate:       1 per symbol
  total:               26
retry max attempts:   1 (zero retries)
registry readback:    PASS
bundle readback:      PASS
all 13 artifact inspections: PASS
post-publication readback: PASS
temporary root:       removed
```

The first publication attempt stopped before collection because the protected
final root was not writable by the unprivileged operator. The corrected flow
used a temporary root, verified all artifacts, then performed one privileged
atomic move. No network call or partial final artifact resulted from the first
attempt.

## Safety boundary

```text
data provenance:      unsigned public REST + verified canonical cache
credentials:           none used
signed requests:       none
order endpoints:       none
provider/LLM calls:    none
paper mutation:        none
candidate mutation:    none
promotion state:       unpromoted
paper activation:      false
execution authority:   false
live activation:       false
```

This bundle proves data availability and hash integrity only. It does not prove
historical completeness beyond the stated range, strategy profitability,
learner quality, candidate qualification, paper readiness, or live readiness.
The next learner/derivative research slice must bind to this exact registry and
bundle hash and remain cached-only.
