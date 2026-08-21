"""Production read-only account request and typed reconciliation."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from decimal import Decimal
from typing import Literal

from pydantic import Field

from .domain.contracts import DomainModel
from .live_adapter import _sign_query
from .live_boundary import LIVE_REST_BASE_URL, validate_live_rest_url
from .testnet_private import TestnetAccountSnapshot, parse_testnet_account_snapshot


class LiveAccountRequest(DomainModel):
    method: Literal["GET"]
    url: str
    headers: dict[str, str]
    signed_query: str
    read_only: Literal[True] = True
    order_capability: Literal[False] = False


class LivePositionExpectation(DomainModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    position_side: Literal["BOTH", "LONG", "SHORT"] = "BOTH"
    position_amt: Decimal = Decimal("0")


class LiveAccountReconciliation(DomainModel):
    status: Literal["reconciled", "drift"]
    missing_symbols: tuple[str, ...] = ()
    unexpected_symbols: tuple[str, ...] = ()
    mismatched_symbols: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)
    live_enabled: Literal[False] = False
    order_capability: Literal[False] = False


def build_live_account_request(
    *,
    api_key: str,
    secret: str,
    timestamp_ms: int,
    recv_window: int = 5000,
    base_url: str = LIVE_REST_BASE_URL,
) -> LiveAccountRequest:
    if not api_key:
        raise ValueError("live API key must be explicit and non-empty")
    if not isinstance(timestamp_ms, int) or isinstance(timestamp_ms, bool) or timestamp_ms <= 0:
        raise ValueError("timestamp_ms must be a positive integer")
    if (
        not isinstance(recv_window, int)
        or isinstance(recv_window, bool)
        or not 0 < recv_window <= 60000
    ):
        raise ValueError("recv_window must be between 1 and 60000")
    endpoint = validate_live_rest_url(f"{base_url.rstrip('/')}/fapi/v3/account")
    signed_query = _sign_query(
        {"recvWindow": str(recv_window), "timestamp": str(timestamp_ms)},
        secret=secret,
    )
    return LiveAccountRequest(
        method="GET",
        url=endpoint,
        headers={"Accept": "application/json", "X-MBX-APIKEY": api_key},
        signed_query=signed_query,
    )


def fetch_live_account(request: LiveAccountRequest) -> Mapping[str, object]:
    """Perform exactly one authenticated GET; no retry and no order method."""
    if request.method != "GET" or not request.read_only or request.order_capability:
        raise ValueError("live account transport permits read-only GET only")
    url = f"{request.url}?{request.signed_query}"
    http_request = urllib.request.Request(url, method="GET", headers=request.headers)
    try:
        with urllib.request.urlopen(http_request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"live account GET rejected with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("live account GET transport failed") from exc
    if not isinstance(body, Mapping):
        raise ValueError("malformed live account response")
    return body


def parse_live_account_snapshot(body: Mapping[str, object]) -> TestnetAccountSnapshot:
    return parse_testnet_account_snapshot(body)


def reconcile_live_account(
    snapshot: TestnetAccountSnapshot,
    expected_positions: tuple[LivePositionExpectation, ...],
) -> LiveAccountReconciliation:
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
    missing = sorted(set(expected) - set(remote))
    unexpected = sorted(set(remote) - set(expected))
    mismatched = sorted(key for key in set(expected) & set(remote) if expected[key] != remote[key])
    if missing or unexpected or mismatched:
        return LiveAccountReconciliation(
            status="drift",
            missing_symbols=tuple(sorted({key[0] for key in missing})),
            unexpected_symbols=tuple(sorted({key[0] for key in unexpected})),
            mismatched_symbols=tuple(sorted({key[0] for key in mismatched})),
            reason_codes=("live_account_position_drift",),
        )
    return LiveAccountReconciliation(
        status="reconciled",
        reason_codes=("live_account_reconciled",),
    )


__all__ = [
    "LiveAccountReconciliation",
    "LiveAccountRequest",
    "LivePositionExpectation",
    "build_live_account_request",
    "fetch_live_account",
    "parse_live_account_snapshot",
    "reconcile_live_account",
]
