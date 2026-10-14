from __future__ import annotations

from decimal import Decimal

from autonomous_futures.execution.trade_plan import SymbolFilters
from autonomous_futures.research.portfolio_qualification import (
    MAX_LEDGER_DRIFT,
    CandidateDecisionEvent,
    PortfolioLedger,
    PortfolioMemberSpec,
    simulate_shared_wallet_portfolio,
)
from autonomous_futures.research.runtime_qualification import RuntimeQualificationPolicy
from autonomous_futures.strategy.macro_liquidity_scalper import Candle, ScalperSignal

D = Decimal


def _default_filters() -> SymbolFilters:
    return SymbolFilters(
        tick_size=D("0.01"),
        step_size=D("0.01"),
        min_qty=D("0.01"),
        max_qty=D("10000"),
        min_notional=D("5"),
    )


def _make_signal(
    symbol: str,
    decision_ms: int,
    *,
    entry: Decimal,
    tp: Decimal,
    sl: Decimal,
) -> ScalperSignal:
    return ScalperSignal(
        symbol=symbol,
        timestamp_ms=decision_ms - 900_000,
        side="BUY",
        order_type="LIMIT",
        sweep_price=entry,
        stop_loss=sl,
        take_profit=tp,
        atr=abs(entry - sl),
        max_hold_bars=8,
    )


def test_portfolio_ledger_preserves_decimal_identities_with_zero_drift() -> None:
    ledger = PortfolioLedger(starting_equity=D("4224.09882354"))
    wallet_drift, equity_drift = ledger.verify_identities()
    assert wallet_drift == D("0")
    assert equity_drift == D("0")
    assert ledger.wallet == D("4224.09882354")
    assert ledger.equity() == D("4224.09882354")
    assert ledger.available_margin() == D("4224.09882354")


def test_shared_wallet_portfolio_reserves_margin_and_compounds_shared_equity() -> None:
    start_ms = 1_704_067_200_000  # 2024-01-01T00:00:00Z
    end_ms = start_ms + 5 * 3_600_000  # 5 hours across 5 windows
    policy = RuntimeQualificationPolicy(
        starting_equity=D("1000"),
        minimum_trades=2,
        minimum_profitable_windows=1,
    )
    btc_member = PortfolioMemberSpec(member_id="scalper-btc", symbol="BTCUSDT")
    eth_member = PortfolioMemberSpec(member_id="scalper-eth", symbol="ETHUSDT")

    decision_ms = start_ms + 900_000
    events = [
        CandidateDecisionEvent(
            decision_ms=decision_ms,
            member=btc_member,
            signal=_make_signal("BTCUSDT", decision_ms, entry=D("100"), tp=D("103"), sl=D("99")),
        ),
        CandidateDecisionEvent(
            decision_ms=decision_ms,
            member=eth_member,
            signal=_make_signal(
                "ETHUSDT", decision_ms, entry=D("50"), tp=D("51.50"), sl=D("49.50")
            ),
        ),
    ]

    btc_bars: list[Candle] = []
    eth_bars: list[Candle] = []
    for ts in range(start_ms, end_ms, 300_000):
        if ts == decision_ms:
            btc_bars.append(Candle(ts, D("100.20"), D("100.50"), D("99.80"), D("100.30"), D("10")))
            eth_bars.append(Candle(ts, D("50.10"), D("50.25"), D("49.90"), D("50.15"), D("20")))
        elif ts == decision_ms + 300_000:
            btc_bars.append(Candle(ts, D("100.30"), D("103.50"), D("100.10"), D("103.20"), D("10")))
            eth_bars.append(Candle(ts, D("50.15"), D("51.80"), D("50.05"), D("51.60"), D("20")))
        else:
            btc_bars.append(Candle(ts, D("100.00"), D("100.10"), D("99.90"), D("100.00"), D("10")))
            eth_bars.append(Candle(ts, D("50.00"), D("50.05"), D("49.95"), D("50.00"), D("20")))

    result = simulate_shared_wallet_portfolio(
        events=events,
        execution_by_symbol={"BTCUSDT": btc_bars, "ETHUSDT": eth_bars},
        funding_by_symbol={
            "BTCUSDT": [(decision_ms + 150_000, D("0.0001"), D("100.00"))],
            "ETHUSDT": [(decision_ms + 150_000, D("0.0001"), D("50.00"))],
        },
        filters_by_symbol={"BTCUSDT": _default_filters(), "ETHUSDT": _default_filters()},
        leverages_by_symbol={"BTCUSDT": (5,), "ETHUSDT": (5,)},
        fees_by_symbol={
            "BTCUSDT": (D("0.0002"), D("0.0004")),
            "ETHUSDT": (D("0.0002"), D("0.0004")),
        },
        policy=policy,
        oos_start_ms=start_ms,
        end_ms=end_ms,
    )

    assert result["execution_authority"] is False
    assert result["gates"]["accounting_reconciled"] is True
    assert result["metrics"]["trade_count"] == 2
    assert result["metrics"]["max_concurrent_positions"] == 2
    assert D(result["metrics"]["max_reserved_margin_usdt"]) > D("0")
    assert D(result["metrics"]["max_wallet_drift"]) < MAX_LEDGER_DRIFT
    assert D(result["metrics"]["max_equity_drift"]) < MAX_LEDGER_DRIFT
    assert D(result["metrics"]["net_pnl"]) > D("0")
    assert set(result["by_symbol"]) == {"BTCUSDT", "ETHUSDT"}


