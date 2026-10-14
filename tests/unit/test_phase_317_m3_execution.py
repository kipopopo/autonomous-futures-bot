"""Phase 317 Milestone 3 Unit Tests: Execution, Micro-Capital Governance & Continuous Integration.

Verifies:
- Suite 1: TestOrderTaggingFormatAndLength (<= 36 chars, canary-p317-ict-..., collision freedom)
- Suite 2: TestChildOrderCapAndStepSizeQuantization ($5.00 cap, LOT_SIZE, step-up compliance)
- Suite 3: TestPortfolioExposureCap ($25.00 USDT ceiling rejection and recovery)
- Suite 4: TestLiquidCashReserveFloor (>= 75.0% unencumbered cash floor rejection)
- Suite 5: TestDailyLossLimitFailClosedCircuitBreaker ($3.00 loss flattening and halting)
- Suite 6: TestDoubleEntryLedgerBalanceConservation (|Delta| < 10^-15 USDT across transitions)
- Suite 7: TestOrderDispatchStateMachine (step_6_ready -> entry -> fill -> protective brackets)
- Suite 8: TestContinuousTraderNonBlockingCycleLatency (< 15ms cycle execution overhead)
"""

from __future__ import annotations

import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from unittest.mock import AsyncMock, patch

import pytest

from autonomous_futures.execution.binance_gateway import (
    DEFAULT_SPECS,
    BinanceFuturesGateway,
    generate_p317_ict_client_order_id,
)
from autonomous_futures.execution.continuous_trader import ContinuousSelfDrivingTrader
from autonomous_futures.execution.self_driving import (
    OrderSide,
    OrderStatus,
    SelfDrivingState,
    build_default_self_driving_engine,
)
from autonomous_futures.feed.kline_sequencer import (
    ACTIVE_PAIRS,
    ACTIVE_TIMEFRAMES,
)
from autonomous_futures.strategy.ict_mmxm import (
    Candle,
    PdArray,
    PdArrayType,
    SetupDirection,
    TwinsSetupState,
    TwinsStep,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle as MacroCandle,
)

# =============================================================================
# Helper Utilities & Fixtures
# =============================================================================

def _build_test_candle(ts_ms: int, p: str = "100.0", vol: str = "1000.0") -> Candle:
    d = Decimal(p)
    return Candle(
        timestamp_ms=ts_ms,
        open=d,
        high=d + Decimal("1.0"),
        low=d - Decimal("1.0"),
        close=d + Decimal("0.5"),
        volume=Decimal(vol),
    )


def _build_test_macro_candle(ts_ms: int, p: str = "100.0", vol: str = "1000.0") -> MacroCandle:
    d = Decimal(p)
    return MacroCandle(
        timestamp_ms=ts_ms,
        open=d,
        high=d + Decimal("1.0"),
        low=d - Decimal("1.0"),
        close=d + Decimal("0.5"),
        volume=Decimal(vol),
    )


def _build_mock_twins_state(
    symbol: str = "SOLUSDT",
    side: Literal["BUY", "SELL"] = "BUY",
    entry_price: Decimal = Decimal("170.00"),
    stop_loss: Decimal = Decimal("165.00"),
    tp_partial: Decimal = Decimal("180.00"),
    tp_final: Decimal = Decimal("195.00"),
    step_6_ready: bool = True,
) -> TwinsSetupState:
    return TwinsSetupState(
        symbol=symbol,
        step_1_htf_hit=True,
        step_2_m5_cisd=True,
        step_3_twins_fvg=True,
        step_4_ote_retrace=True,
        step_5_m1_cisd=True,
        step_6_ready=step_6_ready,
        active_pda=PdArray(
            array_type=PdArrayType.FVG_BISI,
            timeframe="15m",
            top=Decimal("172.00"),
            bottom=Decimal("168.00"),
            mean_threshold=Decimal("170.00"),
            direction=SetupDirection.BULLISH.value,
            creation_ts=1700000000000,
        ),
        m5_cisd_price=Decimal("169.00"),
        m1_cisd_price=entry_price,
        ote_62=Decimal("169.50"),
        ote_705=entry_price,
        ote_79=Decimal("167.00"),
        stdv_2_0=tp_partial,
        stdv_4_0=tp_final,
        stop_loss=stop_loss,
        take_profit_partial=tp_partial,
        take_profit_final=tp_final,
        side=side,
        step=TwinsStep.STEP_6_READY if step_6_ready else TwinsStep.STEP_4_OTE_RETRACE,
    )


