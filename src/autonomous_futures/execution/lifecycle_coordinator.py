"""Connect durable trade ownership, actual fill recovery, and protective exchange I/O."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from autonomous_futures.execution.account_evidence import atomic_json, finite_decimal, read_account
from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.entry_risk import remaining_daily_budget
from autonomous_futures.execution.exit_invalidation import CausalExitReader
from autonomous_futures.execution.fill_recovery import summarize_fills
from autonomous_futures.execution.live_orders import LiveOrderBook
from autonomous_futures.execution.protective_executor import ProtectiveExecutor
from autonomous_futures.execution.protective_lifecycle import (
    TERMINAL,
    OrderEvidence,
    ProtectiveAction,
    Role,
    protective_actions,
)
from autonomous_futures.execution.trade_autopsy_evidence import (
    build_closed_trade_autopsy,
    summarize_autopsy_feedback,
)
from autonomous_futures.execution.trade_plan import ExitSlice, SymbolFilters, TradePlan
from autonomous_futures.execution.writer_lease import ExecutionLease


def restore_plan(body: dict[str, Any]) -> TradePlan:
    fields = dict(body)
    if fields["family"] not in {"MACRO_SCALPER", "ICT_TWINS"} or fields["side"] not in {
        "BUY",
        "SELL",
    }:
        raise ValueError("Invalid persisted trade identity")
    for name in ("entry", "quantity", "stop", "tp1"):
        fields[name] = finite_decimal(fields[name])
    fields["tp2"] = None if fields["tp2"] is None else finite_decimal(fields["tp2"])
    parts = []
    for part in fields["exits"]:
        if part["role"] not in {"STOP", "TP1", "TP2"}:
            raise ValueError("Invalid persisted exit role")
        parts.append(
            ExitSlice(part["role"], finite_decimal(part["quantity"]), finite_decimal(part["price"]))
        )
    fields["exits"] = tuple(parts)
    return TradePlan(**fields)


class LifecycleCoordinator:
    def __init__(
        self,
        gateway: BinanceFuturesGateway,
        directory: Path,
        *,
        lease: ExecutionLease,
        exit_reader: CausalExitReader | None = None,
    ) -> None:
        lease.assert_held()
        self.gateway, self.directory, self.lease = gateway, directory, lease
        self.exit_reader = exit_reader
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "owned-trades.json"
        self.autopsies_path = directory / "trade-autopsies.json"
        self.trades: dict[str, dict[str, Any]] = (
            json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        )
        self.protective = ProtectiveExecutor(gateway, directory, lease=lease)
        self.entries = LiveOrderBook(gateway, directory, lease=lease)

    def save(self) -> None:
        self.lease.assert_held()
        atomic_json(self.path, self.trades, durable=True)

    def _record_closed_autopsy(
        self,
        *,
        trade: dict[str, Any],
        plan: TradePlan,
        closed_ms: int,
        daily_breached: bool,
        external_risk_breach: bool,
    ) -> None:
        self.lease.assert_held()
        autopsy = build_closed_trade_autopsy(
            plan,
            trade,
            closed_ms=closed_ms,
            daily_breached=daily_breached,
            external_risk_breach=external_risk_breach,
        )
        trade["closed_ms"] = closed_ms
        trade["outcome_autopsy"] = autopsy
        closed_autopsies = [
            row["outcome_autopsy"]
            for row in self.trades.values()
            if isinstance(row.get("outcome_autopsy"), dict)
        ]
        atomic_json(
            self.autopsies_path,
            {
                "updated_ms": closed_ms,
                "summary": summarize_autopsy_feedback(closed_autopsies),
                "autopsies": closed_autopsies,
            },
            durable=True,
        )

    def prepare(self, plan: TradePlan, now_ms: int) -> str:
        """Persist complete ownership intent before either bracket or entry network I/O."""
        self.lease.assert_held()
        client_id = "afbot-" + hashlib.sha256(plan.signal_key.encode()).hexdigest()[:30]
        if plan.signal_key in self.trades:
            if self.trades[plan.signal_key]["plan"] != plan.to_dict():
                raise ValueError("Prepared trade identity collision")
            return client_id
        if any(
            not trade["closed"] and trade["plan"]["symbol"] == plan.symbol
            for trade in self.trades.values()
        ):
            raise ValueError("Another lifecycle already occupies this symbol")
        self.trades[plan.signal_key] = {
            "plan": plan.to_dict(),
            "entry_id": client_id,
            "created_ms": now_ms,
            "fills": {},
            "closed": False,
        }
        self.save()
        return client_id

    def register_entry(self, plan: TradePlan, client_id: str) -> None:
        expected = "afbot-" + hashlib.sha256(plan.signal_key.encode()).hexdigest()[:30]
        entry = self.entries.orders.get(client_id)
        if client_id != expected or entry is None or entry["signal_id"] != plan.signal_key:
            raise ValueError("Only this writer's durable entry intention may become owned exposure")
        if (
            entry["symbol"] != plan.symbol
            or entry["side"] != plan.side
            or finite_decimal(entry["price"]) != plan.entry
            or finite_decimal(entry["quantity"]) != plan.quantity
            or entry["reduce_only"]
        ):
            raise ValueError("Journal entry does not bind the trade plan")
        if plan.signal_key in self.trades:
            if self.trades[plan.signal_key]["plan"] != plan.to_dict():
                raise ValueError("Owned trade identity collision")
            return
        if any(
            not trade.get("closed", False) and trade["plan"]["symbol"] == plan.symbol
            for trade in self.trades.values()
        ):
            raise ValueError("Another owned lifecycle already occupies this symbol")
        self.trades[plan.signal_key] = {
            "plan": plan.to_dict(),
            "entry_id": client_id,
            "created_ms": entry["timestamp_ms"],
            "fills": {},
            "closed": False,
        }
        self.save()

    async def evidence(
        self,
        trade: dict[str, Any],
        client_id: str,
        role: Role,
        response: dict[str, Any],
        now_ms: int,
    ) -> OrderEvidence:
        plan = restore_plan(trade["plan"])
        side: Literal["BUY", "SELL"] = (
            plan.side if role == "ENTRY" else ("SELL" if plan.side == "BUY" else "BUY")
        )
        if (
            response.get("symbol") != plan.symbol
            or response.get("side") != side
            or response.get("clientOrderId") != client_id
        ):
            raise ValueError("Authenticated order does not match lifecycle ownership")
        executed = finite_decimal(response["executedQty"])
        existing = trade["fills"].get(client_id, [])
        known_quantity = sum((finite_decimal(row["qty"]) for row in existing), Decimal("0"))
        identifier = response.get("orderId", response.get("algoId"))
        if identifier is None:
            raise ValueError("Authenticated order has no exchange identifier")
        order_id = int(identifier)
        if executed < known_quantity:
            raise ValueError("Cumulative exchange fills moved backwards")
        if executed > known_quantity:
            incoming = await self.gateway.get_order_fills(
                plan.symbol, order_id, max(1, trade["created_ms"] - 1000), now_ms
            )
            by_id = {int(row["id"]): row for row in existing}
            for row in incoming:
                identity = int(row["id"])
                if identity in by_id and by_id[identity] != row:
                    raise ValueError("Authenticated fill changed after persistence")
                by_id[identity] = row
            existing = list(by_id.values())
            trade["fills"][client_id] = existing
        summary = summarize_fills(
            existing, symbol=plan.symbol, order_id=order_id, side=side, executed_quantity=executed
        )
        trade.setdefault("fill_summaries", {})[client_id] = {
            **json.loads(json.dumps(dataclasses.asdict(summary), default=str)),
            "source": "binance_authenticated_user_trades",
        }
        if role == "ENTRY" and summary.first_fill_ms is not None:
            trade["first_fill_ms"] = summary.first_fill_ms
        self.save()
        price = (
            finite_decimal(response["stopPrice"] if role == "STOP" else response["price"])
            if role != "FLATTEN"
            else None
        )
        return OrderEvidence(
            client_id,
            role,
            plan.symbol,
            side,
            finite_decimal(response["origQty"]),
            executed,
            str(response["status"]),
            response.get("reduceOnly") in (True, "true"),
            price,
        )

    async def advance(self, now_ms: int, *, external_risk_breach: bool = False) -> tuple[str, ...]:
        self.lease.assert_held()
        unresolved_entries = set(await self.entries.reconcile())
        await self.protective.reconcile()
        account = read_account(self.directory / "exchange-account.json", now_ms)
        try:
            remaining_daily_budget(account)
            daily_breached = False
        except ValueError:
            daily_breached = True  # Unknown daily allowance cannot justify holding unbounded risk.
        errors = []
        for key, trade in self.trades.items():
            if trade["closed"]:
                continue
            plan = restore_plan(trade["plan"])
            try:
                if trade["entry_id"] not in self.entries.orders:
                    pending_stops = [
                        record
                        for record in self.protective.records.values()
                        if record["request"]["plan_key"] == key
                        and record["request"]["operation"] == "PLACE"
                        and record["state"] not in TERMINAL
                    ]
                    position = next(
                        (row for row in account["positions"] if row["symbol"] == plan.symbol), None
                    )
                    if position is not None and finite_decimal(position["positionAmt"]):
                        raise ValueError(
                            "Untracked exposure appeared before this entry was submitted"
                        )
                    if daily_breached or now_ms >= plan.decision_ms + 300000:
                        for pending in pending_stops:
                            request = pending["request"]
                            await self.protective.execute(
                                plan,
                                ProtectiveAction(
                                    request["client_id"],
                                    "STOP",
                                    "CANCEL",
                                    "STOP_MARKET",
                                    cast(Literal["BUY", "SELL"], request["side"]),
                                    finite_decimal(request["quantity"]),
                                    finite_decimal(request["price"]),
                                ),
                            )
                    if not pending_stops:
                        trade["closed"] = True
                        self._record_closed_autopsy(
                            trade=trade,
                            plan=plan,
                            closed_ms=now_ms,
                            daily_breached=daily_breached,
                            external_risk_breach=external_risk_breach,
                        )
                        self.save()
                    continue
                entry_record = self.entries.orders[trade["entry_id"]]
                if trade["entry_id"] in unresolved_entries:
                    raise ValueError(
                        "Entry reconciliation is unresolved; "
                        "cached fills cannot prove current ownership"
                    )
                entry = await self.evidence(
                    trade, trade["entry_id"], "ENTRY", entry_record["exchange"], now_ms
                )
                exits = []
                for record_key, record in self.protective.records.items():
                    if not record_key.startswith("PLACE:") or record["request"]["plan_key"] != key:
                        continue
                    if "exchange" not in record or record["state"] == "UNKNOWN":
                        request = record["request"]
                        reported = finite_decimal(
                            record.get("exchange", {}).get("executedQty", "0")
                        )
                        exits.append(
                            OrderEvidence(
                                record_key.split(":", 1)[1],
                                cast(Role, request["role"]),
                                plan.symbol,
                                cast(Literal["BUY", "SELL"], request["side"]),
                                finite_decimal(request["quantity"]),
                                reported,
                                "UNKNOWN",
                                True,
                                None
                                if request["price"] is None
                                else finite_decimal(request["price"]),
                            )
                        )
                        continue
                    response = dict(record["exchange"])
                    response["status"] = record["state"]
                    exits.append(
                        await self.evidence(
                            trade,
                            record_key.split(":", 1)[1],
                            cast(Role, record["request"]["role"]),
                            response,
                            now_ms,
                        )
                    )
                position = next(
                    (row for row in account["positions"] if row["symbol"] == plan.symbol), None
                )
                quantity = (
                    finite_decimal(position["positionAmt"])
                    if position is not None
                    else Decimal("0")
                )
                filters = SymbolFilters.from_gateway(self.gateway.symbol_specs[plan.symbol])
                invalidated = False
                if quantity and plan.family == "ICT_TWINS" and self.exit_reader is not None:
                    try:
                        first_fill = trade.get("first_fill_ms")
                        if first_fill is None:
                            raise ValueError("No authenticated first fill for exit history")
                        observation = await asyncio.wait_for(
                            self.exit_reader.read(plan, now_ms, first_fill), timeout=2
                        )
                        invalidated = bool(
                            trade.get("strategy_invalidated", False)
                        ) or observation.invalidates(plan, first_fill)
                        trade["exit_observation"] = {
                            "source": "binance_closed_1m",
                            "boundary_ms": observation.boundary_ms,
                            "close": str(observation.close),
                            "invalidated": invalidated,
                        }
                    except Exception as exc:
                        # Missing exit evidence cannot justify continuing owned risk.
                        invalidated = True
                        trade["exit_observation"] = {
                            "source": "unavailable",
                            "error_type": type(exc).__name__,
                            "invalidated": True,
                        }
                    self.save()
                if invalidated:
                    trade["strategy_invalidated"] = True
                    self.save()
                actions = protective_actions(
                    plan,
                    entry,
                    tuple(exits),
                    quantity,
                    filters,
                    now_ms=now_ms,
                    first_fill_ms=trade.get("first_fill_ms"),
                    daily_breached=daily_breached,
                    entry_expiry_ms=plan.decision_ms + 300000,
                    strategy_invalidated=invalidated,
                    external_risk_breach=external_risk_breach,
                )
                for action in actions:
                    await self.protective.execute(plan, action)
                if entry.status in TERMINAL and quantity == 0 and not actions:
                    trade["closed"] = True
                    self._record_closed_autopsy(
                        trade=trade,
                        plan=plan,
                        closed_ms=now_ms,
                        daily_breached=daily_breached,
                        external_risk_breach=external_risk_breach,
                    )
                    self.save()
            except Exception as exc:
                # A failure for one owned symbol must not skip the other symbols'
                # protective work. Keep transport errors sanitized (signed URLs may
                # contain credentials); actual evidence errors remain reviewable.
                trade["recovery_error"] = (
                    str(exc) if isinstance(exc, (ValueError, KeyError)) else type(exc).__name__
                )
                self.save()
                errors.append(key)
        # Unknown protective commands must not disappear behind an empty trade loop
        # (for example, an orphaned command recovered after a crash). Keep entries
        # disabled until every persisted protective intention has exchange evidence.
        errors.extend(
            f"protective:{key}"
            for key, record in self.protective.records.items()
            if record.get("state") == "UNKNOWN"
        )
        return tuple(errors)
