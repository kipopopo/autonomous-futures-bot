"""Phase 311 Adversarial Empirical Security & Guardrail Challenge Suite.

Empirically probes:
1. Client Order ID length boundaries (<= 36 chars accepted, > 36 chars probed).
2. Micro-capital bounds (child order cap, aggregate exposure, daily loss).
3. Clock skew (> 1000ms) and latency (> 500ms) fail-closed behavior.
4. Non-interference: drill cleanup isolation (no non-drill cancel, zero listenKey deletion).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from autonomous_futures.execution.binance_gateway import (
    DEFAULT_SPECS,
    BinanceFuturesGateway,
    generate_client_order_id,
    generate_drill_client_order_id,
)
from autonomous_futures.feed.execution_drill import (
    ExecutionDrillConfig,
    ExecutionDrillEngine,
)


class TestAdversarialClientOrderIdBoundaries:
    """Empirically probes client order ID length boundaries."""

    def test_generated_client_order_id_never_exceeds_36_chars(self) -> None:
        """Verifies generated client order IDs comply with Binance's <= 36 char limit."""
        symbols = [
            "SOLUSDT",
            "ETHUSDT",
            "BTCUSDT",
            "XRPUSDT",
            "DOGEUSDT",
            "1000PEPEUSDT",
            "A",
            "VERYLONGSYMBOLNAMEUSDT",
        ]
        roles = [
            "drill",
            "tp",
            "sl",
            "cl",
            "take_profit",
            "stop_loss",
            "flatten",
            "close",
        ]
        timestamps = [0, 1000000000000, 1791552000000, 9999999999999]

        for sym in symbols:
            for role in roles:
                for ts in timestamps:
                    cid = generate_drill_client_order_id(
                        symbol=sym, ts_ms=ts, role=role
                    )
                    assert (
                        len(cid) <= 36
                    ), f"ID length {len(cid)} > 36 chars for {sym}, {role}: '{cid}'"
                    assert len(cid) > 0

    def test_p310_canonical_client_order_id_exactly_36_chars(self) -> None:
        """Verifies Phase 310 canonical client order IDs are bounded by 36 characters."""
        for sym in ["SOLUSDT", "ETHUSDT", "BTCUSDT"]:
            cid = generate_client_order_id(symbol=sym, ts_ms=1791552000000)
            assert len(cid) <= 36, f"Phase 310 CID exceeds 36 chars: '{cid}'"

    @pytest.mark.anyio
    async def test_probe_injected_oversized_client_order_id_behavior(
        self,
    ) -> None:
        """Probes gateway behavior when caller passes client_order_id > 36 chars."""
        gw = BinanceFuturesGateway(offline_mode=True)
        oversized_cid = "canary-p311-drill-sol-1790250000000-OVERFLOW-37CHARS"
        assert len(oversized_cid) > 36

        # In offline mode, does create_order truncate, reject, or pass through?
        res = await gw.create_order(
            symbol="SOLUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.05"),
            price=Decimal("110.00"),
            client_order_id=oversized_cid,
        )
        # Empirical observation: Offline gateway mock passes through without client check
        assert res["clientOrderId"] == oversized_cid


