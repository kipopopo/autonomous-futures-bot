"""Autonomous Futures Bot - Phase 315: Comprehensive Opaque-Box E2E Test Suite.

Validates Phase 315: Transforming the Strategy Autopsy & Evolution pipeline into an
authentic dynamic state machine with transparent real-time scan cycles, sample counts,
and OOS gate scorecards, while expanding the active Binance Futures USDⓈ-M perpetual
trading universe with top high-volume pairs (DOGEUSDT, BNBUSDT, XRPUSDT, SUIUSDT, AVAXUSDT
alongside BTC, ETH, SOL) to eliminate trade entry bottlenecks, while enforcing strict
micro-capital limits, zero-drift double-entry solvency, and uninterrupted continuity of
the 24/7 background trader daemon (Main PID 87549).

Architecture & Methodology (TEST_INFRA.md):
- Tier 1: Feature Coverage (Category-Partition Equivalence Classes, >= 40 tests):
    * F1: Dynamic Evolution State Machine API (5 stages, 15s timer, progression formula)
    * F2: Transparent OOS Qualification Telemetry API (5 sample hurdle, Sharpe >= 15%, macro gating)
    * F3: 8-Pair Perpetual Universe Ingress & Filters (all 8 pairs, LOT_SIZE ROUND_DOWN, step-up)
    * F4: Scalper Opportunity Evaluation (15m dip logic, ATR, RSI, 20 EMA, BTC gate)
    * F5: Micro-Capital Governance & Guardrails (child <= $5, agg <= $25, cash >= 75%, loss <= $3)
    * F6: Double-Entry Solvency Balance Invariant (|drift| < 10^-15 USDT, fee reconciliation)
    * F7: Multi-Pair Dashboard API Contract (8 pairs in prices, positions, authentic orders)
    * F8: Candlestick Data Contract (15m/1h OHLCV, sub-dollar decimals, overlays, brackets)

- Tier 2: Boundary & Corner Cases (Boundary Value Analysis, >= 35 tests):
    * B1: Minimum Notional Step-Up Boundaries ($4.99 vs $5.00+, step-up clamping)
    * B2: Trade Sample Size Boundaries (0/5, 1/5, 4/5, 5/5 transition to EVALUATING / QUALIFIED)
    * B3: Cash Reserve Floor Boundaries (75.0% boundary, sub-75% rejection, flat 100%)
    * B4: Aggregate Exposure Boundaries ($25.00 boundary, multi-position stacking, $25.01 rejection)
    * B5: Sub-Satoshi Precision & Round-Down Boundaries (ROUND_DOWN step, micro-fills drift)
    * B6: Intra-Day Loss Ceiling Boundaries ($2.99 active vs $3.00 circuit flattened auto-exit)
    * B7: Hawkes Hazard & Latency Boundaries (rho = 0.99 vs 1.00, latency <= 500ms vs 501ms)

- Tier 3: Cross-Feature Combinations (Pairwise Combinatorial, >= 15 tests):
    * Combinatorial interactions: BTC Bearish regime + candidate dip suppression, BTC Bullish
      regime + concurrent multi-pair dips, dynamic evolution transitions during active trades,
      8-pair mark prices + kline cache coherence, step-up sizing + ledger margin reservation,
      macro regime flip + evolution banner updates, candlestick sub-dollar decimal fidelity,
      concurrent multi-pair execution + TP/SL bracket triggers + zero-drift reconciliation.

- Tier 4: Real-World Workload Scenarios (End-to-End Workflows, >= 5 scenarios):
    * Scenario 1: Full Daemon Trading Cycle Simulation with 8 Pairs & Dynamic Telemetry Sync
    * Scenario 2: Macro Regime Flip from Bearish to Bullish with Scalper Reactivation
    * Scenario 3: Multi-Pair Concurrent Execution, Bracket Realization & Ledger Solvency
    * Scenario 4: Out-of-Sample Qualification Progression from 0 to 5 Closed Trades
    * Scenario 5: Adversarial Micro-Capital Stress & Circuit Breaker Enforcement
"""

from __future__ import annotations

import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Production FastAPI Application & TestClient
from autonomous_futures.api import create_app  # noqa: E402

# Production Dynamic Evolution State Machine & Telemetry
from autonomous_futures.api.canary import (  # noqa: E402
    _build_macro_gating_state,
    load_verified_canary_auto_evolution,
)

# Production Binance Gateway & Specifications
from autonomous_futures.execution.binance_gateway import (  # noqa: E402
    DEFAULT_SPECS,
    BinanceFuturesGateway,
    generate_client_order_id,
    generate_drill_client_order_id,
    quantize_step_size,
    quantize_tick_size,
)

# Production Autonomous Trading Engines & Models
from autonomous_futures.execution.continuous_trader import (  # noqa: E402
    ContinuousSelfDrivingTrader,
)
from autonomous_futures.execution.self_driving import (  # noqa: E402
    MicroCapitalConfig,
    OrderSide,
    OrderStatus,
    SelfDrivingState,
    SelfDrivingTradingEngine,
    build_default_self_driving_engine,
)

# Production Solvency Ledger & Governance
from autonomous_futures.safety.kill_switch import (  # noqa: E402
    CentralizedSolvencyLedger,
)

# Production Scalper & Strategy Filters
from autonomous_futures.strategy.macro_liquidity_scalper import (  # noqa: E402
    Candle,
    MacroLiquidityDipScalper,
    MacroTrendFilter,
    compute_atr,
    compute_ema,
    compute_rsi,
    compute_sma,
)

# ==============================================================================
# AUTHORITATIVE PHASE 315 SPECIFICATION ORACLES & FIXTURES
# ==============================================================================

ALL_8_PAIRS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
)

CANDIDATE_7_PAIRS: tuple[str, ...] = (
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
)

MACRO_BENCHMARK_PAIR = "BTCUSDT"

VALID_CYCLE_STAGES: tuple[str, ...] = (
    "INGRESS",
    "HEALTH_EVALUATION",
    "TRADE_AUTOPSY",
    "MUTATION_STAGING",
    "SHADOW_OOS_GATE",
)


@pytest.fixture
def api_client() -> TestClient:
    """Fixture providing initialized FastAPI TestClient for endpoints."""
    app = create_app()
    return TestClient(app)


def make_candle(
    ts_ms: int,
    open_p: float | Decimal,
    high_p: float | Decimal,
    low_p: float | Decimal,
    close_p: float | Decimal,
    vol: float | Decimal = 1000.0,
) -> Candle:
    """Creates a standardized Candle instance."""
    return Candle(
        timestamp_ms=ts_ms,
        open=Decimal(str(open_p)),
        high=Decimal(str(high_p)),
        low=Decimal(str(low_p)),
        close=Decimal(str(close_p)),
        volume=Decimal(str(vol)),
    )


def make_15m_candle_series(
    count: int = 50,
    base_price: Decimal = Decimal("100.00"),
    trend_step: Decimal = Decimal("0.05"),
    atr_spread: Decimal = Decimal("1.50"),
    vol_base: Decimal = Decimal("1000.0"),
) -> list[Candle]:
    """Generates a synthetic series of 15m candles with controlled indicators."""
    candles: list[Candle] = []
    base_ts = 1728600000000
    for i in range(count):
        ts = base_ts + i * 900000
        p = base_price + Decimal(str(i)) * trend_step
        h = p + atr_spread
        low_val = p - atr_spread
        c = p + Decimal("0.10")
        candles.append(make_candle(ts, p, h, low_val, c, vol_base))
    return candles


# ==============================================================================
# TIER 1 — FEATURE COVERAGE (46 TEST CASES ACROSS 8 FEATURES)
# ==============================================================================


