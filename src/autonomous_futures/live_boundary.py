"""Offline live-boundary eligibility checks; never activates network access."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field

from .domain.contracts import DomainModel, StrictPositiveDecimal

LIVE_REST_BASE_URL = "https://fapi.binance.com"


def validate_live_rest_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "fapi.binance.com"
        or not parsed.path.startswith("/fapi/")
    ):
        raise ValueError("URL is not an allowed production endpoint")
    return url


class LiveBoundaryInputs(DomainModel):
    testnet_evidence_complete: bool
    legal_review_confirmed: bool
    venue_account_confirmed: bool
    secret_manager_ready: bool
    kill_switch_verified: bool
    reconciliation_clean: bool
    symbol_approved: bool
    explicit_live_activation: bool
    live_enabled: bool
    max_quote_notional: StrictPositiveDecimal


class LiveBoundaryDecision(DomainModel):
    status: Literal["blocked", "design_eligible"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    live_enabled: Literal[False] = False
    network_allowed: Literal[False] = False
    max_quote_notional: StrictPositiveDecimal


def evaluate_live_boundary(inputs: LiveBoundaryInputs) -> LiveBoundaryDecision:
    checks = (
        (inputs.testnet_evidence_complete, "testnet_evidence_incomplete"),
        (inputs.legal_review_confirmed, "legal_review_missing"),
        (inputs.venue_account_confirmed, "venue_account_review_missing"),
        (inputs.secret_manager_ready, "secret_manager_not_ready"),
        (inputs.kill_switch_verified, "kill_switch_not_verified"),
        (inputs.reconciliation_clean, "reconciliation_not_clean"),
        (inputs.symbol_approved, "live_symbol_not_approved"),
        (inputs.explicit_live_activation, "live_activation_not_explicit"),
        (inputs.live_enabled, "live_enabled_flag_false"),
    )
    reasons = tuple(reason for passed, reason in checks if not passed)
    if reasons:
        return LiveBoundaryDecision(
            status="blocked",
            reason_codes=reasons,
            max_quote_notional=inputs.max_quote_notional,
        )
    return LiveBoundaryDecision(
        status="design_eligible",
        reason_codes=("live_design_eligible_not_activated",),
        max_quote_notional=inputs.max_quote_notional,
    )
