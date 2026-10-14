from decimal import Decimal as D

import pytest

from autonomous_futures.execution.daily_risk import DailyRisk


def test_five_percent_scales_with_day_start_equity():
    assert DailyRisk(D("100"), D("100")).limit_usdt == D("5")
    assert DailyRisk(D("4224.09882354"), D("4224.09882354")).limit_usdt == D("211.204941177")


def test_boundary_includes_unrealized_equity_loss():
    assert not DailyRisk(D("100"), D("95.000000000000001")).breached
    assert DailyRisk(D("100"), D("95")).breached
    assert DailyRisk(D("100"), D("94")).remaining_usdt == 0


def test_external_flows_do_not_change_trading_loss():
    assert DailyRisk(D("100"), D("105"), D("10")).breached
    assert not DailyRisk(D("100"), D("90"), D("-10")).breached


@pytest.mark.parametrize("baseline,current", [("0", "100"), ("NaN", "100"), ("100", "Infinity")])
def test_invalid_evidence_rejected(baseline, current):
    with pytest.raises(ValueError):
        DailyRisk(D(baseline), D(current))


def evidence(timestamp, equity="100", external_flows=None):
    return {
        "source": "binance_authenticated_rest",
        "timestamp_ms": timestamp,
        "testnet": True,
        "reconciliation": {"verified": True},
        "account": {"totalMarginBalance": equity},
        "daily_external_flows": [] if external_flows is None else external_flows,
    }


def test_tracker_cannot_invent_midday_baseline(tmp_path):
    from autonomous_futures.execution.daily_risk import DailyRiskTracker

    tracker = DailyRiskTracker(tmp_path / "day.json", equity_basis="ACCOUNT")
    with pytest.raises(ValueError, match="Missing authentic day-start"):
        tracker.observe(evidence(3600000), 3600000)
    assert not tracker.path.exists()


def test_tracker_latches_breach_across_recovery_and_restart(tmp_path):
    from autonomous_futures.execution.daily_risk import DailyRiskTracker

    path = tmp_path / "day.json"
    tracker = DailyRiskTracker(path, equity_basis="ACCOUNT")
    assert tracker.observe(evidence(1000), 1000)["limit_usdt"] == "5"
    assert tracker.observe(evidence(2000, "95"), 2000)["breached"]
    restarted = DailyRiskTracker(path, equity_basis="ACCOUNT")
    assert restarted.observe(evidence(3000, "101"), 3000)["remaining_usdt"] == "0"
    assert not restarted.observe(evidence(86401000, "101"), 86401000)["breached"]


def test_tracker_counts_deposits_as_basis_adjustments_not_loss_relief(tmp_path):
    from autonomous_futures.execution.daily_risk import DailyRiskTracker

    tracker = DailyRiskTracker(tmp_path / "day.json", equity_basis="ACCOUNT")
    tracker.observe(evidence(1000), 1000)
    snapshot = evidence(
        2000,
        "106",
        [
            {
                "incomeType": "TRANSFER",
                "asset": "USDT",
                "tranId": "deposit-1",
                "time": 1500,
                "income": "10",
            }
        ],
    )
    risk = tracker.observe(snapshot, 2000)
    assert risk["net_external_flows"] == "10"
    assert risk["loss_usdt"] == "4"
    assert risk["remaining_usdt"] == "1"

    from autonomous_futures.execution.entry_risk import remaining_daily_budget

    snapshot["daily_risk"] = risk
    snapshot["testnet"] = True
    assert remaining_daily_budget(snapshot) == D("1")


def test_tracker_does_not_count_withdrawals_as_trading_losses(tmp_path):
    from autonomous_futures.execution.daily_risk import DailyRiskTracker

    tracker = DailyRiskTracker(tmp_path / "day.json", equity_basis="ACCOUNT")
    tracker.observe(evidence(1000), 1000)
    risk = tracker.observe(
        evidence(
            2000,
            "90",
            [
                {
                    "incomeType": "TRANSFER",
                    "asset": "USDT",
                    "tranId": "withdrawal-1",
                    "time": 1500,
                    "income": "-10",
                }
            ],
        ),
        2000,
    )
    assert risk["loss_usdt"] == "0"
    assert not risk["breached"]


def test_tracker_excludes_transfers_already_reflected_in_day_start_equity(tmp_path):
    from autonomous_futures.execution.daily_risk import DailyRiskTracker

    tracker = DailyRiskTracker(tmp_path / "day.json", equity_basis="ACCOUNT")
    before_capture = [
        {
            "incomeType": "TRANSFER",
            "asset": "USDT",
            "tranId": "deposit-before-capture",
            "time": 500,
            "income": "10",
        }
    ]
    tracker.observe(evidence(1000, "110", before_capture), 1000)
    risk = tracker.observe(evidence(2000, "105", before_capture), 2000)
    assert risk["net_external_flows"] == "0"
    assert risk["loss_usdt"] == "5"


def test_tracker_rejects_ambiguous_or_unclassified_external_flows(tmp_path):
    from autonomous_futures.execution.daily_risk import DailyRiskTracker

    tracker = DailyRiskTracker(tmp_path / "day.json", equity_basis="ACCOUNT")
    tracker.observe(evidence(1000), 1000)
    ambiguous = evidence(
        2000,
        "100",
        [
            {
                "incomeType": "TRANSFER",
                "asset": "USDT",
                "tranId": "same-time",
                "time": 1000,
                "income": "1",
            }
        ],
    )
    with pytest.raises(ValueError, match="ambiguous"):
        tracker.observe(ambiguous, 2000)
    unsupported = evidence(
        2000,
        "100",
        [
            {
                "incomeType": "WELCOME_BONUS",
                "asset": "USDT",
                "tranId": "bonus-1",
                "time": 1500,
                "income": "1",
            }
        ],
    )
    with pytest.raises(ValueError, match="unclassified"):
        tracker.observe(unsupported, 2000)


def test_daily_risk_rejects_duplicate_external_flow_rows(tmp_path):
    from autonomous_futures.execution.daily_risk import DailyRiskTracker

    tracker = DailyRiskTracker(tmp_path / "day.json", equity_basis="ACCOUNT")
    tracker.observe(evidence(1000), 1000)
    duplicate = {
        "incomeType": "TRANSFER",
        "asset": "USDT",
        "tranId": "duplicate",
        "time": 1500,
        "income": "10",
    }
    with pytest.raises(ValueError, match="Duplicate external flow"):
        tracker.observe(evidence(2000, "110", [duplicate, duplicate.copy()]), 2000)


def test_tracker_rejects_fake_evidence_and_unselected_basis(tmp_path):
    from autonomous_futures.execution.daily_risk import DailyRiskTracker

    with pytest.raises(ValueError):
        DailyRiskTracker(tmp_path / "day.json", equity_basis="UNCONFIGURED")
    tracker = DailyRiskTracker(tmp_path / "day.json", equity_basis="ACCOUNT")
    data = evidence(1000)
    data["reconciliation"]["verified"] = False
    with pytest.raises(ValueError, match="fresh reconciled"):
        tracker.observe(data, 1000)
