"""Manual live preflight; reads credential presence only and never sends network."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from .domain.contracts import DomainModel
from .live_activation import LiveActivationToken
from .live_boundary import validate_live_rest_url

REQUIRED_LIVE_CREDENTIAL_NAMES = (
    "BINANCE_LIVE_API_KEY",
    "BINANCE_LIVE_SECRET_KEY",
)


class LivePreflightDecision(DomainModel):
    status: Literal["blocked", "ready_for_manual_activation"]
    token_id: str
    credential_names_present: tuple[str, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    live_enabled: Literal[False] = False
    network_allowed: Literal[False] = False


def _present_credential_names(credential_dir: Path) -> tuple[str, ...]:
    return tuple(
        name
        for name in REQUIRED_LIVE_CREDENTIAL_NAMES
        if (path := credential_dir / name).is_file() and path.stat().st_size > 0
    )


def evaluate_live_preflight(
    token: LiveActivationToken,
    *,
    credential_dir: Path,
    base_url: str,
    account_reconciled: bool,
    positions_flat: bool,
    kill_switch_ready: bool,
    now: datetime,
) -> LivePreflightDecision:
    reasons: list[str] = []
    present = _present_credential_names(credential_dir)
    reasons.extend(
        f"credential_missing_{name}"
        for name in REQUIRED_LIVE_CREDENTIAL_NAMES
        if name not in present
    )
    try:
        validate_live_rest_url(f"{base_url.rstrip('/')}/fapi/v1/account")
    except ValueError:
        reasons.append("invalid_production_endpoint")
    if not account_reconciled:
        reasons.append("account_not_reconciled")
    if not positions_flat:
        reasons.append("positions_not_flat")
    if not kill_switch_ready:
        reasons.append("kill_switch_not_verified")
    if now >= token.expires_at:
        reasons.append("token_expired")
    if token.state == "issued_not_enabled":
        reasons.append("token_not_enabled")
    blocking_reasons = tuple(reason for reason in reasons if reason != "token_not_enabled")
    status: Literal["blocked", "ready_for_manual_activation"] = (
        "blocked" if blocking_reasons else "ready_for_manual_activation"
    )
    return LivePreflightDecision(
        status=status,
        token_id=token.token_id,
        credential_names_present=present,
        reason_codes=tuple(reasons),
    )


__all__ = [
    "LivePreflightDecision",
    "REQUIRED_LIVE_CREDENTIAL_NAMES",
    "evaluate_live_preflight",
]
