# E2E Test Infra: Autonomous Futures Bot — Phase 311

## Test Philosophy
- **Opaque-Box, Requirement-Driven**: Tests derive strictly from `ORIGINAL_REQUEST.md` (Phase 311) and `PROJECT.md` without dependency on undocumented private internals.
- **Progressive Testability & Zero-Mock Integrity**: Tests evaluate concrete behaviors of the execution harness, exchange filters, gateway client, ATR protective brackets, Telegram alert formatters, double-entry solvency ledger, and Merkle DAG cryptographic telemetry.
- **Mathematical Exactness**: Absolute zero-drift balance invariant $|\Delta| < 10^{-15}\text{ USDT}$ enforced across all lifecycle transitions.
- **Non-Interference Guarantee**: Strict isolation ensuring the 24/7 background daemon on Kainode VPS is never disrupted (isolated client order IDs, separate storage namespaces, no listenKey termination, no global mass cancellations).

---

## 4-Tier Test Methodology

### Tier 1 — Feature Coverage (Category-Partition Equivalence Classes)
Each of the 8 core features is partitioned into functional equivalence classes with at least 5 isolated test cases per feature (>= 40 tests total):
1. **Feature 1: Testnet Execution Drill CLI Harness & Flags**:
   - Equivalence classes: `--symbol` selection (`SOLUSDT`, `ETHUSDT`), `--side` (`BUY`, `SELL`), `--notional` specification, `--dry-run` flag, `--cleanup`/`--auto-close` routine, and `--verify-only` mode.
2. **Feature 2: Binance Exchange Filter Validation & Precision Step-Up**:
   - Equivalence classes: `LOT_SIZE` quantization with `ROUND_DOWN`, `PRICE_FILTER` tick quantization with `ROUND_HALF_UP`, `MIN_NOTIONAL` validation, and allowable single step-size precision step-up (+1 tick) to meet the 5.00 USDT exchange floor without violating micro-capital bounds.
3. **Feature 3: Gateway REST Extensions & Signed Order Dispatch**:
   - Equivalence classes: `get_order` endpoint (`GET /fapi/v1/order`), `get_open_orders` endpoint (`GET /fapi/v1/openOrders`), `cancel_all_open_orders` endpoint, `create_order` support for `TAKE_PROFIT_MARKET` with `stopPrice`, HMAC-SHA256 signature verification, and strictly monotonic nonces.
4. **Feature 4: Dynamic ATR-Based Bracket Management**:
   - Equivalence classes: 14-period ATR calculation from 15m klines, dynamic Take-Profit target ($+2.0\times$ ATR), dynamic Stop-Loss target ($-1.2\times$ ATR), strict $1.66:1$ Risk:Reward ratio ($2.0 / 1.2 = 1.6667$), and `reduceOnly=True` enforcement.
5. **Feature 5: Real-Time Multi-Channel Telegram Alerting**:
   - Equivalence classes: MarkdownV2 character escaping (19 reserved characters), order submission alert formatting, fill confirmation alert formatting, bracket establishment alerts with TP/SL percentage distance, and cleanup position flattening alerts.
6. **Feature 6: CentralizedSolvencyLedger & Mathematical Zero-Drift Balance Invariant**:
   - Equivalence classes: Double-entry balance equation $\text{Cash} + \text{Allocated Margin} + \text{Unrealized PnL} = \text{Starting Equity} + \text{Realized PnL}$, absolute drift tolerance $|\Delta| < 10^{-15}\text{ USDT}$, order margin staging, fill reconciliation with fees and slippage, and position flattening solvency snapshots.
7. **Feature 7: Cryptographic Merkle DAG Telemetry & Upstream Lineage**:
   - Equivalence classes: Isolated SQLite database (`canary-lifecycle-telemetry.sqlite3`), append-only JSONL audit sink (`canary-orders.jsonl`), structured drill report (`canary-drill-report.json`), drill summary (`drill-summary.json`), and cryptographic chaining to Phase 310 upstream parent root `0004387045399718c6229d1a18fec40399d4baba01b0eecd0ab51c782268dd84`.
8. **Feature 8: Non-Disruptive Cleanup, Flattening & VPS Daemon Protection**:
   - Equivalence classes: Selective client order ID prefix filtering (`canary-p311-drill-`), cancelling only drill-placed bracket orders, flattening residual drill positions via market `reduceOnly=True` order, preserving WebSocket user data stream `listenKey` (never deleting via `DELETE /fapi/v1/listenKey`), and isolated process space.

