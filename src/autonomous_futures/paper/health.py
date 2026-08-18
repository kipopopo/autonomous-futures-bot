"""Read-only aggregate health for paper observations and lifecycle marks."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from ..domain.contracts import DomainModel, StrictNonNegativeDecimal
from .lifecycle import PaperLifecycleTelemetry
from .maturity import evaluate_paper_maturity
from .observation import PaperObservation, PaperObservationBinding


class PaperLifecycleHealth(DomainModel):
    trade_id: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    lifecycle_status: Literal["open", "exit_ready"]
    mark_to_market_pnl: Decimal
    pnl_pct: Decimal
    holding_seconds: int = Field(ge=0, strict=True)
    mark_age_seconds: int = Field(ge=0, strict=True)
    stale: bool
    stop_loss_hit: bool
    take_profit_hit: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)


class PaperHealthReport(DomainModel):
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: datetime
    health_status: Literal["unavailable", "maturing", "healthy", "attention", "blocked"]
    maturity_status: Literal["unavailable", "maturing", "blocked", "mature"]
    maturity_end: datetime | None = None
    latest_observed_at: datetime | None = None
    latest_equity: StrictNonNegativeDecimal | None = None
    latest_drawdown_pct: Decimal | None = None
    open_position_count: int | None = Field(default=None, ge=0, strict=True)
    accounting_complete: bool
    lifecycle: tuple[PaperLifecycleHealth, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @field_validator("as_of", "maturity_end", "latest_observed_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
            raise ValueError("paper health timestamps must be timezone-aware UTC")
        return value.astimezone(UTC) if value is not None else None


def _report(
    *,
    binding: PaperObservationBinding,
    as_of: datetime,
    health_status: Literal["unavailable", "maturing", "healthy", "attention", "blocked"],
    maturity_status: Literal["unavailable", "maturing", "blocked", "mature"],
    maturity_end: datetime | None,
    latest: PaperObservation | None,
    accounting_complete: bool,
    lifecycle: tuple[PaperLifecycleHealth, ...],
    reason_codes: tuple[str, ...],
) -> PaperHealthReport:
    return PaperHealthReport(
        candidate_id=binding.candidate_id,
        candidate_artifact_hash=binding.candidate_artifact_hash,
        as_of=as_of,
        health_status=health_status,
        maturity_status=maturity_status,
        maturity_end=maturity_end,
        latest_observed_at=None if latest is None else latest.observed_at,
        latest_equity=None if latest is None else latest.equity,
        latest_drawdown_pct=None if latest is None else latest.drawdown_pct,
        open_position_count=None if latest is None else latest.open_position_count,
        accounting_complete=accounting_complete,
        lifecycle=lifecycle,
        reason_codes=reason_codes,
    )


def aggregate_paper_health(
    observations: Sequence[PaperObservation],
    lifecycle_marks: Sequence[PaperLifecycleTelemetry],
    *,
    candidate_id: str,
    candidate_artifact_hash: str,
    as_of: datetime,
    max_mark_age_seconds: int,
    required_days: int = 7,
) -> PaperHealthReport:
    """Aggregate explicit paper evidence without mutation, clocks, or external inputs."""
    binding = PaperObservationBinding(
        candidate_id=candidate_id,
        candidate_artifact_hash=candidate_artifact_hash,
    )
    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise ValueError("as_of must be timezone-aware UTC")
    if not isinstance(max_mark_age_seconds, int) or isinstance(max_mark_age_seconds, bool):
        raise ValueError("max_mark_age_seconds must be an integer")
    if max_mark_age_seconds <= 0:
        raise ValueError("max_mark_age_seconds must be positive")
    observed_at = as_of.astimezone(UTC)
    maturity = evaluate_paper_maturity(
        observations,
        candidate_id=binding.candidate_id,
        candidate_artifact_hash=binding.candidate_artifact_hash,
        as_of=observed_at,
        required_days=required_days,
    )
    if not observations:
        return _report(
            binding=binding,
            as_of=observed_at,
            health_status="unavailable",
            maturity_status="unavailable",
            maturity_end=None,
            latest=None,
            accounting_complete=False,
            lifecycle=(),
            reason_codes=("paper_health_observation_unavailable",),
        )
    latest = max(
        observations,
        key=lambda observation: observation.observed_at,
    )
    if any(
        observation.candidate_id != binding.candidate_id
        or observation.candidate_artifact_hash != binding.candidate_artifact_hash
        or observation.observed_at > observed_at
        for observation in observations
    ):
        return _report(
            binding=binding,
            as_of=observed_at,
            health_status="blocked",
            maturity_status="blocked",
            maturity_end=maturity.maturity_end,
            latest=latest,
            accounting_complete=False,
            lifecycle=(),
            reason_codes=("paper_health_observation_binding_or_time_invalid",),
        )

    latest_marks: dict[str, PaperLifecycleTelemetry] = {}
    for mark in lifecycle_marks:
        if (
            mark.candidate_id != binding.candidate_id
            or mark.candidate_artifact_hash != binding.candidate_artifact_hash
        ):
            return _report(
                binding=binding,
                as_of=observed_at,
                health_status="blocked",
                maturity_status="blocked",
                maturity_end=maturity.maturity_end,
                latest=latest,
                accounting_complete=False,
                lifecycle=(),
                reason_codes=("paper_health_lifecycle_binding_mismatch",),
            )
        if mark.marked_at > observed_at:
            return _report(
                binding=binding,
                as_of=observed_at,
                health_status="blocked",
                maturity_status="blocked",
                maturity_end=maturity.maturity_end,
                latest=latest,
                accounting_complete=False,
                lifecycle=(),
                reason_codes=("paper_health_future_lifecycle_mark",),
            )
        current = latest_marks.get(mark.trade_id)
        if current is None or mark.marked_at >= current.marked_at:
            latest_marks[mark.trade_id] = mark

    lifecycle: list[PaperLifecycleHealth] = []
    lifecycle_reasons: list[str] = []
    for trade_id in sorted(latest_marks):
        mark = latest_marks[trade_id]
        age_delta = observed_at - mark.marked_at
        age_seconds = int(age_delta.total_seconds())
        if age_delta.total_seconds() != age_seconds:
            raise ValueError("paper health timestamps must have whole-second precision")
        stale = age_seconds > max_mark_age_seconds
        if stale:
            lifecycle_reasons.append("paper_lifecycle_mark_stale")
        if mark.lifecycle_status == "exit_ready":
            lifecycle_reasons.append("paper_lifecycle_exit_ready")
        lifecycle.append(
            PaperLifecycleHealth(
                trade_id=mark.trade_id,
                symbol=mark.symbol,
                lifecycle_status=mark.lifecycle_status,
                mark_to_market_pnl=mark.mark_to_market_pnl,
                pnl_pct=mark.pnl_pct,
                holding_seconds=mark.holding_seconds,
                mark_age_seconds=age_seconds,
                stale=stale,
                stop_loss_hit=mark.stop_loss_hit,
                take_profit_hit=mark.take_profit_hit,
                reason_codes=mark.reason_codes,
            )
        )
    lifecycle_tuple = tuple(lifecycle)
    if maturity.status == "blocked" or not latest.accounting_complete:
        blocked_reasons = list(maturity.reason_codes)
        if not latest.accounting_complete:
            blocked_reasons.append("paper_health_accounting_incomplete")
        return _report(
            binding=binding,
            as_of=observed_at,
            health_status="blocked",
            maturity_status="blocked" if maturity.status != "mature" else maturity.status,
            maturity_end=maturity.maturity_end,
            latest=latest,
            accounting_complete=latest.accounting_complete,
            lifecycle=lifecycle_tuple,
            reason_codes=tuple(dict.fromkeys(blocked_reasons)),
        )
    if latest.open_position_count > 0 and not lifecycle_tuple:
        lifecycle_reasons.append("paper_lifecycle_telemetry_unavailable")
    if lifecycle_reasons:
        return _report(
            binding=binding,
            as_of=observed_at,
            health_status="attention",
            maturity_status=maturity.status,
            maturity_end=maturity.maturity_end,
            latest=latest,
            accounting_complete=latest.accounting_complete,
            lifecycle=lifecycle_tuple,
            reason_codes=tuple(dict.fromkeys(lifecycle_reasons)),
        )
    if maturity.status == "maturing":
        return _report(
            binding=binding,
            as_of=observed_at,
            health_status="maturing",
            maturity_status=maturity.status,
            maturity_end=maturity.maturity_end,
            latest=latest,
            accounting_complete=latest.accounting_complete,
            lifecycle=lifecycle_tuple,
            reason_codes=maturity.reason_codes,
        )
    return _report(
        binding=binding,
        as_of=observed_at,
        health_status="healthy",
        maturity_status=maturity.status,
        maturity_end=maturity.maturity_end,
        latest=latest,
        accounting_complete=latest.accounting_complete,
        lifecycle=lifecycle_tuple,
        reason_codes=("paper_health_healthy",),
    )
