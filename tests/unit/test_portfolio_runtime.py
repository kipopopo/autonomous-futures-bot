from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from test_protective_lifecycle import PLAN

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.causal_scanner import CausalScanner
from autonomous_futures.execution.entry_admission import EntryAdmission
from autonomous_futures.execution.portfolio_runtime import (
    RuntimePortfolioMember,
    load_admitted_portfolios,
    symbol_is_occupied,
)
from autonomous_futures.execution.trade_plan import SymbolFilters
from autonomous_futures.feed.exchange_clock import ExchangeClock
from autonomous_futures.feed.live_market_feed import LiveMarketFeed
from autonomous_futures.feed.runtime_hawkes_calibration import RuntimeHawkesCalibration
from autonomous_futures.feed.runtime_microstructure import RuntimeMicrostructure
from autonomous_futures.strategy.ict_mmxm import Candle as IctCandle
from autonomous_futures.strategy.macro_liquidity_scalper import (
    MacroLiquidityDipScalper,
    MacroTrendFilter,
    ScalperSignal,
)
from scripts.run_qualified_runtime import admitted_portfolios

REPO = Path(__file__).resolve().parents[2]


def _calibration(symbols: tuple[str, ...]) -> RuntimeHawkesCalibration:
    return RuntimeHawkesCalibration(1.0, "a" * 64, ("b" * 64,), symbols)


def _portfolio_account(
    *,
    positions: list[dict[str, str]] | None = None,
    open_orders: list[dict[str, object]] | None = None,
    equity: str = "4224.09882354",
) -> dict[str, object]:
    return {
        "testnet": True,
        "timestamp_ms": 15_060_000,
        "account": {
            "totalMarginBalance": equity,
            "availableBalance": equity,
            "totalWalletBalance": equity,
        },
        "daily_risk": {
            "verified": True,
            "equity_basis": "ACCOUNT",
            "day_start_equity_usdt": equity,
            "current_equity_usdt": equity,
            "loss_usdt": "0",
            "limit_usdt": "211.20494117",
            "remaining_usdt": "211.20494117",
            "breached": False,
        },
        "positions": positions or [],
        "open_orders": open_orders or [],
        "symbol_configuration": [
            {"symbol": "AVAXUSDT", "leverage": 1},
            {"symbol": "ETHUSDT", "leverage": 1},
            {"symbol": "SOLUSDT", "leverage": 1},
        ],
    }


def test_load_admitted_portfolios_verifies_6_member_mf_portfolio() -> None:
    portfolios = load_admitted_portfolios(REPO, require_execution_authority=False)
    assert len(portfolios) == 1
    p = portfolios[0]
    assert p.portfolio_id == "macro-scalper-uninspected-3sym-medium-frequency-v1"
    assert p.family == "MACRO_SCALPER"
    assert p.symbols == ("AVAXUSDT", "ETHUSDT", "SOLUSDT")
    assert len(p.members) == 6
    assert [m.member_id for m in p.members] == [
        "avax-1-hf-d-3.5-tp6.0-sl10.0",
        "eth-1-deep-d-4.0-tp10.0-sl6.0",
        "eth-2-med-d-3.5-tp10.0-sl8.0",
        "eth-3-hf-d-3.0-tp12.0-sl12.0",
        "sol-1-deep-d-4.0-tp3.0-sl3.0",
        "sol-2-hf-d-1.8-tp8.0-sl10.0",
    ]
    assert {sym: len(ms) for sym, ms in p.members_by_symbol.items()} == {
        "AVAXUSDT": 1,
        "ETHUSDT": 3,
        "SOLUSDT": 2,
    }
    assert p.execution_authority is False
    assert p.execution_domain["schema"] == "researched-execution-domain-v1"
    assert p.execution_domain["maximum_concurrent_symbols"] == 3
    assert p.execution_domain["leverages"] == [1]
    assert p.get_member("eth-2-med-d-3.5-tp10.0-sl8.0").symbol == "ETHUSDT"