# =============================================================================
# Suite 1: TestOrderTaggingFormatAndLength
# =============================================================================

class TestOrderTaggingFormatAndLength:
    """Verifies deterministic client order ID syntax, max 36-char bounds, and uniqueness."""

    def test_p317_ict_client_order_id_format_and_max_length_all_pairs(self) -> None:
        ts = 1700000000000
        for sym in ACTIVE_PAIRS:
            cid = generate_p317_ict_client_order_id(sym, ts_ms=ts, role="ict")
            assert len(cid) <= 36, f"Order tag length {len(cid)} exceeds 36 chars for {sym}: {cid}"
            assert len(cid) == 36, f"Expected exactly 36 chars, got {len(cid)}: {cid}"
            # Format: canary-p317-ict-{sym[:3]}-{13-digit-ts}-{2-char-hex}
            assert re.match(r"^canary-p317-ict-[a-z]{3}-\d{13}-[a-f0-9]{2}$", cid)

    def test_p317_bracket_order_id_format_and_length(self) -> None:
        ts = 1700000000000
        tp_cid = generate_p317_ict_client_order_id("SOLUSDT", ts_ms=ts, role="tp")
        sl_cid = generate_p317_ict_client_order_id("SOLUSDT", ts_ms=ts, role="sl")

        assert len(tp_cid) <= 36
        assert len(sl_cid) <= 36
        assert re.match(r"^canary-p317-tp-[a-z]{3}-\d{13}-[a-f0-9]{2}$", tp_cid)
        assert re.match(r"^canary-p317-sl-[a-z]{3}-\d{13}-[a-f0-9]{2}$", sl_cid)

    def test_client_order_id_collision_freedom_under_burst(self) -> None:
        generated = [generate_p317_ict_client_order_id("ETHUSDT") for _ in range(1000)]
        assert len(set(generated)) == 1000, "Collision detected in burst client order ID generation"


# =============================================================================
# Suite 2: TestChildOrderCapAndStepSizeQuantization
# =============================================================================

