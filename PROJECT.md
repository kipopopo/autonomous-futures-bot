# Project: Autonomous Futures Bot — Phase 295: Live Strategy Activation & Walk-Forward OOS Promotion Gates

## Architecture
Phase 295 links staged quantitative candidate strategies to live Binance market feeds and real-time Hawkes microstructure telemetry, enforcing rigorous multi-tier out-of-sample promotion gates and fail-closed veto interlocks, and driving promoted signals directly into the paper-safe execution simulator with continuous mathematical zero-drift balance validation.

```
[Phase 292 Binance USDⓈ-M Ingress] (Depth, Trades, Mark Prices)
                 │
                 ├─────────────────────────────────────────────────┐
                 ▼                                                 ▼
[Phase 293 Hawkes Streamer] (Jump Intensity, Spectral Radius ρ)    │
                 │                                                 │
                 ▼                                                 │
┌────────────────────────────────────────────────────────────┐     │
│ Phase 295 Candidate Strategy Evaluator                     │     │
│ - Manifest v2 Ingress (BTCUSDT, ETHUSDT, SOLUSDT)          │     │
│ - Causal Indicator Engine (Donchian, Volatility, Momentum) │     │
│ - Candidate State Machine (UNPROMOTED, PROMOTED, BLOCKED)  │     │
└────────────────────────────┬───────────────────────────────┘     │
                             │                                     │
                             ▼                                     │
┌────────────────────────────────────────────────────────────┐     │
│ Walk-Forward OOS Promotion Gates & Real-Time Vetoes        │     │
│ - OOS Gates: Avg Return >= 0, DD <= 15%, PF >= 1.05, N >= 5│     │
│ - Veto 1: Hawkes Supercritical (ρ >= 1.0 or severe hazard) │     │
│ - Veto 2: Gateway Heartbeat Age > 500ms or Skew > 250ms    │     │
│ - Veto 3: Margin Headroom (Active > 60 USDT, Reserve < 40%)│     │
└────────────────────────────┬───────────────────────────────┘     │
                             │ Promoted & Unvetoed                 │
                             │ ParentOrderIntention                │
                             │ c=canary-p295-{sym}-{ts}-{uuid}     │
                             ▼                                     │
┌────────────────────────────────────────────────────────────┐     │
│ Phase 294 Paper Execution Engine Pipeline                  │     │
│ - ChildOrderGenerator: Slicing <= 5.00 USDT, ROUND_DOWN    │     │
│ - SimulatedPassiveMatchingEngine: Queue priority matching  │◄────┘
│ - PaperExecutionLedger: Continuous Zero-Drift Balance      │
│   Cash + Margin + Unrealized PnL = Equity + Realized PnL   │
│   Strict absolute tolerance |Δ| < 10^-15 USDT              │
└────────────────────────────┬───────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────┐
│ Observational API & Web App Dashboard                      │
│ - FastAPI: /api/v1/canary/strategy-activation              │
│ - React/Vite/Tailwind: Strategy Activation Page            │
│ - Cryptographic SHA-256 Merkle DAG Hash Chain              │
└────────────────────────────────────────────────────────────┘
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Candidate Registry Manifest v2 Ingress | Ingest and cryptographically verify `artifacts/paper_live/candidate_registry.json` binding active candidates (`cand-btcusdt-dcb-002`, `cand-ethusdt-dcb-003`, `cand-solusdt-rgb-001`) | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Causal Strategy Feature Computation | Compute Donchian channel breakout, rolling volatility (ATR/Bollinger), and trade momentum on incoming market ticks/bars without forward lookahead | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Typed Parent Order Intention Formulation | Generate typed, bounded `ParentOrderIntention` objects with deterministic tagging (`c=canary-p295-{sym}-{ts}-{uuid}`) | M1 | ORIGINAL_REQUEST §R1 |
| 4 | Walk-Forward OOS Qualification Gate Evaluator | Evaluate candidate qualification criteria: Avg Return >= 0.0, Worst DD <= 15.0%, Profit Factor >= 1.05, Trade Count >= 5 across >= 1 window | M1 | ORIGINAL_REQUEST §R2 |
| 5 | Candidate Lifecycle State Machine | Manage candidate status transitions: `UNPROMOTED` (probation/testing), `PROMOTED` (qualified), `BLOCKED` (failed gate/loss breach), `VETOED` (transient suppression) | M1 | ORIGINAL_REQUEST §R2 |
| 6 | Hawkes Microstructure Veto Interlock | Suppress signal dispatch fail-closed if spectral radius ρ >= 1.0 or severe predatory front-running hazard is active | M1 | ORIGINAL_REQUEST §R2 |
| 7 | Gateway Heartbeat & Clock Skew Veto | Reject signal generation fail-closed if gateway heartbeat age > 500 ms or clock skew > 250 ms (with recovery hysteresis) | M1 | ORIGINAL_REQUEST §R2 |
| 8 | Portfolio Exposure & Margin Reserve Veto | Reject signal generation if active exposure > 60.00 USDT, per-symbol exposure > 20.00 USDT, or cash reserve < 40% (utilization > 60%) | M1 | ORIGINAL_REQUEST §R2 |
| 9 | Intra-Phase Cumulative Loss Budget Ceiling | Cumulative loss >= 7.00 USDT triggers immediate portfolio-wide lockout and micro-chunked position liquidation (<= 5.00 USDT) | M1 | ORIGINAL_REQUEST §R2, §R3 |
| 10 | Micro Child Order Slicing Integration | Route promoted intentions to Phase 294 `slice_parent_order` with chunk notional strictly <= 5.00 USDT and `ROUND_DOWN` precision | M1 | ORIGINAL_REQUEST §R3 |
| 11 | Passive Matching Simulation Execution | Simulate maker/taker queue execution against Phase 292 top-5 book depth and aggregate trade flow with realistic fees/slippage | M1 | ORIGINAL_REQUEST §R3 |
| 12 | Mathematical Double-Entry Zero-Drift Ledger | Enforce continuous reconciliation invariant: `Cash + Allocated Margin + Unrealized PnL = Starting Equity + Realized PnL` with |Δ| < 10^-15 USDT | M1 | ORIGINAL_REQUEST §R3 |
| 13 | Cryptographic SHA-256 Merkle DAG Persistence | Persist audit artifacts in `artifacts/research/phase295/` with Merkle DAG chain linking upstream Phase 294 summary hashes | M1 | ORIGINAL_REQUEST §R3 |
| 14 | Deterministic Strategy Activation CLI Runner | Implement `scripts/run_phase_295_strategy_activation.py` executing 4 simulation tracks with clean exit code 0 | M1 | ORIGINAL_REQUEST Acceptance Criteria |
| 15 | Observational FastAPI Strategy Activation Route | Implement `/api/v1/canary/strategy-activation` returning candidate promotion status, OOS metrics, signals, vetoes, and execution stats | M2 | ORIGINAL_REQUEST §R4 |
| 16 | Interactive Dashboard Strategy Activation View | Update React/Vite dashboard with `#strategy-activation` route, scorecard grid, candidate cards, veto monitor, and zero-drift gauge | M2 | ORIGINAL_REQUEST §R4 |
| 17 | Strict Paper-Safe Confinement Enforcement | Guarantee `EXECUTION AUTHORITY: OFF`, 0 live API credentials, 0 real exchange orders transmitted | M1, M2 | ORIGINAL_REQUEST §R5 |
| 18 | Opaque-Box E2E Testing Suite (Tiers 1-4) | Comprehensive independent test suite covering Feature Coverage, Boundary & Corner, Pairwise Combinations, and Real-World Workloads | E2E Track | Project Pattern Dual Track |
| 19 | Adversarial Coverage Hardening (Tier 5) | Adversarial test coverage and white-box stress testing via Challenger loop to eliminate gaps | M3 (Phase 2) | Project Pattern Final Milestone |
| 20 | Static Quality Gates & Full Verification | Static checks (`ruff`, `mypy`, `tsc`) and targeted test suites pass with 0 errors | M3 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Independent opaque-box test infrastructure (`TEST_INFRA.md`) and comprehensive test suite (Tiers 1-4) published via `TEST_READY.md` | none | DONE |
| M1 | Core Strategy Activation Engine & CLI Runner | `src/autonomous_futures/feed/strategy_activation.py` (candidate loading, features, OOS gates, vetoes, child slicing, matching, ledger zero-drift, Merkle DAG) + `scripts/run_phase_295_strategy_activation.py` | none | DONE |
| M2 | Observational API & Web App Dashboard | Read-only endpoint `/api/v1/canary/strategy-activation` in `src/autonomous_futures/api/` + React dashboard Strategy Activation view in `frontend/src/` | M1 | DONE |
| M3 | Final Milestone: 100% E2E Test Pass & Adversarial Hardening | Phase 1: 100% E2E test pass (Tiers 1-4); Phase 2: Adversarial Coverage Hardening (Tier 5); runner exit code 0; static quality gates (`ruff`, `mypy`, `tsc`) clean | E2E, M1, M2 | DONE |

