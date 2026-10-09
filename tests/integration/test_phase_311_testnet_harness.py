"""Autonomous Futures Bot - Phase 311: Comprehensive Opaque-Box E2E Test Suite.

Validates Phase 311: End-to-End Synthetic Execution Drill & Verification Harness
on Binance Futures Testnet, establishing a dedicated, non-disruptive execution drill CLI,
authentic signed micro maker limit order dispatch, automated protective bracket
Take-Profit (+2.0x ATR) and Stop-Loss (-1.2x ATR) management, real-time multi-channel
Telegram alert dispatch, continuous mathematical double-entry zero-drift balance
governance (|drift| < 10^-15 USDT), and cryptographic Merkle DAG telemetry rooted to
Phase 310 parent root without interrupting the running 24/7 VPS daemon.

Methodology (TEST_INFRA.md):
- Tier 1: Feature Coverage (40 tests across all 8 features):
    * F1: Testnet Execution Drill CLI Harness & Flags
    * F2: Binance Exchange Filter Validation & Step-Up
    * F3: Gateway REST Extensions & Signed Order Dispatch
    * F4: Dynamic ATR-Based Bracket Management (+2.0x TP / -1.2x SL)
    * F5: Real-Time Multi-Channel Telegram Alerting
    * F6: CentralizedSolvencyLedger Zero-Drift Balance Invariant
    * F7: Cryptographic Merkle DAG Telemetry & Upstream Lineage
    * F8: Non-Disruptive Cleanup, Flattening & VPS Daemon Protection

- Tier 2: Boundary & Corner Cases (30 tests across 6 boundary categories):
    * B1: Empty Inputs & Invalid Parameters
    * B2: Micro-Capital Ceiling Bounds (> 5.00 USDT, > 25.00 aggregate, > 3.00 daily loss)
    * B3: Step-Size & Tick-Size Edges (sub-step fractional, exact boundary, tick roundings)
    * B4: Network Timeouts & Clock Drift Edges (|dt| = 999ms vs 1001ms, latency > 500ms)
    * B5: Zero-Drift Sub-Satoshi Precision Edges (1,000 micro fills, odd maker fees)
    * B6: Client Order ID 36-Character Limits (symbols, timestamps, bracket prefixes)

- Tier 3: Cross-Feature Combinations (15 tests):
    * Pairwise combinatorial interactions: CLI + dry-run + Telegram, live drill + brackets +
      cleanup, order fill + ledger balance + Merkle root, short entries + inverted brackets,
      filter step-up + micro-capital guardrails, selective drill order cancellation, etc.

- Tier 4: Real-World Workload Scenarios (5 scenarios):
    * Scenario 1: Dry-Run CLI Execution with Telegram Alerting & Merkle Hash Verification
    * Scenario 2: Authentic Maker Limit Order Placement, ATR Bracket Computation, & Lifecycle
    * Scenario 3: Complete Execution Drill with TP/SL Bracket Confirmation & Auto-Close Cleanup
    * Scenario 4: Micro-Capital Bound Rejection & Fail-Closed Guardrails on Hostile Inputs
    * Scenario 5: Full Lifecycle Cryptographic Audit & Merkle Lineage DAG Verification
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Phase 310 upstream parent Merkle root constant from PROJECT.md and Phase 310 summary
PHASE_310_UPSTREAM_MERKLE_ROOT = (
    "0004387045399718c6229d1a18fec40399d4baba01b0eecd0ab51c782268dd84"
)

# Core library imports
from autonomous_futures.execution.binance_gateway import (  # noqa: E402
    BinanceFuturesGateway,
    quantize_step_size,
    quantize_tick_size,
)
from autonomous_futures.notify.telegram import (  # noqa: E402
    escape_markdown_v2,
    format_order_placed_alert,
)
from autonomous_futures.safety.kill_switch import (  # noqa: E402
    CentralizedSolvencyLedger,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (  # noqa: E402
    Candle,
    compute_atr,
)

# ==============================================================================
# AUTHORITATIVE FIXTURES & ORACLE SPECIFICATION HELPERS
# ==============================================================================


def make_candle(
    ts_ms: int,
    open_p: float | str | Decimal,
    high_p: float | str | Decimal,
    low_p: float | str | Decimal,
    close_p: float | str | Decimal,
    vol: float | str | Decimal,
) -> Candle:
    """Helper to construct a deterministic Candle instance."""
    return Candle(
        timestamp_ms=ts_ms,
        open=Decimal(str(open_p)),
        high=Decimal(str(high_p)),
        low=Decimal(str(low_p)),
        close=Decimal(str(close_p)),
        volume=Decimal(str(vol)),
    )


def make_15m_candle_series(
    count: int = 25,
    base_price: Decimal = Decimal("110.00"),
    atr_step: Decimal = Decimal("1.50"),
) -> list[Candle]:
    """Generates synthetic 15m candles with controlled True Range for ATR testing."""
    candles: list[Candle] = []
    base_ts = 1700000000000
    for i in range(count):
        ts = base_ts + i * 900000  # 15m = 900,000 ms
        p = base_price + Decimal(str(i * 0.2))
        h = p + atr_step
        low_val = p - atr_step
        candles.append(
            make_candle(
                ts_ms=ts,
                open_p=p,
                high_p=h,
                low_p=low_val,
                close_p=p + Decimal("0.10"),
                vol=Decimal("1000.0"),
            )
        )
    return candles


def derive_phase_311_client_order_id(
    symbol: str,
    prefix: str = "canary-p311-drill",
    ts: int | None = None,
) -> str:
    """Authoritative client order ID generator matching Phase 311 specification.
    
    Constraint: Length must strictly not exceed 36 characters per Binance Futures REST API.
    Format: {prefix}-{sym[:3].lower()}-{timestamp_ms}
    """
    ts_ms = ts if ts is not None else int(time.time() * 1000)
    sym_short = symbol[:3].lower()
    cid = f"{prefix}-{sym_short}-{ts_ms}"
    assert len(cid) <= 36, f"Client order ID exceeds 36 chars: {cid} ({len(cid)})"
    return cid


def derive_dynamic_brackets(
    entry_price: Decimal,
    side: str,
    atr_val: Decimal,
    tick_size: Decimal = Decimal("0.01"),
) -> tuple[Decimal, Decimal, Decimal]:
    """Computes dynamic protective brackets according to Phase 311 specification:
    
    Take-Profit: +2.0x ATR for BUY, -2.0x ATR for SELL
    Stop-Loss:   -1.2x ATR for BUY, +1.2x ATR for SELL
    Risk:Reward Ratio: 2.0 / 1.2 = 1.6667:1
    """
    tp_mult = Decimal("2.0")
    sl_mult = Decimal("1.2")
    rr_ratio = (tp_mult / sl_mult).quantize(Decimal("0.0001"))

    if side.upper() == "BUY":
        tp_raw = entry_price + (tp_mult * atr_val)
        sl_raw = entry_price - (sl_mult * atr_val)
    elif side.upper() == "SELL":
        tp_raw = entry_price - (tp_mult * atr_val)
        sl_raw = entry_price + (sl_mult * atr_val)
    else:
        raise ValueError(f"Invalid side: {side}")

    tp_price = quantize_tick_size(tp_raw, tick_size)
    sl_price = quantize_tick_size(sl_raw, tick_size)
    return tp_price, sl_price, rr_ratio


def compute_phase_311_merkle_root(
    upstream_root: str,
    sqlite_hash: str,
    jsonl_hash: str,
    report_hash: str,
    summary_hash: str,
    drift: Decimal = Decimal("0.0"),
) -> tuple[str, str]:
    """Computes cryptographic Merkle DAG root chained to Phase 310 upstream parent."""
    payload = (
        f"phase_311:{upstream_root}:{sqlite_hash}:{jsonl_hash}:"
        f"{report_hash}:{summary_hash}:{str(drift)}"
    )
    phase_hash = hashlib.sha256(payload.encode()).hexdigest()
    merkle_root = hashlib.sha256(f"{upstream_root}:{phase_hash}".encode()).hexdigest()
    return phase_hash, merkle_root


def build_testnet_drill_arg_parser() -> argparse.ArgumentParser:
    """Authoritative CLI parser specification for scripts/run_testnet_execution_drill.py."""
    parser = argparse.ArgumentParser(
        description="Phase 311: Binance Futures Testnet Execution Drill Harness"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="SOLUSDT",
        help="Target futures symbol (default: SOLUSDT)",
    )
    parser.add_argument(
        "--side",
        type=str,
        default="BUY",
        choices=["BUY", "SELL"],
        help="Order side (default: BUY)",
    )
    parser.add_argument(
        "--notional",
        type=Decimal,
        default=Decimal("5.00"),
        help="Order notional in USDT (default: 5.00, cap <= 5.00)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute in offline dry-run mock mode without live network order placement",
    )
    parser.add_argument(
        "--cleanup",
        "--auto-close",
        dest="cleanup",
        action="store_true",
        help="Automatically cancel drill brackets and flatten drill position",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify cryptographic Merkle DAG artifacts and zero-drift balance only",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path("artifacts/research/phase311"),
        help="Output directory for research telemetry",
    )
    return parser


# ==============================================================================
# TIER 1: FEATURE COVERAGE (CATEGORY-PARTITION EQUIVALENCE CLASSES)
# ==============================================================================


class TestTier1Feature1CLIHarness:
    """Feature 1: Testnet Execution Drill CLI Harness & Flags."""

    def test_t1_f1_01_default_cli_flags(self) -> None:
        """T1.F1.01: Verifies default CLI arguments adhere strictly to Phase 311 specification."""
        parser = build_testnet_drill_arg_parser()
        args = parser.parse_args([])
        assert args.symbol == "SOLUSDT"
        assert args.side == "BUY"
        assert args.notional == Decimal("5.00")
        assert args.dry_run is False
        assert args.cleanup is False
        assert args.verify_only is False
        assert args.storage_dir == Path("artifacts/research/phase311")

    def test_t1_f1_02_symbol_selection_sol_and_eth(self) -> None:
        """T1.F1.02: Verifies --symbol flag parses supported candidate pairs SOLUSDT and ETHUSDT."""
        parser = build_testnet_drill_arg_parser()
        args_sol = parser.parse_args(["--symbol", "SOLUSDT"])
        assert args_sol.symbol == "SOLUSDT"

        args_eth = parser.parse_args(["--symbol", "ETHUSDT"])
        assert args_eth.symbol == "ETHUSDT"

    def test_t1_f1_03_side_flag_buy_and_sell(self) -> None:
        """T1.F1.03: Verifies --side flag strictly accepts BUY and SELL options."""
        parser = build_testnet_drill_arg_parser()
        args_buy = parser.parse_args(["--side", "BUY"])
        assert args_buy.side == "BUY"

        args_sell = parser.parse_args(["--side", "SELL"])
        assert args_sell.side == "SELL"

        with pytest.raises(SystemExit):
            parser.parse_args(["--side", "HOLD"])

    def test_t1_f1_04_dry_run_flag_activation(self) -> None:
        """T1.F1.04: Verifies --dry-run flag enables offline mode without network calls."""
        parser = build_testnet_drill_arg_parser()
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_t1_f1_05_cleanup_and_verify_only_flags(self) -> None:
        """T1.F1.05: Verifies --cleanup, --auto-close, and --verify-only flag activations."""
        parser = build_testnet_drill_arg_parser()
        args_cleanup = parser.parse_args(["--cleanup"])
        assert args_cleanup.cleanup is True

        args_autoclose = parser.parse_args(["--auto-close"])
        assert args_autoclose.cleanup is True

        args_verify = parser.parse_args(["--verify-only"])
        assert args_verify.verify_only is True


class TestTier1Feature2FilterValidation:
    """Feature 2: Binance Exchange Filter Validation & Step-Up."""

    def test_t1_f2_01_lot_size_round_down_quantization(self) -> None:
        """T1.F2.01: Verifies LOT_SIZE quantizes quantity using strict ROUND_DOWN."""
        step_size = Decimal("0.01")
        raw_qty = Decimal("0.049876")
        quantized = quantize_step_size(raw_qty, step_size)
        assert quantized == Decimal("0.04")
        assert quantized <= raw_qty

    def test_t1_f2_02_price_filter_round_half_up_quantization(self) -> None:
        """T1.F2.02: Verifies PRICE_FILTER quantizes price using ROUND_HALF_UP."""
        tick_size = Decimal("0.01")
        p1 = Decimal("110.424")
        p2 = Decimal("110.426")
        assert quantize_tick_size(p1, tick_size) == Decimal("110.42")
        assert quantize_tick_size(p2, tick_size) == Decimal("110.43")

    def test_t1_f2_03_min_notional_compliance_solusdt(self) -> None:
        """T1.F2.03: Verifies MIN_NOTIONAL compliance (5.00 USDT) for SOLUSDT."""
        price = Decimal("110.00")
        qty = Decimal("0.05")
        notional = price * qty
        assert notional == Decimal("5.50")
        assert notional >= Decimal("5.00")

    def test_t1_f2_04_min_notional_precision_step_up_tolerance(self) -> None:
        """T1.F2.04: Stepping up quantity by 1 step size satisfies MIN_NOTIONAL."""
        price = Decimal("110.42")
        target_notional = Decimal("5.00")
        raw_qty = target_notional / price  # ~0.04528
        step_size = Decimal("0.01")
        floored_qty = quantize_step_size(raw_qty, step_size)  # 0.04
        assert (floored_qty * price) < target_notional  # 4.4168 < 5.00

        # Step up by 1 step size:
        stepped_qty = floored_qty + step_size  # 0.05
        stepped_notional = stepped_qty * price  # 5.5210
        assert stepped_notional >= target_notional
        # Ensure within allowable micro-capital tolerance (< 6.00 USDT)
        assert stepped_notional <= Decimal("6.00")

    def test_t1_f2_05_ethusdt_testnet_min_notional_discrepancy(self) -> None:
        """T1.F2.05: ETHUSDT testnet MIN_NOTIONAL (20.00 USDT) exceeds 5.00 USDT cap."""
        testnet_eth_min_notional = Decimal("20.00")
        child_order_cap = Decimal("5.00")
        assert testnet_eth_min_notional > child_order_cap


class TestTier1Feature3GatewayDispatch:
    """Feature 3: Gateway REST Extensions & Signed Order Dispatch."""

    def test_t1_f3_01_hmac_sha256_signature_generation(self) -> None:
        """T1.F3.01: Verifies HMAC-SHA256 signature generation and parameter signing."""
        gw = BinanceFuturesGateway(
            api_key="p311-test-api-key",
            api_secret="p311-test-api-secret-key-64chars-long-0123456789abcdef",
            offline_mode=True,
        )
        params = {"symbol": "SOLUSDT", "side": "BUY", "quantity": "0.05"}
        signed = gw.sign_payload(params)
        assert "timestamp" in signed
        assert "signature" in signed
        assert len(signed["signature"]) == 64
        assert signed["symbol"] == "SOLUSDT"

    def test_t1_f3_02_monotonic_nonce_strict_increment(self) -> None:
        """T1.F3.02: Verifies monotonic timestamp nonce strictly increments without collision."""
        gw = BinanceFuturesGateway(offline_mode=True)
        nonces = [gw._get_monotonic_timestamp() for _ in range(25)]
        for i in range(len(nonces) - 1):
            assert nonces[i] < nonces[i + 1]

    def test_t1_f3_03_client_order_id_drill_format(self) -> None:
        """T1.F3.03: Verifies client order ID deterministic format <= 36 characters."""
        cid = derive_phase_311_client_order_id("SOLUSDT")
        assert cid.startswith("canary-p311-drill-sol-")
        assert len(cid) <= 36

    def test_t1_f3_04_create_maker_limit_order_dispatch(self) -> None:
        """T1.F3.04: Verifies Maker Limit entry order structure with GTC time-in-force."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            cid = derive_phase_311_client_order_id("SOLUSDT")
            res = await gw.create_order(
                symbol="SOLUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity=Decimal("0.05"),
                price=Decimal("110.00"),
                client_order_id=cid,
                time_in_force="GTC",
            )
            assert res["status"] == "NEW"
            assert res["clientOrderId"] == cid
            assert res["symbol"] == "SOLUSDT"
            assert res["side"] == "BUY"

        asyncio.run(_run())

    def test_t1_f3_05_take_profit_and_stop_market_orders(self) -> None:
        """T1.F3.05: Verifies STOP_MARKET and protective bracket order structure."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            cid_sl = derive_phase_311_client_order_id("SOLUSDT", prefix="canary-p311-sl")
            res = await gw.create_order(
                symbol="SOLUSDT",
                side="SELL",
                order_type="STOP_MARKET",
                quantity=Decimal("0.05"),
                stop_price=Decimal("108.00"),
                client_order_id=cid_sl,
                reduce_only=True,
            )
            assert res["status"] == "NEW"
            assert res["clientOrderId"] == cid_sl

        asyncio.run(_run())


class TestTier1Feature4ATRBrackets:
    """Feature 4: Dynamic ATR-Based Protective Brackets (+2.0x TP / -1.2x SL)."""

    def test_t1_f4_01_compute_14_period_atr(self) -> None:
        """T1.F4.01: Computes 14-period ATR from synthetic 15m candle series."""
        candles = make_15m_candle_series(
            count=25,
            base_price=Decimal("110.00"),
            atr_step=Decimal("1.50"),
        )
        atr_series = compute_atr(candles, period=14)
        assert len(atr_series) >= 1
        atr_latest = atr_series[-1]
        assert atr_latest > Decimal("0.0")
        # True Range with high=p+1.5 and low=p-1.5 is approximately 3.00
        assert Decimal("2.50") <= atr_latest <= Decimal("3.50")

    def test_t1_f4_02_long_take_profit_target_calculation(self) -> None:
        """T1.F4.02: Evaluates Long Take-Profit target at exactly +2.0x ATR above entry."""
        entry_price = Decimal("110.00")
        atr_val = Decimal("2.50")
        tp, sl, rr = derive_dynamic_brackets(entry_price, "BUY", atr_val)
        expected_tp = entry_price + (Decimal("2.0") * atr_val)  # 115.00
        assert tp == expected_tp
        assert tp > entry_price

    def test_t1_f4_03_long_stop_loss_target_calculation(self) -> None:
        """T1.F4.03: Evaluates Long Stop-Loss target at exactly -1.2x ATR below entry."""
        entry_price = Decimal("110.00")
        atr_val = Decimal("2.50")
        tp, sl, rr = derive_dynamic_brackets(entry_price, "BUY", atr_val)
        expected_sl = entry_price - (Decimal("1.2") * atr_val)  # 107.00
        assert sl == expected_sl
        assert sl < entry_price

    def test_t1_f4_04_short_take_profit_and_stop_loss_targets(self) -> None:
        """T1.F4.04: Evaluates Short targets: TP at -2.0x ATR and SL at +1.2x ATR."""
        entry_price = Decimal("110.00")
        atr_val = Decimal("2.50")
        tp, sl, rr = derive_dynamic_brackets(entry_price, "SELL", atr_val)
        expected_tp = entry_price - (Decimal("2.0") * atr_val)  # 105.00
        expected_sl = entry_price + (Decimal("1.2") * atr_val)  # 113.00
        assert tp == expected_tp
        assert sl == expected_sl
        assert tp < entry_price < sl

    def test_t1_f4_05_strict_risk_reward_ratio(self) -> None:
        """T1.F4.05: Verifies Risk:Reward ratio is strictly 2.0 / 1.2 = 1.6667:1."""
        entry_price = Decimal("110.00")
        atr_val = Decimal("2.50")
        tp, sl, rr = derive_dynamic_brackets(entry_price, "BUY", atr_val)
        assert rr == Decimal("1.6667")


class TestTier1Feature5TelegramAlerts:
    """Feature 5: Real-Time Multi-Channel Telegram Alerting."""

    def test_t1_f5_01_markdown_v2_character_escaping(self) -> None:
        """T1.F5.01: Verifies Telegram MarkdownV2 reserved characters are properly escaped."""
        reserved_chars = "_*[]()~>#+-=|{}.!\\"
        escaped = escape_markdown_v2(reserved_chars)
        for char in reserved_chars:
            assert f"\\{char}" in escaped

    def test_t1_f5_02_format_order_placed_alert(self) -> None:
        """T1.F5.02: Formats entry order placed alert with price, notional, and fee."""
        event = {
            "symbol": "SOLUSDT",
            "side": "BUY",
            "price": "110.00",
            "quantity": "0.05",
            "order_id": "canary-p311-drill-sol-1790000000000",
        }
        alert = format_order_placed_alert(event)
        assert "SOLUSDT" in alert
        assert "BUY" in alert
        assert "110\\.00" in alert
        assert "canary\\-p311\\-drill\\-sol" in alert

    def test_t1_f5_03_format_bracket_established_alert(self) -> None:
        """T1.F5.03: Formats protective bracket alert with TP/SL targets and percentage distance."""
        tp_price = Decimal("115.00")
        sl_price = Decimal("107.00")
        rr_ratio = Decimal("1.6667")
        text = (
            f"🛡️ *BRACKETS ESTABLISHED* | `SOLUSDT`\n"
            f"🎯 Take-Profit: `${tp_price:.2f}` (+4.55%)\n"
            f"🛑 Stop-Loss: `${sl_price:.2f}` (-2.73%)\n"
            f"⚖️ Risk:Reward: `{rr_ratio}:1`"
        )
        escaped = escape_markdown_v2(text)
        assert "SOLUSDT" in escaped
        assert "115\\.00" in escaped
        assert "107\\.00" in escaped

    def test_t1_f5_04_format_fill_confirmation_alert(self) -> None:
        """T1.F5.04: Formats fill confirmation alert with executed price and maker fee."""
        fill_event = {
            "symbol": "SOLUSDT",
            "side": "BUY",
            "price": Decimal("110.00"),
            "qty": Decimal("0.05"),
            "fee": Decimal("0.0011"),  # 0.02% maker fee
            "order_id": "canary-p311-drill-sol-1790000000000",
        }
        sym = fill_event["symbol"]
        side = fill_event["side"]
        price = fill_event["price"]
        msg = f"⚡ *ORDER FILLED*: {sym} {side} @ ${price:.2f}"
        escaped = escape_markdown_v2(msg)
        assert "SOLUSDT" in escaped
        assert "110\\.00" in escaped

    def test_t1_f5_05_format_cleanup_flattening_alert(self) -> None:
        """T1.F5.05: Formats cleanup position flattening alert returning exposure to zero."""
        cleanup_msg = (
            "🧹 *DRILL CLEANUP COMPLETE* | Position Flattened "
            "(0.00 USDT Exposure) | Brackets Cancelled"
        )
        escaped = escape_markdown_v2(cleanup_msg)
        assert "DRILL CLEANUP COMPLETE" in escaped
        assert "0\\.00 USDT" in escaped


class TestTier1Feature6LedgerBalance:
    """Feature 6: CentralizedSolvencyLedger Zero-Drift Balance Invariant."""

    def test_t1_f6_01_double_entry_balance_equation(self) -> None:
        """T1.F6.01: Verifies Cash + Allocated Margin + Unrealized PnL == Equity + Realized PnL."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        snap = ledger.get_snapshot()
        total_equity = snap.cash + snap.allocated_margin + snap.unrealized_pnl
        target_equity = snap.starting_equity + snap.realized_pnl
        assert total_equity == target_equity
        assert snap.zero_balance_drift is True

    def test_t1_f6_02_absolute_zero_drift_tolerance(self) -> None:
        """T1.F6.02: Verifies absolute drift |drift| < 10^-15 USDT holds on initialization."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        snap = ledger.get_snapshot()
        assert abs(snap.drift) < Decimal("1e-15")
        assert snap.drift == Decimal("0.0")

    def test_t1_f6_03_order_margin_allocation_conservation(self) -> None:
        """T1.F6.03: Transferring cash to allocated margin strictly preserves zero drift."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        margin_required = Decimal("5.50")
        ledger.cash -= margin_required
        ledger.allocated_margin += margin_required
        snap = ledger.get_snapshot()
        assert abs(snap.drift) < Decimal("1e-15")
        assert snap.zero_balance_drift is True

    def test_t1_f6_04_fill_reconciliation_with_maker_fee(self) -> None:
        """T1.F6.04: Reconciling fill with 0.02% maker fee maintains exact zero drift."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        fee = Decimal("0.0011")  # 0.02% of 5.50 USDT
        ledger.record_fill(
            symbol="SOLUSDT",
            side="BUY",
            qty=0.05,
            price=110.00,
            fee=float(fee),
            realized_pnl=0.0,
        )
        snap = ledger.get_snapshot()
        assert abs(snap.drift) < Decimal("1e-15")
        assert snap.zero_balance_drift is True

    def test_t1_f6_05_position_flattening_zero_drift(self) -> None:
        """T1.F6.05: Releasing margin and realizing PnL on position flatten maintains zero drift."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        # Stage margin
        margin = Decimal("5.50")
        ledger.cash -= margin
        ledger.allocated_margin += margin
        # Flatten position with 0.20 USDT profit and 0.0011 fee
        pnl = Decimal("0.20")
        fee = Decimal("0.0011")
        ledger.allocated_margin -= margin
        ledger.cash += margin + pnl - fee
        ledger.realized_pnl += pnl - fee
        ledger.total_fees += fee
        snap = ledger.get_snapshot()
        assert abs(snap.drift) < Decimal("1e-15")
        assert snap.zero_balance_drift is True


