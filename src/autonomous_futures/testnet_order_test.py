"""Offline signed descriptor for a future USDⓈ-M order-test request."""

from __future__ import annotations

import re
from typing import Literal

from .domain.contracts import DomainModel
from .testnet import (
    TESTNET_REST_BASE_URL,
    TestnetOrderProposal,
    TestnetSymbolFilters,
    sign_testnet_query,
    validate_testnet_order,
)


class TestnetOrderTestRequest(DomainModel):
    method: Literal["POST"]
    url: str
    headers: dict[str, str]
    signed_query: str
    live_enabled: Literal[False] = False


def build_testnet_order_test_request(
    proposal: TestnetOrderProposal,
    filters: TestnetSymbolFilters,
    *,
    api_key: str,
    secret: str,
    timestamp_ms: int,
    client_order_id: str,
    recv_window: int = 5000,
    base_url: str = TESTNET_REST_BASE_URL,
) -> TestnetOrderTestRequest:
    risk = validate_testnet_order(proposal, filters)
    if not risk.allowed:
        raise ValueError(f"testnet order-test risk blocked: {','.join(risk.reason_codes)}")
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
    if not re.fullmatch(r"afbot-test-[A-Za-z0-9._-]+", client_order_id):
        raise ValueError("client_order_id must use the afbot-test- prefix")
    signed_query = sign_testnet_query(
        {
            "newClientOrderId": client_order_id,
            "quantity": str(proposal.quantity),
            "recvWindow": str(recv_window),
            "reduceOnly": str(proposal.reduce_only).lower(),
            "side": proposal.side,
            "symbol": proposal.symbol,
            "timestamp": str(timestamp_ms),
            "type": "MARKET",
        },
        secret=secret,
    )
    return TestnetOrderTestRequest(
        method="POST",
        url=f"{base_url}/fapi/v1/order/test",
        headers={"Accept": "application/json", "X-MBX-APIKEY": api_key},
        signed_query=signed_query,
    )