## Interface Contracts

### Candidate Strategy Evaluator ↔ Promotion Gate Evaluator
- Models:
  ```python
  class CandidatePromotionStatus(StrEnum):
      UNPROMOTED = "UNPROMOTED"
      PROMOTED = "PROMOTED"
      BLOCKED = "BLOCKED"
      VETOED = "VETOED"

  class OOSPromotionGateRecord(DomainModel):
      candidate_id: str
      symbol: str
      status: CandidatePromotionStatus
      oos_average_return_pct: Decimal
      oos_worst_drawdown_pct: Decimal
      oos_profit_factor: Decimal
      oos_trade_count: int
      oos_window_count: int
      gates_passed: dict[str, bool]
      qualified: bool
      evaluated_at: datetime
  ```
- Evaluator Signature:
  `evaluate_oos_promotion_gates(candidate: CreatorCandidateArtifact, qualification: CreatorCandidateQualificationArtifact) -> OOSPromotionGateRecord`

### Strategy Evaluator ↔ Veto Interlocks & Child Slicing
- Deterministic Client Order ID:
  `c=canary-p295-{symbol}-{timestamp_ms}-{uuid}` (Parent)
  `c=canary-p295-{symbol}-{timestamp_ms}-{uuid}-slice-{i}` (Child)
