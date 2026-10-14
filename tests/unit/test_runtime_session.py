import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from test_production_remediation import account_data
from test_protective_lifecycle import PLAN

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.daily_risk import DailyRiskTracker
from autonomous_futures.execution.entry_admission import EntryAdmission
from autonomous_futures.execution.lifecycle_coordinator import LifecycleCoordinator
from autonomous_futures.execution.runtime_session import QualifiedIntention, RuntimeSession
from autonomous_futures.execution.writer_lease import ExecutionLease
from autonomous_futures.feed.authenticated_user_stream import AuthenticatedUserDataStream
from autonomous_futures.feed.exchange_clock import ExchangeClock
from autonomous_futures.feed.live_market_feed import LiveMarketFeed
from autonomous_futures.feed.runtime_hawkes_calibration import RuntimeHawkesCalibration
from autonomous_futures.feed.runtime_microstructure import RuntimeMicrostructure

CALIBRATION = RuntimeHawkesCalibration(1.0, "a" * 64, ("b" * 64,), ("SOLUSDT",))


class OneEventSocket:
    def __init__(self, event: dict[str, Any]) -> None:
        self.event = event

    async def __aenter__(self) -> OneEventSocket:
        return self

    async def __aexit__(self, *_args: Any) -> bool:
        return False

    async def __aiter__(self) -> AsyncIterator[str]:
        yield json.dumps(self.event)


@pytest.fixture
def session(tmp_path):
    lease = ExecutionLease(tmp_path / "execution.lock")
    lease.acquire()
    gateway = BinanceFuturesGateway(testnet=True, offline_mode=False)
    coordinator = LifecycleCoordinator(gateway, tmp_path, lease=lease)
    monitor = RuntimeMicrostructure(("SOLUSDT",), calibration=CALIBRATION)
    feed = LiveMarketFeed(gateway, monitor)
    user_stream = AuthenticatedUserDataStream(gateway)
    admission = EntryAdmission(
        coordinator,
        monitor,
        repo=tmp_path,
        single_writer_guard=Mock(),
        user_stream_guard=user_stream.assert_entry_ready,
    )
    tracker = DailyRiskTracker(tmp_path / "day.json", equity_basis="ACCOUNT")
    yield RuntimeSession(coordinator, admission, feed, tracker, user_stream)
    lease.close()


def test_protection_cycle_runs_without_market_fit_or_signal(session, monkeypatch):
    observation = AsyncMock(return_value=account_data())
    monkeypatch.setattr("autonomous_futures.execution.runtime_session.observe_account", observation)
    session.coordinator.advance = AsyncMock(return_value=())
    session.admission.admit = AsyncMock()
    assert asyncio.run(session.cycle()) is None
    assert observation.await_count == 1
    assert session.coordinator.advance.await_count == 1
    session.admission.admit.assert_not_awaited()
    assert session.last_cycle_ms is not None
    assert not session.feed.connected


def test_routine_account_polling_is_throttled_and_entry_forces_refresh(
    session, monkeypatch, tmp_path
):
    observation = AsyncMock(return_value=account_data())
    monkeypatch.setattr("autonomous_futures.execution.runtime_session.observe_account", observation)
    session.coordinator.advance = AsyncMock(return_value=())
    session.admission.admit = AsyncMock(return_value={"state": "NEW"})
    session.feed.connected = True
    session.user_stream.connected = True
    session.user_stream.reconciliation_required = False
    session.user_stream_gap = False
    now = time.time_ns() // 1_000_000
    session.feed.clock = ExchangeClock(now, now, now)

    # A recent successful snapshot is reused by the one-second protective loop.
    session.last_account_refresh_monotonic = time.monotonic()
    session.next_account_refresh_monotonic = time.monotonic() + 10
    assert asyncio.run(session.cycle()) is None
    observation.assert_not_awaited()

    # A queued entry forces an authenticated refresh before recovery and another after it.
    intention = QualifiedIntention(PLAN, tmp_path / "report.json")
    assert asyncio.run(session.cycle(intention)) == {"state": "NEW"}
    assert observation.await_count == 2
    assert session.coordinator.advance.await_count == 2


def test_account_refresh_failure_still_attempts_protection_and_blocks_entry(
    session, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "autonomous_futures.execution.runtime_session.observe_account",
        AsyncMock(side_effect=TimeoutError),
    )
    session.coordinator.advance = AsyncMock(return_value=())
    session.admission.admit = AsyncMock()
    intention = QualifiedIntention(PLAN, tmp_path / "report.json")

    with pytest.raises(ValueError, match="account refresh failed"):
        asyncio.run(session.cycle(intention))

    session.coordinator.advance.assert_awaited_once()
    session.admission.admit.assert_not_awaited()
    assert session.last_cycle_ms is not None


def test_account_refresh_failure_uses_backoff_without_skipping_protection(session, monkeypatch):
    observation = AsyncMock(side_effect=TimeoutError)
    monkeypatch.setattr("autonomous_futures.execution.runtime_session.observe_account", observation)
    session.coordinator.advance = AsyncMock(return_value=())

    for _ in range(2):
        with pytest.raises(ValueError, match="account refresh failed"):
            asyncio.run(session.cycle())

    observation.assert_awaited_once()
    assert session.coordinator.advance.await_count == 2
    assert session.account_refresh_error_type == "TimeoutError"
    assert session.account_refresh_backoff_seconds == 2.0


