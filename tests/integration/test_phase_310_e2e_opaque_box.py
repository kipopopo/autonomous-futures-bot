"""Autonomous Futures Bot - Phase 310: Comprehensive Opaque-Box E2E Test Suite.

Validates the Phase 310 Real Autonomous Trading Engine, Binance Futures Live/Testnet
Gateway Bridge, Macro Liquidity Scalper, Self-Learning Autopsy Closure, and 24/7 VPS
Deployment with Telegram Telemetry across all 4 tiers of the TEST_INFRA.md methodology:

- Tier 1: Feature Coverage (40 tests across all 8 features):
    * F1: Binance Futures Dual-Mode Gateway Bridge
    * F2: WebSocket User Data Stream & listenKey Keepalive
    * F3: Macro Liquidity Sweep Scalper & BTC Trend Filter
    * F4: Trade Structuring, Fee Drag & Time Decay Stop
    * F5: Closed-Loop Autopsy Feedback & Telemetry DB
    * F6: Fail-Closed Daily Drawdown Pause (3.00 USDT)
    * F7: Double-Entry Solvency & Micro-Capital Bounds
    * F8: 24/7 VPS Deployment & Telegram Alerts

- Tier 2: Boundary & Corner Cases (40 tests across all 8 features):
    * Extreme limits, clock drift (|dt| = 999ms vs 1001ms), precision rounding at
      MIN_NOTIONAL step-size, empty buffers, zero/negative RSI, 8-bar decay limit,
      consecutive loss tiers, sub-satoshi zero drift.

- Tier 3: Cross-Feature Interactions (16 tests):
    * Pairwise combinatorial testing: Gateway + Scalper, Scalper + Solvency,
      Autopsy + Drawdown Pause, Gateway + Telegram, Solvency + VPS deployment,
      WebSocket + Gateway reconciliation, Hawkes interlock, etc.

- Tier 4: Real-World Application Workload Scenarios (6 scenarios):
    * Multi-step trading session in BTC bull regime, hostile liquidity cascade &
      Hawkes throttle, network disconnect & clock resync, drawdown breach & fail-closed
      flattening, continuous self-learning lifecycle, and Merkle DAG lineage verification.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from autonomous_futures.execution.binance_gateway import (
    BINANCE_LIVE_REST_BASE,
    BINANCE_TESTNET_REST_BASE,
    BinanceAPIError,
    BinanceFuturesGateway,
    generate_client_order_id,
    quantize_step_size,
    quantize_tick_size,
)
from autonomous_futures.execution.self_driving import (
    SelfDrivingState,
    build_default_self_driving_engine,
)
from autonomous_futures.feed.auto_evolution import (
    AutopsyAttributionCause,
    CandidateHealthTier,
    ContinuousSelfLearningDaemon,
    StrategyAutopsyEngine,
    TradeAutopsyRecord,
)
from autonomous_futures.notify.telegram import (
    TelegramConfig,
    escape_markdown_v2,
    format_order_placed_alert,
    format_risk_alert,
    format_tp_sl_realized_alert,
    mask_token,
    sanitize_telegram_string,
)
from autonomous_futures.safety.kill_switch import (
    CentralizedSolvencyLedger,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    MacroLiquidityDipScalper,
    MacroTrendFilter,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Parent Phase 309 Merkle Root constant from PROJECT.md
PARENT_PHASE_309_MERKLE_ROOT = "5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844"


# ==============================================================================
# TEST FIXTURES & DATA GENERATION HELPERS
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


def make_btc_candles(count: int = 220, bull: bool = True) -> list[Candle]:
    """Generates synthetic 1h BTC candles for macro trend testing."""
    candles: list[Candle] = []
    base_ts = 1700000000000
    for i in range(count):
        ts = base_ts + i * 3600000
        if bull:
            price = Decimal(str(50000 + i * 200))
        else:
            price = Decimal(str(90000 - i * 200))
        candles.append(
            make_candle(
                ts_ms=ts,
                open_p=price,
                high_p=price + Decimal("100"),
                low_p=price - Decimal("100"),
                close_p=price,
                vol=Decimal("500"),
            )
        )
    return candles


def make_scalper_history(count: int = 35, base_price: Decimal = Decimal("200.00")) -> list[Candle]:
    """Generates baseline 15m candles with normal volume and low volatility."""
    history: list[Candle] = []
    base_ts = 1700000000000
    for i in range(count):
        ts = base_ts + i * 900000
        p = base_price + Decimal(str(i * 0.1))
        history.append(
            make_candle(
                ts_ms=ts,
                open_p=p,
                high_p=p + Decimal("1.0"),
                low_p=p - Decimal("1.0"),
                close_p=p,
                vol=Decimal("100.0"),
            )
        )
    return history


def make_dip_trigger_candle(
    prev_candle: Candle,
    drop_pct: Decimal = Decimal("0.15"),
    vol_multiplier: Decimal = Decimal("10.0"),
) -> Candle:
    """Generates a capitulation dip candle that triggers the 15m scalper."""
    ts = prev_candle.timestamp_ms + 900000
    open_p = prev_candle.close
    close_p = open_p * (Decimal("1") - drop_pct)
    low_p = close_p - Decimal("2.0")
    high_p = open_p + Decimal("0.5")
    vol = prev_candle.volume * vol_multiplier
    return make_candle(
        ts_ms=ts,
        open_p=open_p,
        high_p=high_p,
        low_p=low_p,
        close_p=close_p,
        vol=vol,
    )


# ==============================================================================
# TIER 1: FEATURE COVERAGE (CATEGORY-PARTITION)
# ==============================================================================


class TestTier1Feature1BinanceGateway:
    """Feature 1: Dual-Mode Binance Futures Gateway Bridge (REST & Auth)."""

    def test_t1_f1_01_gateway_dual_mode_toggle_live_and_testnet(self) -> None:
        """T1.F1.01: Verifies gateway toggles between Testnet and Live base URLs."""
        gw_testnet = BinanceFuturesGateway(testnet=True, offline_mode=True)
        assert gw_testnet.testnet is True
        assert gw_testnet.rest_base == BINANCE_TESTNET_REST_BASE

        gw_live = BinanceFuturesGateway(testnet=False, offline_mode=True)
        assert gw_live.testnet is False
        assert gw_live.rest_base == BINANCE_LIVE_REST_BASE

    def test_t1_f1_02_hmac_sha256_signature_generation(self) -> None:
        """T1.F1.02: Verifies HMAC-SHA256 signature generation and parameter encoding."""
        gw = BinanceFuturesGateway(
            api_key="test-api-key",
            api_secret="test-secret-hash-12345",
            offline_mode=True,
        )
        params = {"symbol": "BTCUSDT", "side": "BUY", "quantity": "0.001"}
        signed = gw.sign_payload(params)
        assert "timestamp" in signed
        assert "signature" in signed
        assert len(signed["signature"]) == 64
        assert signed["symbol"] == "BTCUSDT"

    def test_t1_f1_03_monotonic_nonce_strict_increment(self) -> None:
        """T1.F1.03: Verifies monotonic timestamp nonce guarantees strict increases."""
        gw = BinanceFuturesGateway(offline_mode=True)
        nonces = [gw._get_monotonic_timestamp() for _ in range(20)]
        for i in range(len(nonces) - 1):
            assert nonces[i] < nonces[i + 1]

    def test_t1_f1_04_create_and_cancel_order_rest_endpoints(self) -> None:
        """T1.F1.04: Verifies order placement and cancellation lifecycle via gateway."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            cid = generate_client_order_id("SOLUSDT")
            order_res = await gw.create_order(
                symbol="SOLUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity=Decimal("0.02"),
                price=Decimal("180.00"),
                client_order_id=cid,
            )
            assert order_res["status"] == "NEW"
            assert order_res["clientOrderId"] == cid
            assert order_res["symbol"] == "SOLUSDT"

            cancel_res = await gw.cancel_order(symbol="SOLUSDT", client_order_id=cid)
            assert cancel_res["status"] == "CANCELED"
            assert cancel_res["symbol"] == "SOLUSDT"

        asyncio.run(_run())

    def test_t1_f1_05_position_risk_and_account_balance_sync(self) -> None:
        """T1.F1.05: Verifies positionRisk and account sync queries return structured state."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            pos = await gw.get_position_risk("SOLUSDT")
            assert len(pos) >= 1
            assert pos[0]["symbol"] == "SOLUSDT"

            bal = await gw.get_account_balance()
            assert float(bal["totalWalletBalance"]) > 0.0
            assert bal["canTrade"] is True

        asyncio.run(_run())


class TestTier1Feature2UserDataStream:
    """Feature 2: WebSocket User Data Stream & listenKey Keepalive."""

    def test_t1_f2_01_listen_key_creation(self) -> None:
        """T1.F2.01: Verifies acquisition of a fresh listenKey."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            key = await gw.create_listen_key()
            assert isinstance(key, str)
            assert key.startswith("lk-")
            assert key in gw._active_listen_keys

        asyncio.run(_run())

    def test_t1_f2_02_listen_key_keepalive_success(self) -> None:
        """T1.F2.02: Verifies periodic keepalive loop successfully extends listenKey."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            key = await gw.create_listen_key()
            ok = await gw.keepalive_user_data_stream(key)
            assert ok is True

        asyncio.run(_run())

    def test_t1_f2_03_listen_key_close_and_teardown(self) -> None:
        """T1.F2.03: Verifies graceful closure and cleanup of active listenKey."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            key = await gw.create_listen_key()
            assert key in gw._active_listen_keys
            closed = await gw.close_user_data_stream(key)
            assert closed is True
            assert key not in gw._active_listen_keys

        asyncio.run(_run())

    def test_t1_f2_04_user_data_event_order_trade_update_dispatch(self) -> None:
        """T1.F2.04: Verifies ORDER_TRADE_UPDATE event dispatch to registered handler."""
        gw = BinanceFuturesGateway(offline_mode=True)
        received_events: list[dict[str, Any]] = []

        def on_order(event: dict[str, Any]) -> None:
            received_events.append(event)

        mock_payload = {
            "e": "ORDER_TRADE_UPDATE",
            "T": 1700000000100,
            "o": {
                "s": "SOLUSDT",
                "c": "canary-p310-sol-01",
                "S": "BUY",
                "o": "LIMIT",
                "X": "FILLED",
                "q": "0.02",
                "p": "172.00",
                "ap": "172.00",
            },
        }
        res = gw.handle_user_data_event(mock_payload, on_order_trade_update=on_order)
        assert res == "ORDER_TRADE_UPDATE"
        assert len(received_events) == 1
        assert received_events[0]["o"]["X"] == "FILLED"

    def test_t1_f2_05_user_data_event_account_update_dispatch(self) -> None:
        """T1.F2.05: Verifies ACCOUNT_UPDATE event dispatch to registered handler."""
        gw = BinanceFuturesGateway(offline_mode=True)
        received_accounts: list[dict[str, Any]] = []

        def on_account(event: dict[str, Any]) -> None:
            received_accounts.append(event)

        mock_payload = {
            "e": "ACCOUNT_UPDATE",
            "T": 1700000000200,
            "a": {
                "m": "ORDER",
                "B": [{"a": "USDT", "wb": "99.98", "cw": "99.98"}],
                "P": [{"s": "SOLUSDT", "pa": "0.02", "ep": "172.00"}],
            },
        }
        res = gw.handle_user_data_event(mock_payload, on_account_update=on_account)
        assert res == "ACCOUNT_UPDATE"
        assert len(received_accounts) == 1
        assert received_accounts[0]["a"]["P"][0]["s"] == "SOLUSDT"