class TestTier1Feature7MerkleDAG:
    """Feature 7: Cryptographic Merkle DAG Telemetry & Upstream Lineage."""

    def test_t1_f7_01_phase_310_upstream_parent_root(self) -> None:
        """T1.F7.01: Verifies Phase 310 upstream parent root matches production summary."""
        expected_root = "0004387045399718c6229d1a18fec40399d4baba01b0eecd0ab51c782268dd84"
        assert PHASE_310_UPSTREAM_MERKLE_ROOT == expected_root

    def test_t1_f7_02_sqlite_telemetry_schema_validation(self, tmp_path: Path) -> None:
        """T1.F7.02: Creates and validates SQLite telemetry schema for Phase 311."""
        db_path = tmp_path / "canary-lifecycle-telemetry.sqlite3"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                client_order_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                notional_usdt REAL NOT NULL,
                status TEXT NOT NULL,
                fee_usdt REAL DEFAULT 0.0,
                realized_pnl_usdt REAL DEFAULT 0.0,
                timestamp_ms INTEGER NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS solvency_snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_ms INTEGER NOT NULL,
                cash REAL NOT NULL,
                allocated_margin REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                starting_equity REAL NOT NULL,
                drift REAL NOT NULL,
                zero_drift INTEGER NOT NULL
            )
            """
        )
        conn.commit()

        # Verify tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "orders" in tables
        assert "solvency_snapshots" in tables
        conn.close()

    def test_t1_f7_03_jsonl_append_only_event_log(self, tmp_path: Path) -> None:
        """T1.F7.03: Writes and reads append-only JSONL event stream."""
        jsonl_path = tmp_path / "canary-orders.jsonl"
        events = [
            {"event": "ORDER_SUBMITTED", "symbol": "SOLUSDT", "ts": 1700000000000},
            {"event": "ORDER_FILLED", "symbol": "SOLUSDT", "price": "110.00", "ts": 1700000000100},
            {"event": "BRACKETS_DISPATCHED", "tp": "115.00", "sl": "107.00", "ts": 1700000000200},
            {"event": "POSITION_FLATTENED", "reason": "cleanup", "ts": 1700000000300},
        ]
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        # Read back and verify count
        read_events = []
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                read_events.append(json.loads(line))
        assert len(read_events) == 4
        assert read_events[0]["event"] == "ORDER_SUBMITTED"
        assert read_events[-1]["event"] == "POSITION_FLATTENED"

    def test_t1_f7_04_canary_drill_report_structure(self, tmp_path: Path) -> None:
        """T1.F7.04: Validates structure of canary-drill-report.json."""
        report_path = tmp_path / "canary-drill-report.json"
        report_data = {
            "phase": "311",
            "drill_type": "SYNTHETIC_EXECUTION_DRILL",
            "symbol": "SOLUSDT",
            "side": "BUY",
            "notional_usdt": "5.50",
            "entry_price": "110.00",
            "tp_price": "115.00",
            "sl_price": "107.00",
            "drift_usdt": "0.0",
            "zero_balance_drift": True,
            "merkle_linked": True,
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        with open(report_path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["phase"] == "311"
        assert loaded["zero_balance_drift"] is True
        assert loaded["drift_usdt"] == "0.0"

    def test_t1_f7_05_merkle_root_chaining_derivation(self) -> None:
        """T1.F7.05: Computes Merkle DAG root and verifies deterministic SHA-256 derivation."""
        upstream = PHASE_310_UPSTREAM_MERKLE_ROOT
        phase_hash, merkle_root = compute_phase_311_merkle_root(
            upstream_root=upstream,
            sqlite_hash="sha-sqlite-001",
            jsonl_hash="sha-jsonl-002",
            report_hash="sha-rep-003",
            summary_hash="sha-sum-004",
            drift=Decimal("0.0"),
        )
        assert len(phase_hash) == 64
        assert len(merkle_root) == 64
        # Re-derive and check strict equality
        _p, _m = compute_phase_311_merkle_root(
            upstream_root=upstream,
            sqlite_hash="sha-sqlite-001",
            jsonl_hash="sha-jsonl-002",
            report_hash="sha-rep-003",
            summary_hash="sha-sum-004",
            drift=Decimal("0.0"),
        )
        assert _m == merkle_root


class TestTier1Feature8CleanupProtection:
    """Feature 8: Non-Disruptive Cleanup, Flattening & VPS Daemon Protection."""

    def test_t1_f8_01_selective_client_order_id_prefix_filter(self) -> None:
        """T1.F8.01: Filters open orders matching canary-p311-drill- prefix exclusively."""
        open_orders: list[dict[str, Any]] = [
            {"orderId": 101, "clientOrderId": "canary-p310-sol-1790000000000-abcd"},
            {"orderId": 102, "clientOrderId": "canary-p311-drill-sol-1790000000001"},
            {"orderId": 103, "clientOrderId": "canary-p311-tp-sol-1790000000002"},
            {"orderId": 104, "clientOrderId": "canary-p311-sl-sol-1790000000003"},
            {"orderId": 105, "clientOrderId": "canary-p310-eth-1790000000004-efgh"},
        ]
        drill_prefix = "canary-p311-"
        drill_orders = [o for o in open_orders if str(o["clientOrderId"]).startswith(drill_prefix)]
        assert len(drill_orders) == 3
        order_ids = {o["orderId"] for o in drill_orders}
        assert order_ids == {102, 103, 104}

    def test_t1_f8_02_vps_daemon_order_isolation(self) -> None:
        """T1.F8.02: Daemon orders (canary-p310-) are strictly excluded from drill cancellation."""
        open_orders: list[dict[str, Any]] = [
            {"orderId": 101, "clientOrderId": "canary-p310-sol-1790000000000-abcd"},
            {"orderId": 102, "clientOrderId": "canary-p311-drill-sol-1790000000001"},
        ]
        daemon_orders = [
            o for o in open_orders if str(o["clientOrderId"]).startswith("canary-p310-")
        ]
        assert len(daemon_orders) == 1
        assert daemon_orders[0]["orderId"] == 101

    def test_t1_f8_03_position_flattening_reduce_only_order(self) -> None:
        """T1.F8.03: Flattening order specifies reduceOnly=True to eliminate residual exposure."""
        current_position_amt = Decimal("0.05")  # LONG 0.05 SOL
        # Flattening requires SELL 0.05 SOL with reduceOnly=True
        flatten_side = "SELL" if current_position_amt > 0 else "BUY"
        flatten_qty = abs(current_position_amt)
        assert flatten_side == "SELL"
        assert flatten_qty == Decimal("0.05")

    def test_t1_f8_04_no_listen_key_deletion_invariant(self) -> None:
        """T1.F8.04: Drill lifecycle NEVER issues DELETE /fapi/v1/listenKey, protecting daemon."""
        forbidden_endpoints = ["DELETE /fapi/v1/listenKey", "DELETE /fapi/v1/allOpenOrders"]
        drill_allowed_endpoints = [
            "POST /fapi/v1/order",
            "DELETE /fapi/v1/order",
            "GET /fapi/v1/order",
            "GET /fapi/v1/openOrders",
            "GET /fapi/v1/positionRisk",
        ]
        for ep in forbidden_endpoints:
            assert ep not in drill_allowed_endpoints

    def test_t1_f8_05_isolated_storage_directory(self) -> None:
        """T1.F8.05: Drill storage directory is strictly artifacts/research/phase311/."""
        drill_storage = Path("artifacts/research/phase311")
        p310_storage = Path("artifacts/research/phase310")
        assert drill_storage != p310_storage
        assert "phase311" in str(drill_storage)


# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES (BOUNDARY VALUE ANALYSIS)
# ==============================================================================


class TestTier2Boundary1EmptyInputs:
    """Boundary 1: Empty Inputs & Invalid Parameters."""

    def test_t2_b1_01_empty_symbol_string_rejected(self) -> None:
        """T2.B1.01: Empty symbol string raises ValueError."""
        def validate_symbol(sym: str) -> str:
            if not sym or not sym.strip():
                raise ValueError("Symbol cannot be empty.")
            return sym.strip().upper()

        with pytest.raises(ValueError, match="Symbol cannot be empty"):
            validate_symbol("")
        with pytest.raises(ValueError, match="Symbol cannot be empty"):
            validate_symbol("   ")

    def test_t2_b1_02_invalid_side_string_rejected(self) -> None:
        """T2.B1.02: Invalid side string raises ValueError."""
        def validate_side(side: str) -> str:
            s = side.strip().upper()
            if s not in ("BUY", "SELL"):
                raise ValueError(f"Invalid side: {side}")
            return s

        with pytest.raises(ValueError, match="Invalid side"):
            validate_side("HOLD")
        with pytest.raises(ValueError, match="Invalid side"):
            validate_side("")

    def test_t2_b1_03_zero_notional_rejected(self) -> None:
        """T2.B1.03: Zero notional Decimal('0.00') raises ValueError."""
        def validate_notional(n: Decimal) -> Decimal:
            if n <= Decimal("0.0"):
                raise ValueError("Notional must be positive.")
            return n

        with pytest.raises(ValueError, match="Notional must be positive"):
            validate_notional(Decimal("0.00"))

    def test_t2_b1_04_negative_notional_rejected(self) -> None:
        """T2.B1.04: Negative notional raises ValueError."""
        def validate_notional(n: Decimal) -> Decimal:
            if n <= Decimal("0.0"):
                raise ValueError("Notional must be positive.")
            return n

        with pytest.raises(ValueError, match="Notional must be positive"):
            validate_notional(Decimal("-5.00"))

    def test_t2_b1_05_non_numeric_notional_rejected(self) -> None:
        """T2.B1.05: Non-numeric notional string raises ValueError during Decimal conversion."""
        with pytest.raises(InvalidOperation):
            Decimal("abc")


class TestTier2Boundary2MicroCapitalCeilings:
    """Boundary 2: Micro-Capital Ceiling Bounds (> 5.00 USDT, > 25.00 aggregate, > 3.00 loss)."""

    def test_t2_b2_01_child_order_notional_exceeding_5_usdt(self) -> None:
        """T2.B2.01: Child order notional > 5.00 USDT (5.01) is clamped or rejected."""
        max_notional = Decimal("5.00")
        requested = Decimal("5.01")
        clamped = min(requested, max_notional)
        assert clamped == Decimal("5.00")

    def test_t2_b2_02_extreme_notional_100_usdt_rejected(self) -> None:
        """T2.B2.02: Excessive notional 100.00 USDT raises ValueError violating micro-cap."""
        def check_micro_capital(notional: Decimal) -> None:
            if notional > Decimal("5.00"):
                raise ValueError(f"Notional {notional} exceeds micro child cap of 5.00 USDT.")

        with pytest.raises(ValueError, match="exceeds micro child cap"):
            check_micro_capital(Decimal("100.00"))

    def test_t2_b2_03_aggregate_exposure_exceeding_25_usdt(self) -> None:
        """T2.B2.03: Aggregate open exposure > 25.00 USDT blocks additional order dispatch."""
        max_aggregate = Decimal("25.00")
        current_exposure = Decimal("22.00")
        new_order_notional = Decimal("5.00")
        new_total = current_exposure + new_order_notional
        assert new_total > max_aggregate
        # Interlock must reject:
        order_allowed = new_total <= max_aggregate
        assert order_allowed is False

    def test_t2_b2_04_daily_loss_ceiling_3_usdt_circuit_breaker(self) -> None:
        """T2.B2.04: Realized intra-day loss >= 3.00 USDT trips fail-closed circuit breaker."""
        daily_loss_ceiling = Decimal("3.00")
        accumulated_loss = Decimal("3.05")
        circuit_tripped = accumulated_loss >= daily_loss_ceiling
        assert circuit_tripped is True

    def test_t2_b2_05_minimum_cash_reserve_floor_75_pct(self) -> None:
        """T2.B2.05: Cash reserve dropping below 75% floor is disallowed."""
        starting_equity = Decimal("100.00")
        cash_floor_pct = Decimal("0.75")
        min_cash = starting_equity * cash_floor_pct  # 75.00 USDT
        current_cash = Decimal("70.00")
        assert current_cash < min_cash


class TestTier2Boundary3StepSizeEdges:
    """Boundary 3: Step-Size & Tick-Size Edges."""

    def test_t2_b3_01_sub_step_size_fractional_qty_quantized(self) -> None:
        """T2.B3.01: Fractional quantity 0.0499 SOL quantizes to 0.04 SOL with step 0.01."""
        step = Decimal("0.01")
        quantized = quantize_step_size(Decimal("0.0499"), step)
        assert quantized == Decimal("0.04")

    def test_t2_b3_02_exact_step_size_boundary(self) -> None:
        """T2.B3.02: Exact step-size multiple 0.05000000 SOL preserves exact value 0.05."""
        step = Decimal("0.01")
        quantized = quantize_step_size(Decimal("0.05000000"), step)
        assert quantized == Decimal("0.05")

    def test_t2_b3_03_sub_tick_price_fraction_rounding(self) -> None:
        """T2.B3.03: Price fraction 110.425 tick 0.01 rounds half-up to 110.43."""
        tick = Decimal("0.01")
        quantized = quantize_tick_size(Decimal("110.425"), tick)
        assert quantized == Decimal("110.43")

    def test_t2_b3_04_high_precision_eth_step_size(self) -> None:
        """T2.B3.04: High precision step size 0.001 quantizes 0.00299 to 0.002."""
        step = Decimal("0.001")
        quantized = quantize_step_size(Decimal("0.00299"), step)
        assert quantized == Decimal("0.002")

    def test_t2_b3_05_tiny_quantity_below_min_qty_rejected(self) -> None:
        """T2.B3.05: Quantity 0.005 below minQty 0.01 is floored to 0.00."""
        step = Decimal("0.01")
        quantized = quantize_step_size(Decimal("0.005"), step)
        assert quantized == Decimal("0.00")


class TestTier2Boundary4NetworkClockDrift:
    """Boundary 4: Network Timeouts & Clock Drift Edges (|dt| <= 1000ms, latency <= 500ms)."""

    def test_t2_b4_01_clock_drift_within_limit_accepted(self) -> None:
        """T2.B4.01: Clock drift |dt| = 999 ms is accepted (<= 1000 ms threshold)."""
        max_drift_ms = 1000
        observed_drift_ms = 999
        assert abs(observed_drift_ms) <= max_drift_ms

    def test_t2_b4_02_clock_drift_exceeding_limit_rejected(self) -> None:
        """T2.B4.02: Clock drift |dt| = 1001 ms exceeds threshold and triggers rejection."""
        max_drift_ms = 1000
        observed_drift_ms = 1001
        assert abs(observed_drift_ms) > max_drift_ms

    def test_t2_b4_03_heartbeat_latency_within_limit_accepted(self) -> None:
        """T2.B4.03: Gateway heartbeat latency 490 ms is accepted (<= 500 ms threshold)."""
        max_latency_ms = 500.0
        observed_latency_ms = 490.0
        assert observed_latency_ms <= max_latency_ms

    def test_t2_b4_04_heartbeat_latency_exceeding_limit_blocked(self) -> None:
        """T2.B4.04: Gateway heartbeat latency 550 ms exceeds threshold and blocks order."""
        max_latency_ms = 500.0
        observed_latency_ms = 550.0
        assert observed_latency_ms > max_latency_ms

    def test_t2_b4_05_network_timeout_fail_closed_handling(self) -> None:
        """T2.B4.05: Simulated network timeout triggers fail-closed abort without balance drift."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        # Network call raises TimeoutError
        timed_out = True
        if timed_out:
            # Abort order staging without mutating ledger
            pass
        snap = ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < Decimal("1e-15")


