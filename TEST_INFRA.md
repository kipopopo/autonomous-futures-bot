# E2E Test Infra: Autonomous Futures Bot — Phase 315

## Test Philosophy
- **Opaque-Box, Requirement-Driven**: Tests derive strictly from `ORIGINAL_REQUEST.md` (Phase 315) and `PROJECT.md` without dependency on undocumented private internals.
- **Progressive Testability & Zero-Mock Integrity**: Tests evaluate concrete observable behaviors of the dynamic evolution state machine, transparent Out-of-Sample (OOS) qualification telemetry, 8-pair perpetual universe ingress and exchange filters, 15m macro-confluence liquidity dip scalper, micro-capital risk boundaries, and double-entry solvency ledger.
- **Mathematical Exactness**: Absolute zero-drift balance invariant $|\Delta| < 10^{-15}\text{ USDT}$ enforced across all lifecycle transitions:
  $$\text{Cash} + \text{Allocated Margin} + \text{Unrealized PnL} = \text{Starting Equity} + \text{Realized PnL}$$
- **Non-Interference Guarantee**: Strict isolation ensuring the 24/7 background daemon on Kainode VPS (Main PID 87549) is never disrupted (isolated test namespaces, independent mock transports when offline, isolated SQLite databases).

---

## 4-Tier Test Methodology

### Tier 1 — Feature Coverage (Category-Partition Equivalence Classes)
Each of the 8 core features is partitioned into functional equivalence classes with at least 5 isolated test cases per feature (>= 40 tests total):

1. **Feature 1: Dynamic Evolution State Machine API**:
   - Equivalence classes:
     * 5 discrete cycle stages: `INGRESS` -> `HEALTH_EVALUATION` -> `TRADE_AUTOPSY` -> `MUTATION_STAGING` -> `SHADOW_OOS_GATE`.
     * Dynamic cycle progress percentage calculation ($80\% + (\min(\text{trades}, 5) / 5 \times 20\%)$).
     * 15-second cycle scan interval (`next_cycle_seconds: 15`).
     * Live timestamps (`last_evaluated_timestamp_ms`, `candle_fetch_timestamp_ms`).
     * Daemon status & PID synchronization (`ONLINE 24/7`, PID `87549`).
     * Generation metadata (`active_generation: "GEN #2"`, `next_target_generation: "GEN #3"`).

2. **Feature 2: Transparent OOS Qualification Telemetry API**:
   - Equivalence classes:
     * Required trade sample count hurdle (strictly 5 closed trades).
     * Current acquired trade sample count ($0/5$ up to $\ge 5$).
     * Required Sharpe improvement hurdle ($\ge 15.0\%$).
     * Status indicators: `WAITING_FOR_SAMPLES`, `EVALUATING`, `QUALIFIED`, `REJECTED`.
     * Macro trend gating telemetry (`regime`: `BEARISH`, `BULLISH_ALIGNED`, `NEUTRAL`; `longs_filtered`: `True`/`False`).
     * Human-readable macro gating explanation in Malay/English.

3. **Feature 3: 8-Pair Perpetual Universe Ingress & Filters**:
   - Equivalence classes:
     * Complete 8-pair universe coverage: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `DOGEUSDT`, `BNBUSDT`, `XRPUSDT`, `SUIUSDT`, `AVAXUSDT`.
     * Exchange filter quantization: `LOT_SIZE` with `ROUND_DOWN` step size.
     * `PRICE_FILTER` tick quantization with `ROUND_HALF_UP`.
     * `MIN_NOTIONAL` validation ($5.00 USDT floor across candidates).
     * Sizing step-up rule (+1 step size) for sub-dollar coins (`DOGEUSDT`, `XRPUSDT`, `SUIUSDT`, `AVAXUSDT`) meeting exchange minimum without exceeding micro-capital ceiling.