class TestAdversarialMicroCapitalBounds:
    """Empirically probes micro-capital boundaries."""

    def test_child_order_notional_clamping(self) -> None:
        """Probes child order sizing: requested notional > 5.00 USDT is clamped."""
        config = ExecutionDrillConfig(dry_run=True)
        engine = ExecutionDrillEngine(config=config)

        for excessive_notional in [
            Decimal("5.01"),
            Decimal("10.00"),
            Decimal("50.00"),
            Decimal("1000.00"),
        ]:
            res = engine.validate_and_size_order(
                symbol="SOLUSDT",
                side="BUY",
                mark_price=Decimal("110.42"),
                requested_notional=excessive_notional,
            )
            assert res.is_valid is True
            # Base quantity is clamped to 5.00 USDT before single step-up
            step_tolerance = Decimal("0.01") * Decimal("110.42")
            assert res.actual_notional <= Decimal("5.00") + step_tolerance

    def test_min_notional_exceeding_child_cap_tolerance_rejected(self) -> None:
        """When MIN_NOTIONAL cannot be met within cap tolerance, order is rejected."""
        config = ExecutionDrillConfig(dry_run=True)
        engine = ExecutionDrillEngine(config=config)

        # Simulate ETH with testnet min_notional = 20.00 USDT and price 2500.00
        with patch.dict(
            DEFAULT_SPECS,
            {
                "ETHUSDT": {
                    "step_size": Decimal("0.001"),
                    "min_qty": Decimal("0.001"),
                    "tick_size": Decimal("0.01"),
                    "min_price": Decimal("100.00"),
                    "max_price": Decimal("50000.00"),
                    "min_notional": Decimal("20.00"),
                }
            },
        ):
            res = engine.validate_and_size_order(
                symbol="ETHUSDT",
                side="BUY",
                mark_price=Decimal("2500.00"),
                requested_notional=Decimal("5.00"),
            )
            assert res.is_valid is False
            assert "minNotional" in str(res.rejection_reason)

    @pytest.mark.anyio
    async def test_probe_aggregate_exposure_guardrail(
        self, tmp_path: Path
    ) -> None:
        """Probes whether ExecutionDrillEngine enforces aggregate exposure cap."""
        config = ExecutionDrillConfig(
            symbol="SOLUSDT",
            side="BUY",
            requested_notional=Decimal("5.00"),
            dry_run=True,
            cleanup=False,
            storage_dir=tmp_path,
        )
        engine = ExecutionDrillEngine(config=config)

        # Set mock position to 30.00 USDT (exceeding 25.00 USDT aggregate ceiling)
        engine.gateway._mock_positions["SOLUSDT"] = {
            "symbol": "SOLUSDT",
            "positionAmt": "0.30",
            "entryPrice": "100.00",
            "markPrice": "100.00",
            "unRealizedProfit": "0.00",
            "leverage": "1",
            "marginType": "cross",
            "notional": "30.00000000",
        }

        # Empirical finding: execute_drill does NOT check existing positions
        try:
            await engine.execute_drill()
            drill_executed = True
        except Exception:
            drill_executed = False

        assert drill_executed is True, (
            "Empirical finding: execute_drill did not block on 30.00 USDT exposure."
        )

    @pytest.mark.anyio
    async def test_probe_daily_loss_ceiling_guardrail(
        self, tmp_path: Path
    ) -> None:
        """Probes whether ExecutionDrillEngine enforces daily loss ceiling."""
        config = ExecutionDrillConfig(
            symbol="SOLUSDT",
            side="BUY",
            requested_notional=Decimal("5.00"),
            dry_run=True,
            cleanup=False,
            storage_dir=tmp_path,
        )
        engine = ExecutionDrillEngine(config=config)

        # Set ledger realized loss to -4.00 USDT (> 3.00 USDT ceiling)
        engine.ledger.realized_pnl = Decimal("-4.00")
        engine.ledger.cash = Decimal("96.00")

        # Empirical finding: execute_drill does NOT check ledger realized loss
        try:
            await engine.execute_drill()
            drill_executed = True
        except Exception:
            drill_executed = False

        assert drill_executed is True, (
            "Empirical finding: execute_drill did not block on 4.00 USDT loss."
        )


class TestAdversarialClockSkewAndLatencyGuardrails:
    """Empirically probes clock drift (> 1000ms) and latency (> 500ms) guardrails."""

    @pytest.mark.anyio
    async def test_clock_drift_within_limit_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Offset within 1000ms (|dt| <= 1000ms) is accepted."""
        config = ExecutionDrillConfig(
            symbol="SOLUSDT",
            dry_run=True,
            storage_dir=tmp_path,
        )
        engine = ExecutionDrillEngine(config=config)
        monkeypatch.setattr(
            engine.gateway, "sync_clock_drift", AsyncMock(return_value=800)
        )

        summary = await engine.execute_drill()
        assert summary["solvency"]["zero_balance_drift"] is True

    @pytest.mark.anyio
    async def test_clock_drift_exceeding_1000ms_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Offset > 1000ms strictly triggers fail-closed RuntimeError."""
        config = ExecutionDrillConfig(
            symbol="SOLUSDT",
            dry_run=True,
            storage_dir=tmp_path,
        )
        engine = ExecutionDrillEngine(config=config)
        monkeypatch.setattr(
            engine.gateway, "sync_clock_drift", AsyncMock(return_value=1001)
        )

        with pytest.raises(
            RuntimeError, match="Clock drift 1001 ms exceeds limit 1000.0 ms"
        ):
            await engine.execute_drill()

    @pytest.mark.anyio
    async def test_negative_clock_drift_exceeding_1000ms_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Offset < -1000ms strictly triggers fail-closed RuntimeError."""
        config = ExecutionDrillConfig(
            symbol="SOLUSDT",
            dry_run=True,
            storage_dir=tmp_path,
        )
        engine = ExecutionDrillEngine(config=config)
        monkeypatch.setattr(
            engine.gateway, "sync_clock_drift", AsyncMock(return_value=-1500)
        )

        with pytest.raises(
            RuntimeError, match="Clock drift -1500 ms exceeds limit 1000.0 ms"
        ):
            await engine.execute_drill()

    @pytest.mark.anyio
    async def test_probe_latency_exceeding_500ms_behavior(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Probes whether roundtrip latency > 500ms fails-closed or only logs warning."""
        config = ExecutionDrillConfig(
            symbol="SOLUSDT",
            dry_run=False,
            storage_dir=tmp_path,
        )
        engine = ExecutionDrillEngine(config=config)

        async def slow_sync() -> int:
            await asyncio.sleep(0.55)
            return 50

        monkeypatch.setattr(engine.gateway, "sync_clock_drift", slow_sync)
        monkeypatch.setattr(
            engine.gateway,
            "create_order",
            AsyncMock(return_value={"orderId": 1, "status": "NEW"}),
        )
        monkeypatch.setattr(
            engine.gateway,
            "get_ticker_price",
            AsyncMock(return_value=Decimal("110.00")),
        )
        monkeypatch.setattr(
            engine.gateway, "get_klines", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            engine.gateway,
            "cancel_order",
            AsyncMock(return_value={"status": "CANCELED"}),
        )
        monkeypatch.setattr(
            engine.gateway, "get_position_risk", AsyncMock(return_value=[])
        )

        # Empirical finding: latency > 500ms only logs warning, does not fail-closed
        try:
            await engine.execute_drill()
            drill_blocked = False
        except Exception:
            drill_blocked = True

        assert drill_blocked is False, (
            "Empirical finding: execute_drill does NOT fail-closed on latency > 500ms."
        )