---

### Tier 2 — Boundary & Corner Cases (Boundary Value Analysis)
BVA targets extreme operating boundaries, edge conditions, and adversarial inputs (>= 5 test cases per category, >= 35 tests total):
1. **Empty Inputs & Invalid Parameters**:
   - Empty symbol strings, missing side, negative notional, zero notional, non-numeric strings, and malformed JSON payloads.
2. **Micro-Capital Ceiling Violations**:
   - Order notional $> 5.00$ USDT (e.g. 5.01 USDT, 10.00 USDT, 100.00 USDT) strictly rejected or clamped by fail-closed guardrails.
   - Aggregate exposure exceeding 25.00 USDT triggering instant interlock rejection.
   - Cumulative intra-day loss exceeding 3.00 USDT tripping the circuit breaker.
3. **Step-Size & Tick-Size Edge Cases**:
   - Fractional quantities below minimum step size (e.g. 0.00000001), exact step boundaries, prime-fraction prices requiring rounding, and sub-tick tick size quantizations.
4. **Network Timeouts & Clock Drift Boundaries**:
   - Clock drift $|\Delta t| = 999\text{ ms}$ (accepted) vs $|\Delta t| = 1001\text{ ms}$ (rejected / degraded).
   - Gateway heartbeat latency $\le 500\text{ ms}$ (accepted) vs $> 500\text{ ms}$ (blocked).
   - Network HTTP 504 / timeout simulation triggering fail-closed abort.
5. **Zero-Drift Sub-Satoshi Precision Boundaries**:
   - High-frequency micro fills ($10^{-8}$ to $10^{-18}$ USDT) verifying continuous zero-drift invariant under 1,000 sequential state updates.
   - Irregular fee deductions ($0.02\%$ maker fee) verifying cash and realized PnL precision preservation.
6. **Client Order ID 36-Character Boundary Limits**:
   - Length verification of `canary-p311-drill-{sym}-{ts}`: 3-char symbol (`sol` $\rightarrow 35$ chars $\le 36$), 7-char symbol truncation (`solusdt` truncated to `sol`), and bracket prefixes (`canary-p311-tp-`, `canary-p311-sl-`).

---

### Tier 3 — Cross-Feature Combinations (Pairwise Combinatorial)
Testing pairwise and multi-feature interaction surfaces (>= 15 tests total):
1. **CLI Harness + Dry-Run + Telegram Alerting**: CLI flag parsing in `--dry-run` mode triggers mock order generation and formats Telegram alert without network calls.
2. **Live Drill Dispatch + ATR Brackets + Cleanup Flattening**: Entry maker order fill triggers TP (+2.0x ATR) and SL (-1.2x ATR) creation, followed by `--cleanup` routine cancelling brackets and flattening net position.
3. **Order Fill + Double-Entry Ledger + Merkle Root**: Order fill updates `CentralizedSolvencyLedger`, records event in SQLite and JSONL, and computes Merkle root chained to Phase 310 parent.
4. **Gateway REST + Clock Drift + Monotonic Nonce**: Gateway verifies clock synchronization before dispatching signed order with strictly incremented nonces.
5. **Exchange Filter Step-Up + Micro-Capital Guard + Solvency Balance**: Sizing logic steps up quantity by 1 tick to meet `MIN_NOTIONAL = 5.00 USDT`, validates notional against child cap, and reserves margin in ledger.
6. **Dynamic Brackets + Reverse Side (Short) + reduceOnly**: Short entry order (`SELL`) dispatches TP (`BUY` at $-2.0\times$ ATR) and SL (`BUY` at $+1.2\times$ ATR) with `reduceOnly=True`.
7. **Cleanup Routine + Selective ID Filter + Non-Interference**: Cleanup routine cancels only orders matching `canary-p311-drill-`, leaving simulated daemon `canary-p310-` orders untouched.
8. **Telemetry DB + Telegram Poller Schema Compatibility**: Telemetry records inserted by drill harness match exact SQLite column schema expected by `scripts/run_telegram_notifier.py`.

---