def test_entry_follows_recovery_and_refreshed_account(session, monkeypatch, tmp_path):
    events = []

    async def observe(*args, **kwargs):
        events.append("account")
        return account_data()

    async def recover(now):
        events.append("protect")
        return ()

    async def admit(*args, **kwargs):
        events.append("admit")
        return {"state": "NEW"}

    monkeypatch.setattr("autonomous_futures.execution.runtime_session.observe_account", observe)
    session.coordinator.advance = AsyncMock(side_effect=recover)
    session.admission.admit = AsyncMock(side_effect=admit)
    session.feed.connected = True
    session.user_stream.connected = True
    session.user_stream.reconciliation_required = False
    session.user_stream_gap = False
    now = time.time_ns() // 1_000_000
    session.feed.clock = ExchangeClock(now, now, now)
    readiness_ms = now - 1_000
    report_hash = "a" * 64
    intention = QualifiedIntention(PLAN, tmp_path / "report.json", readiness_ms, report_hash)
    assert asyncio.run(session.cycle(intention)) == {"state": "NEW"}
    assert events == ["account", "protect", "account", "admit"]
    assert session.admission.admit.await_args.kwargs["readiness_ms"] == readiness_ms
    assert session.admission.admit.await_args.kwargs["expected_report_hash"] == report_hash


def test_unresolved_owned_recovery_prevents_admission(session, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "autonomous_futures.execution.runtime_session.observe_account",
        AsyncMock(return_value=account_data()),
    )
    session.coordinator.advance = AsyncMock(return_value=(PLAN.signal_key,))
    session.admission.admit = AsyncMock()
    with pytest.raises(ValueError, match="recovery is unresolved"):
        asyncio.run(session.cycle(QualifiedIntention(PLAN, tmp_path / "report.json")))
    session.admission.admit.assert_not_awaited()
    assert session.last_cycle_ms is None


def test_stalled_strategy_scan_does_not_stop_protective_cycles(session):
    async def scenario():
        scanning = asyncio.Event()
        protected = asyncio.Event()

        async def scan():
            scanning.set()
            await asyncio.Future()

        async def market():
            await asyncio.Future()

        async def cycle(intention=None):
            if scanning.is_set():
                protected.set()

        session.feed.run = AsyncMock(side_effect=market)
        session.user_stream.run = AsyncMock(side_effect=market)
        session.cycle = AsyncMock(side_effect=cycle)
        task = asyncio.create_task(session.run(scan))
        await asyncio.wait_for(protected.wait(), timeout=3)
        assert session.cycle.await_count >= 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_successful_protection_cannot_clear_strategy_failure_health(session, monkeypatch):
    monkeypatch.setattr(
        "autonomous_futures.execution.runtime_session.observe_account",
        AsyncMock(return_value=account_data()),
    )
    session.coordinator.advance = AsyncMock(return_value=())
    session.last_scan_error_type = "ValueError"
    asyncio.run(session.cycle())
    session.publish_health()
    report = json.loads((session.coordinator.directory / "runtime-health.json").read_text())
    assert report["scan_error_type"] == "ValueError"
    assert report["cycle_error_type"] is None
    assert report["last_protective_cycle_ms"] is not None
    assert report["market_connected"] is False
    assert report["microstructure"]["calibration_window_ms"] == 1_800_000
    assert report["microstructure"]["calibration"]["beta_per_second"] == 1.0
    assert len(report["microstructure"]["calibration"]["artifact_sha256"]) == 64
    assert report["microstructure"]["fit"] is None
    assert "execution_authority" not in report


def test_entry_is_blocked_without_connected_user_stream(session, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "autonomous_futures.execution.runtime_session.observe_account",
        AsyncMock(return_value=account_data()),
    )
    session.coordinator.advance = AsyncMock(return_value=())
    session.admission.admit = AsyncMock()
    session.feed.connected = True
    now = time.time_ns() // 1_000_000
    session.feed.clock = ExchangeClock(now, now, now)

    with pytest.raises(ValueError, match="authenticated user-data stream"):
        asyncio.run(session.cycle(QualifiedIntention(PLAN, tmp_path / "report.json")))

    session.admission.admit.assert_not_awaited()


def test_margin_call_user_event_requests_immediate_flatten(session, monkeypatch):
    monkeypatch.setattr(
        "autonomous_futures.execution.runtime_session.observe_account",
        AsyncMock(return_value=account_data()),
    )
    session.coordinator.advance = AsyncMock(return_value=())

    async def scenario():
        await session._on_user_data_event({"e": "MARGIN_CALL"})
        await session.cycle()

    asyncio.run(scenario())

    session.coordinator.advance.assert_awaited_once_with(
        session.last_cycle_ms, external_risk_breach=True
    )
    assert session.force_flatten_reason is None


def test_authenticated_margin_event_flows_through_stream_into_protective_cycle(
    session, monkeypatch
):
    monkeypatch.setattr(
        "autonomous_futures.execution.runtime_session.observe_account",
        AsyncMock(return_value=account_data()),
    )
    session.coordinator.advance = AsyncMock(return_value=())
    session.user_stream.listen_key = "unit-test-listen-key"
    session.user_stream.connector = lambda *_args, **_kwargs: OneEventSocket(
        {"e": "MARGIN_CALL", "E": 1790146800000}
    )

    async def scenario():
        await session.user_stream._consume_connection()
        assert session.user_data_event_counts == {"MARGIN_CALL": 1}
        assert session.force_flatten_reason == "MARGIN_CALL"
        assert session.user_stream.entry_block_reason == "MARGIN_CALL"
        assert session.user_stream_gap

        await session.cycle()

    asyncio.run(scenario())

    assert session.coordinator.advance.await_count == 2
    assert session.coordinator.advance.await_args_list[-1].kwargs == {"external_risk_breach": True}
    assert session.force_flatten_reason is None
    assert session.user_stream.entry_block_reason is None
    assert session.user_stream_gap