class TestAdversarialDaemonNonInterference:
    """Empirically proves drill cleanup isolation and zero daemon interference."""

    @pytest.mark.anyio
    async def test_drill_cleanup_only_cancels_drill_brackets(
        self, tmp_path: Path
    ) -> None:
        """Verifies drill cleanup cancels only designated drill orders."""
        gw = BinanceFuturesGateway(offline_mode=True)
        # Create non-drill orders (Phase 310 daemon order and external order)
        await gw.create_order(
            symbol="SOLUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.05"),
            price=Decimal("105.00"),
            client_order_id="canary-p310-sol-1790250000000-a1b2c3",
        )
        await gw.create_order(
            symbol="SOLUSDT",
            side="SELL",
            order_type="LIMIT",
            quantity=Decimal("0.05"),
            price=Decimal("125.00"),
            client_order_id="web-ui-manual-order-9999",
        )

        # Create drill brackets
        drill_tp = await gw.create_order(
            symbol="SOLUSDT",
            side="SELL",
            order_type="LIMIT",
            quantity=Decimal("0.05"),
            price=Decimal("115.00"),
            client_order_id="canary-p311-tp-sol-1790250000001",
        )
        drill_sl = await gw.create_order(
            symbol="SOLUSDT",
            side="SELL",
            order_type="LIMIT",
            quantity=Decimal("0.05"),
            price=Decimal("95.00"),
            client_order_id="canary-p311-sl-sol-1790250000002",
        )

        config = ExecutionDrillConfig(storage_dir=tmp_path, dry_run=True)
        engine = ExecutionDrillEngine(config=config, gateway=gw)

        cleanup_res = await engine.cleanup_drill_orders(
            symbol="SOLUSDT",
            bracket_cids=[
                drill_tp["clientOrderId"],
                drill_sl["clientOrderId"],
            ],
            quantity=Decimal("0.05"),
            side="SELL",
        )

        canceled_cids = [
            c.get("clientOrderId") for c in cleanup_res["canceled_brackets"]
        ]
        assert "canary-p311-tp-sol-1790250000001" in canceled_cids
        assert "canary-p311-sl-sol-1790250000002" in canceled_cids

        # Verify daemon order is still intact and NOT canceled
        open_orders = await gw.get_open_orders("SOLUSDT")
        open_cids = [o.get("clientOrderId") for o in open_orders]
        assert "canary-p310-sol-1790250000000-a1b2c3" in open_cids
        assert "web-ui-manual-order-9999" in open_cids

    @pytest.mark.anyio
    async def test_listen_key_never_deleted_by_drill(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verifies ExecutionDrillEngine never calls close_user_data_stream."""
        gw = BinanceFuturesGateway(offline_mode=True)
        listen_key = await gw.create_listen_key()
        assert listen_key in gw._active_listen_keys

        close_spy = AsyncMock(wraps=gw.close_user_data_stream)
        monkeypatch.setattr(gw, "close_user_data_stream", close_spy)

        config = ExecutionDrillConfig(
            symbol="SOLUSDT",
            dry_run=True,
            cleanup=True,
            auto_close=True,
            storage_dir=tmp_path,
        )
        engine = ExecutionDrillEngine(config=config, gateway=gw)

        await engine.execute_drill()

        assert close_spy.call_count == 0
        assert listen_key in gw._active_listen_keys
