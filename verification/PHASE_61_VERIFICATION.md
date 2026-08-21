# Phase 61 Verification — DOGEUSDT 365-day immutable research bundle

## Runtime

```text
model: GPT-5.6 Terra
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 61 collects a fresh DOGEUSDT immutable research bundle on Kainode from unsigned public Binance USDⓈ-M REST endpoints.

```text
No credential
No authenticated request
No candidate
No qualification
No paper activation
No live activation
No order
```

## Fresh scope

```text
symbol: DOGEUSDT
primary/context: 5m / 15m
range: 2025-08-21T10:45:00Z → 2026-08-21T10:45:00Z
remote root: /var/lib/autonomous-futures/research/dogeusdt-365d
```

## Immutable components

```text
5m klines:       105,120 rows
15m klines:       35,040 rows
5m mark price:   105,120 rows
funding events:    1,095 rows
exchange filters:     1 DOGEUSDT snapshot
bundle components:     5
```

## Immutable identities

```text
registry_hash: 17f140c77f1911f26dd63bd0d20144149dab7cd424a3760f4b7797d10b61375e
bundle_hash:   30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3
5m manifest:   db73adc0e20c64766b40cee829823d6f62c9ad25c930d024813d87ed6dafb5df
15m manifest:  775e0560c0f648eb222b1f3c97e39afcd266e86a2eeb82f413eefe9218acbe01
mark manifest: 1a21d93c6d26bd97e7996cc9d525664fb00a85058642249097b3f1e2279eb063
funding hash:  35ef9d1e997b116c6fb734eba2a07b8121e991eb2aac4ab7030bbb85c29da807
filters hash:  f7a1871f94520e206b7ed63ebd2a398d52bbf12969e6fb3e6910d3d8e9cffe5e
```

## Read-back verification

```text
registry/bundle hash verification: passed
canonical 5m read: passed (105,120 rows)
canonical 15m read: passed (35,040 rows)
manifest row counts: matched
candidate artifacts in fresh root: 0
temporary files: 0
```

## Safety status

```text
paper_activation=false
execution_authority=false
live_order_enabled=false
new_order_actions_allowed=false
```

The next boundary may create one independent, testing-only DOGEUSDT candidate bound to this exact bundle. XRP candidates/evidence remain unrelated and cannot be reused.

## Verification

```text
local locked suite: 644 passed
local ruff/format/mypy/lock: passed
remote source/static verification: unchanged from Phase56 and passed at the deployed source commit
```