- Parent Order Contract:
  `ParentOrderIntention(parent_order_id=..., candidate_id=..., symbol=..., side=..., order_type=..., target_notional_usdt=..., limit_price=..., created_time_ms=...)`
- Veto Check Signature:
  `validate_realtime_veto_interlocks(interlock: LivePaperRiskInterlock, hawkes_snapshot: HawkesTelemetrySnapshot, feed_health: GatewayHealth, proposed_notional: Decimal, symbol: str) -> VetoDecision`
- Child Order Slicing:
  `slice_parent_order(parent: ParentOrderIntention, filters: BinanceSymbolFilters, reference_price: Decimal, chunk_cap_usdt: Decimal = Decimal("4.50")) -> list[ChildOrderIntention]`

### Double-Entry Accounting Reconciliation Contract
- Invariant Equation:
  $$\text{Cash} + \text{Allocated Margin} + \text{Unrealized PnL} = \text{Starting Equity} + \text{Realized PnL}$$
  $$\text{drift} = |\text{Cash} + \text{Allocated Margin} + \text{Unrealized PnL} - (\text{Starting Equity} + \text{Realized PnL} + \text{PosUnrealized})| < 10^{-15}\text{ USDT}$$

### Observational API ↔ Frontend Contract
- Route: `GET /api/v1/canary/strategy-activation`
- Response Schema:
  ```json
  {
    "phase": "phase_295",
    "status": "STRATEGY_ACTIVATION_VERIFIED",
    "timestamp_ms": 1726912345678,
    "execution_authority": false,
    "paper_safe": true,
    "candidates": [
      {
        "candidate_id": "cand-btcusdt-dcb-002",
        "symbol": "BTCUSDT",
        "status": "PROMOTED",
        "average_return_pct": 2.885,
        "worst_drawdown_pct": 9.606,
        "profit_factor": 1.7503,
        "trade_count": 9,
        "window_count": 3,
        "qualified": true
      }
    ],
    "signals": [],
    "vetoes": {
      "hawkes_supercritical": false,
      "gateway_heartbeat_stale": false,
      "margin_headroom_breach": false
    },
    "ledger": {
      "starting_equity": 100.0,
      "cash": 100.0,
      "allocated_margin": 0.0,
      "unrealized_pnl": 0.0,
      "realized_pnl": 0.0,
      "drift": 0.0
    },
    "upstream_hash": "...",
    "phase_hash": "..."
  }
  ```

## Code Layout
- `src/autonomous_futures/feed/strategy_activation.py`: Core Phase 295 engine (promotion gates, causal evaluator, veto interlocks, execution binding, artifact persistence).
- `src/autonomous_futures/api/canary.py`: Pydantic response models and loader for `/api/v1/canary/strategy-activation`.
- `src/autonomous_futures/api/app.py`: FastAPI route registration for `/api/v1/canary/strategy-activation`.
- `scripts/run_phase_295_strategy_activation.py`: 4-track deterministic CLI simulation runner.
- `frontend/src/lib/navigation.ts`: Dashboard routing for `#strategy-activation`.
- `frontend/src/lib/api.ts`: API client function `fetchCanaryStrategyActivation()`.
- `frontend/src/lib/canary.ts`: Frontend TypeScript models and builder `buildStrategyActivationModel()`.
- `frontend/src/components/strategy-activation-page.tsx`: Interactive Strategy Activation dashboard view.
- `frontend/src/App.tsx`: Navigation bar, route handling, and sidebar link.
- `tests/unit/test_phase_295_strategy_activation.py`: Targeted unit and integration tests.
- `tests/e2e/test_phase_295_strategy_activation_e2e.py`: Opaque-box E2E test suite (Tiers 1-4).
- `frontend/src/components/__tests__/strategy-activation-page.test.tsx`: Vitest tests for UI components.