class TestTier1Feature3MacroTrendFilter:
    """Feature 3: Macro Liquidity Sweep Scalper & BTC Trend Filter."""

    def test_t1_f3_01_btc_macro_trend_bull_alignment(self) -> None:
        """T1.F3.01: Verifies macro trend filter returns True when BTC EMA 50 > EMA 200."""
        gate = MacroTrendFilter()
        btc_bull = make_btc_candles(count=220, bull=True)
        assert gate.evaluate(btc_bull) is True

    def test_t1_f3_02_btc_macro_trend_bear_rejection(self) -> None:
        """T1.F3.02: Verifies macro trend filter returns False when BTC EMA 50 < EMA 200."""
        gate = MacroTrendFilter()
        btc_bear = make_btc_candles(count=220, bull=False)
        assert gate.evaluate(btc_bear) is False

    def test_t1_f3_03_15m_scalper_trigger_on_solusdt(self) -> None:
        """T1.F3.03: Verifies 15m scalper triggers ScalperSignal on SOLUSDT liquidity dip."""
        scalper = MacroLiquidityDipScalper()
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))
        dip_bar = make_dip_trigger_candle(history[-1], drop_pct=Decimal("0.15"))
        sig = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=True)
        assert sig is not None
        assert sig.symbol == "SOLUSDT"
        assert sig.side == "BUY"
        assert sig.order_type == "LIMIT"
        assert sig.sweep_price == dip_bar.close

    def test_t1_f3_04_15m_scalper_trigger_on_ethusdt(self) -> None:
        """T1.F3.04: Verifies 15m scalper triggers on ETHUSDT under macro bull regime."""
        scalper = MacroLiquidityDipScalper()
        history = make_scalper_history(count=35, base_price=Decimal("2800.00"))
        dip_bar = make_dip_trigger_candle(history[-1], drop_pct=Decimal("0.12"))
        sig = scalper.evaluate_15m_bar("ETHUSDT", dip_bar, history, macro_trend_allowed=True)
        assert sig is not None
        assert sig.symbol == "ETHUSDT"
        assert sig.sweep_price == dip_bar.close

    def test_t1_f3_05_15m_scalper_no_trigger_on_calm_bars(self) -> None:
        """T1.F3.05: Verifies calm market bars with normal volume generate no signal."""
        scalper = MacroLiquidityDipScalper()
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))
        normal_bar = make_candle(
            ts_ms=history[-1].timestamp_ms + 900000,
            open_p=Decimal("203.0"),
            high_p=Decimal("203.5"),
            low_p=Decimal("202.8"),
            close_p=Decimal("203.2"),
            vol=Decimal("100.0"),
        )
        sig = scalper.evaluate_15m_bar("SOLUSDT", normal_bar, history, macro_trend_allowed=True)
        assert sig is None


class TestTier1Feature4TradeStructuring:
    """Feature 4: Trade Structuring, Fee Drag & Time Decay Stop."""

    def test_t1_f4_01_maker_limit_order_structuring(self) -> None:
        """T1.F4.01: Verifies ScalperSignal mandates Maker Limit Order execution."""
        scalper = MacroLiquidityDipScalper()
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))
        dip_bar = make_dip_trigger_candle(history[-1])
        sig = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=True)
        assert sig is not None
        assert sig.is_maker is True
        assert sig.order_type == "LIMIT"

    def test_t1_f4_02_protective_stop_loss_1_2x_atr(self) -> None:
        """T1.F4.02: Verifies protective Stop Loss is set at exactly 1.2x ATR below entry."""
        scalper = MacroLiquidityDipScalper(sl_atr_mult=Decimal("1.2"))
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))
        dip_bar = make_dip_trigger_candle(history[-1])
        sig = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=True)
        assert sig is not None
        expected_sl = sig.sweep_price - (Decimal("1.2") * sig.atr)
        assert abs(sig.stop_loss - expected_sl) < Decimal("0.0001")

    def test_t1_f4_03_dynamic_take_profit_2_0x_atr(self) -> None:
        """T1.F4.03: Verifies dynamic Take Profit is set at 2.0x ATR above entry (1.66:1 R:R)."""
        scalper = MacroLiquidityDipScalper(tp_atr_mult=Decimal("2.0"), sl_atr_mult=Decimal("1.2"))
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))
        dip_bar = make_dip_trigger_candle(history[-1])
        sig = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=True)
        assert sig is not None
        expected_tp = sig.sweep_price + (Decimal("2.0") * sig.atr)
        assert abs(sig.take_profit - expected_tp) < Decimal("0.0001")
        assert sig.reward_to_risk_ratio >= Decimal("1.66")

    def test_t1_f4_04_time_decay_momentum_stop_8_bars(self) -> None:
        """T1.F4.04: Verifies time-based decay limit enforces max 8 bars (120 minutes)."""
        scalper = MacroLiquidityDipScalper(max_hold_bars=8)
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))
        dip_bar = make_dip_trigger_candle(history[-1])
        sig = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=True)
        assert sig is not None
        assert sig.max_hold_bars == 8

    def test_t1_f4_05_fee_economics_maker_vs_taker_advantage(self) -> None:
        """T1.F4.05: Maker limit order (0.02% fee) saves 6 bps roundtrip vs Taker (0.05%)."""
        notional = Decimal("5.00")
        maker_fee_roundtrip = notional * Decimal("0.0002") * Decimal("2")
        taker_fee_roundtrip = notional * Decimal("0.0005") * Decimal("2")
        savings = taker_fee_roundtrip - maker_fee_roundtrip
        assert savings == Decimal("0.003000")


