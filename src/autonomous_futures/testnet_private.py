"""Offline private-read contracts for future USDⓈ-M account reconciliation."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import Field, field_validator

from .domain.contracts import DomainModel, StrictNonNegativeDecimal
from .testnet import TESTNET_REST_BASE_URL, sign_testnet_query


class TestnetPrivateRequest(DomainModel):
    method: Literal["GET"]
    url: str
    headers: dict[str, str]
    signed_query: str


class TestnetAccountAsset(DomainModel):
    asset: str = Field(min_length=1)
    wallet_balance: StrictNonNegativeDecimal
    available_balance: StrictNonNegativeDecimal


class TestnetAccountPosition(DomainModel):
    symbol: str = Field(min_length=1)
    position_amt: Decimal
    entry_price: Decimal
    mark_price: Decimal
    position_side: Literal["BOTH", "LONG", "SHORT"]

    @field_validator("position_amt", "entry_price", "mark_price")
    @classmethod
    def values_are_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("testnet account position values must be finite")
        return value


class TestnetAccountSnapshot(DomainModel):
    total_wallet_balance: StrictNonNegativeDecimal
    available_balance: StrictNonNegativeDecimal
    assets: tuple[TestnetAccountAsset, ...]
    positions: tuple[TestnetAccountPosition, ...]


class TestnetPositionExpectation(DomainModel):
    symbol: str = Field(min_length=1)
    position_side: Literal["BOTH", "LONG", "SHORT"]
    position_amt: Decimal

    @field_validator("position_amt")
    @classmethod
    def expected_amount_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("expected position amount must be finite")
        return value


class TestnetAccountReconciliation(DomainModel):
    status: Literal["reconciled", "drift"]
    missing_symbols: tuple[str, ...] = ()
    unexpected_symbols: tuple[str, ...] = ()
    mismatched_symbols: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)
    live_enabled: Literal[False] = False


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid account {field_name}") from exc
    if not parsed.is_finite():
        raise ValueError(f"invalid account {field_name}")
    return parsed


def build_testnet_account_request(
    *,
    api_key: str,
    secret: str,
    timestamp_ms: int,
    recv_window: int = 5000,
    base_url: str = TESTNET_REST_BASE_URL,
) -> TestnetPrivateRequest:
    if not api_key:
        raise ValueError("API key must be explicit and non-empty")
    if base_url != TESTNET_REST_BASE_URL:
        raise ValueError("testnet base URL must be the official USD-M demo host")
    if not isinstance(timestamp_ms, int) or isinstance(timestamp_ms, bool) or timestamp_ms <= 0:
        raise ValueError("timestamp_ms must be a positive integer")
    if (
        not isinstance(recv_window, int)
        or isinstance(recv_window, bool)
        or not 0 < recv_window <= 60000
    ):
        raise ValueError("recv_window must be between 1 and 60000")
    signed_query = sign_testnet_query(
        {
            "recvWindow": str(recv_window),
            "timestamp": str(timestamp_ms),
        },
        secret=secret,
    )
    return TestnetPrivateRequest(
        method="GET",
        url=f"{base_url}/fapi/v3/account",
        headers={"Accept": "application/json", "X-MBX-APIKEY": api_key},
        signed_query=signed_query,
    )


def parse_testnet_account_snapshot(body: Mapping[str, object]) -> TestnetAccountSnapshot:
    try:
        raw_assets = body["assets"]
        raw_positions = body["positions"]
        if not isinstance(raw_assets, list) or not isinstance(raw_positions, list):
            raise ValueError("account arrays malformed")
        assets = tuple(
            TestnetAccountAsset(
                asset=row["asset"],
                wallet_balance=_decimal(row["walletBalance"], "wallet balance"),
                available_balance=_decimal(row["availableBalance"], "available balance"),
            )
            for row in raw_assets
            if isinstance(row, Mapping)
        )
        positions = tuple(
            TestnetAccountPosition(
                symbol=row["symbol"],
                position_amt=_decimal(row["positionAmt"], "position amount"),
                entry_price=_decimal(row["entryPrice"], "entry price"),
                mark_price=_decimal(row["markPrice"], "mark price"),
                position_side=row["positionSide"],
            )
            for row in raw_positions
            if isinstance(row, Mapping)
        )
        if len(assets) != len(raw_assets) or len(positions) != len(raw_positions):
            raise ValueError("account rows malformed")
        return TestnetAccountSnapshot(
            total_wallet_balance=_decimal(body["totalWalletBalance"], "total wallet balance"),
            available_balance=_decimal(body["availableBalance"], "available balance"),
            assets=assets,
            positions=positions,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed testnet account response") from exc


def reconcile_testnet_account(
    snapshot: TestnetAccountSnapshot,
    expected_positions: tuple[TestnetPositionExpectation, ...],
) -> TestnetAccountReconciliation:
    expected = {
        (position.symbol, position.position_side): position.position_amt
        for position in expected_positions
        if position.position_amt != 0
    }
    remote = {
        (position.symbol, position.position_side): position.position_amt
        for position in snapshot.positions
        if position.position_amt != 0
    }
    missing_keys = sorted(set(expected) - set(remote))
    unexpected_keys = sorted(set(remote) - set(expected))
    mismatched_keys = sorted(
        key for key in set(expected) & set(remote) if expected[key] != remote[key]
    )
    if missing_keys or unexpected_keys or mismatched_keys:
        return TestnetAccountReconciliation(
            status="drift",
            missing_symbols=tuple(sorted({key[0] for key in missing_keys})),
            unexpected_symbols=tuple(sorted({key[0] for key in unexpected_keys})),
            mismatched_symbols=tuple(sorted({key[0] for key in mismatched_keys})),
            reason_codes=("testnet_account_position_drift",),
        )
    return TestnetAccountReconciliation(
        status="reconciled",
        reason_codes=("testnet_account_reconciled",),
    )
