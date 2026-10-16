import asyncio
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from test_protective_lifecycle import PLAN

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.causal_scanner import CausalScanner
from autonomous_futures.execution.ict_reclaim_entry import IctReclaimEntryStore
from autonomous_futures.execution.trade_plan import SymbolFilters
from autonomous_futures.feed.live_market_feed import LiveMarketFeed
from autonomous_futures.feed.runtime_hawkes_calibration import RuntimeHawkesCalibration
from autonomous_futures.feed.runtime_microstructure import RuntimeMicrostructure
from autonomous_futures.strategy.ict_mmxm import Candle as IctCandle
from autonomous_futures.strategy.ict_mmxm import IctMmxmEngine, TwinsSetupState

REPO = Path(__file__).resolve().parents[2]


def calibration_for(symbols):
    return RuntimeHawkesCalibration(1.0, "a" * 64, ("b" * 64,), tuple(symbols))


def test_rejected_genuine_report_cannot_authorize_signal_scan(tmp_path):
    gateway = BinanceFuturesGateway(testnet=True, offline_mode=False)
    gateway.get_klines = AsyncMock()
    feed = LiveMarketFeed(
        gateway,
        RuntimeMicrostructure(
            ("LINKUSDT", "BTCUSDT"),
            calibration=calibration_for(("LINKUSDT", "BTCUSDT")),
        ),
    )
    scanner = CausalScanner(
        feed,
        repo=REPO,
        account_path=tmp_path / "account.json",
        reports={
            ("MACRO_SCALPER", "LINKUSDT"): REPO
            / "tests/fixtures/runtime-qualification/rejected-link-scalper.json"
        },
    )
    with pytest.raises(ValueError, match="No reviewed deployment admission"):
        asyncio.run(scanner())
    gateway.get_klines.assert_not_awaited()


def test_placeholder_family_cannot_enter_canonical_scanner(tmp_path):
    feed = LiveMarketFeed(
        BinanceFuturesGateway(testnet=True, offline_mode=False),
        RuntimeMicrostructure(("LINKUSDT",), calibration=calibration_for(("LINKUSDT",))),
    )
    with pytest.raises(ValueError, match="canonical"):
        CausalScanner(
            feed,
            repo=REPO,
            account_path=tmp_path / "account.json",
            reports={("GENERIC_RSI", "LINKUSDT"): tmp_path / "candidate.json"},
        )


def test_reclaim_report_configuration_skips_stale_setup_and_is_cached(tmp_path, monkeypatch):
    gateway = BinanceFuturesGateway(testnet=True, offline_mode=False)
    gateway.symbol_specs["SOLUSDT"] = {}
    feed = LiveMarketFeed(
        gateway,
        RuntimeMicrostructure(("SOLUSDT",), calibration=calibration_for(("SOLUSDT",))),
    )
    decision = 15_060_000
    feed.clock = Mock()
    feed.clock.completed_boundary.return_value = decision
    feed.clock.aligned_ms.return_value = decision
    feed.connected = True
    engine = IctMmxmEngine()
    config = {
        "entry_mode": "reclaim_retest",
        "history_bars": 250,
        "htf_pda_timeframes": ["4h", "1h"],
        **{key: str(value) for key, value in vars(engine).items()},
    }
    receipt = Mock(configuration=config, policy={"entry_ttl_ms": 300_000}, report_hash="a" * 64)
    receipt.execution_domain = {"verified": True}
    verify = Mock(return_value=receipt)
    monkeypatch.setattr("autonomous_futures.execution.causal_scanner.verify_runtime_report", verify)
    monkeypatch.setattr(
        "autonomous_futures.execution.causal_scanner.read_account",
        lambda *args: {
            "account": {"totalMarginBalance": "100", "availableBalance": "100"},
            "symbol_configuration": [{"symbol": "SOLUSDT", "leverage": 1}],
        },
    )
    monkeypatch.setattr(
        "autonomous_futures.execution.causal_scanner.remaining_daily_budget",
        lambda account: Decimal("100"),
    )
    monkeypatch.setattr(
        "autonomous_futures.execution.causal_scanner.verify_execution_domain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "autonomous_futures.execution.causal_scanner.SymbolFilters.from_gateway",
        lambda spec: SymbolFilters(
            Decimal("0.1"), Decimal("0.1"), Decimal("0.1"), Decimal("100"), Decimal("5")
        ),
    )
    monkeypatch.setattr(
        IctMmxmEngine,
        "evaluate_twins_setup",
        lambda self, symbol, *args: TwinsSetupState(
            symbol,
            step_6_ready=True,
            confirmation_ms=decision - 60_000,
            active_pda=Mock(),
            side="BUY",
        ),
    )
    scanner = CausalScanner(
        feed,
        repo=tmp_path,
        account_path=tmp_path / "runtime" / "exchange-account.json",
        reports={("ICT_TWINS", "SOLUSDT"): tmp_path / "report.json"},
        admission_manifest_path=tmp_path / "deploy" / "mainnet-qualification-admission.json",
    )
    bars = tuple(
        IctCandle(
            i * 60_000 + 60_000,
            Decimal("100"),
            Decimal("101"),
            Decimal("99"),
            Decimal("100"),
            Decimal("1"),
        )
        for i in range(250)
    )
    scanner.reader.read = AsyncMock(return_value=bars)

    assert asyncio.run(scanner()) is None
    assert asyncio.run(scanner()) is None
    verify.assert_called_once()
    assert verify.call_args.kwargs["admission_manifest_path"] == (
        tmp_path / "deploy" / "mainnet-qualification-admission.json"
    )