4. **Feature 4: Scalper Opportunity Evaluation across 7 Candidates**:
   - Equivalence classes:
     * 15m candidate klines, 20 EMA, 14 ATR, 20 SMA Volume, 14 RSI.
     * Confluence entry criteria: BTC macro bull regime (`BTC 1h EMA 50 > EMA 200` & `Close > EMA 200`), dip distance $> 2.5\times$ ATR below 20 EMA, volume spike $> 2.2\times$ 20 SMA, RSI $14 < 26.0$.
     * Scanning across all 7 non-BTC candidates (`ETHUSDT`, `SOLUSDT`, `DOGEUSDT`, `BNBUSDT`, `XRPUSDT`, `SUIUSDT`, `AVAXUSDT`).
     * Trade structuring: Maker limit order at `Close` (0.02% maker fee).
     * Bracket targets: Take-Profit at $+2.0\times$ ATR, Stop-Loss at $-1.2\times$ ATR (1.6667:1 Risk:Reward ratio).
     * Time-decay stop at 8 bars (120 minutes).

5. **Feature 5: Micro-Capital Governance & Fail-Closed Guardrails**:
   - Equivalence classes:
     * Micro child order cap $\le \$5.00$ USDT per order slice.
     * Aggregate portfolio exposure ceiling $\le \$25.00$ USDT across all active positions simultaneously.
     * Unencumbered liquid cash reserve floor $\ge 75.0\%$ of wallet equity at all times.
     * Intra-day loss budget $\le \$3.00$ USDT tripping `CIRCUIT_FLATTENED`.
     * Hawkes spectral radius interlock ($\rho < 1.0$).
     * Gateway heartbeat latency interlock ($\le 500$ ms).

6. **Feature 6: Double-Entry Solvency Balance Invariant**:
   - Equivalence classes:
     * Double-entry balance equation: $\text{Cash} + \text{Allocated Margin} + \text{Unrealized PnL} = \text{Starting Equity} + \text{Realized PnL}$.
     * Absolute zero-drift tolerance: $|\Delta| < 10^{-15}\text{ USDT}$.
     * Order margin reservation across multiple pairs.
     * Position fill reconciliation with fee deduction (0.02% maker, 0.04% taker).
     * Take-profit and stop-loss realization with zero balance drift.
     * Position flattening solvency snapshots.

7. **Feature 7: Multi-Pair Dashboard API Contract**:
   - Equivalence classes:
     * `/api/v1/market/prices` returning live mark prices for all 8 pairs.
     * `/api/v1/execution/status` reporting positions dictionary covering all 8 symbols.
     * Truthful flat position state (`0.0` position_qty, `0.0` allocated exposure, `STANDBY / SCANNING`).
     * Active position state reporting exact entry price, unrealized PnL, margin, and bracket target prices.
     * Recent orders feed containing authentic executions (`canary-p310-`, `canary-p311-`), eliminating phantom entries.

8. **Feature 8: Interactive Candlestick Data Contract**:
   - Equivalence classes:
     * `GET /api/v1/market/klines` returning normalized OHLCV for 15m and 1h intervals.
     * High-precision pricing for sub-dollar assets (`DOGEUSDT` 5 decimals, `XRPUSDT` 4 decimals, `SUIUSDT` 4 decimals).
     * Technical overlays (50 EMA, 200 EMA, Volume histogram).
     * Dynamic bracket target lines (TP $+2.0\times$ ATR, SL $-1.2\times$ ATR) rendered only when active position exists, suppressed when flat.

---

## Tier 2 — Boundary & Corner Cases (Boundary Value Analysis)
BVA targets extreme operating boundaries, edge conditions, and adversarial inputs (>= 5 test cases per category, >= 35 tests total):

1. **Minimum Notional Step-Up Boundaries**:
   - Order notional at $4.99 USDT (below $5.00 floor) triggering step-up for `DOGEUSDT`, `XRPUSDT`, `SUIUSDT`, and `AVAXUSDT`.
   - Stepped-up notional within allowable ceiling $[5.00, 5.00 + \text{step} \times \text{price}]$ accepted.
   - Stepped-up notional exceeding allowable ceiling rejected fail-closed.
2. **Trade Sample Size Boundaries**:
   - Exactly 0 closed trades: `WAITING_FOR_SAMPLES (0/5)`, progress $80.0\%$.
   - Intermediate sample counts (1, 2, 3, 4 trades): progress advancing proportionally.
   - Exactly 5 closed trades: boundary transition to `EVALUATING` (progress $100.0\%$).
   - $\ge 5$ trades with Sharpe improvement $\ge 15.0\%$: transition to `QUALIFIED`.