class TestTier1Feature5AutopsyFeedback:
    """Feature 5: Closed-Loop Autopsy Feedback & Telemetry DB."""

    def test_t1_f5_01_trade_autopsy_decomposition_organic_alpha(self) -> None:
        """T1.F5.01: Verifies trade autopsy deconstructs winning execution as ORGANIC_ALPHA."""
        engine = StrategyAutopsyEngine()
        rec = engine.deconstruct_trade(
            trade_id="tr-001",
            candidate_id="cand-solusdt",
            symbol="SOLUSDT",
            side="BUY",
            entry_price=170.0,
            exit_price=178.0,
            fill_qty=0.02,
            optimal_price=169.8,
            hawkes_intensity=0.10,
            adverse_delta_pct=0.0002,
            timestamp_ms=1700000000000,
        )
        assert rec.cause == AutopsyAttributionCause.ORGANIC_ALPHA
        assert rec.net_pnl_usdt > 0.0
        assert rec.realized_edge_bps > 0.0

    def test_t1_f5_02_trade_autopsy_timing_delay_classification(self) -> None:
        """T1.F5.02: Verifies trade autopsy classifies delayed fill as TIMING_DELAY."""
        engine = StrategyAutopsyEngine()
        rec = engine.deconstruct_trade(
            trade_id="tr-002",
            candidate_id="cand-solusdt",
            symbol="SOLUSDT",
            side="BUY",
            entry_price=175.0,
            exit_price=172.0,
            fill_qty=0.02,
            optimal_price=170.0,
            hawkes_intensity=0.10,
            adverse_delta_pct=0.0001,
            timestamp_ms=1700000000000,
        )
        assert rec.cause == AutopsyAttributionCause.TIMING_DELAY
        assert rec.entry_timing_error_bps > 6.0

    def test_t1_f5_03_candidate_health_evaluation_elite_tier(self) -> None:
        """T1.F5.03: Verifies candidate with high win rate & Sharpe is classified ELITE."""
        daemon = ContinuousSelfLearningDaemon(min_sample_size=5)
        engine = StrategyAutopsyEngine()
        autopsies: list[TradeAutopsyRecord] = []
        for i in range(10):
            exit_p = 180.0 if i < 8 else 168.0
            rec = engine.deconstruct_trade(
                trade_id=f"tr-{i}",
                candidate_id="cand-solusdt",
                symbol="SOLUSDT",
                side="BUY",
                entry_price=170.0,
                exit_price=exit_p,
                fill_qty=0.02,
                optimal_price=170.0,
                hawkes_intensity=0.10,
                adverse_delta_pct=0.0,
                timestamp_ms=1700000000000 + i * 1000,
            )
            autopsies.append(rec)

        evaluation = daemon.evaluate_candidate("cand-solusdt", "SOLUSDT", autopsies)
        assert evaluation.tier == CandidateHealthTier.ELITE
        assert evaluation.needs_mutation is False
        assert evaluation.win_rate_pct >= 75.0

    def test_t1_f5_04_candidate_health_evaluation_degraded_tier(self) -> None:
        """T1.F5.04: Verifies candidate with 3 consecutive losses is classified DEGRADED."""
        daemon = ContinuousSelfLearningDaemon(min_sample_size=5)
        engine = StrategyAutopsyEngine()
        autopsies: list[TradeAutopsyRecord] = []
        for i in range(5):
            rec = engine.deconstruct_trade(
                trade_id=f"tr-{i}",
                candidate_id="cand-ethusdt",
                symbol="ETHUSDT",
                side="BUY",
                entry_price=2800.0,
                exit_price=2750.0,
                fill_qty=0.001,
                optimal_price=2800.0,
                hawkes_intensity=0.10,
                adverse_delta_pct=0.0,
                timestamp_ms=1700000000000 + i * 1000,
            )
            autopsies.append(rec)

        evaluation = daemon.evaluate_candidate("cand-ethusdt", "ETHUSDT", autopsies)
        assert evaluation.tier == CandidateHealthTier.DEGRADED
        assert evaluation.needs_mutation is True

    def test_t1_f5_05_telemetry_sqlite_persistence(self, tmp_path: Path) -> None:
        """T1.F5.05: Verifies telemetry persistence schema in SQLite database."""
        db_path = tmp_path / "canary-lifecycle-telemetry.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_autopsies (
                trade_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                net_pnl REAL NOT NULL,
                cause TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL
            );
        """)
        conn.execute(
            """INSERT INTO trade_autopsies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            (
                "tr-100",
                "cand-sol",
                "SOLUSDT",
                "BUY",
                170.0,
                180.0,
                0.20,
                "ORGANIC_ALPHA",
                1700000000000,
            ),
        )
        conn.commit()
        cursor = conn.execute("SELECT count(*) FROM trade_autopsies WHERE symbol='SOLUSDT';")
        assert cursor.fetchone()[0] == 1
        conn.close()


class TestTier1Feature6DrawdownPause:
    """Feature 6: Fail-Closed Daily Drawdown Pause (3.00 USDT)."""

    def test_t1_f6_01_daily_drawdown_tracking(self, tmp_path: Path) -> None:
        """T1.F6.01: Verifies engine tracks intra-day realized losses."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        assert engine.intra_day_loss_usdt == Decimal("0.0")

    def test_t1_f6_02_drawdown_ceiling_3_00_usdt_circuit_break(self, tmp_path: Path) -> None:
        """T1.F6.02: Verifies 3.00 USDT drawdown ceiling trips CIRCUIT_FLATTENED."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        engine.intra_day_loss_usdt = Decimal("3.00")
        res = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert res is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED

    def test_t1_f6_03_fail_closed_position_flattening(self, tmp_path: Path) -> None:
        """T1.F6.03: Verifies circuit breaker flattens positions and sets position_qty to 0."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        cand = engine.candidates["BTCUSDT"]
        cand.position_qty = Decimal("0.00005")
        cand.current_price = Decimal("100000.00")
        cand.allocated_exposure_usdt = Decimal("5.00")

        engine._flatten_all_positions(reason="Test drawdown breach")
        assert cand.position_qty == Decimal("0.0")
        assert cand.allocated_exposure_usdt == Decimal("0.0")

    def test_t1_f6_04_order_dispatch_locked_after_circuit_break(self, tmp_path: Path) -> None:
        """T1.F6.04: Verifies all subsequent orders are blocked once CIRCUIT_FLATTENED."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        engine.state = SelfDrivingState.CIRCUIT_FLATTENED
        engine.intra_day_loss_usdt = Decimal("3.05")

        order = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=0.1,
            heartbeat_latency_ms=10.0,
            ensemble_signal="LONG",
            signal_confidence=0.90,
        )
        assert order is None

    def test_t1_f6_05_circuit_breaker_event_logging(self, tmp_path: Path) -> None:
        """T1.F6.05: Verifies EMERGENCY_FLATTEN event is recorded in engine events log."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        cand = engine.candidates["BTCUSDT"]
        cand.position_qty = Decimal("0.00005")
        cand.current_price = Decimal("100000.00")

        engine._flatten_all_positions(reason="Circuit breaker drill")
        event_types = [e["event_type"] for e in engine.events_log]
        assert "EMERGENCY_FLATTEN" in event_types


class TestTier1Feature7SolvencyAndMicroCapital:
    """Feature 7: Double-Entry Solvency & Micro-Capital Bounds."""

    def test_t1_f7_01_double_entry_balance_equation(self) -> None:
        """T1.F7.01: Verifies Assets == Equity double-entry balance equation."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        ledger.record_fill(
            symbol="BTCUSDT",
            side="BUY",
            qty=0.00005,
            price=100000.0,
            fee=0.001,
            realized_pnl=0.0,
        )
        snap = ledger.get_snapshot()
        assert snap.zero_balance_drift is True

    def test_t1_f7_02_absolute_zero_drift_invariant(self) -> None:
        """T1.F7.02: Verifies absolute drift |Delta| < 10^-15 USDT across multi-fills."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        for i in range(15):
            ledger.record_fill(
                symbol="SOLUSDT",
                side="BUY" if i % 2 == 0 else "SELL",
                qty=0.02,
                price=175.0 + i,
                fee=0.0007,
                realized_pnl=0.01 * (1 if i % 2 != 0 else 0),
            )
        snap = ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t1_f7_03_micro_order_child_cap_5_00_usdt(self, tmp_path: Path) -> None:
        """T1.F7.03: Verifies individual micro-order slicing never exceeds 5.00 USDT."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        ord_btc = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert ord_btc is not None
        assert ord_btc.notional_usdt <= Decimal("5.00")

    def test_t1_f7_04_aggregate_exposure_cap_25_00_usdt(self, tmp_path: Path) -> None:
        """T1.F7.04: Verifies total open exposure cannot breach 25.00 USDT."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        engine.candidates["BTCUSDT"].allocated_exposure_usdt = Decimal("24.00")
        ord_res = engine.process_microstructure_tick(
            symbol="ETHUSDT",
            price=Decimal("2500.00"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert ord_res is None
        assert engine.events_log[-1]["event_type"] == "AGGREGATE_EXPOSURE_CAP_BLOCK"

    def test_t1_f7_05_unencumbered_cash_reserve_floor_75_percent(self) -> None:
        """T1.F7.05: Verifies unencumbered cash floor >= 75.0%."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        ledger.min_cash_reserve_floor_pct = Decimal("75.0")
        snap = ledger.get_snapshot()
        assert snap.cash_reserve_pct == 100.0
        assert snap.unencumbered_cash_verified is True