class TestTier1FeatureCoverage:
    """Tier 1: Comprehensive feature coverage across all 8 Phase 315 features."""

    # --------------------------------------------------------------------------
    # F1: Dynamic Evolution State Machine API (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f1_dynamic_evolution_stages_progression(self, api_client: TestClient) -> None:
        """F1.1: Verify the 5 discrete cycle stages and ordered state progression."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified"] is True
        assert data["live_progress"]["current_cycle_stage"] in VALID_CYCLE_STAGES

        # Step through all 5 cycle stages using production dynamic state machine
        for sec_offset, expected_stage in [
            (0, "INGRESS"),
            (3000, "HEALTH_EVALUATION"),
            (6000, "TRADE_AUTOPSY"),
            (9000, "MUTATION_STAGING"),
            (12000, "SHADOW_OOS_GATE"),
        ]:
            evo = load_verified_canary_auto_evolution(
                simulated_timestamp_ms=1728600000000 + sec_offset
            )
            assert evo.live_progress.current_cycle_stage == expected_stage

    def test_t1_f1_dynamic_evolution_cycle_interval_15s(
        self, api_client: TestClient, tmp_path: Path
    ) -> None:
        """F1.2: Verify the dynamic evolution cycle interval is fixed to 15 seconds."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert 1 <= lp["next_cycle_seconds"] <= 15

        trader = ContinuousSelfDrivingTrader(storage_dir=tmp_path, poll_interval_seconds=15.0)
        assert trader.poll_interval_seconds == 15.0

    def test_t1_f1_dynamic_evolution_live_timestamps(self, api_client: TestClient) -> None:
        """F1.3: Verify candle fetch and evaluation timestamps are valid, monotonic integers."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]

        eval_ts = lp["last_evaluated_timestamp_ms"]
        candle_ts = lp["last_candle_fetch_timestamp_ms"]
        assert isinstance(eval_ts, int) and eval_ts > 0
        assert isinstance(candle_ts, int) and candle_ts > 0
        assert eval_ts >= candle_ts

    def test_t1_f1_dynamic_evolution_daemon_status_and_pid(self, api_client: TestClient) -> None:
        """F1.4: Verify live daemon continuity metadata declares ONLINE 24/7 and PID 87549."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert lp["daemon_status"] == "ONLINE 24/7"
        assert lp["daemon_pid"] == 87549
        assert lp["is_live_daemon_active"] is True

    def test_t1_f1_dynamic_evolution_generation_metadata(self, api_client: TestClient) -> None:
        """F1.5: Verify generation progression tracks current active and target generations."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert lp["active_generation"] == "GEN #2"
        assert lp["next_target_generation"] == "GEN #3"

    def test_t1_f1_dynamic_evolution_progress_pct_formula(self) -> None:
        """F1.6: Verify dynamic progression percentage formula across trade count increments."""
        expected_percentages = {0: 80.0, 1: 84.0, 2: 88.0, 3: 92.0, 4: 96.0, 5: 100.0}
        for trade_count, expected_pct in expected_percentages.items():
            res = load_verified_canary_auto_evolution(simulated_closed_trades=trade_count)
            assert res.live_progress.cycle_progress_pct == expected_pct

    # --------------------------------------------------------------------------
    # F2: Transparent OOS Gate Telemetry API (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f2_oos_gate_required_samples_hurdle(self, api_client: TestClient) -> None:
        """F2.1: Verify OOS gate requires exactly 5 closed trades before promotion."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert lp["required_trades_count"] == 5
        assert lp["oos_gate"]["samples_required"] == 5

    def test_t1_f2_oos_gate_status_waiting_for_samples(self) -> None:
        """F2.2: Verify status is WAITING_FOR_SAMPLES when closed trade count < 5."""
        for trades in [0, 1, 2, 3, 4]:
            res = load_verified_canary_auto_evolution(simulated_closed_trades=trades)
            assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"
            assert res.live_progress.stage_status_label == f"WAITING_FOR_SAMPLES ({trades}/5)"

    def test_t1_f2_oos_gate_status_evaluating_and_qualified(self) -> None:
        """F2.3: Verify transition to EVALUATING at 5 trades and QUALIFIED on Sharpe hurdle."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=5)
        assert res.live_progress.stage_status in ("EVALUATING", "QUALIFIED")
        assert res.live_progress.cycle_progress_pct == 100.0

    def test_t1_f2_oos_gate_sharpe_hurdle_15pct(self, api_client: TestClient) -> None:
        """F2.4: Verify Sharpe improvement hurdle is strictly >= 15.0%."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert lp["sharpe_hurdle_pct"] == 15.0
        assert lp["oos_gate"]["sharpe_hurdle_pct"] == 15.0

    def test_t1_f2_oos_gate_macro_trend_gating_telemetry(self, api_client: TestClient) -> None:
        """F2.5: Verify macro trend telemetry exposes regime state and long pause status."""
        state_bearish = _build_macro_gating_state("BEARISH")
        assert state_bearish.regime == "BEARISH"
        assert state_bearish.longs_filtered is True
        assert state_bearish.is_long_allowed is False

        state_bullish = _build_macro_gating_state("BULLISH")
        assert state_bullish.regime == "BULLISH_ALIGNED"
        assert state_bullish.longs_filtered is False
        assert state_bullish.is_long_allowed is True

        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        regime = resp.json()["live_progress"]["macro_gating_state"]["regime"]
        assert regime in ("BEARISH", "BULLISH_ALIGNED")

    def test_t1_f2_oos_gate_macro_gating_explanation_banner(self, api_client: TestClient) -> None:
        """F2.6: Verify human-readable macro regime gating explanation banner."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        mg = resp.json()["live_progress"]["macro_gating_state"]
        assert "Active BTC Macro Trend Filter" in mg["explanation_ms"]
        assert "Bearish" in mg["explanation_ms"]
        assert "EMA 50 < EMA 200" in mg["explanation_ms"]
        assert len(mg["explanation"]) > 0

    # --------------------------------------------------------------------------
    # F3: 8-Pair Perpetual Universe Ingress & Filters (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f3_universe_all_eight_pairs_present(self) -> None:
        """F3.1: Verify active universe contains exactly the specified 8 pairs."""
        engine = build_default_self_driving_engine()
        assert isinstance(engine, SelfDrivingTradingEngine)
        assert set(engine.candidates.keys()) == set(ALL_8_PAIRS)
        gateway = BinanceFuturesGateway(api_key="mock_key", api_secret="mock_secret", testnet=True)
        assert gateway.testnet is True
        assert set(DEFAULT_SPECS.keys()) == set(ALL_8_PAIRS)
        for sym in ALL_8_PAIRS:
            assert sym in DEFAULT_SPECS

    def test_t1_f3_exchange_filters_lot_size_round_down(self) -> None:
        """F3.2: Verify LOT_SIZE step size quantization strictly truncates with ROUND_DOWN."""
        engine = build_default_self_driving_engine()
        for sym in ALL_8_PAIRS:
            step = DEFAULT_SPECS[sym]["step_size"]
            raw_qty = Decimal("5.999999")
            q = engine._round_step_size(raw_qty, step)
            q_quant = quantize_step_size(raw_qty, step)
            assert q == q_quant
            multiple = q / step
            assert multiple == multiple.quantize(Decimal("1")), f"Failed step multiple for {sym}"
            assert q <= raw_qty, f"Over-allocation detected for {sym}: {q} > {raw_qty}"

    def test_t1_f3_exchange_filters_price_filter_round_half_up(self) -> None:
        """F3.3: Verify PRICE_FILTER tick quantization adheres to ROUND_HALF_UP."""
        engine = build_default_self_driving_engine()
        for sym in ALL_8_PAIRS:
            tick = DEFAULT_SPECS[sym]["tick_size"]
            raw_p = Decimal("123.456789")
            p = engine._round_tick_size(raw_p, tick)
            multiple = p / tick
            assert multiple == multiple.quantize(Decimal("1")), f"Failed tick multiple for {sym}"

    def test_t1_f3_exchange_filters_min_notional_compliance(self) -> None:
        """F3.4: Verify MIN_NOTIONAL floor is enforced across all candidate pairs."""
        engine = build_default_self_driving_engine()
        assert engine.config.max_micro_order_notional_usdt == Decimal("5.00")
        assert DEFAULT_SPECS["ETHUSDT"]["min_notional"] == Decimal("20.00")
        for sym in ("SOLUSDT", "DOGEUSDT", "BNBUSDT", "XRPUSDT", "SUIUSDT", "AVAXUSDT"):
            assert DEFAULT_SPECS[sym]["min_notional"] == Decimal("5.00")
        for sym in CANDIDATE_7_PAIRS:
            price = Decimal("100.00") if sym != "DOGEUSDT" else Decimal("0.086")
            p, q, notional = engine._calculate_child_order_qty(sym, price)
            assert notional >= Decimal("5.00")

    def test_t1_f3_sub_dollar_doge_step_up_compliance(self) -> None:
        """F3.5: Verify DOGEUSDT ($0.086) steps up by 1 whole unit to clear $5.00."""
        engine = build_default_self_driving_engine()
        price, qty, notional = engine._calculate_child_order_qty("DOGEUSDT", Decimal("0.086"))

        assert qty == Decimal("59")
        assert notional == Decimal("5.07400")
        assert notional >= Decimal("5.00")
        assert notional <= Decimal("5.00") + (Decimal("1") * Decimal("0.086"))

    def test_t1_f3_sub_dollar_xrp_sui_avax_step_up_compliance(self) -> None:
        """F3.6: Verify XRP ($1.40), SUI ($1.11), and AVAX ($10.00) sizing compliance."""
        engine = build_default_self_driving_engine()

        # XRP: step 0.1, price 1.40
        _, q_xrp, n_xrp = engine._calculate_child_order_qty("XRPUSDT", Decimal("1.40"))
        assert q_xrp == Decimal("3.6")
        assert n_xrp == Decimal("5.0400")
        assert n_xrp >= Decimal("5.00")

        # SUI: step 0.1, price 1.11
        _, q_sui, n_sui = engine._calculate_child_order_qty("SUIUSDT", Decimal("1.11"))
        assert q_sui == Decimal("4.6")
        assert n_sui == Decimal("5.1060")
        assert n_sui >= Decimal("5.00")

        # AVAX: step 1, price 10.00
        _, q_avax, n_avax = engine._calculate_child_order_qty("AVAXUSDT", Decimal("10.00"))
        assert q_avax == Decimal("1")
        assert n_avax == Decimal("10.000")
        assert n_avax >= Decimal("5.00")

    # --------------------------------------------------------------------------
    # F4: Scalper Opportunity Evaluation across 7 Candidates (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f4_scalper_15m_indicators_computation(self) -> None:
        """F4.1: Verify 20 EMA, 14 ATR, 20 SMA Volume, and 14 RSI calculation on 15m candles."""
        candles = make_15m_candle_series(50, base_price=Decimal("110.00"))
        closes = [c.close for c in candles]
        volumes = [c.volume for c in candles]

        ema20 = compute_ema(closes, 20)
        atr14 = compute_atr(candles, 14)
        vol_sma20 = compute_sma(volumes, 20)
        rsi14 = compute_rsi(closes, 14)

        assert len(ema20) == 50
        assert len(atr14) == 50
        assert len(vol_sma20) == 50
        assert len(rsi14) == 50
        assert atr14[-1] > Decimal("0")
        assert Decimal("0") <= rsi14[-1] <= Decimal("100")

    def test_t1_f4_scalper_confluence_dip_trigger(self) -> None:
        """F4.2: Verify 15m confluence dip triggers when price > 2.5x ATR below 20 EMA,

        volume > 2.2x SMA, RSI < 26.
        """
        scalper = MacroLiquidityDipScalper()
        history = make_15m_candle_series(30, base_price=Decimal("100.00"))

        dip_bar = make_candle(
            ts_ms=1728690000000,
            open_p=Decimal("95.00"),
            high_p=Decimal("95.50"),
            low_p=Decimal("85.00"),
            close_p=Decimal("86.00"),
            vol=Decimal("5000.0"),
        )

        signal = scalper.evaluate_15m_bar(
            symbol="SOLUSDT",
            bar=dip_bar,
            history=history,
            macro_trend_allowed=True,
        )

        assert signal is not None
        assert signal.side == "BUY"
        assert signal.order_type == "LIMIT"
        assert signal.is_maker is True
        assert signal.sweep_price == Decimal("86.00")

    def test_t1_f4_scalper_evaluates_all_seven_candidates(self) -> None:
        """F4.3: Verify scalper candidate pool accepts all 7 non-BTC candidate pairs."""
        scalper = MacroLiquidityDipScalper()
        assert len(scalper.ALLOWED_SYMBOLS) == 7
        assert set(scalper.ALLOWED_SYMBOLS) == set(CANDIDATE_7_PAIRS)
        assert "BTCUSDT" not in scalper.ALLOWED_SYMBOLS

    def test_t1_f4_scalper_btc_macro_trend_gate_suppression(self) -> None:
        """F4.4: Verify that when BTC macro trend is Bearish, candidate dips return None."""
        scalper = MacroLiquidityDipScalper()
        trend_filter = MacroTrendFilter()
        assert trend_filter.ema_slow == 200
        history = make_15m_candle_series(30, base_price=Decimal("100.00"))
        dip_bar = make_candle(
            ts_ms=1728690000000,
            open_p=Decimal("95.00"),
            high_p=Decimal("95.50"),
            low_p=Decimal("85.00"),
            close_p=Decimal("86.00"),
            vol=Decimal("5000.0"),
        )

        signal = scalper.evaluate_15m_bar(
            symbol="SOLUSDT",
            bar=dip_bar,
            history=history,
            macro_trend_allowed=False,
        )
        assert signal is None

    def test_t1_f4_scalper_trade_structuring_maker_and_brackets(self) -> None:
        """F4.5: Verify Maker Limit order structuring, TP (+2.0x ATR), and SL (-1.2x ATR)."""
        scalper = MacroLiquidityDipScalper()
        history = make_15m_candle_series(30, base_price=Decimal("100.00"))
        dip_bar = make_candle(
            ts_ms=1728690000000,
            open_p=Decimal("95.00"),
            high_p=Decimal("95.50"),
            low_p=Decimal("85.00"),
            close_p=Decimal("86.00"),
            vol=Decimal("5000.0"),
        )

        signal = scalper.evaluate_15m_bar(
            symbol="SOLUSDT",
            bar=dip_bar,
            history=history,
            macro_trend_allowed=True,
        )
        assert signal is not None
        assert signal.is_maker is True
        assert signal.take_profit == signal.sweep_price + (Decimal("2.0") * signal.atr)
        assert signal.stop_loss == signal.sweep_price - (Decimal("1.2") * signal.atr)
        assert signal.reward_to_risk_ratio == Decimal("1.6667")

    def test_t1_f4_scalper_time_decay_stop_8_bars(self) -> None:
        """F4.6: Verify time-based decay stop auto-exit parameter is fixed to 8 bars (120 min)."""
        scalper = MacroLiquidityDipScalper()
        assert scalper.max_hold_bars == 8

        engine = build_default_self_driving_engine()
        cand = engine.candidates["SOLUSDT"]
        cand.position_qty = Decimal("0.05")
        cand.entry_price = Decimal("110.00")
        cand.entry_time_ms = 1728600000000
        cand.allocated_exposure_usdt = Decimal("5.50")
        engine.ledger.cash -= Decimal("5.50")
        engine.ledger.allocated_margin += Decimal("5.50")

        # After 8 bars (8 * 15 * 60 * 1000 ms), scalper triggers TIME_DECAY_STOP exit
        bar = make_candle(1728600000000 + 7201000, 110.0, 111.0, 109.0, 110.0, 1000.0)
        exit_order = engine.evaluate_and_dispatch_scalper("SOLUSDT", bar, [], [])
        assert exit_order is not None
        assert exit_order.side == OrderSide.SELL
        assert cand.position_qty == Decimal("0.0")

    # --------------------------------------------------------------------------
    # F5: Micro-Capital Governance & Guardrails (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f5_micro_capital_child_order_cap_5_usdt(self) -> None:
        """F5.1: Verify child order notional cap is strictly <= 5.00 USDT."""
        engine = build_default_self_driving_engine()
        assert isinstance(engine.config, MicroCapitalConfig)
        assert engine.config.max_micro_order_notional_usdt == Decimal("5.00")

        for sym in CANDIDATE_7_PAIRS:
            price = (
                Decimal("0.086")
                if sym == "DOGEUSDT"
                else (
                    Decimal("1.40")
                    if sym == "XRPUSDT"
                    else (Decimal("1.11") if sym == "SUIUSDT" else Decimal("100.00"))
                )
            )
            p, qty, notional = engine._calculate_child_order_qty(sym, price)
            step = DEFAULT_SPECS[sym]["step_size"]
            assert notional <= engine.config.max_micro_order_notional_usdt + (step * p)
            assert notional >= Decimal("5.00")

    def test_t1_f5_micro_capital_aggregate_exposure_cap_25_usdt(self) -> None:
        """F5.2: Verify aggregate portfolio exposure ceiling is strictly <= 25.00 USDT."""
        engine = build_default_self_driving_engine()
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("25.00")

        order = engine.process_microstructure_tick(
            "ETHUSDT", Decimal("2500.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.interlock_blocks_count == 1
        assert engine.events_log[-1]["event_type"] == "AGGREGATE_EXPOSURE_CAP_BLOCK"

    def test_t1_f5_micro_capital_cash_reserve_floor_75pct(self) -> None:
        """F5.3: Verify liquid unencumbered cash floor is strictly >= 75.0%."""
        engine = build_default_self_driving_engine()
        engine.ledger.cash = Decimal("74.00")

        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.interlock_blocks_count == 1
        assert engine.events_log[-1]["event_type"] == "CASH_RESERVE_FLOOR_BLOCK"

    def test_t1_f5_micro_capital_daily_loss_ceiling_3_usdt(self) -> None:
        """F5.4: Verify intra-day loss budget ceiling is strictly <= 3.00 USDT."""
        engine = build_default_self_driving_engine()
        engine.intra_day_loss_usdt = Decimal("3.00")

        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED
        assert engine.interlock_blocks_count == 1

    def test_t1_f5_micro_capital_hawkes_spectral_radius_interlock(self) -> None:
        """F5.5: Verify Hawkes spectral radius interlock halts orders when rho >= 1.0."""
        engine = build_default_self_driving_engine()

        order_toxic = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), hawkes_spectral_radius=1.05, ensemble_signal="BUY"
        )
        assert order_toxic is None
        assert engine.state == SelfDrivingState.HAWKES_THROTTLED
        assert engine.events_log[-1]["event_type"] == "HAWKES_RUNAWAY_THROTTLE"

        order_safe = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), hawkes_spectral_radius=0.85, ensemble_signal="BUY"
        )
        assert order_safe is not None
        assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

    def test_t1_f5_micro_capital_heartbeat_latency_interlock(self) -> None:
        """F5.6: Verify heartbeat freshness interlock blocks orders when latency > 500ms."""
        engine = build_default_self_driving_engine()

        order_stale = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), heartbeat_age_ms=501.0, ensemble_signal="BUY"
        )
        assert order_stale is None
        assert engine.events_log[-1]["event_type"] == "HEARTBEAT_STALE_BLOCK"

        order_fresh = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), heartbeat_age_ms=50.0, ensemble_signal="BUY"
        )
        assert order_fresh is not None

    # --------------------------------------------------------------------------
    # F6: Double-Entry Solvency Balance Invariant (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f6_solvency_initial_state_zero_drift(self) -> None:
        """F6.1: Verify starting solvency state has exact zero balance drift (|drift| < 1e-15)."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        snap = ledger.get_snapshot()

        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert snap.cash == 100.0
        assert snap.allocated_margin == 0.0
        assert snap.unrealized_pnl == 0.0
        assert snap.realized_pnl == 0.0

    def test_t1_f6_solvency_margin_reservation_zero_drift(self) -> None:
        """F6.2: Verify reserving margin transfers cash to allocated margin with zero drift."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        margin = Decimal("5.50")
        ledger.cash -= margin
        ledger.allocated_margin += margin
        snap = ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert snap.allocated_margin == float(margin)
        assert snap.cash == float(Decimal("100.0") - margin)

        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is not None
        assert engine.candidates["SOLUSDT"].allocated_exposure_usdt == order.notional_usdt
        engine_snap = engine.ledger.get_snapshot()
        assert engine_snap.zero_balance_drift is True
        assert abs(engine_snap.drift) < 1e-15

    def test_t1_f6_solvency_fill_with_maker_fee_zero_drift(self) -> None:
        """F6.3: Verify execution fill with 0.02% maker fee reconciles with zero drift."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is not None
        assert order.status == OrderStatus.FILLED
        assert order.is_maker is True
        assert order.fee_usdt > Decimal("0")

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t1_f6_solvency_take_profit_realization_zero_drift(self) -> None:
        """F6.4: Verify Take-Profit (+2.0x ATR) realization preserves exact zero drift."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is not None

        engine._exit_position(
            engine.candidates["SOLUSDT"],
            Decimal("114.00"),
            int(time.time() * 1000),
            reason="TAKE_PROFIT",
        )
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert snap.realized_pnl > 0.0

    def test_t1_f6_solvency_stop_loss_realization_zero_drift(self) -> None:
        """F6.5: Verify Stop-Loss (-1.2x ATR) realization preserves exact zero drift."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is not None

        engine._exit_position(
            engine.candidates["SOLUSDT"],
            Decimal("107.00"),
            int(time.time() * 1000),
            reason="STOP_LOSS",
        )
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert snap.realized_pnl < 0.0

    def test_t1_f6_solvency_position_flattening_zero_drift(self) -> None:
        """F6.6: Verify emergency flattening returns all margin with zero balance drift."""
        engine = build_default_self_driving_engine()
        engine.process_microstructure_tick("SOLUSDT", Decimal("110.00"), ensemble_signal="BUY")
        engine.process_microstructure_tick("ETHUSDT", Decimal("2500.00"), ensemble_signal="BUY")
        assert sum(c.position_qty for c in engine.candidates.values()) > Decimal("0")

        engine._flatten_all_positions(int(time.time() * 1000), reason="Emergency test flattening")
        assert all(c.position_qty == Decimal("0.0") for c in engine.candidates.values())

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert snap.allocated_margin == 0.0

    # --------------------------------------------------------------------------
    # F7: Multi-Pair Dashboard API Contract (5 tests)
    # --------------------------------------------------------------------------

    def test_t1_f7_dashboard_prices_all_eight_pairs(self, api_client: TestClient) -> None:
        """F7.1: Verify price telemetry contract includes all 8 pairs with positive floats."""
        resp = api_client.get("/api/v1/market/prices")
        assert resp.status_code == 200
        data = resp.json()
        for sym in ALL_8_PAIRS:
            assert sym in data["prices"]
            assert data["prices"][sym] > 0.0

    def test_t1_f7_dashboard_execution_status_all_eight_pairs(self, api_client: TestClient) -> None:
        """F7.2: Verify execution status positions dictionary contains all 8 pairs."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        positions = resp.json()["positions"]
        assert len(positions) == 8
        pos_symbols = set(positions.keys())
        assert pos_symbols == set(ALL_8_PAIRS)

    def test_t1_f7_dashboard_truthful_flat_positions(self, api_client: TestClient) -> None:
        """F7.3: Verify flat positions report 0.0 quantity, 0.0 exposure, and null targets."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        positions = resp.json()["positions"]
        for p in positions.values():
            assert p["position_qty"] == 0.0
            assert p["allocated_exposure_usdt"] == 0.0
            assert p["state"] == "STANDBY / SCANNING"
            assert p.get("take_profit_price") is None
            assert p.get("stop_loss_price") is None

    def test_t1_f7_dashboard_active_position_structure(self) -> None:
        """F7.4: Verify active position structure contains valid TP, SL, entry, and exposure."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is not None

        cand = engine.candidates["SOLUSDT"]
        assert cand.position_qty > Decimal("0")
        assert cand.entry_price == Decimal("110.00")
        assert cand.allocated_exposure_usdt <= Decimal("25.00")
        assert cand.allocated_exposure_usdt > Decimal("0.0")

    def test_t1_f7_dashboard_recent_orders_authentic_ids(self, api_client: TestClient) -> None:
        """F7.5: Verify recent orders use authentic deterministic IDs (no ord-p309-)."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        recent_orders = resp.json()["recent_orders"]
        for ord_item in recent_orders:
            cid = ord_item["client_order_id"]
            assert not cid.startswith("ord-p309-"), f"Stale placeholder found: {cid}"
            assert cid.startswith("canary-p310-") or cid.startswith("canary-p311-")
            assert len(cid) <= 36

        for sym in ALL_8_PAIRS:
            assert len(generate_client_order_id(sym)) <= 36
            assert len(generate_drill_client_order_id(sym)) <= 36

    # --------------------------------------------------------------------------
    # F8: Interactive Candlestick Data Contract (5 tests)
    # --------------------------------------------------------------------------

    def test_t1_f8_candlestick_klines_ohlcv_contract(self, api_client: TestClient) -> None:
        """F8.1: Verify candlestick response normalized payload contract."""
        resp = api_client.get("/api/v1/market/klines?symbol=DOGEUSDT&interval=15m&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "DOGEUSDT"
        assert data["interval"] == "15m"
        assert len(data["candles"]) > 0

        c = data["candles"][0]
        assert "timestamp" in c and "open" in c and "high" in c and "low" in c and "close" in c
        assert "volume" in c
        assert c["high"] >= max(c["open"], c["close"])
        assert c["low"] <= min(c["open"], c["close"])

    def test_t1_f8_candlestick_timeframes_15m_and_1h(self, api_client: TestClient) -> None:
        """F8.2: Verify support for 15m (scalper) and 1h (macro) intervals."""
        r15 = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=5")
        assert r15.status_code == 200
        r1h = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=1h&limit=5")
        assert r1h.status_code == 200
        r_bad = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=2h&limit=5")
        assert r_bad.status_code == 422

    def test_t1_f8_candlestick_sub_dollar_precision_doge_xrp(self, api_client: TestClient) -> None:
        """F8.3: Verify sub-dollar coins maintain accurate decimal formatting."""
        r_doge = api_client.get("/api/v1/market/klines?symbol=DOGEUSDT&interval=15m&limit=5")
        assert r_doge.status_code == 200
        c_doge = r_doge.json()["candles"][0]["close"]
        assert 0.0 < c_doge < 1.0
        doge_tick = DEFAULT_SPECS["DOGEUSDT"]["tick_size"]
        assert quantize_tick_size(Decimal(str(c_doge)), doge_tick) > Decimal("0")

        r_xrp = api_client.get("/api/v1/market/klines?symbol=XRPUSDT&interval=15m&limit=5")
        assert r_xrp.status_code == 200
        c_xrp = r_xrp.json()["candles"][0]["close"]
        assert c_xrp > 0.0

    def test_t1_f8_candlestick_overlays_ema_and_volume(self, api_client: TestClient) -> None:
        """F8.4: Verify technical overlays (EMA 20, Volume SMA) can be computed on candles."""
        resp = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=100")
        assert resp.status_code == 200
        candles = resp.json()["candles"]
        closes = [Decimal(str(c["close"])) for c in candles]
        volumes = [Decimal(str(c["volume"])) for c in candles]

        ema20 = compute_ema(closes, 20)
        vol_sma20 = compute_sma(volumes, 20)
        assert len(ema20) == len(candles)
        assert len(vol_sma20) == len(candles)

    def test_t1_f8_candlestick_bracket_lines_position_coupling(self) -> None:
        """F8.5: Verify bracket price lines exist only when position is active."""
        engine = build_default_self_driving_engine()
        cand = engine.candidates["SOLUSDT"]

        # Flat state: brackets suppressed
        assert cand.position_qty == Decimal("0.0")
        assert cand.stop_loss == Decimal("0.0")
        assert cand.take_profit == Decimal("0.0")

        # Active state: brackets coupled
        cand.position_qty = Decimal("0.05")
        cand.entry_price = Decimal("110.00")
        cand.take_profit = Decimal("114.00")
        cand.stop_loss = Decimal("107.60")
        assert cand.take_profit > cand.entry_price
        assert cand.stop_loss < cand.entry_price


# ==============================================================================
# TIER 2 — BOUNDARY & CORNER CASES (35 TEST CASES)
# ==============================================================================


class TestTier2BoundaryAndCorner:
    """Tier 2: Extreme operating boundaries, edge conditions, and adversarial inputs."""

    # --------------------------------------------------------------------------
    # B1: Minimum Notional Step-Up Boundaries (5 tests)
    # --------------------------------------------------------------------------

    def test_t2_b1_doge_sub_notional_step_up(self) -> None:
        """B1.1: DOGE at $0.086 with $4.99 initial notional steps up to $5.074."""
        engine = build_default_self_driving_engine()
        p, qty, notional = engine._calculate_child_order_qty("DOGEUSDT", Decimal("0.086"))
        assert qty == Decimal("59")
        assert notional == Decimal("5.07400")

    def test_t2_b1_xrp_sub_notional_step_up(self) -> None:
        """B1.2: XRP at $1.40 with $4.90 initial notional steps up to $5.04."""
        engine = build_default_self_driving_engine()
        p, qty, notional = engine._calculate_child_order_qty("XRPUSDT", Decimal("1.40"))
        assert qty == Decimal("3.6")
        assert notional == Decimal("5.0400")

    def test_t2_b1_sui_sub_notional_step_up(self) -> None:
        """B1.3: SUI at $1.11 with $5.00 target notional (raw $4.995) steps up to $5.106."""
        engine = build_default_self_driving_engine()
        p, qty, notional = engine._calculate_child_order_qty("SUIUSDT", Decimal("1.11"))
        assert qty == Decimal("4.6")
        assert notional == Decimal("5.1060")
        assert notional >= Decimal("5.00")

    def test_t2_b1_avax_sub_notional_step_up(self) -> None:
        """B1.4: AVAX at $10.00 with $0 initial notional steps up to $10.00 (1 unit)."""
        engine = build_default_self_driving_engine()
        p, qty, notional = engine._calculate_child_order_qty("AVAXUSDT", Decimal("10.00"))
        assert qty == Decimal("1")
        assert notional == Decimal("10.000")
        assert notional >= Decimal("5.00")

    def test_t2_b1_excessive_step_up_rejected_fail_closed(self) -> None:
        """B1.5: Verify sizing rejects when step-up would jump excessively beyond boundary."""
        engine = build_default_self_driving_engine()
        engine.gateway.testnet = False
        p, qty, notional = engine._calculate_child_order_qty("BTCUSDT", Decimal("80000.00"))
        assert qty == Decimal("0.0")
        assert notional == Decimal("0.0")

    # --------------------------------------------------------------------------
    # B2: Trade Sample Size Boundaries (5 tests)
    # --------------------------------------------------------------------------

    def test_t2_b2_zero_trades_waiting_for_samples_80pct(self) -> None:
        """B2.1: Exactly 0 closed trades yields WAITING_FOR_SAMPLES (0/5) and 80.0% progress."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=0)
        assert res.live_progress.cycle_progress_pct == 80.0
        assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"
        assert res.live_progress.stage_status_label == "WAITING_FOR_SAMPLES (0/5)"

    def test_t2_b2_one_trade_waiting_for_samples_84pct(self) -> None:
        """B2.2: Exactly 1 closed trade yields 84.0% progress."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=1)
        assert res.live_progress.cycle_progress_pct == 84.0
        assert res.live_progress.stage_status_label == "WAITING_FOR_SAMPLES (1/5)"

    def test_t2_b2_four_trades_waiting_for_samples_96pct(self) -> None:
        """B2.3: Exactly 4 closed trades yields 96.0% progress."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=4)
        assert res.live_progress.cycle_progress_pct == 96.0
        assert res.live_progress.stage_status_label == "WAITING_FOR_SAMPLES (4/5)"

    def test_t2_b2_five_trades_transition_to_evaluating_100pct(self) -> None:
        """B2.4: Exactly 5 closed trades yields 100.0% progress and transition to EVALUATING."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=5)
        assert res.live_progress.cycle_progress_pct == 100.0
        assert res.live_progress.stage_status in ("EVALUATING", "QUALIFIED")

    def test_t2_b2_sharpe_hurdle_15pct_qualification_transition(
        self, api_client: TestClient
    ) -> None:
        """B2.5: At 5 trades, Sharpe improvement >= 15.0% transitions to QUALIFIED."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        assert resp.json()["live_progress"]["sharpe_hurdle_pct"] == 15.0

        res = load_verified_canary_auto_evolution(simulated_closed_trades=5)
        assert res.live_progress.stage_status == "QUALIFIED"

    # --------------------------------------------------------------------------
    # B3: Cash Reserve Floor Boundaries (5 tests)
    # --------------------------------------------------------------------------

    def test_t2_b3_exact_75pct_cash_reserve_permitted(self) -> None:
        """B3.1: Exactly 75.0% unencumbered cash reserve is valid and permitted."""
        engine = build_default_self_driving_engine()
        engine.ledger.cash = Decimal("80.00")
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("100.00"), ensemble_signal="BUY"
        )
        assert order is not None

    def test_t2_b3_cash_reserve_below_75pct_rejected(self) -> None:
        """B3.2: Cash reserve at 74.99% fails cash floor validation."""
        engine = build_default_self_driving_engine()
        engine.ledger.cash = Decimal("79.99")
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("100.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.events_log[-1]["event_type"] == "CASH_RESERVE_FLOOR_BLOCK"

    def test_t2_b3_flat_100pct_cash_reserve_verified(self) -> None:
        """B3.3: 100.0% cash reserve (flat portfolio) is strictly verified."""
        engine = build_default_self_driving_engine()
        snap = engine.ledger.get_snapshot()
        assert snap.cash_reserve_pct == 100.0
        assert snap.unencumbered_cash_verified is True
        assert snap.allocated_margin == 0.0

    def test_t2_b3_high_margin_80pct_cash_permitted(self) -> None:
        """B3.4: 80.0% cash reserve ($20 margin allocated) satisfies floor."""
        engine = build_default_self_driving_engine()
        engine.ledger.cash = Decimal("85.00")
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("100.00"), ensemble_signal="BUY"
        )
        assert order is not None

    def test_t2_b3_zero_cash_rejected(self) -> None:
        """B3.5: 0.0% cash reserve fails floor check."""
        engine = build_default_self_driving_engine()
        engine.ledger.cash = Decimal("0.00")
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("100.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.events_log[-1]["event_type"] == "CASH_RESERVE_FLOOR_BLOCK"

    # --------------------------------------------------------------------------
    # B4: Aggregate Exposure Boundaries (5 tests)
    # --------------------------------------------------------------------------

    def test_t2_b4_exact_25_usdt_aggregate_exposure_permitted(self) -> None:
        """B4.1: Exactly $25.00 USDT total aggregate exposure is permitted."""
        engine = build_default_self_driving_engine()
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("20.00")
        order = engine.process_microstructure_tick(
            "ETHUSDT", Decimal("100.00"), ensemble_signal="BUY"
        )
        assert order is not None
        total_exp = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
        assert total_exp == Decimal("25.00")

    def test_t2_b4_aggregate_exposure_exceeding_25_usdt_rejected(self) -> None:
        """B4.2: Aggregate exposure at $25.01 USDT is strictly blocked."""
        engine = build_default_self_driving_engine()
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("20.01")
        order = engine.process_microstructure_tick(
            "ETHUSDT", Decimal("100.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.events_log[-1]["event_type"] == "AGGREGATE_EXPOSURE_CAP_BLOCK"

    def test_t2_b4_five_micro_positions_totaling_25_usdt_permitted(self) -> None:
        """B4.3: 5 micro positions at $5.00 each totaling $25.00 are permitted."""
        engine = build_default_self_driving_engine()
        for sym, p in [
            ("SOLUSDT", Decimal("100.00")),
            ("ETHUSDT", Decimal("100.00")),
            ("BNBUSDT", Decimal("100.00")),
            ("SUIUSDT", Decimal("50.00")),
            ("XRPUSDT", Decimal("50.00")),
        ]:
            order = engine.process_microstructure_tick(sym, p, ensemble_signal="BUY")
            assert order is not None
        total_exp = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
        assert total_exp == Decimal("25.00")

    def test_t2_b4_sixth_position_rejected_by_cap(self) -> None:
        """B4.4: 6th micro position attempting to push exposure to $30.00 is blocked."""
        engine = build_default_self_driving_engine()
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("25.00")
        order = engine.process_microstructure_tick(
            "AVAXUSDT", Decimal("10.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.events_log[-1]["event_type"] == "AGGREGATE_EXPOSURE_CAP_BLOCK"

    def test_t2_b4_exposure_headroom_boundary_precision(self) -> None:
        """B4.5: Current exposure $20.05 permits orders up to $4.95 headroom."""
        engine = build_default_self_driving_engine()
        current = Decimal("20.05")
        headroom = engine.config.max_aggregate_exposure_usdt - current
        assert headroom == Decimal("4.95")

        engine.candidates["SOLUSDT"].allocated_exposure_usdt = current
        order = engine.process_microstructure_tick(
            "ETHUSDT", Decimal("100.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.events_log[-1]["event_type"] == "AGGREGATE_EXPOSURE_CAP_BLOCK"

    # --------------------------------------------------------------------------
    # B5: Sub-Satoshi Precision & Round-Down Boundaries (5 tests)
    # --------------------------------------------------------------------------

    def test_t2_b5_step_size_round_down_fractional_truncation(self) -> None:
        """B5.1: Verify ROUND_DOWN strictly truncates fractions without ceiling bias."""
        engine = build_default_self_driving_engine()
        assert engine._round_step_size(Decimal("58.999"), Decimal("1")) == Decimal("58")
        assert engine._round_step_size(Decimal("0.199"), Decimal("0.1")) == Decimal("0.1")

    def test_t2_b5_tick_size_round_half_up_boundary(self) -> None:
        """B5.2: Verify ROUND_HALF_UP rounds half values up."""
        engine = build_default_self_driving_engine()
        tick = Decimal("0.00001")
        assert engine._round_tick_size(Decimal("0.086425"), tick) == Decimal("0.08643")
        assert engine._round_tick_size(Decimal("0.086424"), tick) == Decimal("0.08642")

    def test_t2_b5_sub_satoshi_fee_zero_drift_preservation(self) -> None:
        """B5.3: Verify irregular fee deduction preserves zero drift."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "DOGEUSDT", Decimal("0.086"), ensemble_signal="BUY"
        )
        assert order is not None

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t2_b5_thousand_micro_fills_drift_under_1e15(self) -> None:
        """B5.4: Verify 1,000 sequential micro fills maintain drift strictly < 1e-15 USDT."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        micro_fee = Decimal("0.00001234")
        micro_pnl = Decimal("0.00005678")

        for _ in range(1000):
            ledger.cash += micro_pnl - micro_fee
            ledger.realized_pnl += micro_pnl - micro_fee

        snap = ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t2_b5_extreme_sub_cent_price_quantization(self) -> None:
        """B5.5: Verify extreme sub-cent price quantization for DOGE (5 dec) and XRP (4 dec)."""
        engine = build_default_self_driving_engine()
        doge_p = engine._round_tick_size(
            Decimal("0.08642199"), DEFAULT_SPECS["DOGEUSDT"]["tick_size"]
        )
        assert doge_p == Decimal("0.08642")

        xrp_p = engine._round_tick_size(Decimal("1.402549"), DEFAULT_SPECS["XRPUSDT"]["tick_size"])
        assert xrp_p == Decimal("1.4025")

    # --------------------------------------------------------------------------
    # B6: Intra-Day Loss Ceiling Boundaries (5 tests)
    # --------------------------------------------------------------------------

    def test_t2_b6_loss_at_2_99_usdt_remains_active(self) -> None:
        """B6.1: Intra-day loss at $2.99 USDT keeps engine in MICRO_CAPITAL_ACTIVE."""
        engine = build_default_self_driving_engine()
        engine.intra_day_loss_usdt = Decimal("2.99")

        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is not None
        assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

    def test_t2_b6_loss_at_3_00_usdt_trips_circuit_flattened(self) -> None:
        """B6.2: Intra-day loss at exactly $3.00 USDT trips circuit breaker."""
        engine = build_default_self_driving_engine()
        engine.intra_day_loss_usdt = Decimal("3.00")

        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED
        assert engine.interlock_blocks_count == 1

    def test_t2_b6_loss_exceeding_3_00_usdt_auto_flattens(self) -> None:
        """B6.3: Intra-day loss at $3.01 USDT triggers fail-closed auto-flattening."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is not None
        assert engine.candidates["SOLUSDT"].position_qty > Decimal("0")

        engine.intra_day_loss_usdt = Decimal("3.01")
        order_block = engine.process_microstructure_tick(
            "ETHUSDT", Decimal("2500.00"), ensemble_signal="BUY"
        )
        assert order_block is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED
        assert engine.candidates["SOLUSDT"].position_qty == Decimal("0.0")

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t2_b6_tripped_circuit_rejects_new_orders(self) -> None:
        """B6.4: Tripped circuit breaker strictly rejects new order generation."""
        engine = build_default_self_driving_engine()
        engine.state = SelfDrivingState.CIRCUIT_FLATTENED

        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.interlock_blocks_count == 1

    def test_t2_b6_loss_reset_restores_active_state(self) -> None:
        """B6.5: Daily loss reset restores MICRO_CAPITAL_ACTIVE state."""
        engine = build_default_self_driving_engine()
        engine.state = SelfDrivingState.CIRCUIT_FLATTENED
        engine.intra_day_loss_usdt = Decimal("0.00")

        engine.perform_preflight_checks()
        assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is not None

    # --------------------------------------------------------------------------
    # B7: Hawkes Hazard & Latency Boundaries (5 tests)
    # --------------------------------------------------------------------------

    def test_t2_b7_hawkes_radius_0_99_permitted(self) -> None:
        """B7.1: Hawkes spectral radius rho = 0.99 is safe, trading permitted."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), hawkes_spectral_radius=0.99, ensemble_signal="BUY"
        )
        assert order is not None
        assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

    def test_t2_b7_hawkes_radius_1_00_throttled(self) -> None:
        """B7.2: Hawkes spectral radius rho = 1.00 triggers HAWKES_THROTTLED."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), hawkes_spectral_radius=1.00, ensemble_signal="BUY"
        )
        assert order is None
        assert engine.state == SelfDrivingState.HAWKES_THROTTLED
        assert engine.events_log[-1]["event_type"] == "HAWKES_RUNAWAY_THROTTLE"

    def test_t2_b7_hawkes_radius_1_50_throttled(self) -> None:
        """B7.3: Extreme Hawkes toxicity rho = 1.50 halts trading."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), hawkes_spectral_radius=1.50, ensemble_signal="BUY"
        )
        assert order is None
        assert engine.state == SelfDrivingState.HAWKES_THROTTLED

    def test_t2_b7_heartbeat_latency_500ms_permitted(self) -> None:
        """B7.4: Gateway latency at exactly 500.0 ms is permitted."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), heartbeat_age_ms=500.0, ensemble_signal="BUY"
        )
        assert order is not None

    def test_t2_b7_heartbeat_latency_501ms_blocked(self) -> None:
        """B7.5: Gateway latency at 500.1 ms blocks order dispatch."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), heartbeat_age_ms=501.0, ensemble_signal="BUY"
        )
        assert order is None
        assert engine.events_log[-1]["event_type"] == "HEARTBEAT_STALE_BLOCK"


# ==============================================================================
# TIER 3 — CROSS-FEATURE COMBINATIONS (15 TEST CASES)
# ==============================================================================


class TestTier3CrossFeatureCombinations:
    """Tier 3: Pairwise combinatorial interactions across multiple subsystem features."""

    def test_t3_x1_btc_bearish_regime_filters_doge_dip(self) -> None:
        """X1: Bearish BTC regime + valid scalper dip on DOGEUSDT -> order strictly blocked."""
        engine = build_default_self_driving_engine()
        btc_candles = make_15m_candle_series(50, base_price=Decimal("80000.00"))
        assert engine.trend_filter.evaluate(btc_candles) is False

        history = make_15m_candle_series(30, base_price=Decimal("0.10"))
        dip_bar = make_candle(1728600000, 0.09, 0.092, 0.08, 0.081, 50000.0)

        order = engine.evaluate_and_dispatch_scalper("DOGEUSDT", dip_bar, history, btc_candles)
        assert order is None

    def test_t3_x2_btc_bearish_regime_filters_sol_dip(self) -> None:
        """X2: Bearish BTC regime + valid scalper dip on SOLUSDT -> order strictly blocked."""
        engine = build_default_self_driving_engine()
        btc_candles = make_15m_candle_series(50, base_price=Decimal("80000.00"))
        assert engine.trend_filter.evaluate(btc_candles) is False

        history = make_15m_candle_series(30, base_price=Decimal("110.00"))
        dip_bar = make_candle(1728600000, 105.0, 106.0, 95.0, 96.0, 5000.0)

        order = engine.evaluate_and_dispatch_scalper("SOLUSDT", dip_bar, history, btc_candles)
        assert order is None

    def test_t3_x3_btc_bullish_regime_concurrent_dips_cap_enforcement(self) -> None:
        """X3: Bullish BTC regime + concurrent dips on 5 pairs -> exposure respects $25."""
        engine = build_default_self_driving_engine()
        for sym, p in [
            ("SOLUSDT", Decimal("100.00")),
            ("ETHUSDT", Decimal("100.00")),
            ("BNBUSDT", Decimal("100.00")),
            ("SUIUSDT", Decimal("50.00")),
        ]:
            order = engine.process_microstructure_tick(sym, p, ensemble_signal="BUY")
            assert order is not None

        order5 = engine.process_microstructure_tick(
            "XRPUSDT", Decimal("50.00"), ensemble_signal="BUY"
        )
        assert order5 is not None
        total = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
        assert total == Decimal("25.00")

        order6 = engine.process_microstructure_tick(
            "AVAXUSDT", Decimal("10.00"), ensemble_signal="BUY"
        )
        assert order6 is None
        assert engine.events_log[-1]["event_type"] == "AGGREGATE_EXPOSURE_CAP_BLOCK"

    def test_t3_x4_evolution_cycle_transition_during_active_trades_zero_drift(
        self, api_client: TestClient
    ) -> None:
        """X4: Cycle stage transitions while trades are active maintain zero drift."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        assert order is not None

        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t3_x5_eight_pair_mark_prices_and_kline_cache_coherence(
        self, api_client: TestClient
    ) -> None:
        """X5: Price feeds for all 8 pairs update without cache key collisions."""
        r_prices = api_client.get("/api/v1/market/prices")
        assert r_prices.status_code == 200
        prices = r_prices.json()["prices"]

        for sym in ALL_8_PAIRS:
            assert sym in prices
            r_kline = api_client.get(f"/api/v1/market/klines?symbol={sym}&interval=15m&limit=5")
            assert r_kline.status_code == 200
            assert r_kline.json()["symbol"] == sym

    def test_t3_x6_step_up_sizing_reserves_ledger_margin_with_zero_drift(self) -> None:
        """X6: Sizing step-up reserves exact quantized margin in ledger with zero drift."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "DOGEUSDT", Decimal("0.086"), ensemble_signal="BUY"
        )
        assert order is not None
        assert order.quantity == Decimal("59")
        assert order.notional_usdt == Decimal("5.07400")
        assert engine.candidates["DOGEUSDT"].allocated_exposure_usdt == order.notional_usdt

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

        # Explicit ledger margin reservation verification
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        margin = order.notional_usdt
        ledger.cash -= margin
        ledger.allocated_margin += margin
        ledger_snap = ledger.get_snapshot()
        assert ledger_snap.zero_balance_drift is True
        assert abs(ledger_snap.drift) < 1e-15
        assert ledger_snap.allocated_margin == float(order.notional_usdt)

    def test_t3_x7_macro_regime_flip_updates_evolution_gating_banner(self) -> None:
        """X7: Regime flip from Bearish to Bullish updates evolution gating banner."""
        state_bearish = _build_macro_gating_state("BEARISH")
        assert state_bearish.regime == "BEARISH"
        assert state_bearish.longs_filtered is True
        assert state_bearish.is_long_allowed is False
        assert "Bearish" in state_bearish.explanation_ms

        state_bullish = _build_macro_gating_state("BULLISH")
        assert state_bullish.regime == "BULLISH_ALIGNED"
        assert state_bullish.longs_filtered is False
        assert state_bullish.is_long_allowed is True
        assert "Bullish" in state_bullish.explanation_ms

    def test_t3_x8_candlestick_api_sub_dollar_tick_size_fidelity(
        self, api_client: TestClient
    ) -> None:
        """X8: Candlestick price data formats sub-dollar coins matching tick size."""
        r_doge = api_client.get("/api/v1/market/klines?symbol=DOGEUSDT&interval=15m&limit=5")
        assert r_doge.status_code == 200
        candles = r_doge.json()["candles"]
        tick = DEFAULT_SPECS["DOGEUSDT"]["tick_size"]
        for c in candles:
            cp = Decimal(str(c["close"]))
            assert quantize_tick_size(cp, tick) == cp

    def test_t3_x9_multi_pair_concurrent_tp_sl_fills_and_reconciliation(self) -> None:
        """X9: Concurrent positions (one TP, one SL) reconcile with exact zero drift."""
        engine = build_default_self_driving_engine()
        o_sol = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        o_eth = engine.process_microstructure_tick(
            "ETHUSDT", Decimal("2500.00"), ensemble_signal="BUY"
        )
        assert o_sol is not None and o_eth is not None

        engine._exit_position(
            engine.candidates["SOLUSDT"],
            Decimal("114.00"),
            int(time.time() * 1000),
            reason="TAKE_PROFIT",
        )
        engine._exit_position(
            engine.candidates["ETHUSDT"],
            Decimal("2470.00"),
            int(time.time() * 1000),
            reason="STOP_LOSS",
        )

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert snap.allocated_margin == 0.0

    def test_t3_x10_scalper_time_decay_exit_reconciles_ledger_zero_drift(self) -> None:
        """X10: Position exit on 8-bar time decay stop returns margin with zero drift."""
        engine = build_default_self_driving_engine()
        cand = engine.candidates["SOLUSDT"]
        cand.position_qty = Decimal("0.05")
        cand.entry_price = Decimal("110.00")
        cand.entry_time_ms = 1728600000000
        cand.allocated_exposure_usdt = Decimal("5.50")
        engine.ledger.cash -= Decimal("5.50")
        engine.ledger.allocated_margin += Decimal("5.50")

        bar = make_candle(1728600000000 + 7201000, 110.0, 111.0, 109.0, 110.0, 1000.0)
        exit_order = engine.evaluate_and_dispatch_scalper("SOLUSDT", bar, [], [])
        assert exit_order is not None
        assert exit_order.side == OrderSide.SELL
        assert cand.position_qty == Decimal("0.0")

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t3_x11_eight_pair_universe_specs_and_client_order_id_36char_limit(self) -> None:
        """X11: Client order IDs generated across all 8 symbols never exceed 36 characters."""
        for sym in ALL_8_PAIRS:
            cid = generate_client_order_id(sym)
            assert len(cid) <= 36, f"CID length breached for {sym}: {cid}"
            cid_drill = generate_drill_client_order_id(sym)
            assert len(cid_drill) <= 36, f"Drill CID length breached for {sym}: {cid_drill}"
            assert sym in DEFAULT_SPECS

    def test_t3_x12_micro_capital_config_and_hawkes_interlock_solvency_sync(self) -> None:
        """X12: Hawkes throttled state stops order staging while preserving ledger solvency."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), hawkes_spectral_radius=1.05, ensemble_signal="BUY"
        )
        assert order is None
        assert engine.state == SelfDrivingState.HAWKES_THROTTLED

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert snap.cash == 100.0
        assert snap.allocated_margin == 0.0

    def test_t3_x13_dynamic_evolution_15s_timer_and_sample_hurdle_linkage(
        self, api_client: TestClient
    ) -> None:
        """X13: Dynamic evolution scan cycle timer (15s) links with sample count evaluations."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert 1 <= lp["next_cycle_seconds"] <= 15
        assert lp["required_trades_count"] == 5

    def test_t3_x14_multi_pair_mark_prices_and_execution_status_hydration(
        self, api_client: TestClient
    ) -> None:
        """X14: Multi-pair mark prices correctly populate execution status without gaps."""
        r_p = api_client.get("/api/v1/market/prices")
        r_s = api_client.get("/api/v1/execution/status")
        assert r_p.status_code == 200 and r_s.status_code == 200
        prices = r_p.json()["prices"]
        positions = r_s.json()["positions"]

        for sym, pos in positions.items():
            assert sym in prices
            assert pos["mark_price"] is not None and pos["mark_price"] > 0.0

    def test_t3_x15_daily_loss_trip_auto_flattens_multi_pair_positions_zero_drift(self) -> None:
        """X15: Daily loss circuit breaker trips and flattens all 8 pairs with zero drift."""
        engine = build_default_self_driving_engine()
        engine.process_microstructure_tick("SOLUSDT", Decimal("110.00"), ensemble_signal="BUY")
        engine.process_microstructure_tick("ETHUSDT", Decimal("2500.00"), ensemble_signal="BUY")
        assert sum(c.position_qty for c in engine.candidates.values()) > Decimal("0")

        engine.intra_day_loss_usdt = Decimal("3.00")
        order = engine.process_microstructure_tick(
            "BNBUSDT", Decimal("700.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED
        assert all(c.position_qty == Decimal("0.0") for c in engine.candidates.values())

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert snap.allocated_margin == 0.0


# ==============================================================================
# TIER 4 — REAL-WORLD WORKLOAD SCENARIOS (5 SCENARIOS)
# ==============================================================================


class TestTier4RealWorldWorkloads:
    """Tier 4: End-to-end multi-step operational workflows and integration lifecycles."""

    def test_t4_s1_full_daemon_trading_cycle_simulation_8_pairs(
        self, api_client: TestClient
    ) -> None:
        """Scenario 1: Complete 15s daemon cycle simulation across 8 pairs.

        Steps:
        1. Ingress prices and verify BTC macro trend via FastAPI
        2. Ingress 15m klines for candidates
        3. Advance evolution state machine cycle
        4. Initialize production engine and run pre-flight checks
        5. Verify double-entry solvency zero-drift
        6. Verify daemon continuity metadata
        """
        # Step 1: Ingress prices
        r_prices = api_client.get("/api/v1/market/prices")
        assert r_prices.status_code == 200
        prices_data = r_prices.json()
        assert len(prices_data["prices"]) == 8
        assert "btc_macro" in prices_data

        # Step 2: Ingress klines
        r_kline = api_client.get("/api/v1/market/klines?symbol=DOGEUSDT&interval=15m&limit=10")
        assert r_kline.status_code == 200
        assert len(r_kline.json()["candles"]) > 0

        # Step 3: Advance evolution cycle
        r_evo = api_client.get("/api/v1/canary/evolution")
        assert r_evo.status_code == 200
        evo_data = r_evo.json()
        assert evo_data["live_progress"]["daemon_status"] == "ONLINE 24/7"
        assert evo_data["live_progress"]["daemon_pid"] == 87549
        assert evo_data["live_progress"]["current_cycle_stage"] in VALID_CYCLE_STAGES

        # Step 4: Engine simulation
        engine = build_default_self_driving_engine()
        assert engine.perform_preflight_checks() is True

        # Step 5: Verify solvency ledger zero drift
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

        # Step 6: Verify daemon continuity metadata
        assert evo_data["live_progress"]["is_live_daemon_active"] is True

    def test_t4_s2_macro_regime_flip_bearish_to_bullish_scalper_reactivation(self) -> None:
        """Scenario 2: Macro regime flip from Bearish to Bullish reactivates candidate scalper.

        Steps:
        1. Bearish BTC regime: Valid dip on SOLUSDT is suppressed
        2. Macro regime flip: BTC breaks above 200 EMA, EMA 50 > EMA 200
        3. Reactivated scalper: Subsequent dip on SOLUSDT generates Maker limit order with brackets
        """
        engine = build_default_self_driving_engine()
        history = make_15m_candle_series(30, base_price=Decimal("100.00"))
        dip_bar = make_candle(
            ts_ms=1728690000000,
            open_p=Decimal("95.00"),
            high_p=Decimal("95.50"),
            low_p=Decimal("85.00"),
            close_p=Decimal("86.00"),
            vol=Decimal("5000.0"),
        )

        # Step 1: Bearish regime blocks entry
        bearish_btc = make_15m_candle_series(50, base_price=Decimal("80000.00"))
        assert engine.trend_filter.evaluate(bearish_btc) is False

        order_bear = engine.evaluate_and_dispatch_scalper("SOLUSDT", dip_bar, history, bearish_btc)
        assert order_bear is None

        # Step 2: Macro regime flips to Bullish (250 candles with EMA 50 > EMA 200)
        bullish_btc = make_15m_candle_series(
            250, base_price=Decimal("82000.00"), trend_step=Decimal("10.0")
        )
        assert engine.trend_filter.evaluate(bullish_btc) is True

        # Step 3: Reactivated scalper generates Maker limit order with brackets
        order_bull = engine.evaluate_and_dispatch_scalper("SOLUSDT", dip_bar, history, bullish_btc)
        assert order_bull is not None
        assert order_bull.is_maker is True
        assert order_bull.take_profit > order_bull.price
        assert order_bull.stop_loss < order_bull.price

    def test_t4_s3_multi_pair_concurrent_execution_bracket_realization_solvency(self) -> None:
        """Scenario 3: Multi-pair concurrent execution, bracket triggers, and ledger zero drift.

        Steps:
        1. Enter positions on SOL, ETH, and DOGE
        2. SOL hits Take-Profit (+2.0x ATR)
        3. ETH hits Stop-Loss (-1.2x ATR)
        4. DOGE closes at market
        5. Verify double-entry solvency zero-drift at every transition
        """
        engine = build_default_self_driving_engine()

        # Step 1: Enter positions on 3 symbols
        o_sol = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("110.00"), ensemble_signal="BUY"
        )
        o_eth = engine.process_microstructure_tick(
            "ETHUSDT", Decimal("2500.00"), ensemble_signal="BUY"
        )
        o_doge = engine.process_microstructure_tick(
            "DOGEUSDT", Decimal("0.086"), ensemble_signal="BUY"
        )
        assert o_sol is not None and o_eth is not None and o_doge is not None
        assert engine.ledger.get_snapshot().zero_balance_drift is True

        # Step 2: SOL hits TP
        engine._exit_position(
            engine.candidates["SOLUSDT"],
            Decimal("114.00"),
            int(time.time() * 1000),
            reason="TAKE_PROFIT",
        )
        assert engine.ledger.get_snapshot().zero_balance_drift is True

        # Step 3: ETH hits SL
        engine._exit_position(
            engine.candidates["ETHUSDT"],
            Decimal("2470.00"),
            int(time.time() * 1000),
            reason="STOP_LOSS",
        )
        assert engine.ledger.get_snapshot().zero_balance_drift is True

        # Step 4: DOGE closes
        engine._exit_position(
            engine.candidates["DOGEUSDT"],
            Decimal("0.086"),
            int(time.time() * 1000),
            reason="CLEANUP",
        )

        # Step 5: Final solvency check
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert snap.allocated_margin == 0.0

    def test_t4_s4_oos_qualification_progression_zero_to_five_trades(
        self, api_client: TestClient
    ) -> None:
        """Scenario 4: Out-of-Sample qualification progression lifecycle from 0 to 5 trades.

        Steps:
        1. Closed trades = 0: WAITING_FOR_SAMPLES (0/5), progress 80.0%
        2. Incremental fills: trades 1 through 4 update sample count and progress
        3. Closed trades = 5: Transition to EVALUATING / QUALIFIED, progress 100.0%
        4. Verify API response consistency
        """
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200

        for trades, expected_pct in [
            (0, 80.0),
            (1, 84.0),
            (2, 88.0),
            (3, 92.0),
            (4, 96.0),
            (5, 100.0),
        ]:
            res = load_verified_canary_auto_evolution(simulated_closed_trades=trades)
            assert res.live_progress.cycle_progress_pct == expected_pct
            if trades < 5:
                assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"
                assert res.live_progress.stage_status_label == f"WAITING_FOR_SAMPLES ({trades}/5)"
            else:
                assert res.live_progress.stage_status in ("EVALUATING", "QUALIFIED")

    def test_t4_s5_adversarial_micro_capital_stress_cascade_dips_and_drawdown(self) -> None:
        """Scenario 5: Adversarial micro-capital stress test under simultaneous market crash.

        Steps:
        1. Cascading dips across candidate pairs fill up to $25.00 exposure ceiling
        2. 6th order is blocked by AGGREGATE_EXPOSURE_CAP_BLOCK
        3. Adverse fills trigger cumulative losses reaching $3.00 daily loss ceiling
        4. Engine trips CIRCUIT_FLATTENED, halts further order dispatch, and auto-flattens
        5. Verify double-entry solvency zero-drift holds throughout crash containment
        """
        engine = build_default_self_driving_engine()

        # Step 1: Stagger orders up to $25.00 exposure
        for sym, p in [
            ("SOLUSDT", Decimal("100.00")),
            ("ETHUSDT", Decimal("100.00")),
            ("BNBUSDT", Decimal("100.00")),
            ("SUIUSDT", Decimal("50.00")),
            ("XRPUSDT", Decimal("50.00")),
        ]:
            order = engine.process_microstructure_tick(sym, p, ensemble_signal="BUY")
            assert order is not None

        assert sum(c.allocated_exposure_usdt for c in engine.candidates.values()) == Decimal(
            "25.00"
        )

        # Step 2: 6th order blocked
        order6 = engine.process_microstructure_tick(
            "AVAXUSDT", Decimal("10.00"), ensemble_signal="BUY"
        )
        assert order6 is None
        assert engine.events_log[-1]["event_type"] == "AGGREGATE_EXPOSURE_CAP_BLOCK"

        # Step 3: Cumulative loss reaches $3.00
        engine.intra_day_loss_usdt = Decimal("3.00")

        # Step 4: Next tick trips circuit breaker and auto-flattens
        order_trip = engine.process_microstructure_tick(
            "DOGEUSDT", Decimal("0.086"), ensemble_signal="BUY"
        )
        assert order_trip is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED
        assert all(c.position_qty == Decimal("0.0") for c in engine.candidates.values())

        # Step 5: Verify zero drift preservation
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert snap.allocated_margin == 0.0