3. **Cash Reserve Floor Boundaries**:
   - Unencumbered cash at exactly 75.0%: permitted.
   - Unencumbered cash at 74.99%: fails cash floor check, new margin allocations rejected.
4. **Aggregate Portfolio Exposure Boundaries**:
   - Aggregate exposure at exactly $25.00 USDT: permitted.
   - Order that would cause aggregate exposure to reach $25.01 USDT: strictly rejected by interlock.
5. **Sub-Satoshi Precision & Round-Down Boundaries**:
   - High-precision step size quantization using `ROUND_DOWN` ensuring zero over-allocation.
   - High-frequency sequential fills ($10^{-8}$ to $10^{-15}$ USDT) verifying continuous zero-drift conservation ($|\Delta| < 10^{-15}$ USDT).
6. **Intra-Day Loss Ceiling Boundaries**:
   - Intra-day loss at $2.99 USDT: engine remains in `MICRO_CAPITAL_ACTIVE`.
   - Intra-day loss at $3.00 USDT: engine instantaneously trips `CIRCUIT_FLATTENED`, auto-flattens positions, and halts trading.
7. **Hawkes Hazard & Heartbeat Latency Boundaries**:
   - Hawkes spectral radius $\rho = 0.99$: safe, trading active.
   - Hawkes spectral radius $\rho = 1.00$: throttled (`HAWKES_THROTTLED`), order dispatch blocked.
   - Gateway heartbeat latency at 500.0 ms: accepted.
   - Gateway heartbeat latency at 500.1 ms: rejected / degraded.

---

## Tier 3 — Cross-Feature Combinations (Pairwise Combinatorial)
Testing pairwise and multi-feature interaction surfaces (>= 15 tests total):

1. **BTC Bearish Regime + Scalper Dip on Candidate Pairs**:
   - Valid dip criteria met on `DOGEUSDT` and `SOLUSDT`, but BTC 1h/4h macro trend is Bearish (`EMA 50 < EMA 200`): long entry orders strictly blocked.
2. **BTC Bullish Regime + Concurrent Multi-Pair Dips**:
   - Dips trigger simultaneously on `SOLUSDT`, `ETHUSDT`, `DOGEUSDT`, and `AVAXUSDT`: verify child order cap ($\le \$5$) and aggregate exposure ceiling ($\le \$25$) are jointly enforced.
3. **Dynamic Evolution State Transition during Active Trades**:
   - Advancing cycle stages (`INGRESS` -> `HEALTH_EVALUATION` -> `TRADE_AUTOPSY` -> `MUTATION_STAGING` -> `SHADOW_OOS_GATE`) while trades are active preserves exact zero balance drift.
4. **8-Pair Mark Price Ingress + Kline Cache + Execution Status**:
   - Price feeds for all 8 pairs update in-memory kline caches and execution status without cache collision or missing keys.
5. **Exchange Filter Step-Up + Ledger Margin Reservation + Solvency Invariant**:
   - Sub-dollar sizing step-up reserves exact quantized margin in `CentralizedSolvencyLedger` with $|\Delta| < 10^{-15}$ USDT.
6. **Evolution OOS Gate Telemetry + Macro Trend Gating API Synchronization**:
   - Dynamic evolution endpoint `/api/v1/canary/evolution` reflects both live sample count (`0/5`) and BTC macro regime gating status with explanatory banner.
7. **Candlestick API 4-Decimal Precision + Sub-Dollar Tick Size Quantization**:
   - Kline API endpoints accurately return high-precision prices for `DOGEUSDT` and `XRPUSDT` matching exchange tick sizes.
8. **Multi-Pair Concurrent Execution, TP/SL Bracket Triggers, Fee Deduction & Ledger Reconciliation**:
   - Concurrent positions across different pairs, one hitting TP (+2.0x ATR) and one hitting SL (-1.2x ATR), fee deductions recorded, zero balance drift verified.

---

## Tier 4 — Real-World Workload Scenarios (End-to-End Workflows)
Comprehensive multi-step end-to-end operational workflows (>= 5 scenarios):