class TestChildOrderCapAndStepSizeQuantization:
    """Verifies child order sizing adheres strictly to <= 5.00 USDT cap with Binance stepSize."""

    @pytest.mark.parametrize("symbol,price_str", [
        ("BTCUSDT", "82600.00"),
        ("ETHUSDT", "2500.00"),
        ("SOLUSDT", "170.00"),
        ("DOGEUSDT", "0.08600"),
        ("BNBUSDT", "750.00"),
        ("XRPUSDT", "1.4000"),
        ("SUIUSDT", "1.1100"),
        ("AVAXUSDT", "10.500"),
    ])
    def test_child_order_cap_enforced_across_active_pairs(
        self, tmp_path: Path, symbol: str, price_str: str
    ) -> None:
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        price = Decimal(price_str)
        spec = DEFAULT_SPECS.get(symbol, {})
        step_size = spec.get("step_size", Decimal("0.001"))
        tick_size = spec.get("tick_size", Decimal("0.01"))
        if getattr(engine.gateway, "testnet", True) and symbol == "BTCUSDT":
            step_size = Decimal("0.00001")

        q_price, q_qty, notional = engine._calculate_child_order_qty(symbol, price)

        max_allowed_notional = engine.config.max_micro_order_notional_usdt + (step_size * q_price)
        assert notional <= max_allowed_notional, (
            f"{symbol} notional {notional} exceeded max allowed {max_allowed_notional}"
        )

        # Clean multiple of step_size
        if q_qty > Decimal("0"):
            steps_count = q_qty / step_size
            assert steps_count == steps_count.to_integral_value(), (
                f"{symbol} qty {q_qty} not clean multiple of step {step_size}"
            )

        # Clean multiple of tick_size
        ticks_count = q_price / tick_size
        assert ticks_count == ticks_count.to_integral_value(), (
            f"{symbol} price {q_price} not clean multiple of tick {tick_size}"
        )

    def test_child_order_sub_step_size_quantization_safety(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        # Absurdly high price where 5.00 USDT is less than 1 step size without step-up
        q_price, q_qty, notional = engine._calculate_child_order_qty(
            "ETHUSDT", Decimal("10000000.00")
        )
        assert q_qty == Decimal("0.0")
        assert notional == Decimal("0.0")


# =============================================================================
# Suite 3: TestPortfolioExposureCap
# =============================================================================

class TestPortfolioExposureCap:
    """Verifies aggregate exposure ceiling ($25.00 USDT) blocks excess orders fail-closed."""

    def test_portfolio_exposure_cap_rejection_at_25_usdt(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        # Simulate 4 open positions with $5.00 allocated exposure each = $20.00 total
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("5.00")
        engine.candidates["ETHUSDT"].allocated_exposure_usdt = Decimal("5.00")
        engine.candidates["DOGEUSDT"].allocated_exposure_usdt = Decimal("5.00")
        engine.candidates["XRPUSDT"].allocated_exposure_usdt = Decimal("5.00")

        current_exposure = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
        assert current_exposure == Decimal("20.00")

        # Order 5 on SUIUSDT ($5.00 notional) brings exposure to $25.00 -> APPROVED
        setup_sui = _build_mock_twins_state(symbol="SUIUSDT", entry_price=Decimal("1.25"))
        order_sui = engine.dispatch_ict_intention(setup_sui)
        assert order_sui is not None
        assert order_sui.symbol == "SUIUSDT"

        # Order 6 on AVAXUSDT ($5.00 notional) would push exposure > $25.00 -> REJECTED
        setup_avax = _build_mock_twins_state(symbol="AVAXUSDT", entry_price=Decimal("10.50"))
        blocks_before = engine.interlock_blocks_count
        order_avax = engine.dispatch_ict_intention(setup_avax)
        assert order_avax is None
        assert engine.interlock_blocks_count == blocks_before + 1

    def test_portfolio_exposure_allows_order_after_position_flattening(
        self, tmp_path: Path
    ) -> None:
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("25.00")
        setup_eth = _build_mock_twins_state(symbol="ETHUSDT", entry_price=Decimal("2500.00"))
        assert engine.dispatch_ict_intention(setup_eth) is None

        # Flatten SOL position
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("0.00")
        order = engine.dispatch_ict_intention(setup_eth)
        assert order is not None


# =============================================================================
# Suite 4: TestLiquidCashReserveFloor
# =============================================================================

class TestLiquidCashReserveFloor:
    """Verifies liquid cash reserve floor (>= 75.0%) rejects order slicing when cash is low."""

    def test_liquid_cash_reserve_floor_rejection_below_75_pct(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.perform_preflight_checks()

        # Deplete cash to $76.00 USDT (76.0% reserve)
        engine.ledger.cash = Decimal("76.00")

        # Submitting an order of ~$5.00 would leave ~$71.00 cash (71% < 75%) -> REJECTED
        setup = _build_mock_twins_state(symbol="SOLUSDT", entry_price=Decimal("170.00"))
        blocks_before = engine.interlock_blocks_count
        order = engine.dispatch_ict_intention(setup)

        assert order is None
        assert engine.interlock_blocks_count == blocks_before + 1

    def test_liquid_cash_reserve_boundary_approved_above_75_pct(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.perform_preflight_checks()

        # Cash at $85.00 USDT. An order of $5.00 leaves $80.00 (80% >= 75%) -> APPROVED
        engine.ledger.cash = Decimal("85.00")
        setup = _build_mock_twins_state(symbol="SOLUSDT", entry_price=Decimal("170.00"))
        order = engine.dispatch_ict_intention(setup)
        assert order is not None


# =============================================================================
# Suite 5: TestDailyLossLimitFailClosedCircuitBreaker
# =============================================================================

class TestDailyLossLimitFailClosedCircuitBreaker:
    """Verifies $3.00 USDT daily loss budget trigger auto-flattens all positions fail-closed."""

    def test_daily_loss_limit_trigger_and_fail_closed_flattening(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()
        now_ms = 1700000000000

        # Open positions on SOLUSDT and ETHUSDT
        setup_sol = _build_mock_twins_state(symbol="SOLUSDT", entry_price=Decimal("170.00"))
        setup_eth = _build_mock_twins_state(symbol="ETHUSDT", entry_price=Decimal("2500.00"))
        ord_sol = engine.dispatch_ict_intention(setup_sol, now_ms=now_ms)
        ord_eth = engine.dispatch_ict_intention(setup_eth, now_ms=now_ms)
        assert ord_sol and ord_eth

        assert engine.candidates["SOLUSDT"].position_qty > Decimal("0")
        assert engine.candidates["ETHUSDT"].position_qty > Decimal("0")

        # Simulate losing exit on SOL resulting in -$1.80 loss
        engine.intra_day_loss_usdt = Decimal("1.80")
        assert engine.state.value == SelfDrivingState.MICRO_CAPITAL_ACTIVE.value

        # Simulate second loss of -$1.50, bringing total loss to $3.30 >= $3.00 ceiling
        engine.intra_day_loss_usdt = Decimal("3.30")

        # Attempt to dispatch next tick/intention
        setup_doge = _build_mock_twins_state(symbol="DOGEUSDT", entry_price=Decimal("0.086"))
        order_doge = engine.dispatch_ict_intention(setup_doge, now_ms=now_ms + 60000)

        assert order_doge is None
        assert engine.state.value == SelfDrivingState.CIRCUIT_FLATTENED.value
        # All positions must be flattened to 0
        assert engine.candidates["SOLUSDT"].position_qty == Decimal("0.0")
        assert engine.candidates["ETHUSDT"].position_qty == Decimal("0.0")

    def test_no_new_orders_permitted_while_circuit_flattened(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.state = SelfDrivingState.CIRCUIT_FLATTENED
        setup = _build_mock_twins_state(symbol="XRPUSDT", entry_price=Decimal("1.40"))
        assert engine.dispatch_ict_intention(setup) is None


# =============================================================================
# Suite 6: TestDoubleEntryLedgerBalanceConservation
# =============================================================================

class TestDoubleEntryLedgerBalanceConservation:
    """Verifies double-entry ledger balance conservation (|drift| < 10^-15 USDT)."""

    def test_ledger_zero_drift_at_entry_fill(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.perform_preflight_checks()

        snap0 = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap0.drift))) < Decimal("1e-15")

        setup = _build_mock_twins_state(symbol="SOLUSDT", entry_price=Decimal("170.00"))
        order = engine.dispatch_ict_intention(setup, now_ms=1700000000000)
        assert order is not None

        snap1 = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap1.drift))) < Decimal("1e-15")

    def test_ledger_zero_drift_during_unrealized_pnl_fluctuation(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.perform_preflight_checks()

        setup = _build_mock_twins_state(symbol="SOLUSDT", entry_price=Decimal("170.00"))
        engine.dispatch_ict_intention(setup, now_ms=1700000000000)

        # Mark price surges to 200.00 USDT
        engine.candidates["SOLUSDT"].current_price = Decimal("200.00")
        engine.candidates["SOLUSDT"].unrealized_pnl_usdt = (
            Decimal("200.00") - Decimal("170.00")
        ) * engine.candidates["SOLUSDT"].position_qty
        engine.ledger.unrealized_pnl = engine.candidates["SOLUSDT"].unrealized_pnl_usdt

        snap_bull = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap_bull.drift))) < Decimal("1e-15")

        # Mark price dumps to 140.00 USDT
        engine.candidates["SOLUSDT"].current_price = Decimal("140.00")
        engine.candidates["SOLUSDT"].unrealized_pnl_usdt = (
            Decimal("140.00") - Decimal("170.00")
        ) * engine.candidates["SOLUSDT"].position_qty
        engine.ledger.unrealized_pnl = engine.candidates["SOLUSDT"].unrealized_pnl_usdt

        snap_bear = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap_bear.drift))) < Decimal("1e-15")

    def test_ledger_zero_drift_at_emergency_flattening(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.perform_preflight_checks()

        setup = _build_mock_twins_state(symbol="ETHUSDT", entry_price=Decimal("2500.00"))
        engine.dispatch_ict_intention(setup, now_ms=1700000000000)

        engine._flatten_all_positions(now_ms=1700000060000, reason="Emergency drill")
        snap_flat = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap_flat.drift))) < Decimal("1e-15")
        for cand in engine.candidates.values():
            assert cand.stop_loss == Decimal("0.0")
            assert cand.take_profit == Decimal("0.0")
            assert cand._stop_loss is None
            assert cand._take_profit is None
            assert cand.position_qty == Decimal("0.0")
            assert cand.allocated_exposure_usdt == Decimal("0.0")
            assert cand.unrealized_pnl_usdt == Decimal("0.0")