def test_admitted_portfolios_blocks_when_execution_authority_required() -> None:
    with pytest.raises(ValueError, match="execution_authority=False"):
        admitted_portfolios(REPO, require_execution_authority=True)


def test_runtime_portfolio_member_validates_bounds() -> None:
    with pytest.raises(ValueError, match="distance_threshold must be negative"):
        RuntimePortfolioMember(
            portfolio_id="p1",
            member_id="m1",
            symbol="ETHUSDT",
            distance_threshold=Decimal("1.0"),
        )


def test_symbol_is_occupied_checks_positions_orders_and_pending() -> None:
    flat = _portfolio_account()
    assert symbol_is_occupied("ETHUSDT", flat) is False
    assert symbol_is_occupied("ETHUSDT", flat, pending_symbols=("ETHUSDT",)) is True
    with_pos = _portfolio_account(positions=[{"symbol": "ETHUSDT", "positionAmt": "0.25"}])
    assert symbol_is_occupied("ETHUSDT", with_pos) is True
    assert symbol_is_occupied("SOLUSDT", with_pos) is False
    with_order = _portfolio_account(open_orders=[{"symbol": "SOLUSDT", "reduceOnly": False}])
    assert symbol_is_occupied("SOLUSDT", with_order) is True
    with_reduce_only = _portfolio_account(open_orders=[{"symbol": "SOLUSDT", "reduceOnly": True}])
    assert symbol_is_occupied("SOLUSDT", with_reduce_only) is False


def test_portfolio_scanner_evaluates_members_in_priority_order_and_respects_occupancy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    portfolio = load_admitted_portfolios(REPO)[0]
    feed_symbols = ("AVAXUSDT", "ETHUSDT", "SOLUSDT", "BTCUSDT")
    gateway = BinanceFuturesGateway(testnet=True, offline_mode=False)
    for sym in feed_symbols:
        gateway.symbol_specs[sym] = {}
    feed = LiveMarketFeed(
        gateway,
        RuntimeMicrostructure(feed_symbols, calibration=_calibration(feed_symbols)),
    )
    decision = 15_060_000
    feed.clock = Mock()
    feed.clock.completed_boundary.return_value = decision
    feed.clock.aligned_ms.return_value = decision
    feed.connected = True

    account_state = _portfolio_account()
    monkeypatch.setattr(
        "autonomous_futures.execution.portfolio_runtime.read_account",
        lambda *_args: account_state,
    )
    monkeypatch.setattr(
        "autonomous_futures.execution.portfolio_runtime.remaining_daily_budget",
        lambda _acc: Decimal("211.20"),
    )
    monkeypatch.setattr(
        "autonomous_futures.execution.portfolio_runtime.SymbolFilters.from_gateway",
        lambda _spec: SymbolFilters(
            Decimal("0.01"),
            Decimal("0.001"),
            Decimal("0.001"),
            Decimal("1000"),
            Decimal("5"),
        ),
    )
    monkeypatch.setattr(
        MacroTrendFilter,
        "evaluate_regime",
        lambda *_args: "BULLISH",
    )

    evaluated_thresholds: list[Decimal] = []

    def fake_evaluate(
        self: MacroLiquidityDipScalper,
        symbol: str,
        bar: object,
        history: object,
        regime: str,
    ) -> ScalperSignal | None:
        if symbol != "ETHUSDT":
            return None
        evaluated_thresholds.append(self.dist_atr_threshold)
        # First member (eth-1-deep, -4.0) does not fire; second (eth-2-med, -3.5) fires
        if self.dist_atr_threshold == Decimal("-3.5"):
            return ScalperSignal(
                symbol="ETHUSDT",
                timestamp_ms=decision - 900_000,
                side="BUY",
                order_type="LIMIT",
                sweep_price=Decimal("2500.00"),
                stop_loss=Decimal("2460.00"),
                take_profit=Decimal("2550.00"),
                atr=Decimal("5.00"),
                max_hold_bars=self.max_hold_bars,
            )
        return None

    monkeypatch.setattr(MacroLiquidityDipScalper, "evaluate_15m_bar", fake_evaluate)

    scanner = CausalScanner(
        feed,
        repo=REPO,
        account_path=tmp_path / "exchange-account.json",
        portfolio=portfolio,
    )
    bars = tuple(
        IctCandle(
            i * 900_000,
            Decimal("2500"),
            Decimal("2510"),
            Decimal("2490"),
            Decimal("2500"),
            Decimal("10"),
        )
        for i in range(1, 255)
    )
    scanner.reader.read = AsyncMock(return_value=bars)

    # Call 1 scans AVAXUSDT -> None
    assert asyncio.run(scanner()) is None
    # Call 2 scans ETHUSDT -> evaluates eth-1-deep (-4.0), then eth-2-med (-3.5)
    intention = asyncio.run(scanner())
    assert intention is not None
    assert intention.portfolio_id == "macro-scalper-uninspected-3sym-medium-frequency-v1"
    assert intention.member_id == "eth-2-med-d-3.5-tp10.0-sl8.0"
    assert intention.plan.symbol == "ETHUSDT"
    assert (
        intention.report_hash == "72de22bde9a30101c791bcc981c89481c176b6a4fd63acfd4e2495e8e9122d89"
    )
    # eth-3-hf (-3.0) was not evaluated because eth-2-med already triggered for ETHUSDT
    assert evaluated_thresholds == [Decimal("-4.0"), Decimal("-3.5")]

    # Now mark ETHUSDT as occupied in open_orders: subsequent ETHUSDT scan must return None
    account_state = _portfolio_account(open_orders=[{"symbol": "ETHUSDT", "reduceOnly": False}])
    evaluated_thresholds.clear()
    # Call 3 scans SOLUSDT -> None
    assert asyncio.run(scanner()) is None
    # Call 4 scans AVAXUSDT -> None
    assert asyncio.run(scanner()) is None
    # Call 5 scans ETHUSDT -> skipped before strategy evaluation because ETHUSDT is occupied!
    assert asyncio.run(scanner()) is None
    assert evaluated_thresholds == []


