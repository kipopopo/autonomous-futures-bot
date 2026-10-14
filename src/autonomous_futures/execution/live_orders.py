"""Durable exchange order lifecycle. Acknowledgements never count as fills."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from autonomous_futures.execution.account_evidence import (
    atomic_json,
    exchange_bool,
    finite_decimal,
    read_account,
)
from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway, quantize_step_size
from autonomous_futures.execution.entry_risk import remaining_daily_budget
from autonomous_futures.execution.writer_lease import ExecutionLease
from autonomous_futures.feed.exchange_clock import ExchangeClock

TERMINAL = {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}
_SHA256_CHARACTERS = frozenset("0123456789abcdef")


def _microstructure_record(
    *,
    spectral_radius: Decimal,
    event_timestamp_ms: int,
    beta_per_second: Decimal,
    calibration_sha256: str,
    arrivals_sha256: str,
    fit_timestamp_ms: int,
    generation: int,
    now_ms: int,
    exchange_clock: ExchangeClock | None,
) -> dict[str, Any]:
    if (
        not spectral_radius.is_finite()
        or not 0 <= spectral_radius < 1
        or not beta_per_second.is_finite()
        or beta_per_second <= 0
        or type(event_timestamp_ms) is not int
        or event_timestamp_ms <= 0
        or type(fit_timestamp_ms) is not int
        or fit_timestamp_ms <= 0
        or type(generation) is not int
        or generation < 0
        or any(
            len(digest) != 64 or any(character not in _SHA256_CHARACTERS for character in digest)
            for digest in (calibration_sha256, arrivals_sha256)
        )
    ):
        raise ValueError("Opening order requires complete measured microstructure provenance")
    if exchange_clock is not None:
        aligned_now = exchange_clock.aligned_ms(now_ms)
        uncertainty = exchange_clock.uncertainty_ms
        event_fresh = exchange_clock.event_fresh(event_timestamp_ms, now_ms)
    else:
        aligned_now = now_ms
        uncertainty = 0
        event_fresh = 0 <= now_ms - event_timestamp_ms <= 500
    fit_age = aligned_now - fit_timestamp_ms
    if not event_fresh or not -uncertainty <= fit_age <= 20_000 - uncertainty:
        raise ValueError("Opening order microstructure evidence is stale")
    return {
        "spectral_radius": str(spectral_radius),
        "event_timestamp_ms": event_timestamp_ms,
        "beta_per_second": str(beta_per_second),
        "calibration_sha256": calibration_sha256,
        "arrivals_sha256": arrivals_sha256,
        "fit_timestamp_ms": fit_timestamp_ms,
        "generation": generation,
    }


class LiveOrderBook:
    """Persist intentions before network I/O and reconcile uncertain submissions by ID."""

    def __init__(
        self,
        gateway: BinanceFuturesGateway,
        directory: Path,
        *,
        lease: ExecutionLease | None = None,
    ) -> None:
        self.lease = lease
        if lease is not None:
            lease.assert_held()
        self.gateway = gateway
        self.path = directory / "exchange-orders.json"
        self.account_path = directory / "exchange-account.json"
        self.orders: dict[str, dict[str, Any]] = (
            json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        )
        self.lock = lease.io_lock if lease is not None else asyncio.Lock()

    def save(self) -> None:
        if self.lease is None:
            return  # Read-only reconciliation must not overwrite the writer journal.
        self.lease.assert_held()
        atomic_json(self.path, self.orders, durable=True)

    @staticmethod
    def apply_response(order: dict[str, Any], cid: str, response: dict[str, Any]) -> None:
        reduced = response.get("reduceOnly")
        if (
            response.get("symbol") != order["symbol"]
            or response.get("side") != order["side"]
            or response.get("clientOrderId") != cid
            or reduced not in (True, False, "true", "false")
            or (reduced in (True, "true")) != order["reduce_only"]
            or finite_decimal(response["origQty"]) != finite_decimal(order["quantity"])
            or finite_decimal(response["price"]) != finite_decimal(order["price"])
            or int(response["orderId"]) <= 0
            or (
                "orderId" in order.get("exchange", {})
                and int(response["orderId"]) != int(order["exchange"]["orderId"])
            )
        ):
            raise ValueError("Authenticated entry response does not match durable intention")
        filled = finite_decimal(response["executedQty"])
        prior = finite_decimal(order.get("exchange", {}).get("executedQty", "0"))
        if not prior <= filled <= finite_decimal(order["quantity"]):
            raise ValueError("Authenticated entry cumulative fills are invalid")
        status = str(response["status"])
        if status not in TERMINAL | {"NEW", "PARTIALLY_FILLED"}:
            raise ValueError("Authenticated entry status is unknown")
        order["observed_ms"] = int(time.time() * 1000)
        order["exchange"] = response
        order["state"] = status

    async def reconcile(self) -> tuple[str, ...]:
        """A transport timeout is unknown, not rejected; do not blindly resubmit."""
        unresolved = []
        async with self.lock:
            for cid, order in self.orders.items():
                if order.get("exchange", {}).get("status") in TERMINAL:
                    continue
                try:
                    response = await self.gateway.get_order(
                        symbol=order["symbol"], client_order_id=cid
                    )
                    self.apply_response(order, cid, response)
                except Exception as exc:
                    order["state"] = "UNKNOWN"
                    order["error_type"] = type(exc).__name__
                    self.save()
                    unresolved.append(cid)
                    continue
                self.save()
        return tuple(unresolved)

    async def submit(
        self,
        *,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        signal_id: str,
        qualified: bool,
        spectral_radius: Decimal,
        event_timestamp_ms: int,
        microstructure_beta_per_second: Decimal | None = None,
        microstructure_calibration_sha256: str | None = None,
        microstructure_arrivals_sha256: str | None = None,
        microstructure_fit_timestamp_ms: int | None = None,
        microstructure_generation: int | None = None,
        reduce_only: bool = False,
        leverage: int = 1,
        exchange_clock: ExchangeClock | None = None,
        entry_guard: Callable[[int], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        """Place a maker order only with fresh, reconciled account and measured risk."""
        async with self.lock:
            if self.lease is None:
                raise ValueError("Opening orders require a held execution writer lease")
            self.lease.assert_held()
            if self.gateway.offline_mode:
                raise ValueError("Live lifecycle requires an exchange gateway")
            if not reduce_only and entry_guard is None:
                raise ValueError("Opening orders require a final genuine admission guard")
            now = int(time.time() * 1000)
            microstructure = None
            if not reduce_only:
                if (
                    not qualified
                    or not spectral_radius.is_finite()
                    or not (0 <= spectral_radius < 1)
                ):
                    raise ValueError("Missing qualification or unsafe microstructure")
                if (
                    microstructure_beta_per_second is None
                    or microstructure_calibration_sha256 is None
                    or microstructure_arrivals_sha256 is None
                    or microstructure_fit_timestamp_ms is None
                    or microstructure_generation is None
                ):
                    raise ValueError("Opening order lacks calibrated Hawkes fit provenance")
                microstructure = _microstructure_record(
                    spectral_radius=spectral_radius,
                    event_timestamp_ms=event_timestamp_ms,
                    beta_per_second=microstructure_beta_per_second,
                    calibration_sha256=microstructure_calibration_sha256,
                    arrivals_sha256=microstructure_arrivals_sha256,
                    fit_timestamp_ms=microstructure_fit_timestamp_ms,
                    generation=microstructure_generation,
                    now_ms=now,
                    exchange_clock=exchange_clock,
                )
            account = read_account(self.account_path, now)
            if not reduce_only and account.get("reconciliation", {}).get("verified") is not True:
                raise ValueError("Account is unreconciled")
            spec = self.gateway.symbol_specs.get(symbol)
            if spec is None:
                raise ValueError("Exchange filters unavailable")
            qty = quantize_step_size(quantity, spec["step_size"])
            if (
                not price.is_finite()
                or not qty.is_finite()
                or price <= 0
                or qty <= 0
                or qty < spec["min_qty"]
                or price % spec["tick_size"] != 0
            ):
                raise ValueError("Order fails exchange filters")
            notional = price * qty
            if not reduce_only and notional < spec["min_notional"]:
                raise ValueError("Entry is below the exchange minimum notional")
            cid = "afbot-" + hashlib.sha256(signal_id.encode()).hexdigest()[:30]
            if cid in self.orders:
                previous = self.orders[cid]
                if (
                    previous["symbol"] != symbol
                    or previous["side"] != side
                    or finite_decimal(previous["price"]) != price
                    or finite_decimal(previous["quantity"]) != qty
                    or previous["reduce_only"] != reduce_only
                    or int(previous.get("leverage", 1)) != leverage
                ):
                    raise ValueError("Signal identity already binds a different order intention")
                return previous
            positions = account["positions"]
            if any(p.get("positionSide", "BOTH") != "BOTH" for p in positions):
                raise ValueError("Hedge-mode execution requires a separate position-side contract")
            pending = Decimal("0")
            observed_ids = set()
            for order in account["open_orders"]:
                observed_ids.add(str(order["clientOrderId"]))
                if not exchange_bool(order.get("reduceOnly")):
                    if finite_decimal(order["price"]) <= 0:
                        raise ValueError("Cannot value a pending market order")
                    remaining = finite_decimal(order["origQty"]) - finite_decimal(
                        order["executedQty"]
                    )
                    # availableBalance already deducts exchange-observed order margin.
                    if remaining < 0:
                        raise ValueError("Invalid remaining exchange order quantity")
            for existing_id, order in self.orders.items():
                if (
                    existing_id not in observed_ids
                    and (
                        order["state"] not in TERMINAL
                        or order.get("observed_ms", order["timestamp_ms"])
                        >= account["timestamp_ms"]
                    )
                    and not order["reduce_only"]
                ):
                    pending += (
                        finite_decimal(order["quantity"])
                        * finite_decimal(order["price"])
                        / finite_decimal(order.get("leverage", "1"))
                    )
            if not reduce_only:
                remaining_daily_budget(account)
                if isinstance(leverage, bool) or not isinstance(leverage, int) or leverage < 1:
                    raise ValueError("Invalid requested leverage")
                configuration = next(
                    (
                        item
                        for item in account.get("symbol_configuration", [])
                        if item["symbol"] == symbol
                    ),
                    None,
                )
                if configuration is None or int(configuration["leverage"]) != leverage:
                    raise ValueError(
                        "Requested leverage is not confirmed by exchange configuration"
                    )
                equity = finite_decimal(account["account"]["totalMarginBalance"])
                available = finite_decimal(account["account"]["availableBalance"])
                if equity <= 0 or available < pending + notional / leverage:
                    raise ValueError("Insufficient exchange available margin")
            else:
                position = next((p for p in positions if p["symbol"] == symbol), None)
                amount = finite_decimal(position["positionAmt"]) if position else Decimal("0")
                if qty > abs(amount) or amount == 0 or (amount > 0) != (side == "SELL"):
                    raise ValueError("Exit does not reduce the observed position")
            if not reduce_only:
                assert entry_guard is not None
                final_observation = entry_guard(int(time.time() * 1000))
                if final_observation is not None:
                    try:
                        microstructure = _microstructure_record(
                            spectral_radius=finite_decimal(final_observation["spectral_radius"]),
                            event_timestamp_ms=final_observation["event_timestamp_ms"],
                            beta_per_second=finite_decimal(final_observation["beta_per_second"]),
                            calibration_sha256=final_observation["calibration_sha256"],
                            arrivals_sha256=final_observation["arrivals_sha256"],
                            fit_timestamp_ms=final_observation["fit_timestamp_ms"],
                            generation=final_observation["generation"],
                            now_ms=int(time.time() * 1000),
                            exchange_clock=exchange_clock,
                        )
                    except (KeyError, TypeError) as exc:
                        raise ValueError(
                            "Final admission omitted microstructure provenance"
                        ) from exc
                else:
                    assert microstructure is not None
                    microstructure = _microstructure_record(
                        spectral_radius=finite_decimal(microstructure["spectral_radius"]),
                        event_timestamp_ms=microstructure["event_timestamp_ms"],
                        beta_per_second=finite_decimal(microstructure["beta_per_second"]),
                        calibration_sha256=microstructure["calibration_sha256"],
                        arrivals_sha256=microstructure["arrivals_sha256"],
                        fit_timestamp_ms=microstructure["fit_timestamp_ms"],
                        generation=microstructure["generation"],
                        now_ms=int(time.time() * 1000),
                        exchange_clock=exchange_clock,
                    )
            order = {
                "symbol": symbol,
                "side": side,
                "price": str(price),
                "quantity": str(qty),
                "reduce_only": reduce_only,
                "leverage": leverage,
                "state": "SUBMITTING",
                "signal_id": signal_id,
                "timestamp_ms": now,
            }
            if microstructure is not None:
                order["microstructure"] = microstructure
            self.orders[cid] = order
            self.save()
            try:
                response = await self.gateway.create_order(
                    symbol=symbol,
                    side=side,
                    order_type="LIMIT",
                    quantity=qty,
                    price=price,
                    client_order_id=cid,
                    time_in_force="GTX",
                    reduce_only=reduce_only,
                )
                self.apply_response(order, cid, response)
            except Exception:
                order["state"] = "UNKNOWN"
                self.save()
                raise
            self.save()
            return order