def test_scanner_dispatches_persisted_reclaim_once_with_report_pin(tmp_path, monkeypatch):
    gateway = BinanceFuturesGateway(testnet=True, offline_mode=False)
    gateway.symbol_specs["SOLUSDT"] = {}
    feed = LiveMarketFeed(
        gateway,
        RuntimeMicrostructure(("SOLUSDT",), calibration=calibration_for(("SOLUSDT",))),
    )
    feed.connected = True
    feed.clock = Mock()
    feed.clock.completed_boundary.return_value = 15_060_000
    feed.clock.aligned_ms.return_value = 15_060_000
    engine = IctMmxmEngine()
    config = {
        "entry_mode": "reclaim_retest",
        "history_bars": 250,
        "htf_pda_timeframes": ["4h", "1h"],
        **{key: str(value) for key, value in vars(engine).items()},
    }
    report_hash = "a" * 64
    receipt = Mock(
        configuration=config,
        policy={"entry_ttl_ms": 300_000},
        report_hash=report_hash,
        execution_domain={"verified": True},
    )
    verify = Mock(return_value=receipt)
    monkeypatch.setattr("autonomous_futures.execution.causal_scanner.verify_runtime_report", verify)
    monkeypatch.setattr(
        "autonomous_futures.execution.causal_scanner.read_account",
        lambda *args: {
            "account": {"totalMarginBalance": "100", "availableBalance": "100"},
            "symbol_configuration": [{"symbol": "SOLUSDT", "leverage": 1}],
        },
    )
    monkeypatch.setattr(
        "autonomous_futures.execution.causal_scanner.remaining_daily_budget",
        lambda account: Decimal("100"),
    )
    monkeypatch.setattr(
        "autonomous_futures.execution.causal_scanner.verify_execution_domain",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "autonomous_futures.execution.causal_scanner.SymbolFilters.from_gateway",
        lambda spec: SymbolFilters(
            Decimal("0.1"), Decimal("0.1"), Decimal("0.1"), Decimal("100"), Decimal("5")
        ),
    )
    account_path = tmp_path / "runtime" / "exchange-account.json"
    report_path = tmp_path / "report.json"
    plan = replace(PLAN, decision_ms=15_000_000)
    IctReclaimEntryStore(account_path.with_name("ict-reclaim-entry-state.json"), tmp_path).begin(
        plan, report_path, report_hash, entry_ttl_ms=300_000
    )
    scanner = CausalScanner(
        feed,
        repo=tmp_path,
        account_path=account_path,
        reports={("ICT_TWINS", "SOLUSDT"): report_path},
    )
    bars = tuple(
        IctCandle(
            index * 60_000,
            Decimal("101"),
            Decimal("103"),
            Decimal("99"),
            Decimal("101"),
            Decimal("10"),
        )
        for index in range(1, 251)
    )
    scanner.reader.read = AsyncMock(return_value=bars)

    intention = asyncio.run(scanner())
    assert intention is not None
    assert intention.plan.signal_key == plan.signal_key
    assert intention.readiness_ms == 15_060_000
    assert intention.report_hash == report_hash
    assert asyncio.run(scanner()) is None
    verify.assert_called_once()
