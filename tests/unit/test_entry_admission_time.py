import asyncio
import threading
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest
from test_protective_lifecycle import PLAN

from autonomous_futures.execution.entry_admission import EntryAdmission, validate_intention_time
from autonomous_futures.feed.exchange_clock import ExchangeClock


@pytest.mark.parametrize("family,limit", [("ICT_TWINS", 60000), ("MACRO_SCALPER", 300000)])
def test_causal_intention_expires_at_family_deadline(family, limit):
    plan = replace(PLAN, family=family)
    validate_intention_time(plan, plan.decision_ms)
    validate_intention_time(plan, plan.decision_ms + limit - 1)
    for timestamp in (plan.decision_ms - 1, plan.decision_ms + limit):
        with pytest.raises(ValueError, match="causal decision"):
            validate_intention_time(plan, timestamp)


def test_staged_reclaim_uses_fresh_causal_stage_and_original_expiry():
    plan = replace(PLAN, decision_ms=1_000)
    validate_intention_time(
        plan,
        121_000,
        readiness_ms=120_000,
        maximum_plan_age_ms=300_000,
    )
    for now, ready in ((301_000, 300_000), (121_000, 121_001)):
        with pytest.raises(ValueError, match="causal"):
            validate_intention_time(
                plan,
                now,
                readiness_ms=ready,
                maximum_plan_age_ms=300_000,
            )


def test_report_hashing_does_not_block_the_market_event_loop(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr("autonomous_futures.execution.entry_admission.time.time", lambda: 1.001)

    def verify(*args, **kwargs):
        entered.set()
        if not release.wait(2):
            raise AssertionError("Report verification blocked event-loop progress")
        raise ValueError("Explicit rejected-report fixture")

    monkeypatch.setattr(
        "autonomous_futures.execution.entry_admission.verify_runtime_report", verify
    )
    coordinator = Mock()
    coordinator.lease.assert_held = Mock()
    coordinator.gateway.get_position_mode = AsyncMock(return_value=False)
    admission = EntryAdmission(
        coordinator,
        Mock(),
        repo=tmp_path,
        single_writer_guard=Mock(),
        user_stream_guard=Mock(),
    )

    async def scenario():
        task = asyncio.create_task(
            admission.admit(
                PLAN, tmp_path / "report.json", exchange_clock=ExchangeClock(1000, 1000, 1000)
            )
        )
        assert await asyncio.to_thread(entered.wait, 1)
        assert not task.done()
        release.set()
        with pytest.raises(ValueError, match="rejected-report fixture"):
            await task

    asyncio.run(scenario())


def test_intention_expiry_is_rechecked_after_report_verification(tmp_path, monkeypatch):
    now = [1.001]
    captured = {}
    monkeypatch.setattr("autonomous_futures.execution.entry_admission.time.time", lambda: now[0])

    def verify(*args, **kwargs):
        captured.update(kwargs)
        now[0] += 60
        return Mock(policy={"daily_loss_pct": "5"}, configuration={"entry_mode": "limit_touch"})

    monkeypatch.setattr(
        "autonomous_futures.execution.entry_admission.verify_runtime_report", verify
    )
    coordinator = Mock()
    coordinator.lease.assert_held = Mock()
    coordinator.gateway.get_position_mode = AsyncMock(return_value=False)
    admission = EntryAdmission(
        coordinator,
        Mock(),
        repo=tmp_path,
        single_writer_guard=Mock(),
        user_stream_guard=Mock(),
        admission_manifest_path=tmp_path / "mainnet-admission.json",
    )
    with pytest.raises(ValueError, match="causal decision"):
        asyncio.run(
            admission.admit(
                PLAN, tmp_path / "report.json", exchange_clock=ExchangeClock(1000, 1000, 1000)
            )
        )
    assert captured["admission_manifest_path"] == tmp_path / "mainnet-admission.json"


def test_hedge_mode_is_rejected_before_account_evidence_or_protective_orders(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "autonomous_futures.execution.entry_admission.validate_intention_time",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "autonomous_futures.execution.entry_admission.verify_runtime_report",
        lambda *args, **kwargs: Mock(
            policy={"daily_loss_pct": "5"}, configuration={"entry_mode": "limit_touch"}
        ),
    )
    coordinator = Mock()
    coordinator.lease.assert_held = Mock()
    coordinator.gateway.get_position_mode = AsyncMock(return_value=True)
    admission = EntryAdmission(
        coordinator,
        Mock(),
        repo=tmp_path,
        single_writer_guard=Mock(),
        user_stream_guard=Mock(),
    )
    clock = Mock()
    clock.aligned_ms.return_value = PLAN.decision_ms

    with pytest.raises(ValueError, match="one-way exchange position mode"):
        asyncio.run(admission.admit(PLAN, tmp_path / "report.json", exchange_clock=clock))

    coordinator.gateway.get_position_mode.assert_awaited_once_with()
    coordinator.prepare.assert_not_called()


@pytest.mark.parametrize(
    "configuration,readiness_ms,expected",
    [
        ({"entry_mode": "reclaim_retest"}, None, "requires a completed causal reclaim"),
        ({"entry_mode": "limit_touch"}, PLAN.decision_ms + 1, "not authorized"),
    ],
)
def test_report_entry_mode_must_authorize_staged_readiness(
    tmp_path, monkeypatch, configuration, readiness_ms, expected
):
    monkeypatch.setattr("autonomous_futures.execution.entry_admission.time.time", lambda: 1.002)
    monkeypatch.setattr(
        "autonomous_futures.execution.entry_admission.verify_runtime_report",
        lambda *args, **kwargs: Mock(
            policy={"daily_loss_pct": "5", "entry_ttl_ms": "300000"},
            configuration=configuration,
        ),
    )
    coordinator = Mock()
    coordinator.lease.assert_held = Mock()
    coordinator.gateway.get_position_mode = AsyncMock(return_value=False)
    admission = EntryAdmission(
        coordinator,
        Mock(),
        repo=tmp_path,
        single_writer_guard=Mock(),
        user_stream_guard=Mock(),
    )

    with pytest.raises(ValueError, match=expected):
        asyncio.run(
            admission.admit(
                PLAN,
                tmp_path / "report.json",
                exchange_clock=ExchangeClock(1000, 1000, 1000),
                readiness_ms=readiness_ms,
            )
        )

    coordinator.gateway.get_position_mode.assert_not_awaited()
    coordinator.prepare.assert_not_called()


def test_intention_is_bound_to_the_report_verified_at_admission(tmp_path, monkeypatch):
    monkeypatch.setattr("autonomous_futures.execution.entry_admission.time.time", lambda: 1.001)
    monkeypatch.setattr(
        "autonomous_futures.execution.entry_admission.verify_runtime_report",
        lambda *args, **kwargs: Mock(
            policy={"daily_loss_pct": "5"},
            configuration={"entry_mode": "limit_touch"},
            report_hash="b" * 64,
        ),
    )
    coordinator = Mock()
    coordinator.lease.assert_held = Mock()
    coordinator.gateway.get_position_mode = AsyncMock(return_value=False)
    admission = EntryAdmission(
        coordinator,
        Mock(),
        repo=tmp_path,
        single_writer_guard=Mock(),
        user_stream_guard=Mock(),
    )

    with pytest.raises(ValueError, match="differs from its verified source pin"):
        asyncio.run(
            admission.admit(
                PLAN,
                tmp_path / "report.json",
                exchange_clock=ExchangeClock(1000, 1000, 1000),
                expected_report_hash="a" * 64,
            )
        )
    coordinator.gateway.get_position_mode.assert_not_awaited()
