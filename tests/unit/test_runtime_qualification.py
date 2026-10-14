import hashlib
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from autonomous_futures.execution.qualification_receipts import verify_source_index
from autonomous_futures.execution.trade_plan import SymbolFilters, build_plan, scalper_plan
from autonomous_futures.research.runtime_qualification import (
    RuntimeQualificationPolicy,
    bind_commission_policy,
    bind_equity_scenario,
    exact_scalper_candidates,
    qualification_capital,
    replay_plan,
    source_file_index,
)
from autonomous_futures.strategy.macro_liquidity_scalper import Candle, ScalperSignal


def plan():
    return build_plan(
        family="MACRO_SCALPER",
        symbol="SOLUSDT",
        side="BUY",
        entry=D("100"),
        stop=D("90"),
        tp1=D("120"),
        tp2=None,
        decision_ms=300000,
        hold_ms=900000,
        setup_key="observed",
        filters=SymbolFilters(D(".01"), D(".01"), D(".01"), D("1000"), D("5")),
        equity=D("1000"),
        available_margin=D("1000"),
    )


def candle(ts, open_, high, low, close):
    return Candle(ts, D(open_), D(high), D(low), D(close), D("10"))


def test_post_decision_fill_and_same_bar_stop_win_over_target():
    bars = [candle(0, "100", "130", "80", "100"), candle(300000, "100", "130", "80", "100")]
    result = replay_plan(plan(), bars, [], RuntimeQualificationPolicy(), 1200000, wallet=D("1000"))
    assert result is not None
    assert result["entry_ms"] == 300000
    assert result["reason"] == "STOP_LOSS"
    assert D(result["net_pnl"]) < 0


def test_no_trade_through_means_no_fill():
    assert (
        replay_plan(
            plan(),
            [candle(300000, "100", "120", "100", "110")],
            [],
            RuntimeQualificationPolicy(),
            1200000,
        )
        is None
    )


def test_daily_circuit_precedes_more_distant_strategy_stop():
    result = replay_plan(
        plan(),
        [candle(300000, "100", "101", "80", "90")],
        [],
        RuntimeQualificationPolicy(),
        1200000,
        wallet=D("951"),
        day_start_equity=D("1000"),
        risk_day=0,
    )
    assert result is not None
    assert result["reason"] == "DAILY_LOSS"
    assert D(result["exit_price"]) > D("90")


def test_future_bar_cannot_complete_window_trade():
    bars = [candle(300000, "100", "101", "99", "100"), candle(600000, "100", "130", "80", "100")]
    result = replay_plan(plan(), bars, [], RuntimeQualificationPolicy(), 600000)
    assert result is not None
    assert result["reason"] == "TIME_STOP"
    assert result["exit_price"] == "100"
    assert result["exit_ms"] == 600000


def test_new_policy_has_no_five_dollar_margin_or_notional_cap():
    intention = plan()
    assert intention.initial_margin > D("5")
    assert intention.notional > D("25")


def test_qualification_policy_explicitly_binds_runtime_risk_percentages():
    policy = RuntimeQualificationPolicy()
    capital = policy.capital_policy()

    assert policy.trade_risk_pct == D("0.5")
    assert capital.trade_risk_pct == D("0.5")
    assert policy.daily_loss_pct == D("5")
    assert capital.daily_loss_pct == D("5")


def test_authenticated_testnet_equity_is_a_hash_bound_sizing_seed_only():
    repo = Path(__file__).resolve().parents[2]
    evidence_path = (
        repo
        / "artifacts/qualification/runtime-inputs/testnet-account-probe-20261014-1791918191661.json"
    )
    policy, scenario = qualification_capital(repo=repo, equity_evidence_path=evidence_path)

    assert policy.starting_equity == D("4224.09882354")
    assert policy.trade_risk_pct == D("0.5")
    assert policy.daily_loss_pct == D("5")
    assert scenario is not None
    assert scenario["flat_account"] is True
    assert scenario["utc_day_start_baseline_verified"] is False
    assert scenario["execution_authority"] is False

    report = {
        "policy": {"starting_equity": str(policy.starting_equity)},
        "sources": {},
        "report_hash": "stale",
    }
    bound = bind_equity_scenario(report, scenario, repo)

    assert bound["capital_scenario"] == scenario
    assert bound["sources"]["capital_scenario"] == scenario["evidence"]
    assert bound["report_hash"] != "stale"
    verify_source_index(bound["sources"], bound["source_files"], repo)
    assert "capital_scenario" not in report


def test_authenticated_testnet_commission_rates_are_bound_to_symbol_policy():
    repo = Path(__file__).resolve().parents[2]
    commission_path = (
        repo / "artifacts/qualification/runtime-inputs/testnet-commissions-1791824521337.json"
    )

    policy, evidence = bind_commission_policy(
        RuntimeQualificationPolicy(), commission_path, "ADAUSDT", repo
    )

    assert policy.maker_fee == D("0.000200")
    assert policy.taker_fee == D("0.000400")
    assert evidence["symbol"] == "ADAUSDT"
    assert (
        evidence["path"]
        == "artifacts/qualification/runtime-inputs/testnet-commissions-1791824521337.json"
    )
    assert evidence["sha256"] == hashlib.sha256(commission_path.read_bytes()).hexdigest()
    assert evidence["observed_ms"] == 1791824521337
    verify_source_index(
        {"commissions": evidence}, source_file_index({"commissions": evidence}, repo), repo
    )


