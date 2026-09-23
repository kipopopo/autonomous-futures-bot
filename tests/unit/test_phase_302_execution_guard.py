"""Unit tests for Phase 302: Real-Time Toxic Flow Defense, Adverse Selection Guard

& Dynamic Microstructure Slippage Attribution Engine.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.feed.execution_guard import (
    CanaryExecutionGuardRunner,
    CausalSlippageAttributionEngine,
    ChildOrderStatus,
    DoubleEntryLedger,
    ExecutionMicrostructureCoordinator,
    MicrostructureAdverseSelectionGuard,
    OrderSide,
    QuoteAction,
    ToxicityRiskState,
    verify_phase_302_dag,
)


@pytest.fixture
def guard() -> MicrostructureAdverseSelectionGuard:
    return MicrostructureAdverseSelectionGuard(
        bucket_volume_usdt=Decimal("50.0"),
        vpin_window_buckets=5,
        toxic_vpin_threshold=Decimal("0.70"),
        hawkes_runaway_threshold=Decimal("0.85"),
        risk_aversion_gamma=Decimal("0.10"),
    )


@pytest.fixture
def slippage_engine() -> CausalSlippageAttributionEngine:
    return CausalSlippageAttributionEngine(
        micro_cap_usdt=Decimal("5.00"),
        maker_max_slippage_bps=Decimal("5.0"),
        taker_max_slippage_bps=Decimal("15.0"),
    )


@pytest.fixture
def coordinator() -> ExecutionMicrostructureCoordinator:
    return ExecutionMicrostructureCoordinator(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        max_allowed_heartbeat_age_ms=500.0,
        slippage_abort_ceiling_bps=Decimal("20.0"),
        min_cash_reserve_pct=Decimal("40.0"),
    )


# =====================================================================
# R1: MicrostructureAdverseSelectionGuard Tests
# =====================================================================


def test_guard_trade_ingestion_and_vpin(guard: MicrostructureAdverseSelectionGuard) -> None:
    """Verify aggregate trade ingestion into volume buckets and VPIN computation."""
    # Ingest 5 buy trades of 1.0 BTC at 50,000 USDT -> each trade is 50,000 notional
    # With bucket size 50.0 USDT, each trade completes buckets
    metrics = None
    for _ in range(5):
        metrics = guard.ingest_trade(
            symbol="BTCUSDT",
            price=Decimal("50000.0"),
            quantity=Decimal("0.001"),  # 50 USDT per trade -> exactly 1 bucket
            is_buyer_maker=False,  # Taker buy -> buy volume
        )

    assert metrics is not None
    assert metrics.symbol == "BTCUSDT"
    # All volume is aggressive buy, so VPIN should be 1.0 (pure toxic flow)
    assert metrics.vpin >= Decimal("0.70")
    assert metrics.risk_state == ToxicityRiskState.TOXIC_RUNAWAY
    assert metrics.active_quotes_pulled is True


def test_guard_toxic_flow_pull_quote_defense(
    guard: MicrostructureAdverseSelectionGuard,
) -> None:
    """Verify quote pulling when VPIN or Hawkes indicates predatory toxic flow."""
    # Ingest buy trades to force toxic state
    for _ in range(5):
        guard.ingest_trade(
            symbol="BTCUSDT",
            price=Decimal("50000.0"),
            quantity=Decimal("0.001"),
            is_buyer_maker=False,
        )

    metrics = guard.compute_toxicity(
        symbol="BTCUSDT",
        current_mid=Decimal("50000.0"),
        hawkes_spectral_radius=Decimal("0.40"),
    )
    assert metrics.risk_state == ToxicityRiskState.TOXIC_RUNAWAY

    quote = guard.compute_reservation_quote(
        quote_id="q-001",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        unshaded_mid=Decimal("50000.0"),
        inventory_q=Decimal("0.0"),
        metrics=metrics,
    )
    assert quote.action == QuoteAction.PULLED_DEFENSE
    assert "Toxic flow runaway defense" in quote.reason


def test_guard_avellaneda_stoikov_quote_shading(
    guard: MicrostructureAdverseSelectionGuard,
) -> None:
    """Verify Avellaneda-Stoikov quote shading with inventory penalty and regime cushion."""
    # Normal metrics (not toxic)
    metrics = guard.compute_toxicity(
        symbol="BTCUSDT",
        current_mid=Decimal("50000.0"),
        hawkes_spectral_radius=Decimal("0.30"),
    )
    assert metrics.risk_state == ToxicityRiskState.NORMAL

    # Long inventory (q > 0) -> buy quote shaded down
    quote_long = guard.compute_reservation_quote(
        quote_id="q-long",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        unshaded_mid=Decimal("50000.0"),
        inventory_q=Decimal("0.5"),
        metrics=metrics,
    )
    assert quote_long.action == QuoteAction.SHADED
    assert quote_long.shaded_price < quote_long.unshaded_price


# =====================================================================
# R2: CausalSlippageAttributionEngine Tests
# =====================================================================


def test_child_order_quantization_and_cap(
    slippage_engine: CausalSlippageAttributionEngine,
) -> None:
    """Verify child order slicing satisfies <= 5.00 USDT cap with ROUND_DOWN precision."""
    # High price asset BTC: step_size 0.0001
    child_btc = slippage_engine.create_micro_child_order(
        order_id="child-btc-001",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal("50000.0"),
        target_notional_usdt=Decimal("8.50"),  # Exceeds 5.00 USDT cap
    )
    assert child_btc.status == ChildOrderStatus.INTENDED
    assert child_btc.notional_usdt <= Decimal("5.00")
    # 5.00 / 50000 = 0.0001 BTC
    assert child_btc.quantity == Decimal("0.0001")
    assert child_btc.notional_usdt == Decimal("5.0000")

    # Lower price asset SOL: step_size 0.01
    child_sol = slippage_engine.create_micro_child_order(
        order_id="child-sol-001",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        price=Decimal("150.0"),
        target_notional_usdt=Decimal("4.85"),
    )
    assert child_sol.notional_usdt <= Decimal("5.00")
    # 4.85 / 150 = 0.03233 -> 0.03
    assert child_sol.quantity == Decimal("0.03")
    assert child_sol.notional_usdt == Decimal("4.5000")


def test_slippage_decomposition_maker(
    slippage_engine: CausalSlippageAttributionEngine,
) -> None:
    """Verify 4-component slippage decomposition for maker orders."""
    child = slippage_engine.create_micro_child_order(
        order_id="child-001",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal("50000.0"),
        target_notional_usdt=Decimal("5.00"),
    )
    # Intended: 50000.0, Fill: 50005.0 -> 1.0 bps slippage
    decomp = slippage_engine.decompose_slippage(
        child_order=child,
        fill_price=Decimal("50005.0"),
        dispatch_price=Decimal("50001.0"),
        market_volume=Decimal("50000.0"),
        is_maker=True,
    )
    assert decomp.order_id == "child-001"
    assert decomp.is_maker is True
    assert decomp.total_slippage_bps == Decimal("1.00")
    assert decomp.delay_slippage_bps == Decimal("0.20")
    assert decomp.within_tolerance is True  # 1.0 bps <= 5.0 bps maker ceiling
    assert child.status == ChildOrderStatus.FILLED


def test_slippage_decomposition_taker_breach(
    slippage_engine: CausalSlippageAttributionEngine,
) -> None:
    """Verify rejection when slippage exceeds taker tolerance."""
    child = slippage_engine.create_micro_child_order(
        order_id="child-002",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        price=Decimal("150.0"),
        target_notional_usdt=Decimal("4.50"),
    )
    # Fill price 150.35 on 150.0 = 23.33 bps > 15.0 bps taker limit
    decomp = slippage_engine.decompose_slippage(
        child_order=child,
        fill_price=Decimal("150.35"),
        dispatch_price=Decimal("150.05"),
        market_volume=Decimal("1000.0"),
        is_maker=False,
    )
    assert decomp.total_slippage_bps > Decimal("15.0")
    assert decomp.within_tolerance is False


# =====================================================================
# R3: ExecutionMicrostructureCoordinator & Circuit Breakers Tests
# =====================================================================


def test_coordinator_heartbeat_trip(
    coordinator: ExecutionMicrostructureCoordinator,
) -> None:
    """Verify coordinator trips fail-closed when heartbeat age > 500 ms."""
    normal_metrics = MicrostructureAdverseSelectionGuard().compute_toxicity(
        symbol="BTCUSDT",
        current_mid=Decimal("50000.0"),
    )

    # Fresh heartbeat
    coordinator.record_heartbeat()
    safe, reason = coordinator.check_pre_execution_safety(
        symbol="BTCUSDT",
        metrics=normal_metrics,
        cash_usdt=Decimal("90.0"),
        starting_equity_usdt=Decimal("100.0"),
    )
    assert safe is True
    assert reason == "SAFE"

    # Simulate heartbeat age > 500 ms
    coordinator._last_heartbeat_utc = coordinator._last_heartbeat_utc.replace(year=2020)
    safe_stale, reason_stale = coordinator.check_pre_execution_safety(
        symbol="BTCUSDT",
        metrics=normal_metrics,
        cash_usdt=Decimal("90.0"),
        starting_equity_usdt=Decimal("100.0"),
    )
    assert safe_stale is False
    assert "Stale gateway heartbeat" in reason_stale
    assert coordinator.circuit_tripped is True


def test_coordinator_toxic_flow_interlock(
    coordinator: ExecutionMicrostructureCoordinator,
) -> None:
    """Verify coordinator blocks dispatch on toxic flow runaway."""
    coordinator.record_heartbeat()
    guard = MicrostructureAdverseSelectionGuard()
    # Force toxic flow
    for _ in range(5):
        guard.ingest_trade(
            symbol="ETHUSDT",
            price=Decimal("2500.0"),
            quantity=Decimal("0.1"),
            is_buyer_maker=False,
        )
    toxic_metrics = guard.compute_toxicity(
        symbol="ETHUSDT",
        current_mid=Decimal("2500.0"),
    )
    assert toxic_metrics.risk_state == ToxicityRiskState.TOXIC_RUNAWAY

    safe, reason = coordinator.check_pre_execution_safety(
        symbol="ETHUSDT",
        metrics=toxic_metrics,
        cash_usdt=Decimal("90.0"),
        starting_equity_usdt=Decimal("100.0"),
    )
    assert safe is False
    assert "Toxic flow interlock" in reason


def test_coordinator_cash_reserve_floor(
    coordinator: ExecutionMicrostructureCoordinator,
) -> None:
    """Verify coordinator preserves >= 40% unencumbered cash reserve."""
    coordinator.record_heartbeat()
    normal_metrics = MicrostructureAdverseSelectionGuard().compute_toxicity(
        symbol="SOLUSDT",
        current_mid=Decimal("150.0"),
    )

    # Cash = 50 USDT (50% >= 40% floor) -> SAFE
    safe, _ = coordinator.check_pre_execution_safety(
        symbol="SOLUSDT",
        metrics=normal_metrics,
        cash_usdt=Decimal("50.0"),
        starting_equity_usdt=Decimal("100.0"),
    )
    assert safe is True

    # Cash = 30 USDT (30% < 40% floor) -> BLOCKED
    safe_breach, reason = coordinator.check_pre_execution_safety(
        symbol="SOLUSDT",
        metrics=normal_metrics,
        cash_usdt=Decimal("30.0"),
        starting_equity_usdt=Decimal("100.0"),
    )
    assert safe_breach is False
    assert "Cash reserve breach" in reason


# =====================================================================
# R4: DoubleEntryLedger Zero-Drift Balance Tests
# =====================================================================


def test_ledger_mathematical_zero_drift() -> None:
    """Verify zero-drift balance invariant |drift| < 1e-15 across fills, fees, slippage."""
    ledger = DoubleEntryLedger(starting_equity=Decimal("100.00"))
    solvency_init = ledger.get_solvency_report()
    assert solvency_init.zero_balance_drift_verified is True
    assert solvency_init.drift_usdt == 0.0

    # Record a fill: margin=4.50, realized_pnl=0.035, fee=0.00225, slippage=0.003
    drift = ledger.record_fill(
        allocated_margin=Decimal("1.50"),
        realized_pnl=Decimal("0.035"),
        fee_usdt=Decimal("0.00225"),
        slippage_usdt=Decimal("0.00300"),
        unrealized_pnl=Decimal("0.03"),
    )
    assert drift < Decimal("1e-15")

    solvency_after = ledger.get_solvency_report()
    assert solvency_after.zero_balance_drift_verified is True
    assert solvency_after.drift_usdt < 1e-15
    assert solvency_after.unencumbered_cash_verified is True


# =====================================================================
# R5: Runner & Merkle DAG Invariant Verification Tests
# =====================================================================


def test_phase_302_deterministic_runner_execution(tmp_path: Path) -> None:
    """Verify full end-to-end execution of Phase 302 runner producing valid artifacts."""
    runner = CanaryExecutionGuardRunner(output_dir=tmp_path)
    result = runner.run_all_tracks()

    assert result["status"] == "EXECUTION_GUARD_VERIFIED"
    assert result["circuit_state"] == "NORMAL"
    assert result["paper_safe"] is True
    assert result["execution_authority"] is False
    assert result["solvency"]["zero_balance_drift_verified"] is True
    assert abs(result["solvency"]["drift_usdt"]) < 1e-15

    # Verify generated artifacts
    assert (tmp_path / "canary-execution-guard-telemetry.sqlite3").is_file()
    assert (tmp_path / "canary-execution-events.jsonl").is_file()
    assert (tmp_path / "execution-guard-summary.json").is_file()
    assert (tmp_path / "canary-execution-guard-report.json").is_file()
    assert (tmp_path / "paper-summary.json").is_file()

    # Verify Merkle DAG linking Phase 301
    dag_ok, status_msg, hashes = verify_phase_302_dag(tmp_path)
    assert dag_ok is True
    assert status_msg == "VERIFIED"
    assert len(hashes["merkle_root"]) == 64
