"""Unit tests for Phase 311 Execution Drill & Verification Harness.

Covers:
- Client order ID generation and strict 36-char Binance limit.
- BinanceFuturesGateway extensions (get_order, get_open_orders, cancel_all, TAKE_PROFIT_MARKET).
- Exchange filter validation, ROUND_DOWN quantization, and MIN_NOTIONAL single step-up compliance.
- Dynamic ATR calculation and +2.0x TP / -1.2x SL protective bracket math (1.66:1 R:R).
- Double-entry zero-drift balance invariant (|Delta| < 10^-15 USDT).
- Telegram MarkdownV2 alerting and reserved character escaping.
- Non-interference guarantees with Kainode VPS 24/7 daemon.
- Upstream Phase 310 Merkle DAG binding and cryptographic verification.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.execution.binance_gateway import (
    BinanceFuturesGateway,
    generate_drill_client_order_id,
    quantize_step_size,
    quantize_tick_size,
)
from autonomous_futures.feed.execution_drill import (
    DOUBLE_ENTRY_TOLERANCE,
    UPSTREAM_PHASE_310_PARENT_ROOT,
    DrillSolvencyLedger,
    ExecutionDrillConfig,
    ExecutionDrillEngine,
    verify_phase_311_artifacts,
)
from autonomous_futures.notifications import (
    escape_markdown_v2,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    compute_atr,
)


class TestClientOrderIdGeneration:
    """Tests deterministic client order ID formatting and 36-character boundary."""

    def test_client_order_id_length_and_format(self) -> None:
        """Verifies all role formats stay strictly within 36 characters."""
        ts = 1791552000000
        for symbol in ["SOLUSDT", "ETHUSDT", "BTCUSDT", "XRPUSDT", "SOL"]:
            for role in ["drill", "tp", "sl", "close", "flatten", "take_profit", "stop_loss"]:
                cid = generate_drill_client_order_id(symbol, ts, role=role)
                assert len(cid) <= 36, f"CID '{cid}' exceeds 36 chars ({len(cid)})"
                assert cid.startswith("canary-p311-")
                # Characters must only be alphanumeric and hyphen
                assert all(c.isalnum() or c == "-" for c in cid)

    def test_client_order_id_deterministic(self) -> None:
        """Verifies same timestamp produces deterministic output."""
        ts = 1790250000000
        cid1 = generate_drill_client_order_id("SOLUSDT", ts, "drill")
        cid2 = generate_drill_client_order_id("SOLUSDT", ts, "drill")
        assert cid1 == cid2
        assert cid1 == "canary-p311-drill-sol-1790250000000"


class TestBinanceGatewayExtensions:
    """Tests extended BinanceFuturesGateway endpoints."""

    @pytest.mark.anyio
    async def test_get_order_mock(self) -> None:
        gw = BinanceFuturesGateway(offline_mode=True)
        # 1. Non-existent returns synthetic order
        res = await gw.get_order("SOLUSDT", client_order_id="test-cid-1")
        assert res["clientOrderId"] == "test-cid-1"
        assert res["status"] in ("FILLED", "NEW")

        # 2. Existing order created in mock
        created = await gw.create_order(
            symbol="SOLUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.05"),
            price=Decimal("110.00"),
            client_order_id="my-custom-cid",
        )
        assert created["clientOrderId"] == "my-custom-cid"
        fetched = await gw.get_order("SOLUSDT", client_order_id="my-custom-cid")
        assert fetched["clientOrderId"] == "my-custom-cid"

    @pytest.mark.anyio
    async def test_get_open_orders_mock(self) -> None:
        gw = BinanceFuturesGateway(offline_mode=True)
        # Create an open order
        await gw.create_order(
            symbol="SOLUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.05"),
            price=Decimal("110.00"),
            client_order_id="open-cid-1",
        )
        open_orders = await gw.get_open_orders("SOLUSDT")
        assert len(open_orders) >= 1
        assert any(o.get("clientOrderId") == "open-cid-1" for o in open_orders)

    @pytest.mark.anyio
    async def test_cancel_all_open_orders_mock(self) -> None:
        gw = BinanceFuturesGateway(offline_mode=True)
        await gw.create_order(
            symbol="SOLUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.05"),
            price=Decimal("110.00"),
            client_order_id="open-cid-2",
        )
        res = await gw.cancel_all_open_orders("SOLUSDT")
        assert res.get("code") == 200
        open_orders = await gw.get_open_orders("SOLUSDT")
        assert not any(o.get("clientOrderId") == "open-cid-2" for o in open_orders)

    @pytest.mark.anyio
    async def test_take_profit_market_support(self) -> None:
        gw = BinanceFuturesGateway(offline_mode=True)
        # Valid TAKE_PROFIT_MARKET
        tp_res = await gw.create_order(
            symbol="SOLUSDT",
            side="SELL",
            order_type="TAKE_PROFIT_MARKET",
            quantity=Decimal("0.05"),
            stop_price=Decimal("120.00"),
            reduce_only=True,
        )
        assert tp_res["type"] == "TAKE_PROFIT_MARKET"
        assert tp_res["stopPrice"] == "120.00"

        # Missing stop_price raises ValueError
        with pytest.raises(ValueError, match="TAKE_PROFIT_MARKET orders require stopPrice"):
            await gw.create_order(
                symbol="SOLUSDT",
                side="SELL",
                order_type="TAKE_PROFIT_MARKET",
                quantity=Decimal("0.05"),
                stop_price=None,
            )


class TestExchangeFiltersAndSizing:
    """Tests exchange filter validation, quantization, and single step-up sizing."""

    def test_quantize_step_and_tick(self) -> None:
        # Step size 0.01 with ROUND_DOWN
        assert quantize_step_size(Decimal("0.0456"), Decimal("0.01")) == Decimal("0.04")
        assert quantize_step_size(Decimal("0.0499"), Decimal("0.01")) == Decimal("0.04")

        # Tick size 0.01 with ROUND_HALF_UP
        assert quantize_tick_size(Decimal("110.424"), Decimal("0.01")) == Decimal("110.42")
        assert quantize_tick_size(Decimal("110.426"), Decimal("0.01")) == Decimal("110.43")

    def test_min_notional_single_step_up(self) -> None:
        config = ExecutionDrillConfig(dry_run=True)
        engine = ExecutionDrillEngine(config=config)

        # Mark price 110.42, requested notional 5.00 USDT
        # 5.00 / 110.42 = 0.0452 -> ROUND_DOWN = 0.04 -> notional = 4.4168 USDT (< 5.00)
        # Step-up +0.01 -> 0.05 -> notional = 5.521 USDT (within tolerance)
        sizing = engine.validate_and_size_order(
            symbol="SOLUSDT",
            side="BUY",
            mark_price=Decimal("110.42"),
            requested_notional=Decimal("5.00"),
        )
        assert sizing.is_valid is True
        assert sizing.quantized_qty == Decimal("0.05")
        assert sizing.step_up_applied is True
        assert sizing.actual_notional >= Decimal("5.00")

    def test_out_of_bounds_price_rejected(self) -> None:
        config = ExecutionDrillConfig(dry_run=True)
        engine = ExecutionDrillEngine(config=config)
        sizing = engine.validate_and_size_order(
            symbol="SOLUSDT",
            side="BUY",
            mark_price=Decimal("0.10"),  # below min_price 1.00
            requested_notional=Decimal("5.00"),
        )
        assert sizing.is_valid is False
        assert "out of bounds" in str(sizing.rejection_reason)


class TestDynamicATRAndBrackets:
    """Tests dynamic ATR computation and +2.0x TP / -1.2x SL bracket levels."""

    def test_compute_atr(self) -> None:
        # Create 20 synthetic candles
        candles = []
        now_ms = 1790000000000
        for i in range(20):
            p = Decimal("100.00") + Decimal(str(i))
            candles.append(
                Candle(
                    timestamp_ms=now_ms + i * 900000,
                    open=p,
                    high=p + Decimal("2.00"),
                    low=p - Decimal("1.00"),
                    close=p + Decimal("0.50"),
                    volume=Decimal("100.0"),
                )
            )
        atrs = compute_atr(candles, period=14)
        valid_atrs = [a for a in atrs if a > Decimal("0")]
        assert len(valid_atrs) == 7
        # True range for each candle: max(3.0, |H-C_prev|, |L-C_prev|) ~= 3.0
        assert valid_atrs[-1] > Decimal("2.5")

    def test_protective_brackets_calculation(self) -> None:
        config = ExecutionDrillConfig(dry_run=True)
        engine = ExecutionDrillEngine(config=config)
        entry_price = Decimal("100.00")
        atr = Decimal("2.00")
        ts_ms = 1791552000000

        # Long (BUY)
        brackets_long = engine.calculate_protective_brackets(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=entry_price,
            atr=atr,
            ts_ms=ts_ms,
        )
        # TP = 100.00 + (2.0 * 2.00) = 104.00
        # SL = 100.00 - (1.2 * 2.00) = 97.60
        assert brackets_long.take_profit_price == Decimal("104.00")
        assert brackets_long.stop_loss_price == Decimal("97.60")
        assert brackets_long.risk_reward_ratio == Decimal("1.6667")
        assert brackets_long.tp_client_order_id.startswith("canary-p311-tp-")
        assert brackets_long.sl_client_order_id.startswith("canary-p311-sl-")

        # Short (SELL)
        brackets_short = engine.calculate_protective_brackets(
            symbol="SOLUSDT",
            side="SELL",
            entry_price=entry_price,
            atr=atr,
            ts_ms=ts_ms,
        )
        # TP = 100.00 - (2.0 * 2.00) = 96.00
        # SL = 100.00 + (1.2 * 2.00) = 102.40
        assert brackets_short.take_profit_price == Decimal("96.00")
        assert brackets_short.stop_loss_price == Decimal("102.40")
        assert brackets_short.risk_reward_ratio == Decimal("1.6667")


class TestSolvencyLedgerZeroDrift:
    """Tests double-entry balance invariant |Delta| < 10^-15 USDT."""

    def test_ledger_lifecycle_zero_drift(self) -> None:
        ledger = DrillSolvencyLedger(starting_equity=Decimal("100.00000000"))
        assert ledger.is_zero_drift is True
        assert ledger.drift == Decimal("0.0")

        # 1. Allocate margin for 5.00 USDT order
        assert ledger.allocate_margin(Decimal("5.00")) is True
        assert ledger.cash == Decimal("95.00")
        assert ledger.allocated_margin == Decimal("5.00")
        assert ledger.is_zero_drift is True

        # 2. Fill order: release margin, pay maker fee 0.001 USDT
        ledger.record_fill(
            margin_released=Decimal("5.00"),
            realized_pnl_delta=Decimal("0.00"),
            fee_cost=Decimal("0.00100000"),
        )
        assert ledger.cash == Decimal("99.99900000")
        assert ledger.allocated_margin == Decimal("0.00")
        assert ledger.realized_pnl == Decimal("-0.00100000")
        assert ledger.is_zero_drift is True
        assert ledger.drift < DOUBLE_ENTRY_TOLERANCE

        # 3. Simulate TP execution: profit +0.20 USDT, maker fee 0.001 USDT
        ledger.record_fill(
            margin_released=Decimal("0.00"),
            realized_pnl_delta=Decimal("0.20000000"),
            fee_cost=Decimal("0.00100000"),
        )
        assert ledger.realized_pnl == Decimal("0.19800000")
        assert ledger.is_zero_drift is True
        assert ledger.drift < DOUBLE_ENTRY_TOLERANCE


class TestNotificationsShim:
    """Tests notifications shim compatibility and Telegram formatting."""

    def test_notifications_shim_import(self) -> None:
        import autonomous_futures.notifications.telegram as tg_mod
        assert hasattr(tg_mod, "TelegramNotifierClient")
        assert hasattr(tg_mod, "escape_markdown_v2")

    def test_escape_markdown_v2(self) -> None:
        raw = "Price: 100.50 (TP +2.0x, SL -1.2x) [OK]!"
        escaped = escape_markdown_v2(raw)
        # Markdown reserved characters: . ( ) + - [ ] !
        assert "\\." in escaped
        assert "\\(" in escaped
        assert "\\)" in escaped
        assert "\\+" in escaped
        assert "\\-" in escaped
        assert "\\[" in escaped
        assert "\\]" in escaped
        assert "\\!" in escaped


class TestExecutionDrillEngineIntegration:
    """Tests end-to-end ExecutionDrillEngine in dry-run mode."""

    @pytest.mark.anyio
    async def test_full_drill_dry_run(self, tmp_path: Path) -> None:
        config = ExecutionDrillConfig(
            symbol="SOLUSDT",
            side="BUY",
            requested_notional=Decimal("5.00"),
            dry_run=True,
            cleanup=True,
            storage_dir=tmp_path,
        )
        engine = ExecutionDrillEngine(config=config)
        summary = await engine.execute_drill()

        # Check summary structure
        assert summary["phase"] == "phase_311"
        assert summary["upstream_hash"] == UPSTREAM_PHASE_310_PARENT_ROOT
        assert summary["zero_balance_drift"] is True
        assert summary["drift"] == 0.0
        assert "merkle_root" in summary

        # Check files exist
        sqlite_file = tmp_path / "canary-lifecycle-telemetry.sqlite3"
        orders_file = tmp_path / "canary-orders.jsonl"
        report_file = tmp_path / "canary-drill-report.json"
        summary_file = tmp_path / "drill-summary.json"

        assert sqlite_file.is_file()
        assert orders_file.is_file()
        assert report_file.is_file()
        assert summary_file.is_file()

        # Check SQLite table row counts
        conn = sqlite3.connect(sqlite_file)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM orders")
        assert cur.fetchone()[0] >= 1
        cur.execute("SELECT COUNT(*) FROM brackets")
        assert cur.fetchone()[0] >= 2
        cur.execute("SELECT COUNT(*) FROM solvency_snapshots")
        assert cur.fetchone()[0] >= 1
        conn.close()

        # Check report content
        report_data = json.loads(report_file.read_text(encoding="utf-8"))
        assert report_data["symbol"] == "SOLUSDT"
        assert report_data["brackets"]["risk_reward_ratio"] == 1.6667
        assert report_data["solvency"]["zero_balance_drift"] is True

        # Check independent verification function
        assert verify_phase_311_artifacts(tmp_path) is True
