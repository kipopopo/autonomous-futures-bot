# E2E Test Infra: Autonomous Futures Bot — Phase 310

## Test Philosophy
- **Opaque-box, requirement-driven**: Tests derive strictly from `ORIGINAL_REQUEST.md` (Phase 310) without dependency on internal implementation designs or mocking internal private methods.
- **Methodology**: Systematic 4-tier approach:
  - **Tier 1 — Feature Coverage (>=5 per feature)**: Isolated functional verification using representative happy-path inputs.
  - **Tier 2 — Boundary & Corner Cases (>=5 per feature)**: Boundary Value Analysis (BVA) testing extreme limits, empty buffers, clock drift edges, precision roundings, and negative values.
  - **Tier 3 — Cross-Feature Interactions**: Pairwise combinatorial testing of gateway bridge, scalper engine, solvency ledger, autopsy loop, and VPS alerts.
  - **Tier 4 — Real-World Application Scenarios**: Comprehensive end-to-end trading workflows with live/testnet simulation, volatile sweeps, circuit breaks, and recovery.

## Feature Inventory & Test Mapping
| # | Feature | Requirement Source | Tier 1 | Tier 2 | Tier 3 |
|---|---------|-------------------|:------:|:------:|:------:|
| 1 | Binance Futures Dual-Mode Gateway Bridge | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 2 | WebSocket User Data Stream & listenKey Keepalive | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 3 | Macro Liquidity Sweep Scalper & BTC Trend Filter | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 4 | Trade Structuring, Fee Drag & Time Decay Stop | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 5 | Closed-Loop Autopsy Feedback & Telemetry DB | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 6 | Fail-Closed Daily Drawdown Pause (3.00 USDT) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 7 | Double-Entry Solvency & Micro-Capital Bounds | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 8 | 24/7 VPS Deployment & Telegram Alerts | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |

## Test Architecture
- **Test Runner**: Pytest via `uv run pytest tests/unit/test_phase_310_*.py tests/integration/test_phase_310_*.py`
- **Pass/Fail Semantics**: 100% exit code 0, zero assertion errors, zero unhandled exceptions.
- **Directory Layout**:
  - `tests/unit/test_phase_310_binance_gateway.py`
  - `tests/unit/test_phase_310_macro_scalper.py`
  - `tests/unit/test_phase_310_autopsy_feedback.py`
  - `tests/unit/test_phase_310_vps_solvency.py`
  - `tests/integration/test_phase_310_e2e_opaque_box.py`
  - `tests/unit/test_phase_310_adversarial_challenger_1.py`
  - `tests/unit/test_phase_310_adversarial_challenger_2.py`

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Normal Trading Session with BTC Bull Regime | F1, F2, F3, F4, F7, F8 | Medium |
| 2 | Hostile Market Liquidity Cascade & Hawkes Interlock | F3, F4, F7, F8 | High |
| 3 | Network Disconnect, Clock Drift & Re-sync | F1, F2, F8 | High |
| 4 | Drawdown Breach & Fail-Closed Flattening | F5, F6, F7, F8 | High |
| 5 | End-to-End Trade Autopsy, Telemetry & Merkle DAG Chain | F1, F3, F5, F7, F8 | High |

## Coverage Thresholds
- **Tier 1**: >= 40 tests across features
- **Tier 2**: >= 40 boundary tests
- **Tier 3**: >= 15 pairwise interaction tests
- **Tier 4**: >= 5 end-to-end workload scenario tests
- **Total Minimum Target**: >= 100 test cases