def test_commission_binding_rejects_unrecognized_or_duplicate_symbol_rows(tmp_path: Path):
    repo = tmp_path
    commission_path = repo / "commission.json"
    commission_path.write_text(
        json.dumps(
            {
                "source": "https://testnet.binancefuture.com/fapi/v1/commissionRate",
                "observed_ms": 1,
                "rates": [
                    {
                        "symbol": "ADAUSDT",
                        "maker": "0.0002",
                        "taker": "0.0004",
                        "response_sha256": "a" * 64,
                    },
                    {
                        "symbol": "ADAUSDT",
                        "maker": "0.0002",
                        "taker": "0.0004",
                        "response_sha256": "b" * 64,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exactly one record"):
        bind_commission_policy(RuntimeQualificationPolicy(), commission_path, "ADAUSDT", repo)


@pytest.mark.parametrize("value", [D("0"), D("-1"), D("NaN"), D("Infinity")])
def test_qualification_policy_rejects_nonpositive_or_nonfinite_starting_equity(value):
    with pytest.raises(ValueError, match="positive finite Decimal"):
        RuntimeQualificationPolicy(starting_equity=value)


def test_authenticated_capital_evidence_rejects_nonflat_account(tmp_path: Path):
    actual = Path(__file__).resolve().parents[2] / (
        "artifacts/qualification/runtime-inputs/testnet-account-probe-20261014-1791918191661.json"
    )
    evidence = json.loads(actual.read_text(encoding="utf-8"))
    evidence["open_position_count"] = 1
    repo = tmp_path / "repo"
    path = repo / "capital.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(ValueError, match="flat account"):
        qualification_capital(repo=repo, equity_evidence_path=path)


def test_scalper_planner_applies_qualification_trade_risk_policy():
    policy = RuntimeQualificationPolicy()
    signal = ScalperSignal(
        symbol="SOLUSDT",
        timestamp_ms=300_000,
        side="BUY",
        order_type="LIMIT",
        sweep_price=D("100"),
        stop_loss=D("95"),
        take_profit=D("110"),
        atr=D("5"),
    )
    filters = SymbolFilters(D(".01"), D(".01"), D(".01"), D("1000"), D("5"))

    trade = scalper_plan(
        signal,
        filters,
        equity=D("1000"),
        available_margin=D("1000"),
        remaining_daily_risk=D("50"),
        capital=policy.capital_policy(),
    )
    stressed_risk = trade.quantity * (
        abs(trade.entry - trade.stop) + (trade.entry + trade.stop) * D("0.0013")
    )

    assert stressed_risk <= D("5")
    assert stressed_risk > D("4.9")


def test_scalper_planner_preserves_short_signal_side():
    signal = ScalperSignal(
        symbol="SOLUSDT",
        timestamp_ms=300_000,
        side="SELL",
        order_type="LIMIT",
        sweep_price=D("100"),
        stop_loss=D("105"),
        take_profit=D("90"),
        atr=D("4"),
    )
    filters = SymbolFilters(D(".01"), D(".01"), D(".01"), D("1000"), D("5"))

    trade = scalper_plan(
        signal,
        filters,
        equity=D("1000"),
        available_margin=D("1000"),
        remaining_daily_risk=D("50"),
    )

    assert trade.side == "SELL"
    assert trade.stop > trade.entry > trade.tp1


def test_exact_scalper_candidate_screen_includes_overbought_volume_spike():
    bars = [
        Candle(
            i * 900_000,
            D("100"),
            D("101"),
            D("99"),
            D("100"),
            D("10"),
        )
        for i in range(20)
    ]
    bars.append(Candle(20 * 900_000, D("100"), D("130"), D("99"), D("125"), D("100")))

    assert exact_scalper_candidates(bars) == [20]


def test_qualification_source_index_is_relative_complete_and_byte_verified(tmp_path: Path):
    repo = tmp_path / "repo"
    data = repo / "research/data/market.bin"
    manifest = repo / "research/data/manifest.json"
    filters = repo / "artifacts/filters.json"
    for path, content in (
        (data, b"verified market bytes"),
        (manifest, b"verified manifest bytes"),
        (filters, b"verified filter bytes"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    sources = {
        "market": {
            "dataset": {"path": str(data), "sha256": hashlib.sha256(data.read_bytes()).hexdigest()},
            "manifest": {
                "path": str(manifest),
                "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            },
        },
        "filters": {
            "path": str(filters),
            "sha256": hashlib.sha256(filters.read_bytes()).hexdigest(),
        },
    }

    files = source_file_index(sources, repo)

    assert {item["path"] for item in files} == {
        "artifacts/filters.json",
        "research/data/manifest.json",
        "research/data/market.bin",
    }
    verify_source_index(sources, files, repo)


def test_qualification_source_index_rejects_inputs_outside_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside source bytes")
    sources = {
        "external": {
            "path": str(outside),
            "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
        }
    }

    with pytest.raises(ValueError, match="inside the repository"):
        source_file_index(sources, repo)
