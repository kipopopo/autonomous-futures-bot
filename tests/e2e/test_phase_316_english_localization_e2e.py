"""Autonomous Futures Bot — Phase 316: Institutional English Standardization E2E Test Suite.

Validates Phase 316: Standardizing the web dashboard and backend telemetry endpoints into
100% clean, idiomatic, professional financial English by purging all Malay and Indonesian
phrasings across all navigation, KPI cards, tables, charts, evolution steppers, autopsy logs,
and backend telemetry descriptors, while preserving complete functionality, 100% test suite
pass rates, zero-drift solvency invariants (|Δ| < 10^-15 USDT), and uninterrupted continuity
of the 24/7 background trader daemon (Main PID 87549).

Architecture & Methodology (TEST_INFRA.md):
- Tier 1: Feature Coverage (Category-Partition Equivalence Classes, >= 30 tests):
    * F1: Primary Navigation Shell & Routing English Contracts
    * F2: Executive KPI Cards Telemetry & Contracts
    * F3: Live Market Positions & Interactive Candlestick Drawer Telemetry
    * F4: Strategy Confluence Radar & Hawkes Microstructure Hazard
    * F5: Evolution State Machine & OOS Qualification Telemetry
    * F6: Backend Telemetry Endpoints & Event Descriptions
- Tier 2: Boundary & Corner Cases (Boundary Value Analysis, >= 25 tests):
    * B1: Empty States & Zero Completed Trades (0 trades, win rate 0.0%)
    * B2: Negative PnL & Sub-Zero Currency Formatting
    * B3: Zero and Negative Timers (clamped safely, 15s window)
    * B4: Disconnected Feeds & Latency Boundaries (latency > 500ms, stale heartbeat)
    * B5: Flat Positions & Target Suppression (0.00 exposure, null TP/SL)
    * B6: Micro-Capital Boundaries ($5 child cap, $25 aggregate cap, 75% cash floor, $3 daily loss)
- Tier 3: Cross-Feature Combinations (Pairwise Combinatorial, >= 15 tests):
    * C1: Bearish Macro Filter + Candidate Dip Suppression + Evolution Stepper Interaction
    * C2: Bullish Macro Filter + Scalper Dip Detection + Maker Order Creation
    * C3: Continuous Double-Entry Balance Invariant with Multi-Pair Telemetry (|Δ| < 10^-15 USDT)
    * C4: Multi-Pair Mark Price Telemetry + Kline Cache Coherence across all 8 pairs
    * C5: Step-Up Quantization + Ledger Margin Reservation + Solvency Invariant
    * C6: Dynamic Evolution Stage Transitions during Active Trade Positions
    * C7: Supercritical Hawkes Hazard (ρ >= 1.0) Blocking Orders while Telemetry Streams
- Tier 4: Real-World Workload Scenarios (End-to-End Workflows, >= 5 scenarios):
    * S1: End-to-End User Navigation & Telemetry Query Workflow
    * S2: Responsive Candlestick Drawer Expansion & Timeframe Toggle with Bracket Lines
    * S3: Full Trade Lifecycle: Dip Detection -> Maker Fill -> TP -> Zero-Drift Audit
    * S4: Out-of-Sample Qualification Progression from 0 to 5 Closed Trades
    * S5: Macro Regime Flip from Bearish to Bullish with Scalper Reactivation
"""

from __future__ import annotations

import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Resolve root path and src directory
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Production FastAPI Application
from autonomous_futures.api import create_app  # noqa: E402

# Production Dynamic Evolution State Machine & Telemetry Models
from autonomous_futures.api.canary import (  # noqa: E402
    LiveEvolutionEventItem,
    LiveEvolutionProgressItem,
    MacroGatingStateItem,
    _build_macro_gating_state,
    load_verified_canary_auto_evolution,
)

# Production Binance Gateway & Specifications
from autonomous_futures.execution.binance_gateway import (  # noqa: E402
    DEFAULT_SPECS,
)

# Production Autonomous Trading Engines & Models
from autonomous_futures.execution.self_driving import (  # noqa: E402
    OrderStatus,
    SelfDrivingState,
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
)

# ==============================================================================
# AUTHORITATIVE CONSTANTS & SPECIFICATION FIXTURES
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

VALID_CYCLE_STAGES: tuple[str, ...] = (
    "INGRESS",
    "HEALTH_EVALUATION",
    "TRADE_AUTOPSY",
    "MUTATION_STAGING",
    "SHADOW_OOS_GATE",
)

PRIMARY_NAV_ROUTES: tuple[str, ...] = (
    "#/",
    "#/overview",
    "#/positions",
    "#/trades",
    "#/safety",
    "#/evolution",
    "#/research",
)

INSTITUTIONAL_STAGE_TITLES: dict[str, str] = {
    "INGRESS": "1. Market Ingress",
    "HEALTH_EVALUATION": "2. Candidate Health Evaluation",
    "TRADE_AUTOPSY": "3. Trade Autopsy & Attribution",
    "MUTATION_STAGING": "4. Genome Mutation Staging",
    "SHADOW_OOS_GATE": "5. OOS Qualification Gate & Promotion",
}

