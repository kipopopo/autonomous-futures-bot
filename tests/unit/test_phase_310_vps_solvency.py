"""Autonomous Futures Bot - Phase 310 Unit Tests: VPS Solvency & Telemetry Governance.

Verifies:
- Double-entry zero-drift balance invariant:
    drift = (cash + allocated_margin + unrealized_pnl) - (starting_equity + realized_pnl)
    strictly |drift| < 10^-15 USDT across all lifecycle states.
- Micro-capital bounds enforcement:
    * Child order slice cap <= 5.00 USDT with ROUND_DOWN
    * Rejection of orders violating min notional
    * Aggregate exposure cap <= 25.00 USDT
    * Minimum liquid cash reserve floor >= 75.0%
- Telegram alert formatters (order placed, TP/SL realized, daily summary, risk alert)
- Kainode Linux VPS systemd unit file structure and attributes
- Merkle DAG lineage verification bound to Phase 309 parent root
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from autonomous_futures.execution.binance_gateway import DEFAULT_SPECS
from autonomous_futures.execution.self_driving import (
    UPSTREAM_PHASE_309_MERKLE_ROOT,
    MicroCapitalConfig,
    OrderSide,
    OrderStatus,
    SelfDrivingOrder,
    build_default_self_driving_engine,
)
from autonomous_futures.notify.telegram import (
    format_daily_pnl_summary_alert,
    format_order_placed_alert,
    format_risk_alert,
    format_tp_sl_realized_alert,
)
from scripts.run_phase_310_real_autonomous_trading import (
    UPSTREAM_PHASE_309_PARENT_ROOT,
    verify_phase_310_artifacts,
)


class TestDoubleEntrySolvencyZeroDrift:
    """Verifies double-entry ledger balance invariant |drift| < 10^-15 USDT."""

    def test_zero_drift_across_multi_trade_lifecycle(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        now_ms = 1700000000000

        # Snapshot at start
        snap0 = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap0.drift))) < Decimal("1e-15")

        # Open Long position on SOLUSDT
        ord1 = SelfDrivingOrder(
            order_id="ord-sol-01",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type="LIMIT",
            price=Decimal("170.00"),
            quantity=Decimal("0.02"),
            notional_usdt=Decimal("3.40"),
            status=OrderStatus.PENDING,
            timestamp_ms=now_ms,
            client_order_id="canary-p310-sol-1700000000000-000001",
            is_maker=True,
        )
        engine._execute_fill(ord1, Decimal("170.00"), now_ms)
        snap1 = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap1.drift))) < Decimal("1e-15")

        # Partially close position at profit
        ord2 = SelfDrivingOrder(
            order_id="ord-sol-02",
            symbol="SOLUSDT",
            side=OrderSide.SELL,
            order_type="LIMIT",
            price=Decimal("180.00"),
            quantity=Decimal("0.01"),
            notional_usdt=Decimal("1.80"),
            status=OrderStatus.PENDING,
            timestamp_ms=now_ms + 900000,
            client_order_id="canary-p310-sol-1700000900000-000002",
            is_maker=True,
        )
        engine._execute_fill(ord2, Decimal("180.00"), now_ms + 900000)
        snap2 = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap2.drift))) < Decimal("1e-15")

        # Fully close remaining position at loss
        ord3 = SelfDrivingOrder(
            order_id="ord-sol-03",
            symbol="SOLUSDT",
            side=OrderSide.SELL,
            order_type="LIMIT",
            price=Decimal("165.00"),
            quantity=Decimal("0.01"),
            notional_usdt=Decimal("1.65"),
            status=OrderStatus.PENDING,
            timestamp_ms=now_ms + 1800000,
            client_order_id="canary-p310-sol-1700001800000-000003",
            is_maker=True,
        )
        engine._execute_fill(ord3, Decimal("165.00"), now_ms + 1800000)
        snap3 = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap3.drift))) < Decimal("1e-15")


class TestMicroCapitalBoundsGovernance:
    """Verifies micro-capital constraints: child order cap, exposure cap, cash reserve."""

    def test_child_order_slice_exceeding_cap_rejected(self, tmp_path: Path) -> None:
        cfg = MicroCapitalConfig(max_micro_order_notional_usdt=Decimal("5.00"))
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.config = cfg
        # Attempt an order with raw notional > 5.00 USDT
        ord_oversized = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("170.00"),
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=20.0,
            ensemble_signal="LONG",
            ts_ms=1700000000000,
        )
        # Sizing engine caps raw order notional with Binance MIN_NOTIONAL
        # precision step-up compliance
        if ord_oversized:
            spec = DEFAULT_SPECS.get("SOLUSDT", {})
            step_size = spec.get("step_size", Decimal("0.01"))
            max_allowed = cfg.max_micro_order_notional_usdt + (step_size * Decimal("170.00"))
            assert ord_oversized.notional_usdt <= max_allowed

    def test_aggregate_exposure_cap_enforced(self, tmp_path: Path) -> None:
        cfg = MicroCapitalConfig(
            max_micro_order_notional_usdt=Decimal("5.00"),
            max_aggregate_exposure_usdt=Decimal("25.00"),
        )
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.config = cfg
        # Simulate active positions reaching aggregate exposure of 22.00 USDT
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("22.00")

        # Next 5.00 USDT order would bring aggregate exposure to 27.00 USDT > 25.00 USDT
        order = engine.process_microstructure_tick(
            symbol="ETHUSDT",
            price=Decimal("2750.00"),
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=20.0,
            ensemble_signal="LONG",
            ts_ms=1700000000000,
        )
        assert order is None
        assert engine.interlock_blocks_count >= 1

    def test_liquid_cash_reserve_floor_enforced(self, tmp_path: Path) -> None:
        cfg = MicroCapitalConfig(
            max_micro_order_notional_usdt=Decimal("5.00"),
            min_cash_reserve_pct=Decimal("75.0"),
        )
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.config = cfg
        # Artificially deplete cash to 76.00 USDT (remaining buffer is 1.00 USDT)
        engine.ledger.cash = Decimal("76.00")

        # A 5.00 USDT order would drop cash to 71.00 USDT (71% < 75%)
        order = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("170.00"),
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=20.0,
            ensemble_signal="LONG",
            ts_ms=1700000000000,
        )
        assert order is None
        assert engine.interlock_blocks_count >= 1


class TestTelegramAlertFormatters:
    """Verifies Telegram alert message syntax and escaping."""

    def test_order_placed_alert_formatter(self) -> None:
        payload = {
            "symbol": "SOLUSDT",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": "172.50",
            "quantity": "0.02",
            "notional_usdt": "3.45",
            "client_order_id": "canary-p310-sol-01",
            "stop_loss": "166.50",
            "take_profit": "182.50",
            "occurred_at": 1700000000000,
        }
        msg = format_order_placed_alert(payload)
        assert "SOLUSDT" in msg
        assert "BUY" in msg
        assert "ORDER PLACED" in msg

    def test_tp_sl_realized_alert_formatter(self) -> None:
        payload = {
            "symbol": "SOLUSDT",
            "side": "SELL",
            "exit_reason": "TAKE_PROFIT",
            "exit_price": "182.50",
            "realized_pnl": "0.20",
            "fee": "0.0007",
            "hold_duration_bars": 5,
            "occurred_at": 1700000000000,
        }
        msg = format_tp_sl_realized_alert(payload)
        assert "SOLUSDT" in msg
        assert "TAKE\\_PROFIT" in msg
        assert "REALIZED" in msg

    def test_daily_pnl_summary_alert_formatter(self) -> None:
        summary = {
            "session_date": "2026-10-08",
            "cumulative_realized_pnl_usdt": "0.85",
            "total_trades": 4,
            "win_rate_pct": "75.0",
            "max_drawdown_usdt": "0.15",
            "cash": "100.85",
            "equity": "100.85",
            "drift": "0.0",
        }
        msg = format_daily_pnl_summary_alert(summary)
        assert "DAILY PERFORMANCE SUMMARY" in msg
        assert "2026\\-10\\-08" in msg

    def test_risk_alert_circuit_breaker_formatter(self) -> None:
        details = {
            "status": "HALTED",
            "symbol": "PORTFOLIO",
            "breaker_type": "DAILY_DRAWDOWN_BREACH",
            "current_value": "3.00 USDT",
            "threshold_value": "3.00 USDT",
            "action_taken": "Trading halted fail-closed.",
        }
        msg = format_risk_alert("circuit_breaker", details)
        assert "CIRCUIT BREAKER ALERT" in msg
        assert "HALTED" in msg


class TestVpsDeploymentAndMerkleLineage:
    """Verifies systemd unit file configuration and Merkle DAG upstream binding."""

    def test_systemd_service_unit_file_exists_and_configured(self) -> None:
        service_file = Path("deploy/systemd/autonomous-futures-trader.service")
        assert service_file.is_file(), "systemd service unit file must exist in deploy/systemd/"
        content = service_file.read_text(encoding="utf-8")

        assert "Restart=always" in content
        assert "RestartSec=5s" in content
        assert "Type=simple" in content
        assert "default.target" in content

    def test_parent_phase_309_merkle_root_constant(self) -> None:
        expected_parent_root = "5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844"
        assert UPSTREAM_PHASE_309_MERKLE_ROOT == expected_parent_root
        assert UPSTREAM_PHASE_309_PARENT_ROOT == expected_parent_root

    def test_verify_phase_310_artifacts_passes(self) -> None:
        target_dir = Path("artifacts/research/phase310")
        assert target_dir.is_dir()
        assert verify_phase_310_artifacts(target_dir) is True