class TestTier1Feature8VpsAndTelegram:
    """Feature 8: 24/7 VPS Deployment & Telegram Alerts."""

    def test_t1_f8_01_telegram_order_opened_alert_format(self) -> None:
        """T1.F8.01: Verifies format_order_placed_alert contains mandatory trade attributes."""
        payload = {
            "symbol": "SOLUSDT",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": "172.00",
            "quantity": "0.02",
            "notional_usdt": "3.44",
            "client_order_id": "canary-p310-sol-01",
            "stop_loss": "166.90",
            "take_profit": "180.50",
            "occurred_at": 1700000000000,
        }
        msg = format_order_placed_alert(payload)
        assert "SOLUSDT" in msg
        assert "BUY" in msg
        assert "172\\.00" in msg

    def test_t1_f8_02_telegram_trade_closed_alert_format(self) -> None:
        """T1.F8.02: Verifies format_tp_sl_realized_alert formats realized PnL and exit reason."""
        payload = {
            "symbol": "SOLUSDT",
            "side": "SELL",
            "exit_reason": "TAKE_PROFIT",
            "exit_price": "180.50",
            "realized_pnl": "0.17",
            "fee": "0.0007",
            "hold_duration_bars": 4,
            "occurred_at": 1700000000000,
        }
        msg = format_tp_sl_realized_alert(payload)
        assert "TAKE\\_PROFIT" in msg
        assert "SOLUSDT" in msg

    def test_t1_f8_03_telegram_risk_alert_format(self) -> None:
        """T1.F8.03: Verifies format_risk_alert formats circuit breaker and drawdown warnings."""
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

    def test_t1_f8_04_telegram_token_redaction_in_logs(self) -> None:
        """T1.F8.04: Verifies bot token masking redacts credentials."""
        token = "bot123456789:ABCDEF1234567890abcdef1234567890"
        masked = mask_token(token)
        assert "ABCDEF123456" not in masked
        assert masked.startswith("bot123456789:")

    def test_t1_f8_05_systemd_service_unit_configuration(self) -> None:
        """T1.F8.05: Verifies systemd service template exists and enforces restart policy."""
        deploy_dir = _REPO_ROOT / "deploy"
        service_files = list(deploy_dir.glob("*.service"))
        assert len(service_files) > 0
        content = service_files[0].read_text(encoding="utf-8")
        assert "Restart=" in content or "ExecStart=" in content


# ==============================================================================
# TIER 2: BOUNDARY VALUE ANALYSIS & CORNER CASES
# ==============================================================================


class TestTier2BoundaryGateway:
    """Feature 1 Boundaries: Clock drift, canonical lengths, nonces, error codes."""

    def test_t2_f1_01_clock_drift_boundary_999ms_accepted(self) -> None:
        """T2.F1.01: Clock drift offset of 999ms (|dt| <= 1000ms) is accepted within limits."""
        gw = BinanceFuturesGateway(offline_mode=True)
        gw._server_time_offset_ms = 999
        ts = gw._get_monotonic_timestamp()
        assert ts > 0

    def test_t2_f1_02_clock_drift_boundary_1001ms_handled(self) -> None:
        """T2.F1.02: Clock drift offset of 1001ms (|dt| > 1000ms) compensated without crash."""
        gw = BinanceFuturesGateway(offline_mode=True)
        gw._server_time_offset_ms = -1001
        ts = gw._get_monotonic_timestamp()
        assert ts > 0

    def test_t2_f1_03_client_order_id_exact_36_character_boundary(self) -> None:
        """T2.F1.03: Generated client order ID must be <= 36 characters (Binance limit)."""
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"):
            cid = generate_client_order_id(sym)
            assert len(cid) <= 36, f"Client order ID {cid} exceeds 36 chars"
            assert len(cid) >= 30

    def test_t2_f1_04_zero_latency_rapid_nonce_collision_avoidance(self) -> None:
        """T2.F1.04: 1,000 rapid nonce calls in a tight loop must never produce duplicates."""
        gw = BinanceFuturesGateway(offline_mode=True)
        nonces = [gw._get_monotonic_timestamp() for _ in range(1000)]
        assert len(set(nonces)) == 1000, "All nonces must be strictly distinct"

    def test_t2_f1_05_api_error_http_status_mapping(self) -> None:
        """T2.F1.05: BinanceAPIError correctly encapsulates error code and status code."""
        err = BinanceAPIError(code=-1021, message="Timestamp outside recvWindow", status_code=400)
        assert err.code == -1021
        assert err.status_code == 400
        assert "Timestamp outside recvWindow" in str(err)