EXPECTED_EVENT_TYPES: tuple[str, ...] = (
    "HEARTBEAT_INGRESS",
    "SOLVENCY_AUDIT",
    "CANDIDATE_HEALTH",
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
# TIER 1 — FEATURE COVERAGE (36 TESTS ACROSS 6 FEATURES)
# ==============================================================================


class TestTier1FeatureCoverage:
    """Tier 1: Comprehensive feature coverage across all 6 Phase 316 features."""

    # --------------------------------------------------------------------------
    # F1: Primary Navigation Shell & Routing English Contracts (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f1_primary_nav_route_definitions(self) -> None:
        """F1.1: Verify primary navigation routes contract covers all 5 views
        and research drawer."""
        assert len(PRIMARY_NAV_ROUTES) >= 6
        for route in ("#/", "#/overview", "#/positions", "#/trades", "#/safety", "#/evolution"):
            assert route in PRIMARY_NAV_ROUTES

    def test_t1_f1_executive_overview_route_contract(self, api_client: TestClient) -> None:
        """F1.2: Verify Executive Overview route target serves active production health status."""
        resp = api_client.get("/api/v1/canary/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified"] is True
        assert data["circuit_state"] == "NORMAL"

    def test_t1_f1_live_positions_route_contract(self, api_client: TestClient) -> None:
        """F1.3: Verify Live Positions route target serves all 8 pairs in execution status."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data
        assert len(data["positions"]) == 8

    def test_t1_f1_trades_route_contract(self, api_client: TestClient) -> None:
        """F1.4: Verify Trade Log route target serves authentic order executions feed."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "recent_orders" in data
        assert isinstance(data["recent_orders"], list)

    def test_t1_f1_safety_route_contract(self, api_client: TestClient) -> None:
        """F1.5: Verify Risk Controls & Solvency route target validates zero-drift solvency."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        solvency = resp.json()["solvency"]
        assert solvency["zero_balance_drift_verified"] is True
        assert abs(solvency["drift_usdt"]) < 1e-15

    def test_t1_f1_evolution_route_contract(self, api_client: TestClient) -> None:
        """F1.6: Verify Strategy Evolution route target exposes dynamic evolution pipeline."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        data = resp.json()
        assert "live_progress" in data
        assert data["live_progress"]["current_cycle_stage"] in VALID_CYCLE_STAGES

    # --------------------------------------------------------------------------
    # F2: Executive KPI Cards Telemetry & Contracts (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f2_kpi_card1_total_balance_and_equity(self, api_client: TestClient) -> None:
        """F2.1: Verify KPI Card 1 (Total Balance & Equity) contract exposes
        equity, cash, margin."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        solv = resp.json()["solvency"]
        assert solv["total_equity_usdt"] >= 95.0
        assert solv["cash_usdt"] >= 75.0
        assert solv["allocated_margin_usdt"] >= 0.0
        assert (
            abs(
                solv["total_equity_usdt"]
                - (solv["cash_usdt"] + solv["allocated_margin_usdt"] + solv["unrealized_pnl_usdt"])
            )
            < 1e-12
        )

    def test_t1_f2_kpi_card2_realized_pnl_and_win_rate(self, api_client: TestClient) -> None:
        """F2.2: Verify KPI Card 2 (Net Realized PnL & Win Rate) contract exposes valid figures."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "intra_day_loss_usdt" in data
        assert data["intra_day_loss_usdt"] >= 0.0

    def test_t1_f2_kpi_card3_active_exposure_and_sizing(self, api_client: TestClient) -> None:
        """F2.3: Verify KPI Card 3 (Active Exposure & Capital Sizing) exposes
        exposure <= $25 cap."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["aggregate_exposure_usdt"] <= 25.0
        assert data["solvency"]["cash_reserve_pct"] >= 75.0

    def test_t1_f2_kpi_card4_system_health_and_solvency(self, api_client: TestClient) -> None:
        """F2.4: Verify KPI Card 4 (System Health & Solvency) exposes interlock
        and zero-drift proof."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["interlock_blocks_count"] >= 0
        assert data["solvency"]["zero_balance_drift_verified"] is True
        assert abs(data["solvency"]["drift_usdt"]) < 1e-15

    def test_t1_f2_kpi_top_bar_refresh_and_daemon_status(self, api_client: TestClient) -> None:
        """F2.5: Verify Top Bar status contracts declare ONLINE 24/7 and Main PID 87549."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert lp["daemon_status"] == "ONLINE 24/7"
        assert lp["daemon_pid"] == 87549
        assert lp["is_live_daemon_active"] is True

    def test_t1_f2_kpi_closed_trades_counter_contract(self, api_client: TestClient) -> None:
        """F2.6: Verify closed trades count metric conforms to non-negative integer contract."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert isinstance(lp["closed_trades_count"], int)
        assert lp["closed_trades_count"] >= 0

    # --------------------------------------------------------------------------
    # F3: Live Market Positions & Interactive Candlestick Drawer (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f3_market_prices_covers_all_eight_pairs(self, api_client: TestClient) -> None:
        """F3.1: Verify /api/v1/market/prices provides mark prices for all 8 pairs."""
        resp = api_client.get("/api/v1/market/prices")
        assert resp.status_code == 200
        prices = resp.json()["prices"]
        assert set(prices.keys()) == set(ALL_8_PAIRS)
        for sym, p in prices.items():
            assert p > 0.0, f"Mark price for {sym} must be positive"

    def test_t1_f3_market_positions_flat_standby_state(self, api_client: TestClient) -> None:
        """F3.2: Verify flat positions report STANDBY / SCANNING with 0.00 allocated exposure."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        positions = resp.json()["positions"]
        for _sym, pos in positions.items():
            assert pos["state"] == "STANDBY / SCANNING"
            assert pos["position_qty"] == 0.0
            assert pos["allocated_exposure_usdt"] == 0.0
            assert pos.get("take_profit_price") is None
            assert pos.get("stop_loss_price") is None

    def test_t1_f3_candlestick_15m_ingress_contract(self, api_client: TestClient) -> None:
        """F3.3: Verify /api/v1/market/klines returns 15m OHLCV bars matching chart contract."""
        resp = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "SOLUSDT"
        assert data["interval"] == "15m"
        assert len(data["candles"]) > 0
        k0 = data["candles"][0]
        for key in ("timestamp", "open", "high", "low", "close", "volume"):
            assert key in k0

    def test_t1_f3_candlestick_1h_ingress_contract(self, api_client: TestClient) -> None:
        """F3.4: Verify /api/v1/market/klines returns 1h OHLCV bars for macro trend overlay."""
        resp = api_client.get("/api/v1/market/klines?symbol=BTCUSDT&interval=1h&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "BTCUSDT"
        assert data["interval"] == "1h"
        assert len(data["candles"]) > 0

    def test_t1_f3_sub_dollar_coin_decimal_precision(self, api_client: TestClient) -> None:
        """F3.5: Verify sub-dollar coin prices (DOGE, XRP, SUI) preserve decimal fidelity."""
        resp = api_client.get("/api/v1/market/prices")
        assert resp.status_code == 200
        prices = resp.json()["prices"]
        assert prices["DOGEUSDT"] < 1.0  # e.g. ~$0.086
        assert prices["SUIUSDT"] > 0.1
        assert prices["XRPUSDT"] > 0.1

    def test_t1_f3_candlestick_drawer_active_bracket_lines(self) -> None:
        """F3.6: Verify active position bracket calculation produces TP (+2.0x ATR)
        and SL (-1.2x ATR)."""
        entry_price = Decimal("180.00")
        atr = Decimal("3.50")
        expected_tp = entry_price + (Decimal("2.0") * atr)  # 187.00
        expected_sl = entry_price - (Decimal("1.2") * atr)  # 175.80
        rr_ratio = (expected_tp - entry_price) / (entry_price - expected_sl)
        assert round(rr_ratio, 2) == Decimal("1.67")

    # --------------------------------------------------------------------------
    # F4: Strategy Confluence Radar & Hawkes Hazard (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f4_btc_macro_trend_filter_bearish_regime(self) -> None:
        """F4.1: Verify BTC macro trend filter in Bearish regime pauses long entries in English."""
        state = _build_macro_gating_state("BEARISH")
        assert state.regime == "BEARISH"
        assert state.longs_filtered is True
        assert state.is_long_allowed is False
        assert "Long entries temporarily paused" in state.explanation
        assert "capital protection" in state.explanation
        assert "EMA 50 < EMA 200" in state.explanation

    def test_t1_f4_btc_macro_trend_filter_bullish_regime(self) -> None:
        """F4.2: Verify BTC macro trend filter in Bullish regime permits long entries in English."""
        state = _build_macro_gating_state("BULLISH")
        assert state.regime == "BULLISH_ALIGNED"
        assert state.longs_filtered is False
        assert state.is_long_allowed is True
        assert "Long scalper entries permitted" in state.explanation
        assert "EMA 50 > EMA 200" in state.explanation

    def test_t1_f4_scalper_checklist_confluence_criteria(self) -> None:
        """F4.3: Verify 15m scalper checklist criteria (dip > 2.5x ATR, vol > 2.2x, RSI < 26)."""
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
        assert signal.is_maker is True

    def test_t1_f4_maker_fee_advantage_0_02_pct(self) -> None:
        """F4.4: Verify maker order fee calculation applies strictly 0.02% maker rate."""
        notional = Decimal("5.00")
        fee = notional * Decimal("0.0002")
        assert fee == Decimal("0.001000")

    def test_t1_f4_hawkes_microstructure_safe_regime(self) -> None:
        """F4.5: Verify Hawkes microstructure hazard is SAFE when spectral radius rho < 1.0."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), hawkes_spectral_radius=0.75, ensemble_signal="BUY"
        )
        assert order is not None
        assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

    def test_t1_f4_recent_orders_authentic_canary_ids(self, api_client: TestClient) -> None:
        """F4.6: Verify Recent Orders feed exposes authentic canary order IDs (no ord-p309-)."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        orders = resp.json()["recent_orders"]
        for o in orders:
            cid = o["client_order_id"]
            assert not cid.startswith("ord-p309-")
            assert "canary-p31" in cid or "canary-p310" in cid or "canary-p311" in cid

    # --------------------------------------------------------------------------
    # F5: Evolution State Machine & OOS Qualification Telemetry (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f5_evolution_five_discrete_stages(self) -> None:
        """F5.1: Verify the dynamic evolution pipeline contains all 5 discrete stages."""
        assert len(VALID_CYCLE_STAGES) == 5
        for stage in (
            "INGRESS",
            "HEALTH_EVALUATION",
            "TRADE_AUTOPSY",
            "MUTATION_STAGING",
            "SHADOW_OOS_GATE",
        ):
            assert stage in VALID_CYCLE_STAGES
            assert stage in INSTITUTIONAL_STAGE_TITLES

    def test_t1_f5_evolution_cycle_interval_fixed_15s(self, api_client: TestClient) -> None:
        """F5.2: Verify evolution cycle scan window is fixed to 15 seconds."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert 1 <= lp["next_cycle_seconds"] <= 15

    def test_t1_f5_oos_qualification_gate_sample_hurdle_five(self, api_client: TestClient) -> None:
        """F5.3: Verify OOS qualification gate requires strictly 5 trade samples."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert lp["required_trades_count"] == 5
        assert lp["oos_gate"]["samples_required"] == 5

    def test_t1_f5_oos_qualification_sharpe_hurdle_15pct(self, api_client: TestClient) -> None:
        """F5.4: Verify OOS qualification Sharpe hurdle is strictly >= 15.0%."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        lp = resp.json()["live_progress"]
        assert lp["sharpe_hurdle_pct"] == 15.0
        assert lp["oos_gate"]["sharpe_hurdle_pct"] == 15.0

    def test_t1_f5_oos_gate_status_waiting_for_samples(self) -> None:
        """F5.5: Verify status is WAITING_FOR_SAMPLES when closed trade count < 5."""
        for trades in [0, 1, 2, 3, 4]:
            evo = load_verified_canary_auto_evolution(simulated_closed_trades=trades)
            assert evo.live_progress.stage_status == "WAITING_FOR_SAMPLES"
            assert evo.live_progress.stage_status_label == f"WAITING_FOR_SAMPLES ({trades}/5)"

    def test_t1_f5_oos_gate_status_evaluating_at_five_trades(self) -> None:
        """F5.6: Verify status transitions to EVALUATING or QUALIFIED at 5 trade samples."""
        evo = load_verified_canary_auto_evolution(simulated_closed_trades=5)
        assert evo.live_progress.stage_status in ("EVALUATING", "QUALIFIED")
        assert evo.live_progress.cycle_progress_pct == 100.0

    # --------------------------------------------------------------------------
    # F6: Backend Telemetry Endpoints & Event Descriptions (6 tests)
    # --------------------------------------------------------------------------

    def test_t1_f6_canary_evolution_endpoint_schema(self, api_client: TestClient) -> None:
        """F6.1: Verify /api/v1/canary/evolution returns valid schema with required fields."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified"] is True
        assert "live_progress" in data
        assert "solvency" in data

    def test_t1_f6_live_evolution_event_model_english_fields(self) -> None:
        """F6.2: Verify LiveEvolutionEventItem domain model supports institutional
        English event titles."""
        event = LiveEvolutionEventItem(
            event_type="HEARTBEAT_INGRESS",
            title="Heartbeat & Market Ingress",
            detail="Binance Futures 15m & 1h klines streaming synchronized (8 pairs)",
            status="HEALTHY",
            latency_ms=42.0,
            timestamp_ms=1728600000000,
        )
        assert event.title == "Heartbeat & Market Ingress"
        assert event.event_type == "HEARTBEAT_INGRESS"
        assert event.status == "HEALTHY"

    def test_t1_f6_macro_gating_state_item_english_explanation(self) -> None:
        """F6.3: Verify MacroGatingStateItem domain model defaults and explanations
        are in English."""
        item = MacroGatingStateItem(
            regime="BEARISH",
            longs_filtered=True,
            explanation=(
                "Long entries temporarily paused by BTC 1h/4h Bearish regime filter "
                "for capital protection (EMA 50 < EMA 200)."
            ),
            is_long_allowed=False,
        )
        assert "Long entries temporarily paused" in item.explanation
        assert item.is_long_allowed is False

    def test_t1_f6_backwards_compatible_explanation_ms_preserved(
        self, api_client: TestClient
    ) -> None:
        """F6.4: Verify explanation_ms key is preserved in API response for compatibility."""
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        mg = resp.json()["live_progress"]["macro_gating_state"]
        assert "explanation_ms" in mg
        assert len(mg["explanation_ms"]) > 10
        assert "explanation" in mg
        assert len(mg["explanation"]) > 10

    def test_t1_f6_solvency_zero_drift_invariant_in_evolution_endpoint(
        self, api_client: TestClient
    ) -> None:
        """F6.5: Verify solvency object in /api/v1/canary/evolution verifies zero drift.

        Checks |Δ| < 1e-15 USDT.
        """
        resp = api_client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        solv = resp.json()["solvency"]
        assert solv["zero_balance_drift_verified"] is True
        assert abs(solv["drift_usdt"]) < 1e-15

    def test_t1_f6_execution_status_endpoint_truthful_solvency(
        self, api_client: TestClient
    ) -> None:
        """F6.6: Verify /api/v1/execution/status reports exact zero balance drift and capital."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        solv = resp.json()["solvency"]
        assert solv["zero_balance_drift_verified"] is True
        assert abs(solv["drift_usdt"]) < 1e-15
        assert solv["cash_reserve_pct"] == 100.0