### Tier 4 — Real-World Workload Scenarios (End-to-End Workflows)
Comprehensive multi-step end-to-end operational workflows (>= 5 scenarios):
1. **Scenario 1: Dry-Run Verification Lifecycle**:
   - Execute CLI with `--symbol SOLUSDT --dry-run`, verify credentials, exchange filters, ATR bracket calculations, zero-drift balance invariant, and Merkle artifact integrity without dispatching network orders.
2. **Scenario 2: Authentic Maker Limit Entry, ATR Brackets & Order Lifecycle**:
   - Dispatch entry Maker Limit order (`GTC`/`GTX`) with deterministic client order ID, simulate/verify fill confirmation, calculate 14-period ATR, and deploy protective TP/SL brackets adhering to 1.66:1 Risk:Reward ratio.
3. **Scenario 3: Complete Execution Drill with Auto-Close & Position Cleanup**:
   - Full drill cycle: Stage order $\rightarrow$ fill order $\rightarrow$ deploy brackets $\rightarrow$ trigger `--cleanup` $\rightarrow$ cancel pending brackets $\rightarrow$ flatten position via `reduceOnly` market order $\rightarrow$ verify net position returns to 0.00.
4. **Scenario 4: Adversarial Micro-Capital & Fail-Closed Guardrails**:
   - Hostile input testing: Notional 10.00 USDT rejected, clock drift 1200 ms rejected, gateway latency 600 ms rejected, Hawkes $\rho \ge 1.0$ blocked, preserving capital solvency.
5. **Scenario 5: Complete End-to-End Cryptographic Audit & Lineage DAG Verification**:
   - Run complete drill session $\rightarrow$ persist SQLite database $\rightarrow$ append JSONL logs $\rightarrow$ export `canary-drill-report.json` and `drill-summary.json` $\rightarrow$ verify cryptographic Merkle DAG chain rooted to Phase 310 upstream parent `0004387045399718c6229d1a18fec40399d4baba01b0eecd0ab51c782268dd84`.

---

## Feature Inventory & Test Mapping

| # | Feature | Requirement Source | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---------|-------------------|:------:|:------:|:------:|:------:|
| 1 | Testnet Execution Drill CLI Harness & Flags | ORIGINAL_REQUEST §R1, PROJECT §Feature 1 | 5 | 5 | ✓ | ✓ |
| 2 | Binance Exchange Filter Validation & Step-Up | ORIGINAL_REQUEST §R1, PROJECT §Feature 2 | 5 | 5 | ✓ | ✓ |
| 3 | Gateway REST Extensions & Signed Dispatch | ORIGINAL_REQUEST §R1, PROJECT §Feature 3, 4 | 5 | 5 | ✓ | ✓ |
| 4 | Dynamic ATR-Based Protective Brackets | ORIGINAL_REQUEST §R2, PROJECT §Feature 5 | 5 | 5 | ✓ | ✓ |
| 5 | Real-Time Multi-Channel Telegram Alerting | ORIGINAL_REQUEST §R3, PROJECT §Feature 8 | 5 | 5 | ✓ | ✓ |
| 6 | CentralizedSolvencyLedger Zero-Drift Balance | ORIGINAL_REQUEST §R4, PROJECT §Feature 9 | 5 | 5 | ✓ | ✓ |
| 7 | Cryptographic Merkle DAG Telemetry | ORIGINAL_REQUEST §R4, PROJECT §Feature 10, 11 | 5 | 5 | ✓ | ✓ |
| 8 | Non-Disruptive Cleanup & VPS Protection | ORIGINAL_REQUEST §R2, R5, PROJECT §Feature 7, 13 | 5 | 5 | ✓ | ✓ |

---

## Test Architecture & Execution

### Test Suite Location
- Integration Test Suite: `tests/integration/test_phase_311_testnet_harness.py`
- Targeted Unit Tests: `tests/unit/test_phase_311_execution_drill.py`

### Test Runner Command
```bash
.venv/Scripts/python -m pytest tests/integration/test_phase_311_testnet_harness.py -v
```

### Coverage Thresholds
- **Tier 1**: $\ge 40$ feature tests (8 features $\times \ge 5$ tests)
- **Tier 2**: $\ge 30$ boundary and corner tests
- **Tier 3**: $\ge 15$ pairwise interaction tests
- **Tier 4**: $\ge 5$ real-world workload scenario tests
- **Total Minimum Target**: $\ge 90$ test cases with 100% pass rate (0 failures).
