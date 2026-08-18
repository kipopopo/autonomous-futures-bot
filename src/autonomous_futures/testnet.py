"""Offline-only contracts for a future USDⓈ-M Futures testnet adapter."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from typing import Literal
from urllib.parse import urlencode, urlsplit

from pydantic import Field, model_validator

from .domain.contracts import DomainModel, StrictPositiveDecimal

TESTNET_REST_BASE_URL = "https://demo-fapi.binance.com"
TESTNET_WEBSOCKET_BASE_URL = "wss://demo-fstream.binance.com"


def validate_testnet_rest_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "demo-fapi.binance.com"
        or not parsed.path.startswith("/fapi/")
    ):
        raise ValueError("URL is not an allowed USD-M testnet endpoint")
    return url


def sign_testnet_query(params: Mapping[str, str], *, secret: str) -> str:
    if not secret:
        raise ValueError("testnet signing secret must be explicit and non-empty")
    if "signature" in params:
        raise ValueError("query must not already contain a signature")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in params.items()):
        raise ValueError("testnet query keys and values must be strings")
    query = urlencode(sorted(params.items()))
    signature = hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


class TestnetSymbolFilters(DomainModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    min_quantity: StrictPositiveDecimal
    max_quantity: StrictPositiveDecimal
    step_size: StrictPositiveDecimal
    min_notional: StrictPositiveDecimal
    max_leverage: StrictPositiveDecimal

    @model_validator(mode="after")
    def ranges_are_valid(self) -> TestnetSymbolFilters:
        if self.max_quantity < self.min_quantity:
            raise ValueError("max quantity must not be below min quantity")
        if self.step_size > self.max_quantity:
            raise ValueError("step size must not exceed max quantity")
        return self


class TestnetOrderProposal(DomainModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    side: Literal["BUY", "SELL"]
    quantity: StrictPositiveDecimal
    mark_price: StrictPositiveDecimal
    leverage: StrictPositiveDecimal
    reduce_only: bool
    existing_symbol_position: bool
    open_position_count: int = Field(ge=0, strict=True)
    max_open_positions: int = Field(gt=0, strict=True)
    max_quote_notional: StrictPositiveDecimal


class TestnetRiskDecision(DomainModel):
    allowed: bool
    quote_notional: StrictPositiveDecimal
    margin_notional: StrictPositiveDecimal
    reason_codes: tuple[str, ...] = Field(min_length=1)
    live_enabled: Literal[False] = False


def validate_testnet_order(
    proposal: TestnetOrderProposal,
    filters: TestnetSymbolFilters,
) -> TestnetRiskDecision:
    quote_notional = proposal.quantity * proposal.mark_price
    margin_notional = quote_notional / proposal.leverage
    reasons: list[str] = []
    if proposal.symbol != filters.symbol:
        reasons.append("symbol_filter_mismatch")
    if proposal.quantity < filters.min_quantity:
        reasons.append("quantity_below_exchange_minimum")
    if proposal.quantity > filters.max_quantity:
        reasons.append("quantity_above_exchange_maximum")
    if proposal.quantity % filters.step_size != 0:
        reasons.append("quantity_step_invalid")
    if quote_notional < filters.min_notional:
        reasons.append("quote_notional_below_exchange_minimum")
    if quote_notional > proposal.max_quote_notional:
        reasons.append("quote_notional_limit_exceeded")
    if proposal.leverage > filters.max_leverage:
        reasons.append("leverage_above_exchange_maximum")
    if not proposal.reduce_only and proposal.open_position_count >= proposal.max_open_positions:
        reasons.append("open_position_limit_exceeded")
    if proposal.reduce_only and not proposal.existing_symbol_position:
        reasons.append("reduce_only_position_missing")
    if not proposal.reduce_only and proposal.existing_symbol_position:
        reasons.append("duplicate_symbol_position")
    return TestnetRiskDecision(
        allowed=not reasons,
        quote_notional=quote_notional,
        margin_notional=margin_notional,
        reason_codes=tuple(sorted(reasons)) if reasons else ("testnet_order_risk_approved",),
    )


def classify_testnet_error(
    http_status: int,
    message: str,
) -> Literal["retry", "reconcile", "halt", "reject"]:
    lowered = message.lower()
    if http_status == 503 and "unknown error" in lowered:
        return "reconcile"
    if http_status == 503 and "service unavailable" in lowered:
        return "retry"
    if http_status == 429:
        return "retry"
    if http_status == 418:
        return "halt"
    if 400 <= http_status < 500:
        return "reject"
    if http_status >= 500:
        return "retry"
    return "halt"


def reconcile_testnet_order(
    local_state: Literal["not_submitted", "submitted", "unknown"],
    exchange_status: str | None,
) -> Literal["safe_to_submit", "reconciled_no_retry", "retry_allowed", "halt_ambiguous_state"]:
    status = None if exchange_status is None else exchange_status.upper()
    if local_state == "not_submitted" and status is None:
        return "safe_to_submit"
    if local_state == "unknown" and status in {"NEW", "PARTIALLY_FILLED", "FILLED"}:
        return "reconciled_no_retry"
    if local_state == "unknown" and status in {"CANCELED", "EXPIRED", "REJECTED"}:
        return "retry_allowed"
    return "halt_ambiguous_state"
