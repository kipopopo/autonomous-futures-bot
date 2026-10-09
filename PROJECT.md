# Project: Autonomous Futures Bot — Phase 311

## Architecture
Phase 311 establishes a dedicated, non-disruptive End-to-End Synthetic Execution Drill & Verification Harness on Binance Futures Testnet for Autonomous Futures Bot. The harness provides an authentic signed micro maker limit order dispatch CLI, automated protective bracket Take-Profit (+2.0x ATR) and Stop-Loss (-1.2x ATR) management, real-time multi-channel Telegram alerts, mathematical double-entry zero-drift balance governance ($|\Delta| < 10^{-15}$ USDT), and cryptographic Merkle DAG telemetry rooted to Phase 310, all operating with zero interference to the running 24/7 daemon on Kainode VPS.

```
+-----------------------------------------------------------------------------------+
|                        Phase 311 Execution Drill Harness CLI                      |
|                  scripts/run_testnet_execution_drill.py                           |
|  - Flags: --symbol, --side, --notional, --dry-run, --cleanup, --verify-only       |
|  - Micro-Capital Bounds: child <= 5.00 USDT, aggregate <= 25.00, daily loss <= 3.00|
|  - Precision Quantization: LOT_SIZE (ROUND_DOWN), PRICE_FILTER (ROUND_HALF_UP)    |
|  - Binance Filter Compliance: MIN_NOTIONAL step-up (+1 step size tolerance)       |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                     BinanceFuturesGateway & Drill Engine                          |
|  - Dual-mode: Testnet (REST https://testnet.binancefuture.com) / Dry-Run Mock     |
|  - HMAC-SHA256 signature generator & monotonic nonce                              |
|  - Clock drift sync (|dt| <= 1000ms) & Heartbeat latency (<= 500ms)               |
|  - Client Order ID Partitioning: canary-p311-drill-{sym[:3]}-{ts} (<= 36 chars)   |
|  - Methods: create_order, cancel_order, get_order, get_open_orders, positionRisk  |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                    Dynamic Bracket & Position Lifecycle Manager                   |
|  - Entry Order: Maker Limit (GTC / GTX) at sweep price / best bid                 |
|  - ATR Engine: 14-period ATR calculated from 15m klines                           |
|  - Take-Profit Bracket: +2.0x ATR (Limit / TAKE_PROFIT_MARKET, reduceOnly=True)   |
|  - Stop-Loss Bracket: -1.2x ATR (STOP_MARKET, reduceOnly=True)                    |
|  - Risk:Reward Ratio: Strict 1.66:1 (2.0 / 1.2 = 1.6667)                          |
|  - Cleanup Routine: Selective cancel of drill brackets & reduceOnly market flatten|
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                   CentralizedSolvencyLedger & Zero-Drift Invariant                |
|  - Double-Entry Invariant: Cash + Margin + UnrealizedPnL == Equity + RealizedPnL   |
|  - Absolute Drift Tolerance: |drift| == 0.00 < 10^-15 USDT                        |
|  - Continuous verification at Order Staging, Fill, Bracket, and Cleanup Flatten   |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                 Telemetry Persistence, Merkle DAG & Telegram Alerting             |
|  - SQLite: artifacts/research/phase311/canary-lifecycle-telemetry.sqlite3         |
|  - Audit Log: artifacts/research/phase311/canary-orders.jsonl                     |
|  - Structured Reports: canary-drill-report.json & drill-summary.json              |
|  - Merkle Root Chaining: Linked to Phase 310 root:                                |
|    0004387045399718c6229d1a18fec40399d4baba01b0eecd0ab51c782268dd84              |
|  - Telegram Alerts: TelegramNotifierClient MarkdownV2 alerts for Entry, Fill,     |
|    Brackets, and Cleanup Flattening                                               |
|  - VPS Daemon Non-Interference: NEVER delete listenKey, NEVER delete allOpenOrders|
+-----------------------------------------------------------------------------------+
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Testnet Execution Drill CLI Harness | CLI `scripts/run_testnet_execution_drill.py` with `--symbol`, `--side`, `--notional`, `--dry-run`, `--cleanup`/`--auto-close`, `--verify-only` | M3 | R1 |
| 2 | Binance Exchange Filter Validation & Step-Up | Validate `LOT_SIZE`, `PRICE_FILTER`, `MIN_NOTIONAL` with `ROUND_DOWN` quantization and single step size step-up allowance | M1 | R1 |
| 3 | Gateway REST Extensions | Implement `get_order`, `get_open_orders`, `cancel_all_orders` (selective), and `TAKE_PROFIT_MARKET` in `BinanceFuturesGateway` | M1 | R2 |
| 4 | Authentic HMAC-SHA256 Signed Order Dispatch | Authenticated `POST /fapi/v1/order` for Maker Limit entry (`GTC`/`GTX`) with fallback mock simulation | M1 | R2 |
| 5 | Dynamic ATR-Based Bracket Management | Compute 14-period ATR from 15m klines; submit +2.0x ATR TP and -1.2x ATR SL (1.66:1 R:R) | M1 | R2 |
| 6 | Deterministic Client Order ID Generation | Format `canary-p311-drill-{sym[:3]}-{ts}` strictly bounded to <= 36 characters | M1 | R2, R3 |
| 7 | Non-Disruptive Cleanup & Position Flattening | Selectively cancel drill brackets and flatten drill test position without affecting VPS daemon | M1 | R2, R5 |
| 8 | Multi-Channel Telegram Alerting | Instant MarkdownV2 alerts for order submission, fill confirmation, bracket establishment, and PnL exit | M2 | R3 |
| 9 | Double-Entry Zero-Drift Ledger Governance | Reconcile `Cash + Margin + Unrealized PnL == Equity + Realized PnL` maintaining $|\Delta| < 10^{-15}$ USDT | M2 | R4 |
| 10 | Real-Time Telemetry Persistence | Store in SQLite `canary-lifecycle-telemetry.sqlite3`, `canary-orders.jsonl`, and `canary-drill-report.json` | M2 | R4 |
| 11 | Cryptographic Merkle DAG Chaining | Chain Phase 311 artifacts to Phase 310 upstream root `0004387045399718c6229d1a18fec40399d4baba01b0eecd0ab51c782268dd84` | M2 | R4 |
| 12 | Micro-Capital & Fail-Closed Guardrails | Child cap <= 5.00 USDT, aggregate exposure <= 25.00 USDT, daily loss ceiling <= 3.00 USDT, heartbeat <= 500 ms, clock skew <= 1000 ms | M3 | R5 |
| 13 | Kainode VPS Daemon Non-Interference Guarantee | Isolated client order IDs, separate process space, no listenKey deletion, no global order cancellation | M3 | R5 |
| 14 | 4-Tier Comprehensive E2E Verification Suite | Pytest suite covering CLI flags, bracket math, Telegram dispatch, zero-drift balance, and quality gates | M4 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Gateway REST Extensions, Bracket Engine & Drill Core | `src/autonomous_futures/execution/binance_gateway.py`, `src/autonomous_futures/feed/execution_drill.py`, exchange filters, dynamic ATR bracket calculations, position cleanup | none | DONE |
| M2 | Telegram Alerts, Zero-Drift Ledger & Merkle DAG Telemetry | `src/autonomous_futures/notify/telegram.py` alerts, `CentralizedSolvencyLedger` balance governance, SQLite & JSONL persistence, Merkle DAG chaining | M1 | DONE |
| M3 | Testnet Execution Drill CLI & Guardrails | `scripts/run_testnet_execution_drill.py`, CLI arguments, micro-capital bounds, fail-closed guards, VPS non-interference | M1, M2 | DONE |
| M4 | Comprehensive E2E Test Suite, Adversarial Hardening & Final Gate | `tests/unit/test_phase_311_execution_drill.py`, `tests/integration/test_phase_311_testnet_harness.py`, 4 tiers of tests, ruff, mypy, audit | M1, M2, M3 | DONE |

## Interface Contracts

### BinanceFuturesGateway Extensions
```python
class BinanceFuturesGateway:
    async def get_order(self, symbol: str, order_id: Optional[int] = None, client_order_id: Optional[str] = None) -> Dict[str, Any]: ...
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]: ...
    async def cancel_all_open_orders(self, symbol: str) -> Dict[str, Any]: ...
    def generate_drill_client_order_id(self, symbol: str, ts_ms: Optional[int] = None, role: str = "drill") -> str:
        """Returns deterministic client order ID <= 36 characters: canary-p311-{role}-{sym[:3]}-{timestamp_ms}."""