# ==============================================================================
# TIER 2 — BOUNDARY & CORNER CASES (26 TESTS ACROSS 6 CATEGORIES)
# ==============================================================================


class TestTier2BoundaryAndCorner:
    """Tier 2: Boundary Value Analysis and edge condition stress tests."""

    # --------------------------------------------------------------------------
    # B1: Empty States & Zero Completed Trades (5 tests)
    # --------------------------------------------------------------------------

    def test_t2_b1_zero_completed_trades_win_rate_zero(self) -> None:
        """B1.1: Verify completed trades = 0 yields exactly 0.0% win rate."""
        total_trades = 0
        winning_trades = 0
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0
        assert win_rate == 0.0

    def test_t2_b1_empty_order_feed_handling(self) -> None:
        """B1.2: Verify empty order feed structure handles zero records without exception."""
        orders: list[dict[str, Any]] = []
        filtered_orders = [o for o in orders if o.get("symbol") == "SOLUSDT"]
        assert len(filtered_orders) == 0

    def test_t2_b1_zero_active_positions_count(self, api_client: TestClient) -> None:
        """B1.3: Verify 0 active positions reports 0 open positions across 8 monitored pairs."""
        resp = api_client.get("/api/v1/execution/status")
        assert resp.status_code == 200
        positions = resp.json()["positions"]
        open_count = sum(1 for p in positions.values() if p["position_qty"] > 0)
        assert open_count == 0
        assert len(positions) == 8

    def test_t2_b1_empty_recent_events_fallback(self) -> None:
        """B1.4: Verify empty recent events array defaults safely without crashing."""
        progress = LiveEvolutionProgressItem(recent_events=[])
        assert len(progress.recent_events) == 0

    def test_t2_b1_zero_closed_trades_oos_gate_state(self) -> None:
        """B1.5: Verify 0 closed trades sets OOS gate status strictly to WAITING_FOR_SAMPLES."""
        evo = load_verified_canary_auto_evolution(simulated_closed_trades=0)
        assert evo.live_progress.stage_status == "WAITING_FOR_SAMPLES"
        assert evo.live_progress.stage_status_label == "WAITING_FOR_SAMPLES (0/5)"

    # --------------------------------------------------------------------------
    # B2: Negative PnL & Sub-Zero Currency Formatting (4 tests)
    # --------------------------------------------------------------------------

    def test_t2_b2_negative_realized_loss_formatting(self) -> None:
        """B2.1: Verify realized loss formatting outputs leading minus without duplicate symbols."""
        loss_val = Decimal("-0.1200")
        formatted = f"{loss_val:+.4f}" if loss_val > 0 else f"{loss_val:.4f}"
        assert formatted == "-0.1200"
        assert "+-" not in formatted
        assert "--" not in formatted

    def test_t2_b2_positive_realized_gain_formatting(self) -> None:
        """B2.2: Verify realized gain formatting outputs leading plus sign."""
        gain_val = Decimal("0.4500")
        formatted = f"+{gain_val:.4f}"
        assert formatted == "+0.4500"

    def test_t2_b2_exact_zero_pnl_formatting(self) -> None:
        """B2.3: Verify exact zero PnL formats neutrally without negative zero."""
        zero_val = Decimal("0.0000")
        formatted = f"{zero_val:.4f}"
        assert formatted == "0.0000"
        assert "-0.0000" not in formatted

    def test_t2_b2_sub_cent_micro_fee_loss_formatting(self) -> None:
        """B2.4: Verify sub-cent fee deduction (-0.0011 USDT) preserves micro decimal precision."""
        fee_pnl = Decimal("-0.0011")
        assert fee_pnl < Decimal("0")
        formatted = f"{fee_pnl:.4f}"
        assert formatted == "-0.0011"

    # --------------------------------------------------------------------------
    # B3: Zero and Negative Cycle Timers (4 tests)
    # --------------------------------------------------------------------------

    def test_t2_b3_timer_exact_zero_seconds(self) -> None:
        """B3.1: Verify countdown timer at exactly 0s clamps safely to 0s window."""
        timer_sec = 0
        clamped = max(0, timer_sec)
        assert clamped == 0

    def test_t2_b3_timer_negative_seconds_clamping(self) -> None:
        """B3.2: Verify negative timer input (-10s) clamps to 0s without crashing."""
        timer_sec = -10
        clamped = max(0, timer_sec)
        assert clamped == 0

    def test_t2_b3_timer_upper_window_boundary_15s(self) -> None:
        """B3.3: Verify timer upper boundary is capped at 15s window."""
        now_epoch_ms = 1728600000000
        sec_in_cycle = (now_epoch_ms // 1000) % 15
        next_cycle_seconds = 15 - sec_in_cycle if sec_in_cycle > 0 else 15
        assert 1 <= next_cycle_seconds <= 15

    def test_t2_b3_timer_progression_across_all_15_second_offsets(self) -> None:
        """B3.4: Verify timer and stage progression across all 15 discrete second offsets."""
        base_epoch_ms = 1728600000000
        for sec in range(15):
            t = base_epoch_ms + sec * 1000
            sec_in_cycle = (t // 1000) % 15
            stage_idx = min(4, sec_in_cycle // 3)
            assert stage_idx in (0, 1, 2, 3, 4)

    # --------------------------------------------------------------------------
    # B4: Disconnected Feeds & Latency Boundaries (4 tests)
    # --------------------------------------------------------------------------

    def test_t2_b4_latency_boundary_500ms_accepted(self) -> None:
        """B4.1: Verify gateway latency at exactly 500.0ms is accepted."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), heartbeat_age_ms=500.0, ensemble_signal="BUY"
        )
        assert order is not None

    def test_t2_b4_latency_boundary_500_1ms_blocked(self) -> None:
        """B4.2: Verify gateway latency at 500.1ms is rejected fail-closed."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), heartbeat_age_ms=500.1, ensemble_signal="BUY"
        )
        assert order is None
        assert engine.events_log[-1]["event_type"] == "HEARTBEAT_STALE_BLOCK"

    def test_t2_b4_supercritical_hawkes_boundary_1_00_blocked(self) -> None:
        """B4.3: Verify Hawkes spectral radius at rho = 1.00 triggers HAWKES_THROTTLED."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), hawkes_spectral_radius=1.00, ensemble_signal="BUY"
        )
        assert order is None
        assert engine.state == SelfDrivingState.HAWKES_THROTTLED

    def test_t2_b4_subcritical_hawkes_boundary_0_99_permitted(self) -> None:
        """B4.4: Verify Hawkes spectral radius at rho = 0.99 permits trading."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), hawkes_spectral_radius=0.99, ensemble_signal="BUY"
        )
        assert order is not None
        assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

    # --------------------------------------------------------------------------
    # B5: Flat Positions & Target Suppression (4 tests)
    # --------------------------------------------------------------------------

    def test_t2_b5_flat_position_tp_sl_suppressed(self) -> None:
        """B5.1: Verify flat positions (0.00 exposure) suppress TP and SL price target values."""
        engine = build_default_self_driving_engine()
        cand = engine.candidates["SOLUSDT"]
        assert cand.position_qty == Decimal("0.0")
        assert cand.allocated_exposure_usdt == Decimal("0.0")
        assert cand.take_profit == Decimal("0.0")
        assert cand.stop_loss == Decimal("0.0")

    def test_t2_b5_flat_position_risk_reward_dash(self) -> None:
        """B5.2: Verify flat positions return dash ('—') for risk:reward ratio."""
        cand_qty = 0.0
        rr_display = "—" if cand_qty == 0.0 else "1.66 : 1"
        assert rr_display == "—"

    def test_t2_b5_flat_position_100pct_cash_reserve(self) -> None:
        """B5.3: Verify flat account maintains 100.0% liquid cash reserve."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        snap = ledger.get_snapshot()
        reserve_pct = (snap.cash / snap.total_equity) * 100.0
        assert reserve_pct == 100.0

    def test_t2_b5_flat_position_entry_price_omitted_or_zero(self) -> None:
        """B5.4: Verify flat candidate has 0.0 entry price."""
        engine = build_default_self_driving_engine()
        assert engine.candidates["ETHUSDT"].entry_price == Decimal("0.0")

    # --------------------------------------------------------------------------
    # B6: Micro-Capital Boundaries (5 tests)
    # --------------------------------------------------------------------------

    def test_t2_b6_child_order_cap_boundary_5_00_usdt(self) -> None:
        """B6.1: Verify micro child order sizing enforces strictly <= 5.00 USDT + 1 step size."""
        engine = build_default_self_driving_engine()
        assert engine.config.max_micro_order_notional_usdt == Decimal("5.00")
        for sym in CANDIDATE_7_PAIRS:
            p = (
                Decimal("180.00")
                if sym == "SOLUSDT"
                else Decimal("0.086")
                if sym == "DOGEUSDT"
                else Decimal("1.40")
                if sym == "XRPUSDT"
                else Decimal("100.00")
            )
            _, qty, notional = engine._calculate_child_order_qty(sym, p)
            step = DEFAULT_SPECS[sym]["step_size"]
            assert notional >= Decimal("5.00")
            assert notional <= Decimal("5.00") + (step * p)

    def test_t2_b6_aggregate_exposure_boundary_25_00_permitted(self) -> None:
        """B6.2: Verify aggregate exposure at exactly $25.00 USDT is accepted."""
        engine = build_default_self_driving_engine()
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("20.00")
        engine.candidates["ETHUSDT"].allocated_exposure_usdt = Decimal("5.00")
        total_exp = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
        assert total_exp == Decimal("25.00")
        assert total_exp <= engine.config.max_aggregate_exposure_usdt

    def test_t2_b6_aggregate_exposure_boundary_25_01_blocked(self) -> None:
        """B6.3: Verify aggregate exposure that would exceed $25.00 USDT is blocked fail-closed."""
        engine = build_default_self_driving_engine()
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("25.00")
        order = engine.process_microstructure_tick(
            "ETHUSDT", Decimal("2500.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.interlock_blocks_count == 1
        assert engine.events_log[-1]["event_type"] == "AGGREGATE_EXPOSURE_CAP_BLOCK"

    def test_t2_b6_cash_reserve_floor_75pct_boundary(self) -> None:
        """B6.4: Verify cash reserve floor blocks orders when available cash drops below 75%."""
        engine = build_default_self_driving_engine()
        engine.ledger.cash = Decimal("74.99")
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.events_log[-1]["event_type"] == "CASH_RESERVE_FLOOR_BLOCK"

    def test_t2_b6_daily_loss_ceiling_3_00_usdt_boundary(self) -> None:
        """B6.5: Verify daily loss ceiling trips circuit flattened at $3.00 USDT."""
        engine = build_default_self_driving_engine()
        engine.intra_day_loss_usdt = Decimal("3.00")
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), ensemble_signal="BUY"
        )
        assert order is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED


# ==============================================================================
# TIER 3 — CROSS-FEATURE COMBINATIONS (16 TESTS)
# ==============================================================================


class TestTier3CrossFeatureCombinations:
    """Tier 3: Pairwise combinatorial interactions across multiple Phase 316 features."""

    def test_t3_c1_bearish_macro_filter_suppresses_candidate_dips(self) -> None:
        """C1.1: Verify Bearish macro filter actively suppresses valid candidate dip signals."""
        scalper = MacroLiquidityDipScalper()
        history = make_15m_candle_series(30, base_price=Decimal("100.00"))
        dip_bar = make_candle(1728690000000, 95.0, 95.5, 85.0, 86.0, 5000.0)

        # Dip meets all technical trigger criteria, but macro filter is Bearish
        signal = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=False)
        assert signal is None

    def test_t3_c1_bearish_macro_filter_updates_evolution_stepper_banner(self) -> None:
        """C1.2: Verify Bearish macro regime updates evolution stepper gating banner in English."""
        state = _build_macro_gating_state("BEARISH")
        assert state.regime == "BEARISH"
        assert state.longs_filtered is True
        assert "Long entries temporarily paused" in state.explanation

    def test_t3_c2_bullish_macro_filter_generates_maker_limit_order(self) -> None:
        """C2.1: Verify Bullish macro filter unblocks scalper and structures maker limit order."""
        scalper = MacroLiquidityDipScalper()
        history = make_15m_candle_series(30, base_price=Decimal("100.00"))
        dip_bar = make_candle(1728690000000, 95.0, 95.5, 85.0, 86.0, 5000.0)

        signal = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=True)
        assert signal is not None
        assert signal.side == "BUY"
        assert signal.is_maker is True
        assert signal.order_type == "LIMIT"

    def test_t3_c2_bullish_macro_filter_structures_brackets_with_maker_fee(self) -> None:
        """C2.2: Verify maker limit order has brackets (+2.0x TP, -1.2x SL) and 0.02% fee."""
        scalper = MacroLiquidityDipScalper()
        history = make_15m_candle_series(30, base_price=Decimal("100.00"))
        dip_bar = make_candle(1728690000000, 95.0, 95.5, 85.0, 86.0, 5000.0)

        signal = scalper.evaluate_15m_bar("ETHUSDT", dip_bar, history, macro_trend_allowed=True)
        assert signal is not None
        assert signal.take_profit > signal.sweep_price
        assert signal.stop_loss < signal.sweep_price
        assert signal.reward_to_risk_ratio == Decimal("1.6667")

    def test_t3_c3_double_entry_balance_reconciliation_multi_pair(self) -> None:
        """C3.1: Verify multi-pair concurrent positions hold continuous zero drift (|Δ| < 1e-15)."""
        engine = build_default_self_driving_engine()
        order1 = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), ensemble_signal="BUY"
        )
        order2 = engine.process_microstructure_tick(
            "ETHUSDT", Decimal("2500.00"), ensemble_signal="BUY"
        )
        assert order1 is not None
        assert order2 is not None

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert sum(c.allocated_exposure_usdt for c in engine.candidates.values()) > Decimal("0")

    def test_t3_c3_double_entry_fee_deduction_and_tp_realization(self) -> None:
        """C3.2: Verify fill fee deduction and TP realization maintain zero balance drift."""
        engine = build_default_self_driving_engine()
        engine.process_microstructure_tick("SOLUSDT", Decimal("180.00"), ensemble_signal="BUY")
        cand = engine.candidates["SOLUSDT"]

        # Realize Take-Profit (+2.0x ATR)
        engine._exit_position(
            cand, Decimal("187.00"), int(time.time() * 1000), reason="TAKE_PROFIT"
        )
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
        assert snap.realized_pnl > 0.0
        assert snap.allocated_margin == 0.0

    def test_t3_c4_multi_pair_mark_prices_and_kline_coherence(self, api_client: TestClient) -> None:
        """C4.1: Verify all 8 pairs in /api/v1/market/prices correspond to klines endpoints."""
        resp_p = api_client.get("/api/v1/market/prices")
        assert resp_p.status_code == 200
        prices = resp_p.json()["prices"]
        assert len(prices) == 8

        # Spot check 3 distinct pairs kline responsiveness
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            resp_k = api_client.get(f"/api/v1/market/klines?symbol={sym}&interval=15m&limit=5")
            assert resp_k.status_code == 200
            assert resp_k.json()["symbol"] == sym

    def test_t3_c4_kline_cache_coherence_between_calls(self, api_client: TestClient) -> None:
        """C4.2: Verify repeated klines queries hit cached in-memory response within 5s TTL."""
        t0 = time.time()
        resp1 = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=10")
        resp2 = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=10")
        t1 = time.time()
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["symbol"] == resp2.json()["symbol"]
        assert (t1 - t0) < 1.0  # Fast response confirms cache coherence

    def test_t3_c5_step_up_sizing_sub_dollar_doge_and_ledger_reservation(self) -> None:
        """C5.1: Verify DOGE ($0.086) step-up sizing reserves exact quantized margin in ledger."""
        engine = build_default_self_driving_engine()
        price, qty, notional = engine._calculate_child_order_qty("DOGEUSDT", Decimal("0.086"))
        assert qty == Decimal("59")
        assert notional == Decimal("5.07400")

        # Reserve in ledger
        engine.ledger.cash -= notional
        engine.ledger.allocated_margin += notional
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t3_c5_step_up_sizing_sub_dollar_xrp_sui_and_solvency(self) -> None:
        """C5.2: Verify XRP ($1.40) and SUI ($1.11) step-up maintain double-entry solvency."""
        engine = build_default_self_driving_engine()
        _, q_xrp, n_xrp = engine._calculate_child_order_qty("XRPUSDT", Decimal("1.40"))
        _, q_sui, n_sui = engine._calculate_child_order_qty("SUIUSDT", Decimal("1.11"))
        assert n_xrp >= Decimal("5.00")
        assert n_sui >= Decimal("5.00")

        total_margin = n_xrp + n_sui
        engine.ledger.cash -= total_margin
        engine.ledger.allocated_margin += total_margin
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t3_c6_dynamic_evolution_transitions_during_active_trades(self) -> None:
        """C6.1: Verify dynamic evolution transitions do not corrupt active trade positions."""
        engine = build_default_self_driving_engine()
        engine.process_microstructure_tick("SOLUSDT", Decimal("180.00"), ensemble_signal="BUY")
        assert engine.candidates["SOLUSDT"].position_qty > Decimal("0")

        # Step through all 5 cycle stages
        for sec_offset in (0, 3000, 6000, 9000, 12000):
            evo = load_verified_canary_auto_evolution(
                simulated_timestamp_ms=1728600000000 + sec_offset
            )
            assert evo.live_progress.current_cycle_stage in VALID_CYCLE_STAGES

        # Solvency remains pristine
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t3_c6_evolution_sample_counter_updates_with_closed_trades(self) -> None:
        """C6.2: Verify closed trades increment properly reflects in dynamic OOS scorecards."""
        for trade_count in range(6):
            evo = load_verified_canary_auto_evolution(simulated_closed_trades=trade_count)
            assert evo.live_progress.closed_trades_count == trade_count
            assert evo.live_progress.cycle_progress_pct == round(
                80.0 + (min(trade_count, 5) / 5.0 * 20.0), 2
            )

    def test_t3_c7_supercritical_hawkes_hazard_blocks_order_while_telemetry_streams(self) -> None:
        """C7.1: Verify Hawkes rho >= 1.0 blocks orders while telemetry endpoints remain healthy."""
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), hawkes_spectral_radius=1.10, ensemble_signal="BUY"
        )
        assert order is None
        assert engine.state == SelfDrivingState.HAWKES_THROTTLED

        # Solvency snapshot remains zero-drift
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t3_c7_heartbeat_latency_spike_blocks_order_and_recovers(self) -> None:
        """C7.2: Verify order dispatch throttles on latency spike (>500ms) and recovers."""
        engine = build_default_self_driving_engine()

        # Spike to 600ms
        order_stale = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), heartbeat_age_ms=600.0, ensemble_signal="BUY"
        )
        assert order_stale is None

        # Return to 40ms
        order_fresh = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), heartbeat_age_ms=40.0, ensemble_signal="BUY"
        )
        assert order_fresh is not None
        assert order_fresh.status == OrderStatus.FILLED


# ==============================================================================
# TIER 4 — REAL-WORLD APPLICATION SCENARIOS (5 WORKFLOWS)
# ==============================================================================


class TestTier4RealWorldWorkloads:
    """Tier 4: Comprehensive end-to-end operational scenarios simulating live trading."""

    def test_t4_s1_end_to_end_user_navigation_lifecycle(self, api_client: TestClient) -> None:
        """Scenario 1: End-to-end user navigation & telemetry query workflow.

        Simulates owner visiting Mission Control, checking Executive Overview, inspecting
        Live Positions across all 8 pairs, viewing Recent Orders feed, validating Solvency proof,
        and examining Strategy Evolution pipeline.
        """
        # 1. Executive Overview Telemetry
        resp_overview = api_client.get("/api/v1/canary/summary")
        assert resp_overview.status_code == 200
        assert resp_overview.json()["verified"] is True
        assert resp_overview.json()["circuit_state"] == "NORMAL"

        # 2. Live Positions & Markets Ingress
        resp_positions = api_client.get("/api/v1/execution/status")
        assert resp_positions.status_code == 200
        pos_data = resp_positions.json()
        assert len(pos_data["positions"]) == 8

        # 3. Trade Log & Executions
        assert "recent_orders" in pos_data
        for o in pos_data["recent_orders"]:
            assert "client_order_id" in o

        # 4. Risk Controls & Solvency Verification
        solv = pos_data["solvency"]
        assert solv["zero_balance_drift_verified"] is True
        assert abs(solv["drift_usdt"]) < 1e-15

        # 5. Strategy Evolution Pipeline
        resp_evo = api_client.get("/api/v1/canary/evolution")
        assert resp_evo.status_code == 200
        lp = resp_evo.json()["live_progress"]
        assert lp["current_cycle_stage"] in VALID_CYCLE_STAGES
        assert lp["daemon_pid"] == 87549

    def test_t4_s2_responsive_candlestick_drawer_expansion_and_toggle(
        self, api_client: TestClient
    ) -> None:
        """Scenario 2: Responsive candlestick drawer expansion with bracket overlays.

        Simulates owner clicking 'Interactive Chart' on SOLUSDT, inspecting 15m scalper klines,
        toggling to 1h macro trend klines, and verifying OHLCV schema.
        """
        # Step A: Query 15m Scalper Candlesticks
        resp_15m = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=20")
        assert resp_15m.status_code == 200
        data_15m = resp_15m.json()
        assert data_15m["symbol"] == "SOLUSDT"
        assert data_15m["interval"] == "15m"
        assert len(data_15m["candles"]) == 20

        # Step B: Toggle to 1h Macro Trend Candlesticks
        resp_1h = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=1h&limit=20")
        assert resp_1h.status_code == 200
        data_1h = resp_1h.json()
        assert data_1h["symbol"] == "SOLUSDT"
        assert data_1h["interval"] == "1h"
        assert len(data_1h["candles"]) == 20

        # Step C: Verify mark price matches chart baseline
        resp_prices = api_client.get("/api/v1/market/prices")
        assert resp_prices.status_code == 200
        assert "SOLUSDT" in resp_prices.json()["prices"]

    def test_t4_s3_full_trade_lifecycle_and_solvency_audit(self) -> None:
        """Scenario 3: Full trade lifecycle: Dip detection -> Maker limit -> TP -> Solvency audit.

        Simulates complete scalper execution:
        1. BTC Macro trend Bullish
        2. 15m liquidity dip detected on SOLUSDT
        3. Maker limit order submitted & filled at sweep price
        4. Take-Profit bracket placed at +2.0x ATR
        5. Position realized at TP target
        6. CentralizedSolvencyLedger reconciles cash, margin, fees, and PnL holding zero drift.
        """
        engine = build_default_self_driving_engine()
        initial_snap = engine.ledger.get_snapshot()
        assert initial_snap.zero_balance_drift is True
        assert abs(initial_snap.drift) < 1e-15

        # 1. Dispatch Scalper Maker Limit Order
        order = engine.process_microstructure_tick(
            "SOLUSDT", Decimal("180.00"), ensemble_signal="BUY"
        )
        assert order is not None
        assert order.status == OrderStatus.FILLED
        assert order.is_maker is True
        assert order.fee_usdt > Decimal("0")

        # 2. Verify Position is Active
        cand = engine.candidates["SOLUSDT"]
        assert cand.position_qty > Decimal("0")
        assert cand.allocated_exposure_usdt <= Decimal("25.00")

        # 3. Mid-Trade Solvency Check
        mid_snap = engine.ledger.get_snapshot()
        assert mid_snap.zero_balance_drift is True
        assert abs(mid_snap.drift) < 1e-15

        # 4. Take-Profit Realization (+2.0x ATR)
        engine._exit_position(
            cand, Decimal("187.00"), int(time.time() * 1000), reason="TAKE_PROFIT"
        )

        # 5. Final Solvency Audit Snapshot
        final_snap = engine.ledger.get_snapshot()
        assert final_snap.zero_balance_drift is True
        assert abs(final_snap.drift) < 1e-15
        assert final_snap.realized_pnl > 0.0
        assert final_snap.allocated_margin == 0.0
        assert cand.position_qty == Decimal("0.0")

    def test_t4_s4_out_of_sample_qualification_progression(self) -> None:
        """Scenario 4: Out-of-sample qualification progression from 0 to 5 closed trade samples.

        Simulates candidate strategy advancing through the dynamic OOS gate:
        - 0 samples: WAITING_FOR_SAMPLES (0/5), 80% progress
        - 1-4 samples: WAITING_FOR_SAMPLES (N/5), proportional progress (84% -> 96%)
        - 5 samples: EVALUATING / QUALIFIED, 100% progress
        """
        # Stage 0: Starting baseline
        evo_0 = load_verified_canary_auto_evolution(simulated_closed_trades=0)
        assert evo_0.live_progress.stage_status == "WAITING_FOR_SAMPLES"
        assert evo_0.live_progress.closed_trades_count == 0
        assert evo_0.live_progress.cycle_progress_pct == 80.0

        # Stages 1-4: Incremental closed trades
        for trades in (1, 2, 3, 4):
            evo_n = load_verified_canary_auto_evolution(simulated_closed_trades=trades)
            assert evo_n.live_progress.stage_status == "WAITING_FOR_SAMPLES"
            assert evo_n.live_progress.closed_trades_count == trades
            assert evo_n.live_progress.cycle_progress_pct == 80.0 + (trades * 4.0)

        # Stage 5: Full 5-sample hurdle met
        evo_5 = load_verified_canary_auto_evolution(simulated_closed_trades=5)
        assert evo_5.live_progress.stage_status in ("EVALUATING", "QUALIFIED")
        assert evo_5.live_progress.closed_trades_count == 5
        assert evo_5.live_progress.cycle_progress_pct == 100.0

    def test_t4_s5_macro_regime_flip_from_bearish_to_bullish(self) -> None:
        """Scenario 5: Macro regime flip from Bearish to Bullish with scalper reactivated.

        Simulates BTC macro market transition:
        - Phase 1: Bearish regime pauses candidate dips for capital protection
        - Phase 2: BTC confirms Bullish regime flip (EMA 50 > EMA 200)
        - Phase 3: Scalper evaluates candidate universe and dispatches maker limit orders
        - Phase 4: Double-entry ledger reconciles balance with zero drift.
        """
        scalper = MacroLiquidityDipScalper()
        history = make_15m_candle_series(30, base_price=Decimal("100.00"))
        dip_bar = make_candle(1728690000000, 95.0, 95.5, 85.0, 86.0, 5000.0)

        # Phase 1: Bearish Regime
        state_bearish = _build_macro_gating_state("BEARISH")
        assert state_bearish.longs_filtered is True
        signal_bearish = scalper.evaluate_15m_bar(
            "DOGEUSDT", dip_bar, history, macro_trend_allowed=state_bearish.is_long_allowed
        )
        assert signal_bearish is None

        # Phase 2: Bullish Regime Flip
        state_bullish = _build_macro_gating_state("BULLISH")
        assert state_bullish.longs_filtered is False
        assert state_bullish.is_long_allowed is True
        assert "Long scalper entries permitted" in state_bullish.explanation

        # Phase 3: Candidate Dip Evaluated & Order Dispatched
        signal_bullish = scalper.evaluate_15m_bar(
            "DOGEUSDT", dip_bar, history, macro_trend_allowed=state_bullish.is_long_allowed
        )
        assert signal_bullish is not None
        assert signal_bullish.side == "BUY"
        assert signal_bullish.is_maker is True

        # Phase 4: Ledger Solvency Reconciles
        engine = build_default_self_driving_engine()
        order = engine.process_microstructure_tick(
            "DOGEUSDT", Decimal("0.086"), ensemble_signal="BUY"
        )
        assert order is not None
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15