# =============================================================================
# Suite 7: TestOrderDispatchStateMachine
# =============================================================================

class TestOrderDispatchStateMachine:
    """Verifies the state machine: step_6_ready -> intention -> fill -> protective brackets."""

    def test_order_dispatch_state_machine_entry_to_brackets(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()
        now_ms = 1700000000000

        setup = _build_mock_twins_state(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("170.00"),
            stop_loss=Decimal("165.00"),
            tp_partial=Decimal("185.00"),
            tp_final=Decimal("200.00"),
            step_6_ready=True,
        )

        # 1. Dispatch intention
        order = engine.dispatch_ict_intention(setup, now_ms=now_ms)
        assert order is not None
        assert order.status == OrderStatus.FILLED
        assert order.symbol == "SOLUSDT"
        assert order.side == OrderSide.BUY
        assert order.client_order_id.startswith("canary-p317-ict-sol-")

        # 2. Candidate state populated with protective brackets
        cand = engine.candidates["SOLUSDT"]
        assert cand.position_qty > Decimal("0")
        assert cand.stop_loss == Decimal("165.00")
        assert cand.take_profit == Decimal("185.00")

        # 3. Simulate protective Take Profit trigger
        exit_order = engine._exit_position(
            cand=cand,
            exit_price=cand.take_profit,
            ts_ms=now_ms + 900000,
            reason="TAKE_PROFIT",
        )
        assert exit_order.side == OrderSide.SELL
        assert exit_order.status == OrderStatus.FILLED
        assert exit_order.client_order_id.startswith("canary-p317-tp-sol-")
        assert len(exit_order.client_order_id) <= 36
        assert exit_order.order_id.startswith("ord-p317-")
        assert cand.position_qty == Decimal("0.0")
        assert cand.allocated_exposure_usdt == Decimal("0.0")
        assert cand.unrealized_pnl_usdt == Decimal("0.0")
        assert cand.stop_loss == Decimal("0.0")
        assert cand.take_profit == Decimal("0.0")
        assert cand._stop_loss is None
        assert cand._take_profit is None
        assert cand.realized_pnl_usdt > Decimal("0.0")

    def test_order_dispatch_state_machine_stop_loss_exit(self, tmp_path: Path) -> None:
        """Verifies STOP_LOSS exit produces canary-p317-sl- tag and clears candidate state."""
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()
        now_ms = 1700000000000

        setup = _build_mock_twins_state(
            symbol="ETHUSDT",
            side="BUY",
            entry_price=Decimal("2500.00"),
            stop_loss=Decimal("2400.00"),
            tp_partial=Decimal("2700.00"),
            step_6_ready=True,
        )
        order = engine.dispatch_ict_intention(setup, now_ms=now_ms)
        assert order is not None

        cand = engine.candidates["ETHUSDT"]
        assert cand.stop_loss == Decimal("2400.00")

        # Simulate protective Stop Loss exit
        exit_order = engine._exit_position(
            cand=cand,
            exit_price=cand.stop_loss,
            ts_ms=now_ms + 60000,
            reason="STOP_LOSS",
        )
        assert exit_order.side == OrderSide.SELL
        assert exit_order.status == OrderStatus.FILLED
        assert exit_order.client_order_id.startswith("canary-p317-sl-eth-")
        assert len(exit_order.client_order_id) <= 36
        assert not exit_order.is_maker  # SL is aggressive taker
        assert cand.position_qty == Decimal("0.0")
        assert cand.allocated_exposure_usdt == Decimal("0.0")
        assert cand.unrealized_pnl_usdt == Decimal("0.0")
        assert cand.stop_loss == Decimal("0.0")
        assert cand.take_profit == Decimal("0.0")
        assert cand._stop_loss is None
        assert cand._take_profit is None

    def test_order_dispatch_state_machine_short_position_cover(self, tmp_path: Path) -> None:
        """Verifies short position exit buys to cover with symmetric side and clears state."""
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()
        now_ms = 1700000000000

        setup = _build_mock_twins_state(
            symbol="BTCUSDT",
            side="SELL",
            entry_price=Decimal("80000.00"),
            stop_loss=Decimal("82000.00"),
            tp_partial=Decimal("76000.00"),
            step_6_ready=True,
        )
        order = engine.dispatch_ict_intention(setup, now_ms=now_ms)
        assert order is not None
        assert order.side == OrderSide.SELL

        cand = engine.candidates["BTCUSDT"]
        assert cand.position_qty < Decimal("0.0")  # Short position

        # Exit short position via close
        exit_order = engine._exit_position(
            cand=cand,
            exit_price=Decimal("76000.00"),
            ts_ms=now_ms + 120000,
            reason="TAKE_PROFIT",
        )
        assert exit_order.side == OrderSide.BUY  # BUY to cover!
        assert exit_order.status == OrderStatus.FILLED
        assert exit_order.client_order_id.startswith("canary-p317-tp-btc-")
        assert len(exit_order.client_order_id) <= 36
        assert cand.position_qty == Decimal("0.0")
        assert cand.allocated_exposure_usdt == Decimal("0.0")
        assert cand.unrealized_pnl_usdt == Decimal("0.0")
        assert cand.stop_loss == Decimal("0.0")
        assert cand.take_profit == Decimal("0.0")
        assert cand._stop_loss is None
        assert cand._take_profit is None

    def test_order_dispatch_state_machine_emergency_close_tag(self, tmp_path: Path) -> None:
        """Verifies general close exit produces canary-p317-cl- tag."""
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()
        now_ms = 1700000000000

        setup = _build_mock_twins_state(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("170.00"),
            stop_loss=Decimal("165.00"),
            tp_partial=Decimal("185.00"),
            step_6_ready=True,
        )
        order = engine.dispatch_ict_intention(setup, now_ms=now_ms)
        assert order is not None

        cand = engine.candidates["SOLUSDT"]
        exit_order = engine._exit_position(
            cand=cand,
            exit_price=Decimal("172.00"),
            ts_ms=now_ms + 30000,
            reason="MANUAL_CLOSE",
        )
        assert exit_order.client_order_id.startswith("canary-p317-cl-sol-")
        assert len(exit_order.client_order_id) <= 36
        assert cand.position_qty == Decimal("0.0")

    def test_order_dispatch_state_machine_premature_setup_rejection(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        setup_unready = _build_mock_twins_state(symbol="SOLUSDT", step_6_ready=False)
        order = engine.dispatch_ict_intention(setup_unready)
        assert order is None


# =============================================================================
# Suite 8: TestContinuousTraderNonBlockingCycleLatency
# =============================================================================

class TestContinuousTraderNonBlockingCycleLatency:
    """Verifies that evaluation across all 8 active pairs remains strictly < 15ms per cycle."""

    @pytest.mark.anyio
    async def test_continuous_trader_cycle_latency_under_15ms(self, tmp_path: Path) -> None:
        mock_gateway = AsyncMock(spec=BinanceFuturesGateway)
        mock_gateway.get_position_risk.return_value = []
        mock_gateway.get_klines.return_value = [
            [
                1700000000000,
                "100.0",
                "102.0",
                "99.0",
                "101.0",
                "500.0",
                1700000059999,
                "0",
                1,
                "0",
                "0",
                "0",
            ]
        ]
        mock_gateway.testnet = True

        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=mock_gateway,
            telegram_enabled=False,
        )
        trader.engine.perform_preflight_checks()

        # Warm up multi-timeframe buffers across all 8 pairs and 5 horizons
        now = time.time()
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = trader.sequencer.buffers[(sym, tf)]
                for i in range(50):
                    buf.append(_build_test_candle(1700000000000 + i * 60000, "150.0"))
                trader.sequencer.last_fetch_ts[(sym, tf)] = now

        # Populate BTC 1h history for macro filter
        trader.btc_1h_history = [
            _build_test_macro_candle(1700000000000 + i * 3600000, "82600.0") for i in range(210)
        ]
        trader.last_candle_fetch_ts = now

        # Execute cycle and measure elapsed time
        t0 = time.perf_counter()
        await trader.run_single_cycle()
        elapsed_sec = time.perf_counter() - t0
        elapsed_ms = elapsed_sec * 1000.0

        # Assert cycle latency is strictly under 15ms
        assert elapsed_ms < 15.0, (
            f"run_single_cycle latency {elapsed_ms:.2f} ms exceeded 15 ms limit"
        )

    @pytest.mark.anyio
    async def test_continuous_trader_evaluates_all_8_pairs_in_cycle(self, tmp_path: Path) -> None:
        mock_gateway = AsyncMock(spec=BinanceFuturesGateway)
        mock_gateway.get_position_risk.return_value = []
        mock_gateway.get_klines.return_value = []
        mock_gateway.testnet = True

        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=mock_gateway,
            telegram_enabled=False,
        )
        now = time.time()
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = trader.sequencer.buffers[(sym, tf)]
                for i in range(50):
                    buf.append(_build_test_candle(1700000000000 + i * 60000, "100.0"))
                trader.sequencer.last_fetch_ts[(sym, tf)] = now

        trader.btc_1h_history = [
            _build_test_macro_candle(1700000000000 + i * 3600000, "82600.0") for i in range(210)
        ]
        trader.last_candle_fetch_ts = now

        # Mock evaluate_twins_setup to track calls across all 8 pairs
        evaluated_symbols: list[str] = []

        def tracking_eval(symbol: str, *args: Any, **kwargs: Any) -> TwinsSetupState:
            evaluated_symbols.append(symbol)
            return _build_mock_twins_state(symbol=symbol, step_6_ready=False)

        with patch.object(
            trader.ict_engine,
            "evaluate_twins_setup",
            side_effect=tracking_eval,
        ):
            await trader.run_single_cycle()

        for sym in ACTIVE_PAIRS:
            assert sym in evaluated_symbols, f"Symbol {sym} was not evaluated in continuous cycle"
