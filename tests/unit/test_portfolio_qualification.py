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