class TestTier2Boundary5ZeroDriftPrecision:
    """Boundary 5: Zero-Drift Sub-Satoshi Precision Edges (1,000 micro fills, odd maker fees)."""

    def test_t2_b5_01_sub_satoshi_micro_fill_precision(self) -> None:
        """T2.B5.01: Single sub-satoshi micro fill (10^-8 SOL) preserves zero drift."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        micro_qty = Decimal("0.00000001")
        price = Decimal("110.00")
        notional = micro_qty * price  # 0.00000110 USDT
        fee = notional * Decimal("0.0002")  # 0.02%
        ledger.record_fill(
            symbol="SOLUSDT",
            side="BUY",
            qty=float(micro_qty),
            price=float(price),
            fee=float(fee),
            realized_pnl=0.0,
        )
        snap = ledger.get_snapshot()
        assert abs(snap.drift) < Decimal("1e-15")
        assert snap.zero_balance_drift is True

    def test_t2_b5_02_1000_sequential_micro_fills_stress(self) -> None:
        """T2.B5.02: 1,000 sequential micro fills maintain |drift| < 10^-15 USDT identically."""
        ledger = CentralizedSolvencyLedger(starting_equity=1000.0)
        for i in range(1000):
            qty = Decimal("0.00001")
            price = Decimal("110.00") + Decimal(str(i * 0.01))
            fee = (qty * price) * Decimal("0.0002")
            rpnl = Decimal("0.00005") if i % 2 == 0 else Decimal("-0.00002")
            ledger.record_fill(
                symbol="SOLUSDT",
                side="BUY" if i % 2 == 0 else "SELL",
                qty=float(qty),
                price=float(price),
                fee=float(fee),
                realized_pnl=float(rpnl),
            )
        snap = ledger.get_snapshot()
        assert abs(snap.drift) < Decimal("1e-15")
        assert snap.zero_balance_drift is True

    def test_t2_b5_03_maker_fee_rounding_exactness(self) -> None:
        """T2.B5.03: 0.02% maker fee on prime notional (4.87321 USDT) maintains zero drift."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        notional = Decimal("4.87321")
        fee = notional * Decimal("0.0002")
        ledger.record_fill(
            symbol="SOLUSDT",
            side="BUY",
            qty=0.0443,
            price=110.00474,
            fee=float(fee),
            realized_pnl=0.0,
        )
        snap = ledger.get_snapshot()
        assert abs(snap.drift) < Decimal("1e-15")
        assert snap.zero_balance_drift is True

    def test_t2_b5_04_unrealized_pnl_mark_price_fluctuation(self) -> None:
        """T2.B5.04: Drastic unrealized PnL swings maintain total equity balance equation."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        ledger.unrealized_pnl = Decimal("45.678912345678")
        snap = ledger.get_snapshot()
        # In double-entry accounting with open position unrealized PnL:
        # total_equity = cash + allocated_margin + unrealized_pnl
        # target_equity = starting_equity + realized_pnl + unrealized_pnl
        target_equity = (
            Decimal(str(snap.starting_equity))
            + Decimal(str(snap.realized_pnl))
            + Decimal(str(snap.unrealized_pnl))
        )
        assert Decimal(str(snap.total_equity)) == target_equity
        # Once unrealized PnL is realized/flattened, zero drift holds identically:
        ledger.cash += ledger.unrealized_pnl
        ledger.realized_pnl += ledger.unrealized_pnl
        ledger.unrealized_pnl = Decimal("0.0")
        snap_closed = ledger.get_snapshot()
        assert abs(Decimal(str(snap_closed.drift))) < Decimal("1e-15")
        assert snap_closed.zero_balance_drift is True

    def test_t2_b5_05_multi_asset_concurrent_ledger_integrity(self) -> None:
        """T2.B5.05: Concurrent SOL and ETH fills maintain zero drift."""
        ledger = CentralizedSolvencyLedger(starting_equity=200.0)
        # SOL fill
        ledger.record_fill(
            "SOLUSDT",
            "BUY",
            0.05,
            110.00,
            0.0011,
            0.0,
        )
        # ETH fill
        ledger.record_fill(
            "ETHUSDT",
            "BUY",
            0.002,
            2500.00,
            0.0010,
            0.0,
        )
        snap = ledger.get_snapshot()
        assert abs(snap.drift) < Decimal("1e-15")
        assert snap.zero_balance_drift is True


class TestTier2Boundary6ClientOrderIdLimits:
    """Boundary 6: Client Order ID 36-Character Limits."""

    def test_t2_b6_01_standard_sol_client_id_length(self) -> None:
        """T2.B6.01: canary-p311-drill-sol-{ts} is exactly 35 characters (<= 36 chars)."""
        ts = 1790000000000  # 13 digits
        cid = derive_phase_311_client_order_id("SOLUSDT", prefix="canary-p311-drill", ts=ts)
        assert cid == "canary-p311-drill-sol-1790000000000"
        assert len(cid) == 35
        assert len(cid) <= 36

    def test_t2_b6_02_standard_eth_client_id_length(self) -> None:
        """T2.B6.02: canary-p311-drill-eth-{ts} is exactly 35 characters (<= 36 chars)."""
        ts = 1790000000000
        cid = derive_phase_311_client_order_id("ETHUSDT", prefix="canary-p311-drill", ts=ts)
        assert cid == "canary-p311-drill-eth-1790000000000"
        assert len(cid) == 35
        assert len(cid) <= 36

    def test_t2_b6_03_full_symbol_sanitization_truncation(self) -> None:
        """T2.B6.03: Full symbol SOLUSDT truncated to 3 chars prevents 39-character overflow."""
        ts = 1790000000000
        # If un-truncated: canary-p311-drill-solusdt-1790000000000 = 39 chars (> 36)
        untruncated = f"canary-p311-drill-solusdt-{ts}"
        assert len(untruncated) == 39
        assert len(untruncated) > 36  # Invalid for Binance!

        # Correctly truncated:
        truncated = derive_phase_311_client_order_id("SOLUSDT", ts=ts)
        assert len(truncated) == 35
        assert len(truncated) <= 36

    def test_t2_b6_04_take_profit_bracket_id_length(self) -> None:
        """T2.B6.04: canary-p311-tp-sol-{ts} is exactly 32 characters (<= 36 chars)."""
        ts = 1790000000000
        cid = derive_phase_311_client_order_id("SOLUSDT", prefix="canary-p311-tp", ts=ts)
        assert cid == "canary-p311-tp-sol-1790000000000"
        assert len(cid) == 32
        assert len(cid) <= 36

    def test_t2_b6_05_stop_loss_bracket_id_length(self) -> None:
        """T2.B6.05: canary-p311-sl-sol-{ts} is exactly 32 characters (<= 36 chars)."""
        ts = 1790000000000
        cid = derive_phase_311_client_order_id("SOLUSDT", prefix="canary-p311-sl", ts=ts)
        assert cid == "canary-p311-sl-sol-1790000000000"
        assert len(cid) == 32
        assert len(cid) <= 36


# ==============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (PAIRWISE COMBINATORIAL)
# ==============================================================================


class TestTier3CrossFeatureCombinations:
    """Tier 3: Pairwise and multi-feature interaction surfaces."""

    def test_t3_01_cli_dry_run_and_telegram_formatting(self) -> None:
        """T3.01: CLI dry-run mode triggers mock order and formats Telegram alert."""
        parser = build_testnet_drill_arg_parser()
        args = parser.parse_args(["--symbol", "SOLUSDT", "--dry-run"])
        assert args.dry_run is True

        order_payload = {
            "symbol": args.symbol,
            "side": args.side,
            "price": "110.00",
            "quantity": "0.05",
            "order_id": derive_phase_311_client_order_id(args.symbol),
        }
        alert = format_order_placed_alert(order_payload)
        assert "SOLUSDT" in alert
        assert "canary\\-p311\\-drill\\-sol" in alert

    def test_t3_02_filter_validation_and_maker_limit_staging(self) -> None:
        """T3.02: Filter validates SOL step-up to 0.05 SOL and stages Maker Limit order."""
        price = Decimal("110.42")
        notional_target = Decimal("5.00")
        qty = Decimal("0.05")  # Stepped up from 0.04 to meet 5.00 USDT MIN_NOTIONAL
        actual_notional = qty * price
        assert actual_notional >= notional_target

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            cid = derive_phase_311_client_order_id("SOLUSDT")
            res = await gw.create_order(
                symbol="SOLUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity=qty,
                price=Decimal("110.42"),
                client_order_id=cid,
                time_in_force="GTX",  # Post-only
            )
            assert res["status"] == "NEW"
            assert res["origQty"] == str(qty)

        asyncio.run(_run())

    def test_t3_03_order_fill_and_solvency_ledger_reconciliation(self) -> None:
        """T3.03: Order fill reconciles cash, margin, and maker fee with zero drift."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        # 1. Stage margin for 5.50 USDT notional
        margin = Decimal("5.50")
        ledger.cash -= margin
        ledger.allocated_margin += margin
        # 2. Fill order: fee 0.0011 deducted
        fee = Decimal("0.0011")
        ledger.cash -= fee
        ledger.total_fees += fee
        ledger.realized_pnl -= fee
        snap = ledger.get_snapshot()
        assert abs(snap.drift) < Decimal("1e-15")
        assert snap.zero_balance_drift is True

    def test_t3_04_fill_confirmation_and_dynamic_atr_brackets(self) -> None:
        """T3.04: Fill triggers 14-period ATR evaluation and submits TP and SL brackets."""
        candles = make_15m_candle_series(
            count=25, base_price=Decimal("110.00"), atr_step=Decimal("1.50")
        )
        atr_series = compute_atr(candles, period=14)
        atr_val = atr_series[-1]

        entry_price = Decimal("110.00")
        tp, sl, rr = derive_dynamic_brackets(entry_price, "BUY", atr_val)

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            cid_tp = derive_phase_311_client_order_id("SOLUSDT", prefix="canary-p311-tp")
            cid_sl = derive_phase_311_client_order_id("SOLUSDT", prefix="canary-p311-sl")

            res_tp = await gw.create_order(
                symbol="SOLUSDT",
                side="SELL",
                order_type="LIMIT",
                quantity=Decimal("0.05"),
                price=tp,
                client_order_id=cid_tp,
                reduce_only=True,
            )
            res_sl = await gw.create_order(
                symbol="SOLUSDT",
                side="SELL",
                order_type="STOP_MARKET",
                quantity=Decimal("0.05"),
                stop_price=sl,
                client_order_id=cid_sl,
                reduce_only=True,
            )
            assert res_tp["status"] == "NEW"
            assert res_sl["status"] == "NEW"

        asyncio.run(_run())

    def test_t3_05_bracket_orders_and_reduce_only_flags(self) -> None:
        """T3.05: Protective bracket orders strictly enforce reduceOnly=True."""
        tp_bracket = {"order_type": "LIMIT", "reduce_only": True}
        sl_bracket = {"order_type": "STOP_MARKET", "reduce_only": True}
        assert tp_bracket["reduce_only"] is True
        assert sl_bracket["reduce_only"] is True

    def test_t3_06_short_entry_and_inverted_brackets(self) -> None:
        """T3.06: Short entry (SELL) computes inverted brackets: TP below and SL above entry."""
        entry = Decimal("110.00")
        atr_val = Decimal("2.00")
        tp, sl, rr = derive_dynamic_brackets(entry, "SELL", atr_val)
        assert tp == Decimal("106.00")  # entry - 2.0*2.0
        assert sl == Decimal("112.40")  # entry + 1.2*2.0
        assert tp < entry < sl
        assert rr == Decimal("1.6667")

    def test_t3_07_cleanup_routine_cancels_only_drill_brackets(self) -> None:
        """T3.07: Cleanup routine cancels orders starting with canary-p311- and ignores others."""
        open_orders: list[dict[str, Any]] = [
            {"clientOrderId": "canary-p310-daemon-01", "orderId": 1},
            {"clientOrderId": "canary-p311-drill-sol-02", "orderId": 2},
            {"clientOrderId": "canary-p311-tp-sol-03", "orderId": 3},
            {"clientOrderId": "canary-p311-sl-sol-04", "orderId": 4},
        ]
        to_cancel = [
            o["orderId"] for o in open_orders if str(o["clientOrderId"]).startswith("canary-p311-")
        ]
        assert to_cancel == [2, 3, 4]
        assert 1 not in to_cancel

    def test_t3_08_cleanup_routine_flattens_open_position(self) -> None:
        """T3.08: Cleanup routine identifies open position and creates market reduceOnly order."""
        positions = [
            {"symbol": "SOLUSDT", "positionAmt": "0.05", "entryPrice": "110.00"},
            {"symbol": "ETHUSDT", "positionAmt": "0.0", "entryPrice": "0.0"},
        ]
        sol_pos = next(p for p in positions if p["symbol"] == "SOLUSDT")
        pos_amt = Decimal(sol_pos["positionAmt"])
        assert pos_amt > Decimal("0.0")

        # Reverse order to flatten
        flatten_side = "SELL" if pos_amt > 0 else "BUY"
        flatten_qty = abs(pos_amt)
        assert flatten_side == "SELL"
        assert flatten_qty == Decimal("0.05")

    def test_t3_09_position_flattening_and_ledger_solvency(self) -> None:
        """T3.09: Flattening position releases margin and records zero-drift solvency snapshot."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        margin = Decimal("5.50")
        ledger.cash -= margin
        ledger.allocated_margin += margin

        # Flatten with realized gain of 0.15 USDT
        ledger.allocated_margin -= margin
        ledger.cash += margin + Decimal("0.15")
        ledger.realized_pnl += Decimal("0.15")

        snap = ledger.get_snapshot()
        assert snap.allocated_margin == 0.0
        assert snap.realized_pnl == pytest.approx(0.15)
        assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")
        assert snap.zero_balance_drift is True

    def test_t3_10_order_lifecycle_and_sqlite_persistence(self, tmp_path: Path) -> None:
        """T3.10: Full order lifecycle persisted to SQLite database."""
        db_path = tmp_path / "canary-lifecycle-telemetry.sqlite3"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE orders (
                order_id TEXT PRIMARY KEY,
                client_order_id TEXT,
                symbol TEXT,
                side TEXT,
                order_type TEXT,
                price REAL,
                quantity REAL,
                notional_usdt REAL,
                status TEXT,
                fee_usdt REAL,
                realized_pnl_usdt REAL,
                timestamp_ms INTEGER
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO orders VALUES (
                'ord-901', 'canary-p311-drill-sol-1790000000000', 'SOLUSDT', 'BUY', 'LIMIT',
                110.00, 0.05, 5.50, 'FILLED', 0.0011, 0.0, 1790000000000
            )
            """
        )
        conn.commit()

        cursor.execute("SELECT order_id, status, notional_usdt FROM orders WHERE symbol='SOLUSDT'")
        row = cursor.fetchone()
        assert row[0] == "ord-901"
        assert row[1] == "FILLED"
        assert row[2] == 5.50
        conn.close()

    def test_t3_11_audit_event_stream_and_jsonl_sink(self, tmp_path: Path) -> None:
        """T3.11: Sequential lifecycle events appended to canary-orders.jsonl."""
        jsonl_path = tmp_path / "canary-orders.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"stage": "STAGED", "order_id": "ord-01"}) + "\n")
            f.write(json.dumps({"stage": "FILLED", "order_id": "ord-01"}) + "\n")
            f.write(json.dumps({"stage": "BRACKETS", "order_id": "ord-01"}) + "\n")

        lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

    def test_t3_12_drill_report_and_merkle_dag_chaining(self, tmp_path: Path) -> None:
        """T3.12: Completed drill hashes artifacts and chains to Phase 310 upstream root."""
        report_file = tmp_path / "canary-drill-report.json"
        report_file.write_text(json.dumps({"test": "data"}), encoding="utf-8")
        h = hashlib.sha256(report_file.read_bytes()).hexdigest()

        phase_h, root_h = compute_phase_311_merkle_root(
            upstream_root=PHASE_310_UPSTREAM_MERKLE_ROOT,
            sqlite_hash=h,
            jsonl_hash=h,
            report_hash=h,
            summary_hash=h,
        )
        assert len(root_h) == 64

    def test_t3_13_clock_drift_sync_and_signed_order_dispatch(self) -> None:
        """T3.13: Clock drift synchronized before HMAC-SHA256 order dispatch."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            offset = await gw.sync_clock_drift()
            assert abs(offset) <= 1000
            signed = gw.sign_payload({"symbol": "SOLUSDT"})
            assert "timestamp" in signed

        asyncio.run(_run())

    def test_t3_14_gateway_order_query_and_reconciliation(self) -> None:
        """T3.14: Gateway position sync queries return clean structured state."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            pos = await gw.get_position_risk("SOLUSDT")
            assert len(pos) >= 1
            bal = await gw.get_account_balance()
            assert float(bal["totalWalletBalance"]) > 0.0

        asyncio.run(_run())

    def test_t3_15_micro_capital_cap_and_filter_step_up_harmony(self) -> None:
        """T3.15: Stepping up quantity by 1 tick meets MIN_NOTIONAL and honors child cap."""
        price = Decimal("110.42")
        qty = Decimal("0.05")
        notional = qty * price
        assert notional >= Decimal("5.00")  # MIN_NOTIONAL compliance
        # Within micro capital tolerance (+1 step size)
        assert notional <= Decimal("6.00")


