"""Atomic, exchange-sourced account observations shared with the separate web process."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, cast

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway

SNAPSHOT_NAME = "exchange-account.json"
MAX_ACCOUNT_AGE_MS = 30_000
TRADING_INCOME_TYPES = frozenset(
    {"REALIZED_PNL", "COMMISSION", "COMMISSION_REBATE", "FUNDING_FEE", "INSURANCE_CLEAR"}
)
EXTERNAL_BASIS_INCOME_TYPES = frozenset({"TRANSFER"})


def atomic_json(path: Path, data: dict[str, Any], *, durable: bool = False) -> None:
    """Replace complete evidence; never expose a truncated JSON file to readers."""
    temp = path.with_suffix(f".{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8") as output:
        output.write(json.dumps(data, allow_nan=False))
        if durable:
            output.flush()
            os.fsync(output.fileno())
    temp.replace(path)
    if durable and hasattr(os, "O_DIRECTORY"):
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def finite_decimal(value: Any) -> Decimal:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Non-finite exchange value")
    return number


def exchange_bool(value: Any) -> bool:
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError("Missing or invalid authenticated exchange boolean")


class DailyEvidenceTracker(Protocol):
    def observe(self, snapshot: dict[str, Any], now_ms: int) -> dict[str, Any]: ...


def unique_income(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observed: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = f"{row['incomeType']}:{row['tranId']}"
        if identity in observed:
            previous = observed[identity]
            if (
                row["asset"] != previous["asset"]
                or int(row["time"]) != int(previous["time"])
                or finite_decimal(row["income"]) != finite_decimal(previous["income"])
            ):
                raise ValueError("Conflicting authenticated income transaction")
        else:
            finite_decimal(row["income"])
            observed[identity] = row
    return list(observed.values())


async def observe_account(
    gateway: BinanceFuturesGateway, path: Path, *, risk_tracker: DailyEvidenceTracker | None = None
) -> dict[str, Any]:
    """Publish only after all authenticated requests succeed; no offline evidence."""
    if gateway.offline_mode:
        raise ValueError("Offline account data is not exchange evidence")
    account = await gateway.get_account_balance()
    positions = await gateway.get_position_risk()
    open_orders = await gateway.get_open_orders()
    open_algo_orders = await gateway.get_open_algo_orders()
    configurations = await gateway.get_symbol_configuration()
    for key in (
        "totalWalletBalance",
        "availableBalance",
        "totalMarginBalance",
        "totalInitialMargin",
        "totalUnrealizedProfit",
    ):
        finite_decimal(account[key])
    if exchange_bool(account.get("multiAssetsMargin")):
        raise ValueError("USDT reconciliation requires single-asset mode")
    for item in positions:
        for key in ("positionAmt", "entryPrice", "markPrice", "unRealizedProfit"):
            finite_decimal(item[key])
    snapshot: dict[str, Any] = {
        "source": "binance_authenticated_rest",
        "timestamp_ms": int(time.time() * 1000),
        "testnet": gateway.testnet,
        "account": account,
        "positions": positions,
        "open_orders": open_orders,
        "open_algo_orders": open_algo_orders,
        "symbol_configuration": configurations,
    }
    ledger_path = path.with_name("exchange-ledger.json")
    now_ms = snapshot["timestamp_ms"]
    midnight_ms = int(
        datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000
    )
    daily = unique_income(await gateway.get_income_history(midnight_ms, now_ms))
    for row in daily:
        if row["asset"] != "USDT":
            raise ValueError("Non-USDT income requires separate asset accounting")
        if row["incomeType"] not in TRADING_INCOME_TYPES | EXTERNAL_BASIS_INCOME_TYPES:
            raise ValueError("Unclassified authenticated income type")
    external_flows = [
        {
            "incomeType": row["incomeType"],
            "asset": row["asset"],
            "time": int(row["time"]),
            "tranId": str(row["tranId"]),
            "income": str(finite_decimal(row["income"])),
        }
        for row in daily
        if row["incomeType"] in EXTERNAL_BASIS_INCOME_TYPES
    ]
    daily_net = sum(
        (
            finite_decimal(row["income"])
            for row in daily
            if row["incomeType"] in TRADING_INCOME_TYPES
        ),
        Decimal("0"),
    )
    upnl = finite_decimal(account["totalUnrealizedProfit"])
    snapshot["daily_external_flows"] = external_flows
    snapshot["daily_loss_usdt"] = str(max(Decimal("0"), -(daily_net + upnl)))
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        if ledger["testnet"] != gateway.testnet:
            raise ValueError("Ledger belongs to a different exchange environment")
        cursor = int(ledger["last_query_ms"])
        transactions = ledger["transactions"]
        basis_adjustments = ledger.setdefault("basis_adjustments", {})
        if not isinstance(transactions, dict) or not isinstance(basis_adjustments, dict):
            raise ValueError("Persisted exchange ledger has an invalid transaction map")
        rows = unique_income(
            await gateway.get_income_history(max(ledger["started_ms"], cursor - 60_000), now_ms)
        )
        for row in rows:
            if row["asset"] != "USDT":
                raise ValueError("Non-USDT income requires separate asset accounting")
            if int(row["time"]) <= ledger["started_ms"]:
                continue
            key = f"{row['incomeType']}:{row['tranId']}"
            if row["incomeType"] in TRADING_INCOME_TYPES:
                target = transactions
            elif row["incomeType"] in EXTERNAL_BASIS_INCOME_TYPES:
                target = basis_adjustments
            else:
                raise ValueError("Unclassified authenticated income type")
            if key in target and finite_decimal(target[key]) != finite_decimal(row["income"]):
                raise ValueError("Persisted authenticated income amount changed")
            target[key] = str(finite_decimal(row["income"]))
        # Late income remains detectable through drift; a mismatch never resets the baseline.
        ledger["last_query_ms"] = now_ms
    else:
        if (
            any(finite_decimal(p["positionAmt"]) for p in positions)
            or open_orders
            or open_algo_orders
        ):
            raise ValueError(
                "Initial ledger baseline requires a flat account with no pending orders"
            )
        ledger = {
            "started_ms": now_ms,
            "last_query_ms": now_ms,
            "starting_wallet": account["totalWalletBalance"],
            "testnet": gateway.testnet,
            "transactions": {},
            "basis_adjustments": {},
        }
    net = sum((finite_decimal(v) for v in ledger["transactions"].values()), Decimal("0"))
    net_external_flows = sum(
        (finite_decimal(v) for v in ledger.get("basis_adjustments", {}).values()), Decimal("0")
    )
    wallet = finite_decimal(account["totalWalletBalance"])
    wallet_drift = wallet - finite_decimal(ledger["starting_wallet"]) - net - net_external_flows
    equity_drift = finite_decimal(account["totalMarginBalance"]) - wallet - upnl
    snapshot["reconciliation"] = {
        "starting_equity": ledger["starting_wallet"],
        "net_realized_pnl": str(net),
        "net_external_flows": str(net_external_flows),
        "wallet_drift": str(wallet_drift),
        "equity_drift": str(equity_drift),
        "verified": abs(wallet_drift) < Decimal("1e-15") and abs(equity_drift) < Decimal("1e-15"),
    }
    if risk_tracker is None:
        snapshot["daily_risk"] = {
            "verified": False,
            "reason": "Daily equity reference is not configured",
        }
    elif snapshot["reconciliation"]["verified"]:
        try:
            snapshot["daily_risk"] = risk_tracker.observe(snapshot, now_ms)
            if snapshot["daily_risk"].get("verified") is True:
                snapshot["daily_loss_usdt"] = str(
                    finite_decimal(snapshot["daily_risk"]["loss_usdt"])
                )
        except ValueError as exc:
            snapshot["daily_risk"] = {"verified": False, "reason": str(exc)}
    else:
        snapshot["daily_risk"] = {"verified": False, "reason": "Account ledger is unreconciled"}
    atomic_json(ledger_path, ledger, durable=True)
    atomic_json(path, snapshot)
    return snapshot


def read_account(path: Path, now_ms: int | None = None) -> dict[str, Any]:
    snapshot = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    now = int(time.time() * 1000) if now_ms is None else now_ms
    age = now - int(snapshot["timestamp_ms"])
    if snapshot.get("source") != "binance_authenticated_rest" or not (
        0 <= age <= MAX_ACCOUNT_AGE_MS
    ):
        raise ValueError("Account evidence is stale or not exchange-sourced")
    if not isinstance(snapshot["positions"], list) or not isinstance(snapshot["open_orders"], list):
        raise ValueError("Incomplete account evidence")
    account = snapshot["account"]
    if exchange_bool(account.get("multiAssetsMargin")):
        raise ValueError("USDT reconciliation requires single-asset mode")
    wallet = finite_decimal(account["totalWalletBalance"])
    equity = finite_decimal(account["totalMarginBalance"])
    upnl = finite_decimal(account["totalUnrealizedProfit"])
    finite_decimal(account["totalInitialMargin"])
    finite_decimal(account["availableBalance"])
    for position in snapshot["positions"]:
        amount = finite_decimal(position["positionAmt"])
        mark = finite_decimal(position["markPrice"])
        finite_decimal(position["entryPrice"])
        finite_decimal(position["unRealizedProfit"])
        if amount and (mark <= 0 or not position["symbol"].endswith("USDT")):
            raise ValueError("Cannot reconcile an unvalued or non-USDT position")
    reconciliation = snapshot.get("reconciliation")
    if reconciliation and reconciliation.get("verified"):
        expected = (
            finite_decimal(reconciliation["starting_equity"])
            + finite_decimal(reconciliation["net_realized_pnl"])
            + finite_decimal(reconciliation.get("net_external_flows", "0"))
        )
        if abs(wallet - expected) >= Decimal("1e-15") or abs(equity - wallet - upnl) >= Decimal(
            "1e-15"
        ):
            raise ValueError("Declared reconciliation disagrees with observed balances")
    return snapshot
