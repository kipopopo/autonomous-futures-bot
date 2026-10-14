"""Serialize real account/protective cycles before qualified strategy entry admission."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autonomous_futures.execution.account_evidence import (
    SNAPSHOT_NAME,
    atomic_json,
    finite_decimal,
    observe_account,
)
from autonomous_futures.execution.daily_risk import DailyRiskTracker
from autonomous_futures.execution.entry_admission import EntryAdmission
from autonomous_futures.execution.entry_risk import remaining_daily_budget
from autonomous_futures.execution.lifecycle_coordinator import LifecycleCoordinator
from autonomous_futures.execution.trade_plan import TradePlan
from autonomous_futures.feed.authenticated_user_stream import AuthenticatedUserDataStream
from autonomous_futures.feed.live_market_feed import LiveMarketFeed

ACCOUNT_REFRESH_INTERVAL_SECONDS = 10.0
ACCOUNT_REFRESH_MAX_BACKOFF_SECONDS = 10.0
RISK_EVENT_REFRESH_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class QualifiedIntention:
    plan: TradePlan
    report_path: Path
    readiness_ms: int | None = None
    report_hash: str | None = None
    portfolio_id: str | None = None
    member_id: str | None = None


class RuntimeSession:
    """Protect owned exposure without requiring a qualified signal or a warm market fit.

    The signal producer must supply actual causal strategy intentions. This component
    creates no signals, account allocations, fill events, or qualification reports.
    """

    def __init__(
        self,
        coordinator: LifecycleCoordinator,
        admission: EntryAdmission,
        feed: LiveMarketFeed,
        daily_risk: DailyRiskTracker,
        user_stream: AuthenticatedUserDataStream | None = None,
    ) -> None:
        if admission.coordinator is not coordinator or admission.microstructure is not feed.monitor:
            raise ValueError("Runtime components do not share ownership and market evidence")
        if feed.gateway is not coordinator.gateway:
            raise ValueError("Account and market components use different exchange gateways")
        coordinator.lease.assert_held()
        self.coordinator, self.admission, self.feed, self.daily_risk = (
            coordinator,
            admission,
            feed,
            daily_risk,
        )
        self.user_stream = user_stream
        if self.user_stream is not None:
            self.user_stream.on_event = self._on_user_data_event
            self.user_stream.on_reconnect = self._resynchronize_after_user_stream_reconnect
            self.user_stream.on_disconnect = self._on_user_stream_disconnect
        self.lock = asyncio.Lock()
        self.cycle_wakeup = asyncio.Event()
        self.account_refresh_requested = False
        self.user_stream_gap = True
        self.force_flatten_reason: str | None = None
        self.user_data_event_counts: dict[str, int] = {}
        self.last_cycle_ms: int | None = None
        self.last_account_refresh_monotonic: float | None = None
        self.next_account_refresh_monotonic: float | None = None
        self.account_refresh_backoff_seconds = 1.0
        self.account_refresh_error_type: str | None = None
        self.last_cycle_error_type: str | None = None
        self.last_scan_error_type: str | None = None

    async def _refresh_account(self, path: Path) -> dict[str, Any]:
        try:
            snapshot = await observe_account(
                self.coordinator.gateway, path, risk_tracker=self.daily_risk
            )
        except Exception as exc:
            now_monotonic = time.monotonic()
            self.account_refresh_error_type = type(exc).__name__
            self.next_account_refresh_monotonic = (
                now_monotonic + self.account_refresh_backoff_seconds
            )
            self.account_refresh_backoff_seconds = min(
                self.account_refresh_backoff_seconds * 2, ACCOUNT_REFRESH_MAX_BACKOFF_SECONDS
            )
            raise
        now_monotonic = time.monotonic()
        self.last_account_refresh_monotonic = now_monotonic
        refresh_interval = (
            RISK_EVENT_REFRESH_INTERVAL_SECONDS
            if self.force_flatten_reason is not None
            else ACCOUNT_REFRESH_INTERVAL_SECONDS
        )
        self.next_account_refresh_monotonic = now_monotonic + refresh_interval
        self.account_refresh_backoff_seconds = 1.0
        self.account_refresh_error_type = None
        return snapshot

    def publish_health(self) -> None:
        self.coordinator.lease.assert_held()
        monitor = self.feed.monitor
        fit = monitor.fit
        atomic_json(
            self.coordinator.directory / "runtime-health.json",
            {
                "source": "runtime_observation",
                "timestamp_ms": time.time_ns() // 1_000_000,
                "last_protective_cycle_ms": self.last_cycle_ms,
                "cycle_error_type": self.last_cycle_error_type,
                "last_account_refresh_error_type": self.account_refresh_error_type,
                "scan_error_type": self.last_scan_error_type,
                "market_connected": self.feed.connected,
                "market_error_type": self.feed.last_error_type,
                "user_stream_connected": bool(
                    self.user_stream is not None and self.user_stream.connected
                ),
                "user_stream_reconciliation_required": bool(
                    self.user_stream is None or self.user_stream.reconciliation_required
                ),
                "user_stream_entry_block_reason": (
                    None if self.user_stream is None else self.user_stream.entry_block_reason
                ),
                "user_stream_error_type": (
                    None if self.user_stream is None else self.user_stream.last_error_type
                ),
                "user_stream_last_event_type": (
                    None if self.user_stream is None else self.user_stream.last_event_type
                ),
                "user_stream_event_count": (
                    0 if self.user_stream is None else self.user_stream.event_count
                ),
                "user_stream_gap": self.user_stream_gap,
                "user_data_event_counts": dict(self.user_data_event_counts),
                "force_flatten_reason": self.force_flatten_reason,
                "market_generation": monitor.generation,
                "microstructure": {
                    "calibration_window_ms": monitor.calibration_window_ms,
                    "calibration": {
                        "beta_per_second": monitor.calibration.beta_per_second,
                        "artifact_sha256": monitor.calibration.artifact_sha256,
                        "trace_sha256s": list(monitor.calibration.trace_sha256s),
                    },
                    "arrival_count": len(monitor.arrivals),
                    "fit_error": monitor.last_fit_error,
                    "fit": None
                    if fit is None
                    else {
                        "first_ms": fit.first_ms,
                        "last_ms": fit.last_ms,
                        "event_counts": dict(zip(fit.symbols, fit.counts, strict=True)),
                        "beta_per_second": fit.beta,
                        "baseline_boundary_symbols": list(fit.baseline_boundary_symbols),
                        "spectral_radius": fit.spectral_radius,
                        "arrivals_sha256": fit.arrivals_sha256,
                    },
                },
            },
        )

    async def _on_user_data_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("e")
        if not isinstance(event_type, str):
            raise ValueError("Authenticated user event is missing its event type")
        self.user_data_event_counts[event_type] = self.user_data_event_counts.get(event_type, 0) + 1
        self.account_refresh_requested = True
        if event_type in {"MARGIN_CALL", "CONDITIONAL_ORDER_TRIGGER_REJECT"}:
            self.force_flatten_reason = event_type
            if self.user_stream is not None:
                self.user_stream.block_entries(event_type)
        self.cycle_wakeup.set()

    @staticmethod
    def _account_has_exposure(snapshot: dict[str, Any]) -> bool:
        return any(
            finite_decimal(position["positionAmt"]) != 0 for position in snapshot["positions"]
        )

    async def _on_user_stream_disconnect(self) -> None:
        self.user_stream_gap = True
        self.account_refresh_requested = True
        self.cycle_wakeup.set()

    async def _resynchronize_after_user_stream_reconnect(self) -> None:
        """Reconcile all REST-owned state before a reconnected stream can admit entries."""
        async with self.lock:
            self.coordinator.lease.assert_held()
            path = self.coordinator.directory / SNAPSHOT_NAME
            snapshot = await self._refresh_account(path)
            now_ms = time.time_ns() // 1_000_000
            if self.force_flatten_reason is None:
                errors = await self.coordinator.advance(now_ms)
            else:
                errors = await self.coordinator.advance(now_ms, external_risk_breach=True)
            if errors:
                raise ValueError("User-stream recovery found unresolved owned lifecycle state")
            if (
                self.force_flatten_reason is not None
                and not self._account_has_exposure(snapshot)
                and self.user_stream is not None
            ):
                self.user_stream.clear_entry_block(self.force_flatten_reason)
                self.force_flatten_reason = None
            self.account_refresh_requested = False
            self.user_stream_gap = False
            self.cycle_wakeup.set()

    async def cycle(self, intention: QualifiedIntention | None = None) -> dict[str, Any] | None:
        async with self.lock:
            self.coordinator.lease.assert_held()
            observed_event_count = (
                None if self.user_stream is None else self.user_stream.event_count
            )
            risk_reason_at_start = self.force_flatten_reason
            path = self.coordinator.directory / SNAPSHOT_NAME
            observation_error: Exception | None = None
            now_monotonic = time.monotonic()
            refresh_due = (
                self.next_account_refresh_monotonic is None
                or now_monotonic >= self.next_account_refresh_monotonic
                or self.account_refresh_requested
            )
            if intention is not None and self.account_refresh_error_type is None:
                refresh_due = True
            if refresh_due:
                self.account_refresh_requested = False
                try:
                    refreshed_snapshot = await self._refresh_account(path)
                except Exception as exc:
                    # A failed refresh must not skip reconciliation/protection. The coordinator
                    # can still use a cached snapshot while it is fresh; it independently fails
                    # closed if that evidence is missing or stale.
                    observation_error = exc
                    refreshed_snapshot = None
            elif self.account_refresh_error_type is not None:
                observation_error = RuntimeError("Authenticated account refresh is backing off")
                refreshed_snapshot = None
            else:
                refreshed_snapshot = None
            cycle_ms = time.time_ns() // 1_000_000
            if risk_reason_at_start is None:
                errors = await self.coordinator.advance(cycle_ms)
            else:
                errors = await self.coordinator.advance(cycle_ms, external_risk_breach=True)
            if errors:
                raise ValueError("Owned lifecycle recovery is unresolved; new entries are disabled")
            if (
                risk_reason_at_start is not None
                and refreshed_snapshot is not None
                and not self._account_has_exposure(refreshed_snapshot)
                and self.user_stream is not None
            ):
                self.user_stream.clear_entry_block(risk_reason_at_start)
                self.force_flatten_reason = None
            if (
                observation_error is None
                and self.user_stream is not None
                and observed_event_count is not None
                and self.user_stream.mark_reconciled(observed_event_count)
            ):
                self.user_stream_gap = False
            self.last_cycle_ms = cycle_ms
            if observation_error is not None:
                raise ValueError(
                    "Authenticated account refresh failed; new entries are disabled"
                ) from None
            if intention is None:
                return None
            # Recovery may have canceled orders or closed positions. Never size/admit
            # against the balance and order inventory captured before those writes.
            snapshot = await self._refresh_account(path)
            remaining_daily_budget(snapshot)
            if not self.feed.connected or self.feed.clock is None:
                raise ValueError("No connected exchange market feed and observed clock")
            if self.user_stream is None or self.user_stream_gap:
                raise ValueError("No reconciled authenticated user-data stream")
            self.user_stream.assert_entry_ready()
            if intention.portfolio_id is not None:
                return await self.admission.admit(
                    intention.plan,
                    intention.report_path,
                    exchange_clock=self.feed.clock,
                    readiness_ms=intention.readiness_ms,
                    expected_report_hash=intention.report_hash,
                    portfolio_id=intention.portfolio_id,
                    member_id=intention.member_id,
                )
            return await self.admission.admit(
                intention.plan,
                intention.report_path,
                exchange_clock=self.feed.clock,
                readiness_ms=intention.readiness_ms,
                expected_report_hash=intention.report_hash,
            )

    async def run(self, scan: Callable[[], Awaitable[QualifiedIntention | None]]) -> None:
        intentions: asyncio.Queue[QualifiedIntention] = asyncio.Queue(maxsize=1)

        async def scanning() -> None:
            while True:
                try:
                    intention = await scan()
                    self.last_scan_error_type = None
                    if intention is not None:
                        await intentions.put(intention)
                except Exception as exc:
                    self.last_scan_error_type = type(exc).__name__
                self.publish_health()
                await asyncio.sleep(1)

        async def cycles() -> None:
            while True:
                self.cycle_wakeup.clear()
                try:
                    try:
                        intention = intentions.get_nowait()
                    except asyncio.QueueEmpty:
                        intention = None
                    # Strategy REST reads never block the independent protective loop.
                    # cycle still reconciles/protects before admitting a queued intention.
                    await self.cycle(intention)
                    self.last_cycle_error_type = None
                except Exception as exc:
                    self.last_cycle_error_type = type(exc).__name__
                self.publish_health()
                try:
                    await asyncio.wait_for(self.cycle_wakeup.wait(), timeout=1)
                except TimeoutError:
                    pass

        async with asyncio.TaskGroup() as group:
            group.create_task(self.feed.run())
            if self.user_stream is not None:
                group.create_task(self.user_stream.run())
            group.create_task(cycles())
            group.create_task(scanning())
