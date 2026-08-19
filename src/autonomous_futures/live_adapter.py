"""Offline live order descriptor and activation-gated injected transport."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlencode

from .domain.contracts import DomainModel
from .live_boundary import LIVE_REST_BASE_URL, validate_live_rest_url
from .live_review import LiveActivationReview


class LiveOrderRequest(DomainModel):
    method: Literal["POST"]
    url: str
    headers: dict[str, str]
    signed_query: str
    live_enabled: Literal[False] = False


def _sign_query(params: Mapping[str, str], *, secret: str) -> str:
    if not secret:
        raise ValueError("live signing secret must be explicit and non-empty")
    query = urlencode(sorted(params.items()))
    signature = hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


def build_live_order_request(
    *,
    symbol: str,
    side: Literal["BUY", "SELL"],
    quantity: Decimal,
    api_key: str,
    secret: str,
    timestamp_ms: int,
    base_url: str = LIVE_REST_BASE_URL,
) -> LiveOrderRequest:
    if not symbol or symbol != symbol.upper() or not symbol.isalnum():
        raise ValueError("live symbol must be uppercase alphanumeric")
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity <= 0:
        raise ValueError("live quantity must be a finite positive Decimal")
    if not api_key:
        raise ValueError("live API key must be explicit and non-empty")
    if not isinstance(timestamp_ms, int) or isinstance(timestamp_ms, bool) or timestamp_ms <= 0:
        raise ValueError("timestamp_ms must be a positive integer")
    endpoint = validate_live_rest_url(f"{base_url}/fapi/v1/order")
    params = {
        "quantity": str(quantity),
        "side": side,
        "symbol": symbol,
        "timestamp": str(timestamp_ms),
        "type": "MARKET",
    }
    return LiveOrderRequest(
        method="POST",
        url=endpoint,
        headers={"Accept": "application/json", "X-MBX-APIKEY": api_key},
        signed_query=_sign_query(params, secret=secret),
    )


def send_live_order_request(
    review: LiveActivationReview,
    request: LiveOrderRequest,
    transport: Callable[[LiveOrderRequest], object],
    *,
    now: datetime | None = None,
) -> object:
    """Gate an injected transport; this module never owns an HTTP client."""
    if (
        review.state == "reviewed_not_activated"
        or not review.live_enabled
        or not review.network_allowed
    ):
        raise ValueError("live activation review is not activated")
    observed_at = datetime.now(UTC) if now is None else now
    if observed_at.tzinfo is None or observed_at.utcoffset() != UTC.utcoffset(observed_at):
        raise ValueError("live request time must be timezone-aware UTC")
    if observed_at >= review.expires_at:
        raise ValueError("live activation review is expired")
    if request.live_enabled is not True:
        raise ValueError("live request is not enabled")
    return transport(request)


__all__ = ["LiveOrderRequest", "build_live_order_request", "send_live_order_request"]
