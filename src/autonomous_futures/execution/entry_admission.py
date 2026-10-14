"""Connect verified qualification, real microstructure, capital and prearmed protection."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from autonomous_futures.execution.account_evidence import finite_decimal, read_account
from autonomous_futures.execution.commission_headroom import (
    observe_commissions,
    pending_openings,
    verify_margin_with_fees,
)
from autonomous_futures.execution.entry_risk import remaining_daily_budget
from autonomous_futures.execution.lifecycle_coordinator import LifecycleCoordinator
from autonomous_futures.execution.live_orders import TERMINAL
from autonomous_futures.execution.protective_lifecycle import (
    OrderEvidence,
    entry_is_protected,
    prearm_actions,
)
from autonomous_futures.execution.qualification_domain import (
    verify_execution_domain,
    verify_plan_risk,
)
from autonomous_futures.execution.qualification_receipts import (
    verify_runtime_portfolio_report,
    verify_runtime_report,
)
from autonomous_futures.execution.single_writer_guard import LegacyWriterHandoffGuard
from autonomous_futures.execution.trade_plan import SymbolFilters, TradePlan
from autonomous_futures.feed.exchange_clock import ExchangeClock
from autonomous_futures.feed.runtime_microstructure import RuntimeMicrostructure


def validate_intention_time(
    plan: TradePlan,
    exchange_ms: int,
    *,
    readiness_ms: int | None = None,
    maximum_plan_age_ms: int | None = None,
) -> None:
    maximum_age = (
        (60_000 if plan.family == "ICT_TWINS" else 300_000)
        if maximum_plan_age_ms is None
        else maximum_plan_age_ms
    )
    if type(maximum_age) is not int or maximum_age <= 0:
        raise ValueError("Qualified plan has an invalid causal age limit")
    if not 0 <= exchange_ms - plan.decision_ms < maximum_age:
        raise ValueError("Strategy intention is stale or precedes its causal decision")
    if readiness_ms is not None and (
        readiness_ms <= plan.decision_ms or not 0 <= exchange_ms - readiness_ms < 60_000
    ):
        raise ValueError("Staged strategy intention is stale or precedes its causal readiness")


class EntryAdmission:
    def __init__(
        self,
        coordinator: LifecycleCoordinator,
        microstructure: RuntimeMicrostructure,
        *,
        repo: Path,
        single_writer_guard: LegacyWriterHandoffGuard,
        user_stream_guard: Callable[[], None],
    ) -> None:
        self.coordinator, self.microstructure = coordinator, microstructure
        self.repo, self.single_writer_guard = repo, single_writer_guard
        self.user_stream_guard = user_stream_guard

    async def admit(
        self,
        plan: TradePlan,
        report_path: Path,
        *,
        exchange_clock: ExchangeClock,
        readiness_ms: int | None = None,
        expected_report_hash: str | None = None,
        portfolio_id: str | None = None,
        member_id: str | None = None,
    ) -> dict[str, Any]:
        self.coordinator.lease.assert_held()
        self.user_stream_guard()
        local_ms = int(time.time() * 1000)
        validate_intention_time(
            plan,
            exchange_clock.aligned_ms(local_ms),
            readiness_ms=readiness_ms,
            maximum_plan_age_ms=300_000 if readiness_ms is not None else None,
        )
        maximum_plan_age_ms: int | None = None
        if portfolio_id is not None:
            portfolio_receipt = await asyncio.to_thread(
                verify_runtime_portfolio_report,
                report_path,
                repo=self.repo,
                portfolio_id=portfolio_id,
            )
            if expected_report_hash is not None and (
                len(expected_report_hash) != 64
                or any(character not in "0123456789abcdef" for character in expected_report_hash)
                or portfolio_receipt.report_hash != expected_report_hash
            ):
                raise ValueError("Strategy intention report differs from its verified source pin")
            if (
                plan.family != portfolio_receipt.family
                or plan.symbol not in portfolio_receipt.symbols
            ):
                raise ValueError("Portfolio qualification does not authorize this family or symbol")
            valid_members = {
                str(m["member_id"])
                for m in portfolio_receipt.members
                if str(m["symbol"]) == plan.symbol
            }
            if member_id is None or member_id not in valid_members:
                raise ValueError("Portfolio qualification does not authorize this member_id")
            if readiness_ms is not None:
                raise ValueError("Staged entry readiness is not authorized by this qualification")
            verified_policy = portfolio_receipt.policy
            verified_domain = portfolio_receipt.execution_domain
        else:
            receipt = await asyncio.to_thread(
                verify_runtime_report,
                report_path,
                repo=self.repo,
                family=plan.family,
                symbol=plan.symbol,
            )
            if expected_report_hash is not None and (
                len(expected_report_hash) != 64
                or any(character not in "0123456789abcdef" for character in expected_report_hash)
                or receipt.report_hash != expected_report_hash
            ):
                raise ValueError("Strategy intention report differs from its verified source pin")
            entry_mode = receipt.configuration.get("entry_mode", "limit_touch")
            if plan.family == "ICT_TWINS" and entry_mode not in {
                "limit_touch",
                "reclaim_retest",
            }:
                raise ValueError("ICT qualification uses an unsupported live entry mode")
            if plan.family == "ICT_TWINS" and entry_mode == "reclaim_retest":
                if readiness_ms is None:
                    raise ValueError("ICT reclaim-retest requires a completed causal reclaim stage")
                try:
                    entry_ttl = finite_decimal(receipt.policy["entry_ttl_ms"])
                except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
                    raise ValueError("ICT reclaim report has no valid entry expiry policy") from exc
                if entry_ttl != entry_ttl.to_integral_value():
                    raise ValueError("ICT reclaim report entry expiry must use whole milliseconds")
                maximum_plan_age_ms = int(entry_ttl)
                if maximum_plan_age_ms != 300_000:
                    raise ValueError("ICT entry expiry differs from the protective runtime policy")
            elif readiness_ms is not None:
                raise ValueError("Staged entry readiness is not authorized by this qualification")
            verified_policy = receipt.policy
            verified_domain = receipt.execution_domain
        if await self.coordinator.gateway.get_position_mode():
            raise ValueError("Qualified runtime requires one-way exchange position mode")
        local_ms = int(time.time() * 1000)
        validate_intention_time(
            plan,
            exchange_clock.aligned_ms(local_ms),
            readiness_ms=readiness_ms,
            maximum_plan_age_ms=maximum_plan_age_ms,
        )
        if finite_decimal(verified_policy["daily_loss_pct"]) != Decimal("5"):
            raise ValueError("Qualification uses a different daily capital policy")
        account = read_account(self.coordinator.directory / "exchange-account.json", local_ms)
        remaining_daily_budget(account)
        verify_execution_domain(verified_domain, account, leverage=plan.leverage)
        if any(
            row["symbol"] == plan.symbol and finite_decimal(row["positionAmt"])
            for row in account["positions"]
        ):
            raise ValueError("Entry symbol is not flat")
        if any(row["symbol"] == plan.symbol for row in account["open_orders"]):
            raise ValueError("Entry symbol has an existing exchange order")
        if await self.coordinator.gateway.get_open_algo_orders(plan.symbol):
            raise ValueError("Entry symbol has an existing conditional exchange order")
        await asyncio.to_thread(self.single_writer_guard.assert_legacy_inactive)
        fee_symbols = (plan.symbol,) + tuple(
            row[0] for row in pending_openings(account, self.coordinator.entries.orders)
        )
        commissions = await observe_commissions(self.coordinator.gateway, fee_symbols)
        local_ms = int(time.time() * 1000)
        micro = self.microstructure.evidence(
            plan.symbol,
            exchange_clock.aligned_ms(local_ms),
            uncertainty_ms=exchange_clock.uncertainty_ms,
        )
        if not all(
            exchange_clock.event_fresh(timestamp, local_ms)
            for timestamp in (micro.event_timestamp_ms, micro.quote_timestamp_ms)
        ):
            raise ValueError("Market evidence exceeds the exchange clock uncertainty budget")
        if (plan.side == "BUY" and plan.entry >= micro.best_ask) or (
            plan.side == "SELL" and plan.entry <= micro.best_bid
        ):
            raise ValueError("Strategy entry would cross the measured maker book")
        filters = SymbolFilters.from_gateway(self.coordinator.gateway.symbol_specs[plan.symbol])
        entry_id = self.coordinator.prepare(plan, local_ms)
        protection = []
        for action in prearm_actions(plan, filters):
            await self.coordinator.protective.execute(plan, action)
            response = await self.coordinator.gateway.get_conditional_order(
                plan.symbol, action.client_id
            )
            protection.append(
                OrderEvidence(
                    action.client_id,
                    "STOP",
                    plan.symbol,
                    cast(Literal["BUY", "SELL"], response["side"]),
                    finite_decimal(response["origQty"]),
                    finite_decimal(response["executedQty"]),
                    str(response["status"]),
                    response.get("reduceOnly") in (True, "true"),
                    finite_decimal(response["stopPrice"]),
                )
            )
        if not entry_is_protected(plan, tuple(protection)):
            raise ValueError("Exchange has not confirmed full reduce-only prearmed protection")
        # Revalidate the current feed generation after bracket I/O. Old snapshots cannot
        # survive a disconnect or gap and grant entry authority.
        local_ms = int(time.time() * 1000)
        current = self.microstructure.evidence(
            plan.symbol,
            exchange_clock.aligned_ms(local_ms),
            uncertainty_ms=exchange_clock.uncertainty_ms,
        )
        if not all(
            exchange_clock.event_fresh(timestamp, local_ms)
            for timestamp in (current.event_timestamp_ms, current.quote_timestamp_ms)
        ):
            raise ValueError("Market evidence became stale during protection setup")
        if current.generation != micro.generation:
            raise ValueError("Market feed generation changed during protection setup")
        if (plan.side == "BUY" and plan.entry >= current.best_ask) or (
            plan.side == "SELL" and plan.entry <= current.best_bid
        ):
            raise ValueError("Maker book moved across the entry during protection setup")

        def entry_guard(now_ms: int) -> dict[str, Any]:
            self.user_stream_guard()
            self.single_writer_guard.assert_legacy_inactive()
            fresh_account = read_account(self.coordinator.entries.account_path, now_ms)
            pending_symbols = tuple(
                order["symbol"]
                for order in self.coordinator.entries.orders.values()
                if not order["reduce_only"]
                and (
                    order["state"] not in TERMINAL
                    or order.get("observed_ms", order["timestamp_ms"])
                    >= fresh_account["timestamp_ms"]
                )
            )
            verify_execution_domain(
                verified_domain,
                fresh_account,
                leverage=plan.leverage,
                pending_symbols=pending_symbols,
            )
            verify_plan_risk(plan, fresh_account)
            verify_margin_with_fees(
                plan, fresh_account, self.coordinator.entries.orders, commissions, now_ms
            )
            aligned = exchange_clock.aligned_ms(now_ms)
            validate_intention_time(
                plan,
                aligned,
                readiness_ms=readiness_ms,
                maximum_plan_age_ms=maximum_plan_age_ms,
            )
            latest = self.microstructure.evidence(
                plan.symbol, aligned, uncertainty_ms=exchange_clock.uncertainty_ms
            )
            if latest.generation != current.generation:
                raise ValueError("Feed changed while waiting for the execution writer lock")
            if (
                latest.beta_per_second != current.beta_per_second
                or latest.calibration_sha256 != current.calibration_sha256
            ):
                raise ValueError("Hawkes runtime calibration changed during entry admission")
            if not all(
                exchange_clock.event_fresh(timestamp, now_ms)
                for timestamp in (latest.event_timestamp_ms, latest.quote_timestamp_ms)
            ):
                raise ValueError("Market evidence expired before entry submission")
            if (plan.side == "BUY" and plan.entry >= latest.best_ask) or (
                plan.side == "SELL" and plan.entry <= latest.best_bid
            ):
                raise ValueError("Entry would cross the current maker book")
            return {
                "spectral_radius": latest.spectral_radius,
                "event_timestamp_ms": latest.event_timestamp_ms,
                "beta_per_second": latest.beta_per_second,
                "calibration_sha256": latest.calibration_sha256,
                "arrivals_sha256": latest.arrivals_sha256,
                "fit_timestamp_ms": latest.fit_timestamp_ms,
                "generation": latest.generation,
            }

        result = await self.coordinator.entries.submit(
            symbol=plan.symbol,
            side=plan.side,
            price=plan.entry,
            quantity=plan.quantity,
            signal_id=plan.signal_key,
            qualified=True,
            spectral_radius=current.spectral_radius,
            event_timestamp_ms=current.event_timestamp_ms,
            microstructure_beta_per_second=current.beta_per_second,
            microstructure_calibration_sha256=current.calibration_sha256,
            microstructure_arrivals_sha256=current.arrivals_sha256,
            microstructure_fit_timestamp_ms=current.fit_timestamp_ms,
            microstructure_generation=current.generation,
            leverage=plan.leverage,
            exchange_clock=exchange_clock,
            entry_guard=entry_guard,
        )
        self.coordinator.register_entry(plan, entry_id)
        return result