```

### ExecutionDrillEngine ↔ CLI & Telemetry
```python
class ExecutionDrillEngine:
    def __init__(self, gateway: BinanceFuturesGateway, ledger: DrillSolvencyLedger, storage_dir: Path, config: DrillConfig): ...
    async def execute_drill(self) -> DrillReport: ...
    async def cleanup_drill_orders(self, symbol: str, bracket_cids: List[str]) -> Dict[str, Any]: ...
    def verify_artifacts(self) -> bool: ...
```

### CentralizedSolvencyLedger Balance Invariant
```python
# Absolute Zero-Drift Balance Equation:
# drift = abs((cash + allocated_margin + unrealized_pnl) - (starting_equity + realized_pnl))
# assert drift < Decimal("1e-15")
```

## Code Layout
- `src/autonomous_futures/execution/binance_gateway.py`: Binance Futures dual-mode REST gateway with query and bracket extensions.
- `src/autonomous_futures/feed/execution_drill.py`: Core execution drill harness, filter step-up, ATR bracket engine, and position cleanup.
- `src/autonomous_futures/notifications/__init__.py`: Package compatibility shim redirecting to `autonomous_futures.notify`.
- `scripts/run_testnet_execution_drill.py`: Dedicated CLI entry point.
- `artifacts/research/phase311/`: Phase 311 telemetry, JSONL audit logs, drill report, and Merkle root summary.
- `tests/unit/test_phase_311_execution_drill.py`: Targeted unit and bracket computation tests.
- `tests/integration/test_phase_311_testnet_harness.py`: Opaque-box E2E integration drill tests (90 tests).
- `tests/integration/test_phase_311_adversarial_challenge.py`: Adversarial guardrail challenge tests (13 tests).
- `tests/integration/test_phase_311_empirical_challenger.py`: Empirical solvency stress tests (10 tests).