def test_shared_daily_loss_circuit_breaker_halts_portfolio_across_symbols() -> None:
    start_ms = 1_704_067_200_000  # Day 0 UTC
    end_ms = start_ms + 2 * 86_400_000  # 2 UTC days
    policy = RuntimeQualificationPolicy(
        starting_equity=D("1000"),
        daily_loss_pct=D("0.8"),
        trade_risk_pct=D("0.5"),
        windows=2,
    )
    btc_member = PortfolioMemberSpec(member_id="scalper-btc", symbol="BTCUSDT")
    eth_member = PortfolioMemberSpec(member_id="scalper-eth", symbol="ETHUSDT")
    sol_member = PortfolioMemberSpec(member_id="scalper-sol", symbol="SOLUSDT")

    t1 = start_ms + 900_000
    t2 = start_ms + 3_600_000  # Same UTC day after combined loss > 0.8%
    t3 = start_ms + 86_400_000 + 900_000  # Next UTC day (circuit breaker resets!)

    events = [
        CandidateDecisionEvent(
            decision_ms=t1,
            member=btc_member,
            signal=_make_signal("BTCUSDT", t1, entry=D("100"), tp=D("104"), sl=D("99")),
        ),
        CandidateDecisionEvent(
            decision_ms=t1,
            member=eth_member,
            signal=_make_signal("ETHUSDT", t1, entry=D("100"), tp=D("104"), sl=D("99")),
        ),
        CandidateDecisionEvent(
            decision_ms=t2,
            member=sol_member,
            signal=_make_signal("SOLUSDT", t2, entry=D("100"), tp=D("104"), sl=D("99")),
        ),
        CandidateDecisionEvent(
            decision_ms=t3,
            member=sol_member,
            signal=_make_signal("SOLUSDT", t3, entry=D("100"), tp=D("104"), sl=D("99")),
        ),
    ]

    bars_by_sym: dict[str, list[Candle]] = {"BTCUSDT": [], "ETHUSDT": [], "SOLUSDT": []}
    for sym in bars_by_sym:
        for ts in (t1, t1 + 300_000, t2, t3, t3 + 300_000):
            if ts == t1:
                bars_by_sym[sym].append(
                    Candle(ts, D("100.10"), D("100.20"), D("98.50"), D("98.80"), D("10"))
                )
            elif ts == t3:
                bars_by_sym[sym].append(
                    Candle(ts, D("100.10"), D("100.20"), D("99.80"), D("100.10"), D("10"))
                )
            elif ts == t3 + 300_000:
                bars_by_sym[sym].append(
                    Candle(ts, D("100.10"), D("104.50"), D("100.00"), D("104.20"), D("10"))
                )
            else:
                bars_by_sym[sym].append(
                    Candle(ts, D("100.00"), D("100.10"), D("99.90"), D("100.00"), D("10"))
                )

    result = simulate_shared_wallet_portfolio(
        events=events,
        execution_by_symbol=bars_by_sym,
        funding_by_symbol={"BTCUSDT": [], "ETHUSDT": [], "SOLUSDT": []},
        filters_by_symbol={
            "BTCUSDT": _default_filters(),
            "ETHUSDT": _default_filters(),
            "SOLUSDT": _default_filters(),
        },
        leverages_by_symbol={"BTCUSDT": (5,), "ETHUSDT": (5,), "SOLUSDT": (5,)},
        fees_by_symbol={
            "BTCUSDT": (D("0.0002"), D("0.0004")),
            "ETHUSDT": (D("0.0002"), D("0.0004")),
            "SOLUSDT": (D("0.0002"), D("0.0004")),
        },
        policy=policy,
        oos_start_ms=start_ms,
        end_ms=end_ms,
    )

    assert result["gates"]["accounting_reconciled"] is True
    assert result["rejection_reasons"].get("Daily loss budget exhausted") == 1
    assert result["metrics"]["trade_count"] == 3
    assert result["by_symbol"]["SOLUSDT"]["trade_count"] == 1
    assert D(result["by_symbol"]["SOLUSDT"]["net_pnl"]) > D("0")