1. **Scenario 1: Full Daemon Trading Cycle Simulation with 8 Pairs & Dynamic Telemetry**:
   - Complete 15s cycle: Ingress klines for all 8 pairs $\rightarrow$ evaluate BTC macro trend $\rightarrow$ scan 7 candidates for liquidity dips $\rightarrow$ update dynamic evolution state $\rightarrow$ reconcile solvency ledger $\rightarrow$ verify daemon heartbeat.
2. **Scenario 2: Macro Regime Flip from Bearish to Bullish with Scalper Reactivation**:
   - Phase A: Bearish BTC regime suppresses all candidate dips for capital protection.
   - Phase B: BTC breaks above 200 EMA with EMA 50 > EMA 200 (Bullish regime confirmed).
   - Phase C: Candidate dip on `DOGEUSDT` generates authentic maker limit order with TP/SL brackets.
3. **Scenario 3: Multi-Pair Concurrent Execution, Bracket Realization & Ledger Solvency**:
   - Enter positions on 3 distinct pairs (`SOLUSDT`, `ETHUSDT`, `DOGEUSDT`) totaling ~$15 exposure $\le \$25$.
   - First pair hits Take-Profit (+2.0x ATR), second pair hits Stop-Loss (-1.2x ATR), third pair flattened.
   - Double-entry ledger reconciles each event with exact zero drift ($|\Delta| < 10^{-15}$ USDT).
4. **Scenario 4: Out-of-Sample Qualification Progression from 0 to 5 Closed Trades**:
   - Start in `WAITING_FOR_SAMPLES` with 0 trades.
   - Incrementally complete trades 1 through 4: sample counter and progress update.
   - Complete 5th trade: status transitions to `EVALUATING` and checks Sharpe hurdle ($\ge 15.0\%$).
5. **Scenario 5: Adversarial Micro-Capital Stress & Circuit Breaker Enforcement**:
   - Concurrent dips across all 7 candidates: verify aggregate exposure ceiling rejects 6th and 7th positions.
   - Simulate severe adverse market movement hitting $3.00 daily loss: engine trips `CIRCUIT_FLATTENED`, flattens positions, and maintains solvency.

---

## Feature Inventory & Test Mapping

| # | Feature | Requirement Source | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---------|-------------------|:------:|:------:|:------:|:------:|
| 1 | Dynamic Evolution State Machine API | ORIGINAL_REQUEST §R1, PROJECT §F1 | 5 | 5 | ✓ | ✓ |
| 2 | Transparent OOS Gate Telemetry API | ORIGINAL_REQUEST §R1, PROJECT §F2 | 5 | 5 | ✓ | ✓ |
| 3 | 8-Pair Perpetual Universe Ingress & Filters | ORIGINAL_REQUEST §R2, PROJECT §F3 | 6 | 6 | ✓ | ✓ |
| 4 | Scalper Opportunity Evaluation (7 Candidates) | ORIGINAL_REQUEST §R2, PROJECT §F4 | 5 | 5 | ✓ | ✓ |
| 5 | Micro-Capital Governance & Guardrails | ORIGINAL_REQUEST §R4, PROJECT §F5 | 5 | 5 | ✓ | ✓ |
| 6 | Double-Entry Solvency Balance Invariant | ORIGINAL_REQUEST §R4, PROJECT §F6 | 5 | 5 | ✓ | ✓ |
| 7 | Multi-Pair Dashboard API Contract | ORIGINAL_REQUEST §R3, PROJECT §F7 | 5 | 5 | ✓ | ✓ |
| 8 | Interactive Candlestick Data Contract | ORIGINAL_REQUEST §R3, PROJECT §F8 | 5 | 5 | ✓ | ✓ |

---

## Test Architecture & Execution

### Test Suite Location
- Comprehensive E2E Test Suite: `tests/e2e/test_phase_315_e2e_universe_and_evolution.py`

### Test Runner Command
```bash
.venv/Scripts/python -m pytest tests/e2e/test_phase_315_e2e_universe_and_evolution.py -v
```

### Coverage Thresholds
- **Tier 1**: $\ge 40$ feature tests (8 features $\times \ge 5$ tests)
- **Tier 2**: $\ge 35$ boundary and corner tests
- **Tier 3**: $\ge 15$ pairwise interaction tests
- **Tier 4**: $\ge 5$ real-world workload scenario tests
- **Total Target**: $\ge 95$ tests covering all Phase 315 specifications.
