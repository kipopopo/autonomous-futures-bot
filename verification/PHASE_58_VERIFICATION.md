# Phase 58 Verification — refreshed XRPUSDT 365-day immutable bundle

## Runtime

```text
model: GPT-5.6 Terra
provider: OpenAI Codex
effort: Medium
```

## Scope

User authorized a fresh, longer XRPUSDT data scope after two candidates were rejected on the prior 90-day bundle. Phase 58 collects a new immutable 365-day bundle under a separate remote root.

```text
Unsigned public REST only
No credential
No authenticated request
No order
No scheduler
No live execution
```

## Fresh scope

```text
symbol: XRPUSDT
primary/context: 5m / 15m
range: 2025-08-21T10:15:00Z → 2026-08-21T10:15:00Z
remote root: /var/lib/autonomous-futures/research/xrpusdt-365d
```

## Collected immutable components

```text
5m klines:       105,120 rows
15m klines:       35,040 rows
5m mark price:   105,120 rows
funding events:    1,095 rows
exchange filters:     1 XRPUSDT snapshot
bundle components:     5
```

## Immutable identities

```text
registry_hash: b8f56dd8130d9f48393fd89c8eb2d773cf17480ab698c794507c0183d4ecac20
bundle_hash:   f71e1288de701bccd015fb6152357f113acdef17d4985d018798da97e6de92f6
5m manifest:   0edabcd6d34dc7dff7e7731445397ee4f4dc8a71052311473a73b398711b420c
15m manifest:  7d9cd0822a0ab5823be0ca2d685d12e8437c9ce959526355a41a07112f4c896a
mark manifest: a30e4d4cd891001140be0b935d5bc221957fbd0260782e66ebefe32f28040845
funding hash:  6f989eb31aa94662b602102d4ff086fc13105bc9c9c031bb819335cee5f6e79c
filters hash:  4036a9269ec487e7046e70a79082f2528df64622aa2efe4ebcdaf5c02d768a0b
```

## Read-back verification

```text
bundle and registry hash verification: passed
canonical 5m read: passed (105,120 rows)
canonical 15m read: passed (35,040 rows)
manifest row counts: matched
candidate artifacts in fresh root: 0
temporary files: 0
```

The prior 90-day candidate/rejection artifacts remain separate and are not bound to this bundle. Their outcomes must not be reused for fresh-scope qualification.

## Safety status

```text
paper_activation=false
execution_authority=false
live_order_enabled=false
new_order_actions_allowed=false
```

## Verification

```text
local locked suite: 644 passed
local ruff/format/mypy/lock: passed
remote source/static verification: unchanged from Phase56 and passed at the deployed source commit
```

The next boundary may create one new, deterministic testing-only candidate bound to this exact 365-day bundle. It must not reuse a rejected candidate ID, source result, or qualification evidence from the 90-day scope.