def test_entry_admission_verifies_portfolio_receipt_and_member_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    portfolio = load_admitted_portfolios(REPO)[0]
    eth_plan = replace(
        PLAN,
        family="MACRO_SCALPER",
        symbol="ETHUSDT",
        decision_ms=1_000,
    )
    monkeypatch.setattr("autonomous_futures.execution.entry_admission.time.time", lambda: 1.001)
    coordinator = Mock()
    coordinator.lease.assert_held = Mock()
    coordinator.gateway.get_position_mode = AsyncMock(return_value=True)
    admission = EntryAdmission(
        coordinator,
        Mock(),
        repo=REPO,
        single_writer_guard=Mock(),
        user_stream_guard=Mock(),
    )
    clock = ExchangeClock(1000, 1000, 1000)

    # 1. Invalid member_id is rejected before gateway calls
    with pytest.raises(ValueError, match="does not authorize this member_id"):
        asyncio.run(
            admission.admit(
                eth_plan,
                portfolio.report_path,
                exchange_clock=clock,
                expected_report_hash=portfolio.report_hash,
                portfolio_id=portfolio.portfolio_id,
                member_id="sol-1-deep-d-4.0-tp3.0-sl3.0",
            )
        )
    coordinator.gateway.get_position_mode.assert_not_awaited()

    # 2. Valid portfolio_id + member_id passes receipt verification and reaches gateway check
    with pytest.raises(ValueError, match="one-way exchange position mode"):
        asyncio.run(
            admission.admit(
                eth_plan,
                portfolio.report_path,
                exchange_clock=clock,
                expected_report_hash=portfolio.report_hash,
                portfolio_id=portfolio.portfolio_id,
                member_id="eth-1-deep-d-4.0-tp10.0-sl6.0",
            )
        )
    coordinator.gateway.get_position_mode.assert_awaited_once()