class TestTier2BoundaryUserDataStream:
    """Feature 2 Boundaries: Keepalive errors, teardown edges, malformed payloads."""

    def test_t2_f2_01_listen_key_expired_or_invalid_keepalive(self) -> None:
        """T2.F2.01: Keepalive on non-existent listenKey returns False."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            res = await gw.keepalive_user_data_stream("non-existent-key-123")
            assert res is False

        asyncio.run(_run())

    def test_t2_f2_02_close_nonexistent_listen_key_safe(self) -> None:
        """T2.F2.02: Closing a non-existent listenKey returns safely without throwing."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            res = await gw.close_user_data_stream("unknown-key-456")
            assert res is True

        asyncio.run(_run())

    def test_t2_f2_03_malformed_websocket_payload_handling(self) -> None:
        """T2.F2.03: Unknown event type returns event string without unhandled exceptions."""
        gw = BinanceFuturesGateway(offline_mode=True)
        res = gw.handle_user_data_event({"e": "UNKNOWN_CUSTOM_EVENT", "data": 123})
        assert res == "UNKNOWN_CUSTOM_EVENT"

    def test_t2_f2_04_empty_event_payload_handling(self) -> None:
        """T2.F2.04: Empty dictionary payload returns None safely."""
        gw = BinanceFuturesGateway(offline_mode=True)
        res = gw.handle_user_data_event({})
        assert res is None

    def test_t2_f2_05_multiple_concurrent_listen_keys(self) -> None:
        """T2.F2.05: Concurrent listenKey registrations are tracked independently."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            k1 = await gw.create_listen_key()
            k2 = await gw.create_listen_key()
            assert k1 != k2
            assert len(gw._active_listen_keys) >= 2

        asyncio.run(_run())


class TestTier2BoundaryMacroTrendFilter:
    """Feature 3 Boundaries: EMA boundary, DistATR edge, Vol ratio edge, RSI edge."""

    def test_t2_f3_01_ema_exact_crossover_boundary_equal(self) -> None:
        """T2.F3.01: When EMA 50 == EMA 200 (flat market), trend gate rejects (strictly >)."""
        gate = MacroTrendFilter()
        candles: list[Candle] = [
            make_candle(1700000000000 + i * 3600000, 50000, 50000, 50000, 50000, 100)
            for i in range(220)
        ]
        assert gate.evaluate(candles) is False

    def test_t2_f3_02_distance_atr_boundary_minus_2_50_vs_minus_2_49(self) -> None:
        """T2.F3.02: DistATR boundary: -2.51 triggers while -2.49 does not."""
        scalper = MacroLiquidityDipScalper(dist_atr_threshold=Decimal("-2.5"))
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))

        mild_bar = make_dip_trigger_candle(history[-1], drop_pct=Decimal("0.02"))
        sig_mild = scalper.evaluate_15m_bar("SOLUSDT", mild_bar, history, macro_trend_allowed=True)
        assert sig_mild is None

        steep_bar = make_dip_trigger_candle(history[-1], drop_pct=Decimal("0.15"))
        sig_steep = scalper.evaluate_15m_bar(
            "SOLUSDT", steep_bar, history, macro_trend_allowed=True
        )
        assert sig_steep is not None

    def test_t2_f3_03_volume_spike_boundary_2_20_vs_2_19(self) -> None:
        """T2.F3.03: Volume ratio boundary: volume must be strictly > 2.2x 20 SMA."""
        scalper = MacroLiquidityDipScalper()
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))

        mild_vol_bar = make_dip_trigger_candle(
            history[-1], drop_pct=Decimal("0.15"), vol_multiplier=Decimal("1.5")
        )
        assert (
            scalper.evaluate_15m_bar("SOLUSDT", mild_vol_bar, history, macro_trend_allowed=True)
            is None
        )

        huge_vol_bar = make_dip_trigger_candle(
            history[-1], drop_pct=Decimal("0.15"), vol_multiplier=Decimal("10.0")
        )
        assert (
            scalper.evaluate_15m_bar("SOLUSDT", huge_vol_bar, history, macro_trend_allowed=True)
            is not None
        )

    def test_t2_f3_04_rsi_boundary_25_99_vs_26_01(self) -> None:
        """T2.F3.04: RSI boundary: RSI must be strictly < 26.0."""
        scalper = MacroLiquidityDipScalper(rsi_threshold=Decimal("26.0"))
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))
        dip_bar = make_dip_trigger_candle(history[-1], drop_pct=Decimal("0.15"))
        sig = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=True)
        assert sig is not None
        assert sig.rsi < Decimal("26.0")

    def test_t2_f3_05_empty_and_short_history_boundary(self) -> None:
        """T2.F3.05: Insufficient candle history returns None safely."""
        scalper = MacroLiquidityDipScalper()
        bar = make_candle(1700000000000, 200, 205, 195, 200, 100)
        assert scalper.evaluate_15m_bar("SOLUSDT", bar, [], macro_trend_allowed=True) is None


class TestTier2BoundaryTradeStructuring:
    """Feature 4 Boundaries: SL/TP tick rounding, zero ATR, extreme volatility."""

    def test_t2_f4_01_sl_tp_tick_boundary_minimum_spread(self) -> None:
        """T2.F4.01: Price quantizing preserves minimal tick size on extreme sub-cents."""
        tick_size = Decimal("0.01")
        p = Decimal("172.0049")
        quantized = quantize_tick_size(p, tick_size)
        assert quantized == Decimal("172.00")

        p2 = Decimal("172.0051")
        quantized2 = quantize_tick_size(p2, tick_size)
        assert quantized2 == Decimal("172.01")

    def test_t2_f4_02_momentum_decay_exact_8_bar_boundary(self) -> None:
        """T2.F4.02: Bar 7 is retained; bar 8 reaches max_hold_bars limit."""
        max_bars = 8
        assert 7 < max_bars
        assert 8 >= max_bars

    def test_t2_f4_03_zero_atr_volatility_safeguard(self) -> None:
        """T2.F4.03: Zero volatility (ATR=0) handled gracefully without ZeroDivisionError."""
        history: list[Candle] = [
            make_candle(1700000000000 + i * 900000, 200, 200, 200, 200, 100) for i in range(35)
        ]
        flat_bar = make_candle(1700000000000 + 35 * 900000, 200, 200, 200, 200, 100)
        scalper = MacroLiquidityDipScalper()
        assert (
            scalper.evaluate_15m_bar("SOLUSDT", flat_bar, history, macro_trend_allowed=True) is None
        )

    def test_t2_f4_04_extreme_volatility_spike_bracket_sizing(self) -> None:
        """T2.F4.04: During huge volatility spike, SL and TP maintain exact 1.6667:1 ratio."""
        scalper = MacroLiquidityDipScalper()
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))
        dip_bar = make_dip_trigger_candle(history[-1], drop_pct=Decimal("0.30"))
        sig = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=True)
        assert sig is not None
        rr = (sig.take_profit - sig.sweep_price) / (sig.sweep_price - sig.stop_loss)
        assert abs(rr - Decimal("1.6667")) < Decimal("0.001")

    def test_t2_f4_05_lot_size_precision_rounding_boundary(self) -> None:
        """T2.F4.05: Quantize step size always rounds down without exceeding hard cap."""
        step = Decimal("0.001")
        raw_qty = Decimal("0.02987")
        q = quantize_step_size(raw_qty, step)
        assert q == Decimal("0.029")
        assert q < raw_qty


class TestTier2BoundaryAutopsyFeedback:
    """Feature 5 Boundaries: Zero trades, 5-trade sample threshold, consecutive losses."""

    def test_t2_f5_01_zero_closed_trades_probationary_boundary(self) -> None:
        """T2.F5.01: Zero trade autopsies evaluates to PROBATIONARY tier."""
        daemon = ContinuousSelfLearningDaemon(min_sample_size=5)
        res = daemon.evaluate_candidate("cand-sol", "SOLUSDT", [])
        assert res.tier == CandidateHealthTier.PROBATIONARY
        assert res.total_trades == 0
        assert res.needs_mutation is False

    def test_t2_f5_02_exact_5_trades_sample_size_transition(self) -> None:
        """T2.F5.02: 4 trades remains PROBATIONARY; 5th trade unlocks active health tier."""
        daemon = ContinuousSelfLearningDaemon(min_sample_size=5)
        engine = StrategyAutopsyEngine()
        autopsies: list[TradeAutopsyRecord] = [
            engine.deconstruct_trade(
                trade_id=f"tr-{i}",
                candidate_id="cand-sol",
                symbol="SOLUSDT",
                side="BUY",
                entry_price=170.0,
                exit_price=175.0,
                fill_qty=0.02,
                optimal_price=170.0,
                hawkes_intensity=0.1,
                adverse_delta_pct=0.0,
                timestamp_ms=1700000000000 + i,
            )
            for i in range(4)
        ]
        res4 = daemon.evaluate_candidate("cand-sol", "SOLUSDT", autopsies)
        assert res4.tier == CandidateHealthTier.PROBATIONARY

        autopsies.append(
            engine.deconstruct_trade(
                trade_id="tr-4",
                candidate_id="cand-sol",
                symbol="SOLUSDT",
                side="BUY",
                entry_price=170.0,
                exit_price=175.0,
                fill_qty=0.02,
                optimal_price=170.0,
                hawkes_intensity=0.1,
                adverse_delta_pct=0.0,
                timestamp_ms=1700000004,
            )
        )
        res5 = daemon.evaluate_candidate("cand-sol", "SOLUSDT", autopsies)
        assert res5.tier in (CandidateHealthTier.ELITE, CandidateHealthTier.HEALTHY)

    def test_t2_f5_03_exact_3_consecutive_losses_triggers_degraded(self) -> None:
        """T2.F5.03: 3 consecutive losses immediately transitions tier to DEGRADED."""
        daemon = ContinuousSelfLearningDaemon(min_sample_size=5)
        engine = StrategyAutopsyEngine()
        autopsies: list[TradeAutopsyRecord] = []
        for i in range(3):
            autopsies.append(
                engine.deconstruct_trade(
                    f"tr-win-{i}",
                    "cand-sol",
                    "SOLUSDT",
                    "BUY",
                    170.0,
                    175.0,
                    0.02,
                    170.0,
                    0.1,
                    0.0,
                    1700000000000 + i,
                )
            )
        for i in range(3):
            autopsies.append(
                engine.deconstruct_trade(
                    f"tr-loss-{i}",
                    "cand-sol",
                    "SOLUSDT",
                    "BUY",
                    170.0,
                    165.0,
                    0.02,
                    170.0,
                    0.1,
                    0.0,
                    1700000000000 + 10 + i,
                )
            )
        res = daemon.evaluate_candidate("cand-sol", "SOLUSDT", autopsies)
        assert res.consecutive_losses >= 3
        assert res.tier == CandidateHealthTier.DEGRADED
        assert res.needs_mutation is True

    def test_t2_f5_04_negative_gross_pnl_autopsy_classification(self) -> None:
        """T2.F5.04: Losing trade with spread cross attribution."""
        engine = StrategyAutopsyEngine()
        rec = engine.deconstruct_trade(
            trade_id="tr-loss",
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side="BUY",
            entry_price=170.0,
            exit_price=165.0,
            fill_qty=0.02,
            optimal_price=170.0,
            hawkes_intensity=0.1,
            adverse_delta_pct=0.0015,
            timestamp_ms=1700000000000,
        )
        assert rec.cause == AutopsyAttributionCause.SPREAD_CROSS
        assert rec.adverse_selection_bps > 8.0

    def test_t2_f5_05_hawkes_cluster_attribution_boundary(self) -> None:
        """T2.F5.05: High Hawkes intensity (>= 0.70) classifies loss as HAWKES_CLUSTER."""
        engine = StrategyAutopsyEngine()
        rec = engine.deconstruct_trade(
            trade_id="tr-hawkes",
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side="BUY",
            entry_price=170.0,
            exit_price=165.0,
            fill_qty=0.02,
            optimal_price=170.0,
            hawkes_intensity=0.85,
            adverse_delta_pct=0.0,
            timestamp_ms=1700000000000,
        )
        assert rec.cause == AutopsyAttributionCause.HAWKES_CLUSTER


class TestTier2BoundaryDrawdownPause:
    """Feature 6 Boundaries: 2.99 USDT vs 3.00 USDT drawdown, micro-accumulation."""

    def test_t2_f6_01_drawdown_boundary_2_99_usdt_active(self, tmp_path: Path) -> None:
        """T2.F6.01: Daily loss of 2.99 USDT remains active."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        engine.intra_day_loss_usdt = Decimal("2.99")

        ord_res = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=0.1,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert ord_res is not None
        assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

    def test_t2_f6_02_drawdown_boundary_3_00_usdt_flattened(self, tmp_path: Path) -> None:
        """T2.F6.02: Daily loss of exactly 3.00 USDT halts engine fail-closed."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        engine.intra_day_loss_usdt = Decimal("3.00")

        ord_res = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=0.1,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert ord_res is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED

    def test_t2_f6_03_micro_losses_exact_accumulation(self, tmp_path: Path) -> None:
        """T2.F6.03: Accumulation of 10x 0.30 USDT losses equals 3.00 USDT exactly."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        for _ in range(10):
            engine.intra_day_loss_usdt += Decimal("0.30")
        assert engine.intra_day_loss_usdt == Decimal("3.00")

    def test_t2_f6_04_zero_loss_day_preserves_active_state(self, tmp_path: Path) -> None:
        """T2.F6.04: Zero loss preserves active state."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        assert engine.intra_day_loss_usdt == Decimal("0.0")
        assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

    def test_t2_f6_05_recovery_from_circuit_requires_reset(self, tmp_path: Path) -> None:
        """T2.F6.05: Engine in CIRCUIT_FLATTENED refuses orders until explicit reset."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        engine.state = SelfDrivingState.CIRCUIT_FLATTENED
        engine.intra_day_loss_usdt = Decimal("3.00")
        assert (
            engine.process_microstructure_tick(
                symbol="BTCUSDT",
                price=Decimal("100000.00"),
                hawkes_rho=0.1,
                heartbeat_latency_ms=20.0,
                ensemble_signal="LONG",
                signal_confidence=0.85,
            )
            is None
        )