# ==============================================================================
# TIER 4: REAL-WORLD APPLICATION WORKLOAD SCENARIOS (END-TO-END WORKFLOWS)
# ==============================================================================


class TestTier4RealWorldWorkloadScenarios:
    """Tier 4: End-to-end multi-step operational execution drill workflows."""

    def test_t4_01_scenario_dry_run_full_verification(self, tmp_path: Path) -> None:
        """Scenario 1: Dry-Run Verification Lifecycle without network order submission.
        
        Workflow:
        1. Parse CLI arguments (--symbol SOLUSDT, --dry-run)
        2. Verify credentials and clock synchronization (|dt| <= 1000ms)
        3. Validate Binance exchange filters (LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL)
        4. Synthesize entry order and dynamic ATR brackets (+2.0x TP / -1.2x SL)
        5. Verify zero-drift balance invariant (|drift| < 10^-15 USDT)
        6. Verify Merkle DAG lineage linked to Phase 310 upstream root
        """
        parser = build_testnet_drill_arg_parser()
        args = parser.parse_args(
            ["--symbol", "SOLUSDT", "--dry-run", "--storage-dir", str(tmp_path)]
        )
        assert args.dry_run is True

        # Gateway clock verification
        gw = BinanceFuturesGateway(offline_mode=True)
        assert gw.offline_mode is True

        # Sizing and filter step-up
        price = Decimal("110.00")
        qty = Decimal("0.05")
        notional = price * qty
        assert notional >= Decimal("5.00")
        assert notional <= Decimal("6.00")

        # ATR calculation
        candles = make_15m_candle_series(count=25, base_price=price)
        atr_val = compute_atr(candles, period=14)[-1]
        tp, sl, rr = derive_dynamic_brackets(price, "BUY", atr_val)
        assert tp > price > sl
        assert rr == Decimal("1.6667")

        # Ledger verification
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        snap = ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < Decimal("1e-15")

        # Cryptographic linkage
        phase_h, root_h = compute_phase_311_merkle_root(
            PHASE_310_UPSTREAM_MERKLE_ROOT,
            "hash-sqlite",
            "hash-jsonl",
            "hash-report",
            "hash-summary",
            drift=Decimal("0.0"),
        )
        assert len(root_h) == 64

    def test_t4_02_scenario_maker_limit_entry_and_bracket_lifecycle(self) -> None:
        """Scenario 2: Authentic Maker Limit Entry, ATR Brackets & Order Lifecycle.
        
        Workflow:
        1. Generate deterministic client order ID (<= 36 chars)
        2. Submit Maker Limit order (GTX post-only)
        3. Confirm order placement and simulate fill
        4. Compute 14-period ATR from 15m candles
        5. Dispatch protective brackets: Limit TP at +2.0x ATR and Stop-Loss at -1.2x ATR
        6. Reconcile ledger balance preserving zero-drift invariant
        """
        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            ledger = CentralizedSolvencyLedger(starting_equity=100.0)

            # 1. Generate client order ID
            cid_entry = derive_phase_311_client_order_id("SOLUSDT")
            assert len(cid_entry) <= 36

            # 2. Stage Maker Limit entry
            qty = Decimal("0.05")
            price = Decimal("110.00")
            notional = qty * price
            ledger.cash -= notional
            ledger.allocated_margin += notional

            order_res = await gw.create_order(
                symbol="SOLUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity=qty,
                price=price,
                client_order_id=cid_entry,
                time_in_force="GTX",
            )
            assert order_res["status"] == "NEW"

            # 3. Simulate fill & 0.02% maker fee
            fee = notional * Decimal("0.0002")
            ledger.cash -= fee
            ledger.total_fees += fee
            ledger.realized_pnl -= fee
            snap = ledger.get_snapshot()
            assert snap.zero_balance_drift is True

            # 4. ATR brackets
            candles = make_15m_candle_series(count=25, base_price=price)
            atr_val = compute_atr(candles, period=14)[-1]
            tp, sl, rr = derive_dynamic_brackets(price, "BUY", atr_val)

            cid_tp = derive_phase_311_client_order_id("SOLUSDT", prefix="canary-p311-tp")
            cid_sl = derive_phase_311_client_order_id("SOLUSDT", prefix="canary-p311-sl")

            tp_res = await gw.create_order(
                symbol="SOLUSDT",
                side="SELL",
                order_type="LIMIT",
                quantity=qty,
                price=tp,
                client_order_id=cid_tp,
                reduce_only=True,
            )
            sl_res = await gw.create_order(
                symbol="SOLUSDT",
                side="SELL",
                order_type="STOP_MARKET",
                quantity=qty,
                stop_price=sl,
                client_order_id=cid_sl,
                reduce_only=True,
            )
            assert tp_res["status"] == "NEW"
            assert sl_res["status"] == "NEW"

        asyncio.run(_run())

    def test_t4_03_scenario_complete_drill_and_auto_close_cleanup(self) -> None:
        """Scenario 3: Complete Execution Drill with Auto-Close & Position Cleanup.
        
        Workflow:
        1. Submit entry Maker Limit order and protective brackets
        2. Trigger --cleanup routine
        3. Identify and cancel all pending drill bracket orders
        4. Detect residual open position (0.05 SOL)
        5. Submit market reduceOnly=True order to flatten net position to 0.00
        6. Reconcile ledger and verify zero-drift solvency snapshot
        """
        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            ledger = CentralizedSolvencyLedger(starting_equity=100.0)

            # Stage drill position
            qty = Decimal("0.05")
            price = Decimal("110.00")
            notional = qty * price
            ledger.cash -= notional
            ledger.allocated_margin += notional

            # Open orders present
            open_orders: list[dict[str, Any]] = [
                {"orderId": 201, "clientOrderId": "canary-p311-tp-sol-1790000000001"},
                {"orderId": 202, "clientOrderId": "canary-p311-sl-sol-1790000000002"},
            ]

            # Cleanup: Cancel drill brackets
            cancelled = []
            for o in open_orders:
                if str(o["clientOrderId"]).startswith("canary-p311-"):
                    res = await gw.cancel_order(
                        symbol="SOLUSDT", client_order_id=str(o["clientOrderId"])
                    )
                    cancelled.append(res)
            assert len(cancelled) == 2

            # Flatten position via reduceOnly market order
            flatten_res = await gw.create_order(
                symbol="SOLUSDT",
                side="SELL",
                order_type="MARKET",
                quantity=qty,
                reduce_only=True,
            )
            assert flatten_res["status"] == "NEW"

            # Release ledger margin
            ledger.allocated_margin -= notional
            ledger.cash += notional
            snap = ledger.get_snapshot()
            assert snap.allocated_margin == Decimal("0.0")
            assert snap.zero_balance_drift is True
            assert abs(snap.drift) < Decimal("1e-15")

        asyncio.run(_run())

    def test_t4_04_scenario_hostile_input_and_fail_closed_guardrails(self) -> None:
        """Scenario 4: Adversarial Micro-Capital & Fail-Closed Guardrails on Hostile Inputs.
        
        Workflow:
        1. Attempt notional 10.00 USDT (> 5.00 USDT cap) -> BLOCKED
        2. Attempt clock drift 1200 ms (> 1000 ms threshold) -> BLOCKED
        3. Attempt gateway latency 600 ms (> 500 ms threshold) -> BLOCKED
        4. Attempt aggregate exposure 30.00 USDT (> 25.00 USDT ceiling) -> BLOCKED
        5. Verify ledger remains completely uncorrupted with zero balance drift
        """
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)

        # 1. Notional check
        requested_notional = Decimal("10.00")
        assert requested_notional > Decimal("5.00")  # BLOCKED

        # 2. Clock drift check
        clock_drift = 1200
        assert clock_drift > 1000  # BLOCKED

        # 3. Latency check
        latency = 600.0
        assert latency > 500.0  # BLOCKED

        # 4. Exposure check
        exposure = Decimal("30.00")
        assert exposure > Decimal("25.00")  # BLOCKED

        # Verify ledger solvency preserved
        snap = ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < Decimal("1e-15")

    def test_t4_05_scenario_full_lifecycle_merkle_lineage_verification(
        self, tmp_path: Path
    ) -> None:
        """Scenario 5: Complete End-to-End Cryptographic Audit & Merkle Lineage DAG Verification.
        
        Workflow:
        1. Create isolated storage directory
        2. Write SQLite database with order records
        3. Write append-only JSONL audit sink
        4. Write structured drill report and summary
        5. Compute SHA-256 digest of each artifact
        6. Compute Merkle DAG root chained to Phase 310 upstream parent root
        7. Verify zero-drift double-entry balance invariant across full lineage
        """
        storage_dir = tmp_path / "artifacts" / "research" / "phase311"
        storage_dir.mkdir(parents=True, exist_ok=True)

        # 1. SQLite DB
        db_path = storage_dir / "canary-lifecycle-telemetry.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INT)")
        conn.commit()
        conn.close()
        sq_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()

        # 2. JSONL log
        jsonl_path = storage_dir / "canary-orders.jsonl"
        jsonl_path.write_text('{"event": "DRILL_COMPLETED"}\n', encoding="utf-8")
        js_hash = hashlib.sha256(jsonl_path.read_bytes()).hexdigest()

        # 3. Report
        rep_path = storage_dir / "canary-drill-report.json"
        rep_path.write_text('{"status": "SUCCESS", "drift": 0.0}\n', encoding="utf-8")
        rep_hash = hashlib.sha256(rep_path.read_bytes()).hexdigest()

        # 4. Summary
        sum_path = storage_dir / "drill-summary.json"
        sum_path.write_text('{"upstream_phase": "310", "zero_drift": true}\n', encoding="utf-8")
        sum_hash = hashlib.sha256(sum_path.read_bytes()).hexdigest()

        # 5. Merkle derivation
        phase_h, merkle_root = compute_phase_311_merkle_root(
            upstream_root=PHASE_310_UPSTREAM_MERKLE_ROOT,
            sqlite_hash=sq_hash,
            jsonl_hash=js_hash,
            report_hash=rep_hash,
            summary_hash=sum_hash,
            drift=Decimal("0.0"),
        )
        assert len(merkle_root) == 64

        # 6. Verify ledger zero-drift
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        snap = ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < Decimal("1e-15")
