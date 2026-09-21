# E2E Test Infra: Phase 295 Live Strategy Activation & Walk-Forward OOS Promotion Gates

## Test Philosophy
- **Opaque-box & Requirement-driven**: Derived directly from `ORIGINAL_REQUEST.md` (Phase 295 directives) and `PROJECT.md` interface contracts. Validates external behavior, public contracts, and mathematical invariants independently of implementation internals.
- **Methodology**: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial Interactions + Real-World Workload Simulation.
- **Strict Paper-Safe Confinement**: Enforces `EXECUTION AUTHORITY: OFF`, zero real exchange API credentials, and zero live order transmissions across all test runners, fixtures, and assertions.
- **Continuous Zero-Drift Verification**: Mathematical conservation equation $\text{Cash} + \text{Allocated Margin} + \text{Unrealized PnL} = \text{Starting Equity} + \text{Realized PnL}$ verified at every state transition with strict absolute tolerance $|\Delta| < 10^{-15}\text{ USDT}$.

---

## Feature Inventory Coverage (17 Core Features)

| # | Feature | Requirement Source | Tier 1 (Min 5) | Tier 2 (Min 5) | Tier 3 (Pairwise) | Tier 4 (Workload) |
|---|---------|--------------------|:--------------:|:--------------:|:-----------------:|:-----------------:|
| 1 | Candidate Registry Manifest v2 Ingress | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 2 | Causal Strategy Feature Computation | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 3 | Typed Parent Order Intention Formulation | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 4 | Walk-Forward OOS Qualification Gate Evaluator | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 5 | Candidate Lifecycle State Machine | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 6 | Hawkes Microstructure Veto Interlock | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 7 | Gateway Heartbeat & Clock Skew Veto | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 8 | Portfolio Exposure & Margin Reserve Veto | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 9 | Intra-Phase Cumulative Loss Budget Ceiling | ORIGINAL_REQUEST §R2, §R3 | 5 | 5 | ✓ | ✓ |
| 10 | Micro Child Order Slicing Integration | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 11 | Passive Matching Simulation Execution | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 12 | Mathematical Double-Entry Zero-Drift Ledger | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 13 | Cryptographic SHA-256 Merkle DAG Persistence | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 14 | Deterministic Strategy Activation CLI Runner | ORIGINAL_REQUEST Acceptance Criteria | 5 | 5 | ✓ | ✓ |
| 15 | Observational FastAPI Strategy Activation Route | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 16 | Interactive Dashboard Strategy Activation Telemetry | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 17 | Strict Paper-Safe Confinement Enforcement | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ | ✓ |

---

## Test Architecture
- **E2E Test Runner**: Pytest via `uv run pytest tests/e2e/test_phase_295_strategy_activation_e2e.py`
- **Frontend Test Runner**: Vitest via `npm test` in `frontend/`
- **Location**: `tests/e2e/test_phase_295_strategy_activation_e2e.py`
- **Primary Public Contracts Tested**:
  - `evaluate_oos_promotion_gates(candidate, qualification) -> OOSPromotionGateRecord`
  - `validate_realtime_veto_interlocks(interlock, hawkes_snapshot, feed_health, proposed_notional, symbol) -> VetoDecision`
  - `slice_parent_order(parent, filters, reference_price, chunk_cap_usdt) -> list[ChildOrderIntention]`
  - `PaperExecutionLedger.record_fill(...)` with zero-drift invariant assertion $|\Delta| < 10^{-15}\text{ USDT}$
  - CLI Runner: `scripts/run_phase_295_strategy_activation.py` (Track 1: nominal, Track 2: hawkes veto, Track 3: loss ceiling, Track 4: multi-symbol concurrency)
  - FastAPI Route: `GET /api/v1/canary/strategy-activation`
- **Fixtures & Synthetic Feeds**:
  - Authoritative manifest v2 files (`artifacts/paper_live/candidate_registry.json`)
  - Canonical Binance USDⓈ-M exchange filters for BTCUSDT, ETHUSDT, SOLUSDT
  - Synthetic streaming depth snapshots and aggregate trades with causal timestamps
  - Synthetic Hawkes jump processes with varying spectral radius ($\rho \in [0.1, 1.5]$)

---

## Real-World Application Scenarios (Tier 4)

| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Multi-Asset Nominal Walk-Forward Strategy Activation Rehearsal (BTC, ETH, SOL) | F1-F5, F10-F12, F14, F17 | High |
| 2 | Sudden Hawkes Microstructure Supercritical Flare ($\rho = 1.25$) During Active Slicing | F2, F3, F5, F6, F10, F12 | High |
| 3 | Gateway Network Disconnect with Latency Stale Heartbeat (500 ms vs 501 ms) & Hysteresis Recovery | F3, F5, F7, F10, F12 | Medium |
| 4 | Multi-Candidate Concurrent Signal Generation Under Shared 60.00 USDT Portfolio Margin | F1, F3, F5, F8, F10, F12 | High |
| 5 | Adverse Execution Drift & Intra-Phase Loss Ceiling Breach (7.00 USDT) with Emergency Lockout | F5, F9, F10, F11, F12 | High |
| 6 | Unpromoted Probation Candidate Evaluator Ingress & Rejection Behavior | F1, F4, F5, F15 | Medium |
| 7 | Dynamic Regime Shift (NOMINAL $\to$ ELEVATED $\to$ SEVERE) with Throttled Chunk Sizing | F2, F6, F8, F10, F11, F12 | High |
| 8 | Post-Only Passive Limit Queue Matching with Depth Depletion & Slippage Modeling | F10, F11, F12 | Medium |
| 9 | Cryptographic SHA-256 Merkle DAG Hash Chain Linkage Across Phase 294 & Phase 295 | F12, F13, F14, F15 | Medium |
| 10 | Continuous 100-Tick Multi-Symbol Trade Stream Stress with Zero Balance Drift Audit | F1-F12, F17 | High |

---

## Coverage Thresholds
- **Tier 1 (Feature Coverage)**: $\ge 5$ test assertions per feature ($\ge 85$ test cases).
- **Tier 2 (Boundary & Corner Cases)**: $\ge 5$ test assertions per feature ($\ge 85$ boundary test cases).
- **Tier 3 (Cross-Feature Combinations)**: $\ge 20$ pairwise combinatorial interaction test cases.
- **Tier 4 (Real-World Application Scenarios)**: $\ge 10$ comprehensive end-to-end simulated trading sessions.
- **Total E2E Test Suite Target**: $\ge 200$ rigorous, fully verified opaque-box test cases.
- **Zero-Drift Tolerance**: $100\%$ of trade executions pass $|\Delta| < 10^{-15}\text{ USDT}$.
- **Confinement**: $100\%$ tests assert `execution_authority == False` and zero network calls.