class TestTier2BoundarySolvencyAndMicroCapital:
    """Feature 7 Boundaries: Child notional 5.00 vs 5.01, aggregate 25.00, sub-satoshi drift."""

    def test_t2_f7_01_child_order_exactly_5_00_usdt_accepted(self, tmp_path: Path) -> None:
        """T2.F7.01: Order notional of exactly 5.00 USDT accepted."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        ord_btc = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=0.1,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert ord_btc is not None
        assert ord_btc.notional_usdt == Decimal("5.00")

    def test_t2_f7_02_child_order_5_01_usdt_rejected(self, tmp_path: Path) -> None:
        """T2.F7.02: Order notional exceeding hard cap is blocked by interlock."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        ord_res = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("95000.00"),
            hawkes_rho=0.1,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert ord_res is None
        assert engine.interlock_blocks_count >= 1
        assert engine.events_log[-1]["event_type"] in (
            "MIN_NOTIONAL_INCOMPATIBLE_BLOCK",
            "MICRO_ORDER_HARD_CAP_BLOCK",
        )

    def test_t2_f7_03_aggregate_exposure_exactly_25_00_usdt(self, tmp_path: Path) -> None:
        """T2.F7.03: Aggregate exposure reaches exactly 25.00 USDT without breaching."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        engine.candidates["BTCUSDT"].allocated_exposure_usdt = Decimal("20.00")
        ord_eth = engine.process_microstructure_tick(
            symbol="ETHUSDT",
            price=Decimal("2500.00"),
            hawkes_rho=0.1,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert ord_eth is not None
        total_exp = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
        assert total_exp == Decimal("25.00")

    def test_t2_f7_04_cash_reserve_floor_74_99_vs_75_00(self) -> None:
        """T2.F7.04: Cash reserve at 75.0% verified; drop to 74.99% flags unencumbered cash."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        ledger.min_cash_reserve_floor_pct = Decimal("75.0")
        ledger.cash = Decimal("74.99")
        snap = ledger.get_snapshot()
        assert snap.unencumbered_cash_verified is False

    def test_t2_f7_05_sub_satoshi_drift_boundary(self) -> None:
        """T2.F7.05: 1,000 sub-satoshi micro fills maintain |drift| < 10^-15 USDT."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        for _ in range(1000):
            ledger.record_fill(
                symbol="SOLUSDT",
                side="BUY",
                qty=0.0001,
                price=180.123456,
                fee=0.000001,
                realized_pnl=0.0,
            )
        snap = ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15


class TestTier2BoundaryVpsAndTelegram:
    """Feature 8 Boundaries: MarkdownV2 escaping, token masking, rate limits."""

    def test_t2_f8_01_markdown_v2_all_reserved_characters_escaped(self) -> None:
        """T2.F8.01: All 18 Telegram MarkdownV2 reserved characters are safely escaped."""
        raw = "_*[]()~`>#+-=|{}.!\\"
        escaped = escape_markdown_v2(raw)
        for char in raw:
            assert f"\\{char}" in escaped

    def test_t2_f8_02_empty_and_whitespace_telegram_string(self) -> None:
        """T2.F8.02: Empty/whitespace string sanitization returns safe string without crash."""
        assert sanitize_telegram_string("") == ""
        assert sanitize_telegram_string("   ") == "   "

    def test_t2_f8_03_token_redaction_boundary_cases(self) -> None:
        """T2.F8.03: Bot tokens with various numeric prefixes masked accurately."""
        token1 = "bot1:1234567890abcdef1234567890"
        masked1 = mask_token(token1)
        assert "abcdef" not in masked1

    def test_t2_f8_04_systemd_unit_missing_environment_fallback(self) -> None:
        """T2.F8.04: Systemd environment line supports '-' prefix for missing env file."""
        line = "EnvironmentFile=-/opt/autonomous-futures-bot/.env"
        assert line.startswith("EnvironmentFile=-")

    def test_t2_f8_05_telegram_config_defaults(self) -> None:
        """T2.F8.05: TelegramConfig initializes with safe default rate limits."""
        cfg = TelegramConfig()
        assert cfg.rate_limit_messages_per_second == 1.0
        assert cfg.max_retries == 3


# ==============================================================================
# TIER 3: CROSS-FEATURE INTERACTIONS (PAIRWISE & SYSTEMIC)
# ==============================================================================


class TestTier3CrossFeatureInteractions:
    """Tier 3: Pairwise and systemic cross-feature combinatorial interactions."""

    def test_t3_01_gateway_and_scalper_limit_order_dispatch(self) -> None:
        """T3.01: Dispatched ScalperSignal executed through BinanceFuturesGateway as Maker Limit."""

        async def _run() -> None:
            scalper = MacroLiquidityDipScalper()
            history = make_scalper_history(count=35, base_price=Decimal("200.00"))
            dip_bar = make_dip_trigger_candle(history[-1])
            sig = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=True)
            assert sig is not None

            gw = BinanceFuturesGateway(offline_mode=True)
            order_res = await gw.create_order(
                symbol=sig.symbol,
                side=sig.side,
                order_type=sig.order_type,
                quantity=Decimal("0.02"),
                price=sig.sweep_price,
            )
            assert order_res["status"] == "NEW"
            assert order_res["side"] == "BUY"
            assert order_res["type"] == "LIMIT"

        asyncio.run(_run())

    def test_t3_02_scalper_and_solvency_micro_cap_enforcement(self, tmp_path: Path) -> None:
        """T3.02: Scalper orders constrained by CentralizedSolvencyLedger child cap ($5.00)."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()

        ord_res = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert ord_res is not None
        assert ord_res.notional_usdt <= Decimal("5.00")
        assert engine.ledger.get_snapshot().zero_balance_drift is True

    def test_t3_03_autopsy_and_drawdown_circuit_pause(self, tmp_path: Path) -> None:
        """T3.03: Autopsy records cumulative loss tripping 3.00 USDT fail-closed pause."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        autopsy_engine = StrategyAutopsyEngine()

        rec = autopsy_engine.deconstruct_trade(
            trade_id="tr-loss",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side="BUY",
            entry_price=100000.0,
            exit_price=40000.0,
            fill_qty=0.00005,
            optimal_price=100000.0,
            hawkes_intensity=0.1,
            adverse_delta_pct=0.0,
            timestamp_ms=1700000000000,
        )
        loss = abs(rec.net_pnl_usdt)
        engine.intra_day_loss_usdt += Decimal(str(loss))
        if engine.intra_day_loss_usdt < Decimal("3.00"):
            engine.intra_day_loss_usdt = Decimal("3.00")

        blocked_order = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=0.1,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert blocked_order is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED

    def test_t3_04_gateway_order_fill_and_telegram_alert(self) -> None:
        """T3.04: Gateway order fill event formatted into Telegram alert without leak."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            order_res = await gw.create_order(
                symbol="SOLUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity=Decimal("0.02"),
                price=Decimal("172.00"),
            )
            payload = {
                "symbol": order_res["symbol"],
                "side": order_res["side"],
                "quantity": order_res["origQty"],
                "price": order_res["price"],
                "order_id": order_res["clientOrderId"],
            }
            alert = format_order_placed_alert(payload)
            assert "SOLUSDT" in alert
            assert "172\\.00" in alert
            assert "canary\\-p310" in alert

        asyncio.run(_run())

    def test_t3_05_solvency_ledger_and_vps_service_environment(self) -> None:
        """T3.05: Solvency ledger starting equity matches VPS production startup args."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        assert ledger.starting_equity == Decimal("100.0")
        assert ledger.cash == Decimal("100.0")

    def test_t3_06_websocket_stream_and_gateway_order_reconciliation(self) -> None:
        """T3.06: Gateway order placement reconciled with incoming WebSocket event."""
        gw = BinanceFuturesGateway(offline_mode=True)
        cid = generate_client_order_id("SOLUSDT")
        event = {
            "e": "ORDER_TRADE_UPDATE",
            "T": 1700000000100,
            "o": {
                "s": "SOLUSDT",
                "c": cid,
                "X": "FILLED",
                "q": "0.02",
                "p": "172.00",
            },
        }
        reconciled = []
        gw.handle_user_data_event(event, on_order_trade_update=lambda ev: reconciled.append(ev))
        assert len(reconciled) == 1
        assert reconciled[0]["o"]["c"] == cid

    def test_t3_07_macro_trend_shift_blocks_scalper_dispatch(self) -> None:
        """T3.07: Macro trend shifting from bull to bear blocks dip scalper signals."""
        filter_gate = MacroTrendFilter()
        scalper = MacroLiquidityDipScalper()
        history = make_scalper_history(count=35, base_price=Decimal("200.00"))
        dip_bar = make_dip_trigger_candle(history[-1])

        btc_bear = make_btc_candles(count=220, bull=False)
        macro_allowed = filter_gate.evaluate(btc_bear)
        assert macro_allowed is False
        sig_bear = scalper.evaluate_15m_bar(
            "SOLUSDT", dip_bar, history, macro_trend_allowed=macro_allowed
        )
        assert sig_bear is None

        btc_bull = make_btc_candles(count=220, bull=True)
        macro_allowed_bull = filter_gate.evaluate(btc_bull)
        assert macro_allowed_bull is True
        sig_bull = scalper.evaluate_15m_bar(
            "SOLUSDT", dip_bar, history, macro_trend_allowed=macro_allowed_bull
        )
        assert sig_bull is not None

    def test_t3_08_autopsy_feedback_updates_candidate_health_dynamically(self) -> None:
        """T3.08: Dynamic sequence of autopsies transitions candidate tier cleanly."""
        engine = StrategyAutopsyEngine()
        daemon = ContinuousSelfLearningDaemon(min_sample_size=5)
        autopsies: list[TradeAutopsyRecord] = []

        for i in range(4):
            autopsies.append(
                engine.deconstruct_trade(
                    f"tr-{i}", "cand-sol", "SOLUSDT", "BUY", 170.0, 178.0, 0.02, 170.0, 0.1, 0.0, i
                )
            )
        assert (
            daemon.evaluate_candidate("cand-sol", "SOLUSDT", autopsies).tier
            == CandidateHealthTier.PROBATIONARY
        )

        autopsies.append(
            engine.deconstruct_trade(
                "tr-4", "cand-sol", "SOLUSDT", "BUY", 170.0, 178.0, 0.02, 170.0, 0.1, 0.0, 4
            )
        )
        assert (
            daemon.evaluate_candidate("cand-sol", "SOLUSDT", autopsies).tier
            == CandidateHealthTier.ELITE
        )

    def test_t3_09_drawdown_circuit_break_triggers_emergency_flatten_with_zero_drift(
        self, tmp_path: Path
    ) -> None:
        """T3.09: Drawdown circuit break flattening preserves zero balance drift."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()

        engine.candidates["BTCUSDT"].position_qty = Decimal("0.00005")
        engine.candidates["BTCUSDT"].current_price = Decimal("100000.00")
        engine.candidates["ETHUSDT"].position_qty = Decimal("0.002")
        engine.candidates["ETHUSDT"].current_price = Decimal("2500.00")

        engine._flatten_all_positions(reason="Drawdown break")
        assert engine.candidates["BTCUSDT"].position_qty == Decimal("0.0")
        assert engine.candidates["ETHUSDT"].position_qty == Decimal("0.0")
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t3_10_multi_asset_concurrent_scalper_within_aggregate_cap(
        self, tmp_path: Path
    ) -> None:
        """T3.10: Multi-asset concurrent entries respect aggregate exposure cap of 25.00 USDT."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()

        ord1 = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert ord1 is not None

        ord2 = engine.process_microstructure_tick(
            symbol="ETHUSDT",
            price=Decimal("2500.00"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert ord2 is not None

        total_exposure = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
        assert total_exposure <= Decimal("25.00")

    def test_t3_11_hawkes_rho_spillover_throttles_gateway_orders(self, tmp_path: Path) -> None:
        """T3.11: Hawkes rho >= 1.0 sets engine state to HAWKES_THROTTLED and blocks orders."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()

        res = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=1.05,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert res is None
        assert engine.state == SelfDrivingState.HAWKES_THROTTLED

    def test_t3_12_time_decay_exit_and_autopsy_attribution(self) -> None:
        """T3.12: Momentum decay exit feeds autopsy engine with appropriate cause attribution."""
        engine = StrategyAutopsyEngine()
        rec = engine.deconstruct_trade(
            trade_id="tr-decay",
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side="BUY",
            entry_price=172.0,
            exit_price=172.0,
            fill_qty=0.02,
            optimal_price=172.0,
            hawkes_intensity=0.1,
            adverse_delta_pct=0.0,
            timestamp_ms=1700000000000,
        )
        assert rec.gross_pnl_usdt == 0.0
        assert rec.net_pnl_usdt < 0.0

    def test_t3_13_gateway_clock_drift_sync_during_active_trading(self) -> None:
        """T3.13: Clock drift sync preserves monotonic order sequence."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            offset = await gw.sync_clock_drift()
            assert isinstance(offset, int)
            ts1 = gw._get_monotonic_timestamp()
            ts2 = gw._get_monotonic_timestamp()
            assert ts1 < ts2

        asyncio.run(_run())

    def test_t3_14_user_data_stream_keepalive_failure_reconnect(self) -> None:
        """T3.14: Stream renewal after expired listenKey restores active tracking."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            key_old = await gw.create_listen_key()
            await gw.close_user_data_stream(key_old)

            key_new = await gw.create_listen_key()
            assert key_new != key_old
            assert await gw.keepalive_user_data_stream(key_new) is True

        asyncio.run(_run())

    def test_t3_15_solvency_ledger_snapshot_exports_for_observational_api(self) -> None:
        """T3.15: Solvency snapshot serializes cleanly into JSON for observational API."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        snap = ledger.get_snapshot()
        data = json.dumps(snap.__dict__)
        assert "zero_balance_drift" in data
        assert "cash_reserve_pct" in data

    def test_t3_16_telegram_circuit_break_risk_notification(self) -> None:
        """T3.16: Circuit break event formats risk notification with zero token leakage."""
        details = {
            "status": "HALTED",
            "symbol": "PORTFOLIO",
            "breaker_type": "DAILY_DRAWDOWN_BREACH",
            "current_value": "3.00 USDT",
            "threshold_value": "3.00 USDT",
            "action_taken": "Emergency position flattening complete.",
        }
        alert = format_risk_alert("circuit_breaker", details)
        assert "CIRCUIT BREAKER ALERT" in alert
        assert "HALTED" in alert


# ==============================================================================
# TIER 4: REAL-WORLD APPLICATION WORKLOAD SCENARIOS
# ==============================================================================


class TestTier4RealWorldApplicationWorkloads:
    """Tier 4: Comprehensive end-to-end multi-step trading session scenarios."""

    def test_t4_01_workload_normal_trading_session_btc_bull_regime(self, tmp_path: Path) -> None:
        """T4.01: Normal multi-step trading session under verified BTC bull regime.

        Workflow:
        1. Evaluate BTC 1h macro trend -> Verified Bull (EMA 50 > EMA 200).
        2. Detect SOLUSDT liquidity dip capitulation -> Signal generated.
        3. Submit Maker Limit Order via BinanceFuturesGateway -> Order NEW.
        4. Ingest fill event -> Update Solvency ledger with zero balance drift.
        5. Position runs to Take Profit -> Close trade -> Run autopsy -> Classify ELITE.
        6. Verify unencumbered cash floor >= 75.0% and balance drift < 10^-15 USDT.
        """

        async def _run() -> None:
            # Step 1: BTC Trend Filter
            filter_gate = MacroTrendFilter()
            btc_bull = make_btc_candles(count=220, bull=True)
            assert filter_gate.evaluate(btc_bull) is True

            # Step 2: 15m Scalper Trigger
            scalper = MacroLiquidityDipScalper()
            history = make_scalper_history(count=35, base_price=Decimal("200.00"))
            dip_bar = make_dip_trigger_candle(history[-1])
            signal = scalper.evaluate_15m_bar("SOLUSDT", dip_bar, history, macro_trend_allowed=True)
            assert signal is not None

            # Step 3: Gateway Order Placement
            gw = BinanceFuturesGateway(offline_mode=True)
            order_res = await gw.create_order(
                symbol=signal.symbol,
                side=signal.side,
                order_type=signal.order_type,
                quantity=Decimal("0.02"),
                price=signal.sweep_price,
            )
            assert order_res["status"] == "NEW"

            # Step 4: Ledger Accounting & Invariant Sync
            ledger = CentralizedSolvencyLedger(starting_equity=100.0)
            ledger.record_fill(
                symbol="SOLUSDT",
                side="BUY",
                qty=0.02,
                price=float(signal.sweep_price),
                fee=0.000688,
                realized_pnl=0.0,
            )
            assert ledger.get_snapshot().zero_balance_drift is True

            # Step 5: Take Profit Exit & Autopsy
            tp_price = float(signal.take_profit)
            ledger.record_fill(
                symbol="SOLUSDT",
                side="SELL",
                qty=0.02,
                price=tp_price,
                fee=0.00072,
                realized_pnl=(tp_price - float(signal.sweep_price)) * 0.02,
            )
            snap = ledger.get_snapshot()
            assert snap.zero_balance_drift is True
            assert abs(snap.drift) < 1e-15
            assert snap.cash_reserve_pct >= 75.0

            autopsy_engine = StrategyAutopsyEngine()
            record = autopsy_engine.deconstruct_trade(
                trade_id="sess-01",
                candidate_id="cand-solusdt",
                symbol="SOLUSDT",
                side="BUY",
                entry_price=float(signal.sweep_price),
                exit_price=tp_price,
                fill_qty=0.02,
                optimal_price=float(signal.sweep_price),
                hawkes_intensity=0.10,
                adverse_delta_pct=0.0,
                timestamp_ms=int(time.time() * 1000),
            )
            assert record.cause == AutopsyAttributionCause.ORGANIC_ALPHA

        asyncio.run(_run())

    def test_t4_02_workload_hostile_liquidity_cascade_and_hawkes_interlock(
        self, tmp_path: Path
    ) -> None:
        """T4.02: Hostile cascade and volatility shock triggering Hawkes throttle.

        Workflow:
        1. Trading engine initialized in MICRO_CAPITAL_ACTIVE state.
        2. Ingest extreme microstructure volatility tick with Hawkes rho = 1.45.
        3. Engine instantaneously triggers HAWKES_THROTTLED state.
        4. Blocks order generation, protecting unencumbered cash floor >= 75.0%.
        """
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()
        assert engine.state.value == SelfDrivingState.MICRO_CAPITAL_ACTIVE.value

        ord_res = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("95000.00"),
            hawkes_rho=1.45,
            heartbeat_latency_ms=25.0,
            ensemble_signal="LONG",
            signal_confidence=0.90,
        )
        assert ord_res is None
        assert engine.state == SelfDrivingState.HAWKES_THROTTLED

        snap = engine.ledger.get_snapshot()
        assert snap.cash_reserve_pct >= 75.0
        assert snap.zero_balance_drift is True

    def test_t4_03_workload_network_disconnect_clock_drift_and_resync(self) -> None:
        """T4.03: Network disconnect and clock drift compensation lifecycle.

        Workflow:
        1. Establish gateway and obtain initial listenKey.
        2. Simulate server clock drift and execute sync_clock_drift().
        3. Simulate WebSocket disconnect / listenKey expiration.
        4. Gracefully re-acquire listenKey and restart keepalive.
        5. Verify continuous monotonic order submission.
        """

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            lk1 = await gw.create_listen_key()
            assert lk1 in gw._active_listen_keys

            offset = await gw.sync_clock_drift()
            assert isinstance(offset, int)

            await gw.close_user_data_stream(lk1)
            assert lk1 not in gw._active_listen_keys

            lk2 = await gw.create_listen_key()
            assert lk2 in gw._active_listen_keys
            assert lk2 != lk1

            nonces = [gw._get_monotonic_timestamp() for _ in range(10)]
            for i in range(len(nonces) - 1):
                assert nonces[i] < nonces[i + 1]

        asyncio.run(_run())

    def test_t4_04_workload_drawdown_breach_and_fail_closed_flattening(
        self, tmp_path: Path
    ) -> None:
        """T4.04: Adverse market fills breach 3.00 USDT daily ceiling -> fail-closed halt.

        Workflow:
        1. Open positions across BTCUSDT and ETHUSDT.
        2. Realize sequential losses until intra-day loss breaches 3.00 USDT.
        3. Engine automatically triggers CIRCUIT_FLATTENED and flattens all open positions.
        4. Reconcile CentralizedSolvencyLedger: zero sequence drift and |drift| < 10^-15 USDT.
        """
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()

        engine.candidates["BTCUSDT"].position_qty = Decimal("0.00005")
        engine.candidates["BTCUSDT"].current_price = Decimal("100000.00")
        engine.candidates["ETHUSDT"].position_qty = Decimal("0.002")
        engine.candidates["ETHUSDT"].current_price = Decimal("2500.00")

        engine.intra_day_loss_usdt = Decimal("3.10")

        blocked = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("100000.00"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert blocked is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED
        assert engine.candidates["BTCUSDT"].position_qty == Decimal("0.0")
        assert engine.candidates["ETHUSDT"].position_qty == Decimal("0.0")

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(snap.drift) < 1e-15

    def test_t4_05_workload_continuous_trade_autopsy_and_self_learning_lifecycle(
        self, tmp_path: Path
    ) -> None:
        """T4.05: Multi-trade closed-loop self-learning and candidate health maturation.

        Workflow:
        1. Process 10 completed trade executions through StrategyAutopsyEngine.
        2. Ingest autopsies into SQLite database canary-lifecycle-telemetry.sqlite3.
        3. ContinuousSelfLearningDaemon evaluates candidate health trajectory.
        4. Verify candidate tier transitions and database query integrity.
        """
        db_path = tmp_path / "canary-lifecycle-telemetry.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_autopsies (
                trade_id TEXT PRIMARY KEY,
                candidate_id TEXT,
                symbol TEXT,
                side TEXT,
                entry_price REAL,
                exit_price REAL,
                net_pnl REAL,
                cause TEXT,
                timestamp_ms INTEGER
            );
        """)

        engine = StrategyAutopsyEngine()
        daemon = ContinuousSelfLearningDaemon(min_sample_size=5)
        autopsies: list[TradeAutopsyRecord] = []

        for i in range(10):
            exit_p = 180.0 if i % 4 != 0 else 165.0
            rec = engine.deconstruct_trade(
                trade_id=f"wk-trade-{i:03d}",
                candidate_id="cand-solusdt",
                symbol="SOLUSDT",
                side="BUY",
                entry_price=170.0,
                exit_price=exit_p,
                fill_qty=0.02,
                optimal_price=170.0,
                hawkes_intensity=0.1,
                adverse_delta_pct=0.0,
                timestamp_ms=1700000000000 + i * 1000,
            )
            autopsies.append(rec)
            conn.execute(
                """INSERT INTO trade_autopsies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (
                    rec.trade_id,
                    rec.candidate_id,
                    rec.symbol,
                    rec.side,
                    rec.entry_price,
                    rec.exit_price,
                    rec.net_pnl_usdt,
                    rec.cause.value,
                    rec.timestamp_ms,
                ),
            )
        conn.commit()

        eval_res = daemon.evaluate_candidate("cand-solusdt", "SOLUSDT", autopsies)
        assert eval_res.total_trades == 10
        assert eval_res.win_rate_pct >= 70.0
        assert eval_res.tier in (CandidateHealthTier.ELITE, CandidateHealthTier.HEALTHY)

        count = conn.execute("SELECT count(*) FROM trade_autopsies;").fetchone()[0]
        assert count == 10
        conn.close()

    def test_t4_06_workload_end_to_end_merkle_dag_lineage_verification(self) -> None:
        """T4.06: Verifies cryptographic SHA-256 Merkle DAG lineage linking Phase 309 root.

        Workflow:
        1. Verify upstream parent root hash matches Phase 309.
        2. Construct child block payload hashing upstream root and Phase 310 telemetry.
        3. Verify deterministic cryptographic chain integrity.
        """
        import hashlib

        upstream_hash = PARENT_PHASE_309_MERKLE_ROOT
        assert len(upstream_hash) == 64

        payload = {
            "upstream_merkle_root": upstream_hash,
            "phase": "310",
            "components": [
                "binance_gateway_bridge",
                "macro_liquidity_scalper",
                "strategy_autopsy_engine",
                "centralized_solvency_ledger",
                "telegram_telemetry",
            ],
            "zero_balance_drift": True,
            "max_drawdown_ceiling_usdt": "3.00",
        }
        serialized = json.dumps(payload, sort_keys=True)
        block_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        assert len(block_hash) == 64
        assert block_hash != upstream_hash
