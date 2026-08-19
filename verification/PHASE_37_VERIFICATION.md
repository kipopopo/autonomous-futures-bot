# Phase 37 Verification — live risk percentage profile

## Scope

Phase 37 records the recommended risk values for a hypothetical 100 USDT live balance in the offline live-review contract.

```text
max_quote_notional_pct:    50%
max_capital_at_risk_pct:    1%
max_daily_loss_pct:         2%
```

Reference conversion at 100 USDT:

```text
max quote notional: 50 USDT
max capital at risk: 1 USDT
max daily loss: 2 USDT
```

These are design inputs only. They do not activate live trading.

## Existing safety profile

```text
max leverage: 1x
max open positions: 1
symbol: BTCUSDT only for first live design
operational stop target: approximately 1.5%
theoretical price-loss budget after estimated costs: approximately 1.88%
```

Production exchange filters must be rechecked at implementation time. If the live minimum notional exceeds the 50% cap, the action must be blocked rather than increasing the cap automatically.

## State

```text
live review state: reviewed_not_activated
live_enabled: false
network_allowed: false
new_actions_allowed: false
```

No live credential, network request, order, scheduler, or deployment was used.

## Verification

```text
Live-review/risk focused tests: 6 passed
Locked full suite:              624 passed
Ruff check:                     passed
Ruff format:                    passed
Mypy:                           159 source files clean
uv lock --check:                passed
git diff --check:               passed
network/live actions:           0
```

The values require future confirmation alongside legal, venue/account, secret-manager, kill-switch, reconciliation, and VPS gates before any live implementation.