def test_run_portfolio_qualification_parses_extended_member_specs_and_frozen_manifest() -> None:
    import json
    from pathlib import Path

    from autonomous_futures.research.runtime_qualification import content_hash
    from scripts.run_portfolio_qualification import _members_from_selection, _parse_member_spec

    repo = Path(__file__).resolve().parents[2]
    m1 = _parse_member_spec("ethusdt")
    assert m1.symbol == "ETHUSDT"
    assert m1.stop_atr_multiplier == D("1.2")

    m3 = _parse_member_spec("SOLUSDT:-4.0:3.0")
    assert m3.symbol == "SOLUSDT"
    assert m3.distance_threshold == D("-4.0")
    assert m3.target_atr_multiplier == D("3.0")

    m7 = _parse_member_spec("AVAXUSDT:-3.5:6.0:10.0:34.0:1.5:16")
    assert m7.symbol == "AVAXUSDT"
    assert m7.stop_atr_multiplier == D("10.0")
    assert m7.rsi_threshold == D("34.0")
    assert m7.vol_spike_multiplier == D("1.5")
    assert m7.max_hold_bars == 16

    m8 = _parse_member_spec("sol-2-hf:SOLUSDT:-1.8:8.0:10.0:34.0:2.2:32")
    assert m8.member_id == "sol-2-hf"
    assert m8.symbol == "SOLUSDT"
    assert m8.distance_threshold == D("-1.8")
    assert m8.target_atr_multiplier == D("8.0")
    assert m8.stop_atr_multiplier == D("10.0")
    assert m8.rsi_threshold == D("34.0")
    assert m8.vol_spike_multiplier == D("2.2")
    assert m8.max_hold_bars == 32

    manifest_path = (
        repo
        / "research/qualification-development-2024-2026/selected-portfolio-medium-frequency-v1.json"
    )
    members = _members_from_selection(manifest_path)
    assert len(members) == 6
    assert {m.symbol for m in members} == {"AVAXUSDT", "ETHUSDT", "SOLUSDT"}

    dev_report_path = (
        repo
        / "artifacts/qualification/portfolio-scalper-mf-development-20261014"
        / "portfolio-cea9be6fc4913f7d.json"
    )
    dev_report = json.loads(dev_report_path.read_text(encoding="utf-8"))
    dev_body = dict(dev_report)
    dev_hash = dev_body.pop("report_hash")
    assert dev_hash == content_hash(dev_body)
    assert dev_report["decision"] == "DEVELOPMENT_ONLY"
    assert dev_report["portfolio_decision_on_development_sample"] == "QUALIFIED"
    assert dev_report["execution_authority"] is False
    assert all(dev_report["gates"].values())
    assert dev_report["metrics"]["trade_count"] == 495

    holdout_report_path = (
        repo
        / "artifacts/qualification/portfolio-scalper-mf-holdout-2026-08-2026-09"
        / "portfolio-72de22bde9a30101.json"
    )
    holdout_report = json.loads(holdout_report_path.read_text(encoding="utf-8"))
    holdout_body = dict(holdout_report)
    holdout_hash = holdout_body.pop("report_hash")
    assert holdout_hash == content_hash(holdout_body)
    assert holdout_report["decision"] == "QUALIFIED"
    assert holdout_report["execution_authority"] is False
    assert all(holdout_report["gates"].values())
    assert holdout_report["metrics"]["trade_count"] == 35
    assert D(holdout_report["metrics"]["net_pnl"]) > D("0")
    assert D(holdout_report["metrics"]["stress_net_pnl"]) > D("0")
    assert D(holdout_report["metrics"]["drawdown_pct"]) <= D("5.0")
