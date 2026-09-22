"""Unit tests for Phase 301: Live User Data Stream Ingress & Dynamic Bracket Order Management."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.feed.bracket_positions import (
    BracketStatus,
    BracketType,
    CanaryBracketPositionsRunner,
    DynamicBracketOrderManager,
    LiquidationRiskState,
    MultiAssetPositionTracker,
    PositionSide,
    UserDataEventType,
    UserDataStreamIngressManager,
    verify_phase_301_dag,
)


@pytest.fixture
def ingress_manager() -> UserDataStreamIngressManager:
    return UserDataStreamIngressManager()


@pytest.fixture
def bracket_manager() -> DynamicBracketOrderManager:
    return DynamicBracketOrderManager()


@pytest.fixture
def position_tracker() -> MultiAssetPositionTracker:
    return MultiAssetPositionTracker(starting_equity=Decimal("100.00"))


# =====================================================================
# R1: UserDataStreamIngressManager Tests
# =====================================================================


def test_ingress_listen_key_lifecycle(ingress_manager: UserDataStreamIngressManager) -> None:
    """Verify listenKey generation, keepalive ping, and closure."""
    key = ingress_manager.create_listen_key()
    assert key.startswith("lk-")
    assert ingress_manager.is_connected is True

    keepalive_ok = ingress_manager.ping_keepalive()
    assert keepalive_ok is True

    ingress_manager.close_listen_key()
    assert ingress_manager.is_connected is False
    assert ingress_manager.listen_key is None


def test_ingress_emit_event_and_heartbeat(
    ingress_manager: UserDataStreamIngressManager,
) -> None:
    """Verify event emission, payload parsing, and heartbeat freshness."""
    ingress_manager.create_listen_key()
    evt = ingress_manager.emit_event(
        UserDataEventType.ACCOUNT_UPDATE,
        {"balances": [{"asset": "USDT", "walletBalance": "100.00"}]},
        symbol="BTCUSDT",
    )

    assert evt.event_id.startswith("evt-")
    assert evt.event_type == UserDataEventType.ACCOUNT_UPDATE
    assert evt.symbol == "BTCUSDT"
    assert len(ingress_manager.events_log) == 1
    assert ingress_manager.get_heartbeat_age_ms() <= 500.0


# =====================================================================
# R2: DynamicBracketOrderManager Tests
# =====================================================================


def test_bracket_binding_compliance(bracket_manager: DynamicBracketOrderManager) -> None:
    """Verify TP and Trailing SL brackets are bound with micro cap constraint."""
    tp, tsl = bracket_manager.bind_brackets_to_position(
        entry_order_id="cl-entry-001",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        entry_price=Decimal("50000.0"),
        quantity=Decimal("0.0001"),
    )

    assert tp.bracket_type == BracketType.TAKE_PROFIT_LIMIT
    assert tp.side == "SELL"
    assert tp.status == BracketStatus.ARMED
    assert tp.notional_usdt <= Decimal("5.00")
    assert tp.trigger_price > Decimal("50000.0")  # +1.5% TP

    assert tsl.bracket_type == BracketType.TRAILING_STOP_MARKET
    assert tsl.side == "SELL"
    assert tsl.status == BracketStatus.ARMED
    assert tsl.trigger_price < Decimal("50000.0")  # Initial SL level


def test_bracket_trailing_stop_ratchet_long(
    bracket_manager: DynamicBracketOrderManager,
) -> None:
    """Verify trailing stop ratchet increases on price rise and preserves on drop (LONG)."""
    _, tsl = bracket_manager.bind_brackets_to_position(
        entry_order_id="cl-entry-002",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        entry_price=Decimal("50000.0"),
        quantity=Decimal("0.0001"),
    )

    initial_trigger = tsl.trigger_price
    initial_watermark = tsl.ratchet_watermark

    # Mark price rises to 51000
    updated = bracket_manager.update_ratchet(
        tsl, current_mark_price=Decimal("51000.0"), position_side=PositionSide.LONG
    )
    assert updated is True
    assert tsl.ratchet_watermark == Decimal("51000.0")
    assert tsl.trigger_price > initial_trigger

    high_watermark = tsl.ratchet_watermark
    high_trigger = tsl.trigger_price

    # Mark price retraces to 50500 - ratchet must NOT decrease
    updated_drop = bracket_manager.update_ratchet(
        tsl, current_mark_price=Decimal("50500.0"), position_side=PositionSide.LONG
    )
    assert updated_drop is False
    assert tsl.ratchet_watermark == high_watermark
    assert tsl.trigger_price == high_trigger
    assert tsl.trigger_price > initial_watermark * Decimal("0.99")


def test_bracket_trailing_stop_ratchet_short(
    bracket_manager: DynamicBracketOrderManager,
) -> None:
    """Verify trailing stop ratchet decreases on price fall and preserves on rise (SHORT)."""
    _, tsl = bracket_manager.bind_brackets_to_position(
        entry_order_id="cl-entry-003",
        symbol="ETHUSDT",
        side=PositionSide.SHORT,
        entry_price=Decimal("2500.0"),
        quantity=Decimal("0.002"),
    )

    initial_trigger = tsl.trigger_price

    # Mark price falls to 2400 (favorable for SHORT)
    updated = bracket_manager.update_ratchet(
        tsl, current_mark_price=Decimal("2400.0"), position_side=PositionSide.SHORT
    )
    assert updated is True
    assert tsl.ratchet_watermark == Decimal("2400.0")
    assert tsl.trigger_price < initial_trigger

    low_watermark = tsl.ratchet_watermark
    low_trigger = tsl.trigger_price

    # Mark price rises back to 2450 - ratchet must NOT increase
    updated_rise = bracket_manager.update_ratchet(
        tsl, current_mark_price=Decimal("2450.0"), position_side=PositionSide.SHORT
    )
    assert updated_rise is False
    assert tsl.ratchet_watermark == low_watermark
    assert tsl.trigger_price == low_trigger


def test_bracket_oco_coordination(bracket_manager: DynamicBracketOrderManager) -> None:
    """Verify OCO coordination: filling TP automatically cancels opposing TSL."""
    tp, tsl = bracket_manager.bind_brackets_to_position(
        entry_order_id="cl-entry-004",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        entry_price=Decimal("50000.0"),
        quantity=Decimal("0.0001"),
    )

    triggered_tp, canceled_tsl = bracket_manager.coordinate_oco_trigger(
        tp.bracket_id, fill_price=tp.trigger_price, is_maker=True
    )

    assert triggered_tp.status == BracketStatus.FILLED
    assert triggered_tp.fee_usdt > Decimal("0.0")
    assert canceled_tsl is not None
    assert canceled_tsl.status == BracketStatus.CANCELED
    assert "OCO mutual cancellation" in (canceled_tsl.cancellation_reason or "")


# =====================================================================
# R3: MultiAssetPositionTracker Tests
# =====================================================================


def test_position_tracker_open_and_margin_allocation(
    position_tracker: MultiAssetPositionTracker,
) -> None:
    """Verify opening position allocates isolated margin and computes liquidation price."""
    pos = position_tracker.open_or_increase_position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        fill_price=Decimal("50000.0"),
        quantity=Decimal("0.0001"),  # 5.00 USDT
    )

    assert pos.symbol == "BTCUSDT"
    assert pos.side == PositionSide.LONG
    assert pos.size == Decimal("0.0001")
    assert pos.margin_allocated_usdt == Decimal("5.00") / Decimal("3.0")
    assert pos.liquidation_price_usdt < Decimal("50000.0")
    assert position_tracker.cash < Decimal("100.00")


def test_position_tracker_mark_to_market_and_margin_ratio(
    position_tracker: MultiAssetPositionTracker,
) -> None:
    """Verify mark-to-market updates unrealized PnL and calculates margin ratio."""
    position_tracker.open_or_increase_position(
        symbol="ETHUSDT",
        side=PositionSide.LONG,
        fill_price=Decimal("2500.0"),
        quantity=Decimal("0.002"),  # 5.00 USDT
    )

    # Mark price rises to 2600
    pos = position_tracker.update_position_mark("ETHUSDT", Decimal("2600.0"))
    assert pos is not None
    assert pos.unrealized_pnl_usdt == Decimal("0.002") * Decimal("100.0")  # +0.20 USDT
    assert pos.risk_state == LiquidationRiskState.NORMAL


def test_position_tracker_liquidation_emergency_flattening(
    position_tracker: MultiAssetPositionTracker,
) -> None:
    """Verify severe adverse move triggers FAIL_CLOSED_FLATTENED risk state."""
    position_tracker.open_or_increase_position(
        symbol="SOLUSDT",
        side=PositionSide.LONG,
        fill_price=Decimal("150.0"),
        quantity=Decimal("0.03"),  # 4.50 USDT
    )

    # Adverse price crash near liquidation price (margin ratio breaches emergency threshold >= 70%)
    pos = position_tracker.update_position_mark("SOLUSDT", Decimal("101.2"))
    assert pos is not None
    assert pos.margin_ratio_pct >= Decimal("70.0")
    assert pos.risk_state == LiquidationRiskState.FAIL_CLOSED_FLATTENED

    # Emergency flattening
    pnl = position_tracker.flatten_position("SOLUSDT", exit_price=Decimal("101.2"))
    assert pnl < Decimal("0.0")
    assert pos.side == PositionSide.FLAT
    assert pos.size == Decimal("0.0")


# =====================================================================
# R4: Double-Entry Zero-Drift & Merkle DAG Tests
# =====================================================================


def test_position_tracker_double_entry_zero_drift_reconciliation(
    position_tracker: MultiAssetPositionTracker,
) -> None:
    """Verify strict double-entry balance reconciliation with |drift| < 1e-15 USDT."""
    # Open BTC position
    position_tracker.open_or_increase_position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        fill_price=Decimal("50000.0"),
        quantity=Decimal("0.0001"),
    )
    # Open ETH position
    position_tracker.open_or_increase_position(
        symbol="ETHUSDT",
        side=PositionSide.LONG,
        fill_price=Decimal("2500.0"),
        quantity=Decimal("0.002"),
    )

    # Update marks
    position_tracker.update_position_mark("BTCUSDT", Decimal("50500.0"))
    position_tracker.update_position_mark("ETHUSDT", Decimal("2480.0"))

    # Flatten BTC position with profit
    position_tracker.flatten_position("BTCUSDT", exit_price=Decimal("50500.0"), is_maker=True)

    solvency = position_tracker.reconcile_balances()
    assert solvency.drift < Decimal("1e-15")
    assert solvency.zero_balance_drift_verified is True
    assert solvency.cash_reserve_pct >= Decimal("40.0")


def test_runner_deterministic_execution_and_merkle_dag(tmp_path: Path) -> None:
    """Verify CanaryBracketPositionsRunner executes deterministically and chains Merkle DAG."""
    runner = CanaryBracketPositionsRunner(output_dir=tmp_path / "phase301")
    summary = runner.run_all(seed=42)

    assert summary["phase"] == "phase_301"
    assert summary["status"] == "BRACKET_POSITIONS_VERIFIED"
    assert summary["paper_safe"] is True
    assert summary["execution_authority"] is False
    assert summary["solvency"]["zero_balance_drift_verified"] is True
    assert len(summary["brackets"]) >= 2
    assert summary["merkle_root"] != ""

    summary_file = tmp_path / "phase301" / "bracket-position-summary.json"
    assert summary_file.is_file()
    assert verify_phase_301_dag(summary_file) is True
