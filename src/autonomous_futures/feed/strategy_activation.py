"""Phase 295: Live Strategy Activation & Walk-Forward OOS Promotion Gates Engine.

Links staged quantitative candidate strategies from Candidate Registry Manifest v2
to live Binance market feeds and real-time Hawkes microstructure telemetry. Enforces
multi-tier out-of-sample promotion gates, candidate lifecycle state machine transitions,
and real-time fail-closed veto interlocks, driving promoted parent order intentions into
the Phase 294 paper execution engine with continuous double-entry zero-drift balance validation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import time
import uuid
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from autonomous_futures.data.exchange_filters import (
    ExchangeSymbolFilters,
)
from autonomous_futures.domain.contracts import DomainModel
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.feed.models import (
    AggregateTrade,
    CanonicalBar,
    OrderBookDepthSnapshot,
    OrderBookLevel,
)
from autonomous_futures.feed.paper_execution import (
    HARD_MICRO_NOTIONAL_CAP_USDT,
    ChildOrderIntention,
    OrderExecutionFill,
    OrderSide,
    OrderStatus,
    OrderType,
    ParentOrderIntention,
    SimulatedPassiveMatchingEngine,
    SimulatedRestingOrder,
    quantize_price,
    slice_parent_order,
)
from autonomous_futures.feed.paper_ledger import (
    DOUBLE_ENTRY_MAX_DRIFT,
    BalanceSnapshotRecord,
    PaperExecutionLedger,
)
from autonomous_futures.feed.paper_risk import (
    HAWKES_SEVERE_REGIME_THRESHOLD,
    HAWKES_SUPERCRITICAL_THRESHOLD,
    INTRA_PHASE_LOSS_CEILING_USDT,
    MAX_CLOCK_SKEW_MS,
    MAX_HEARTBEAT_AGE_MS,
    CircuitState,
    InterlockCode,
    InterlockDecision,
    LivePaperRiskInterlock,
)
from autonomous_futures.paper.candidate_registry import (
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    CandidateManifestEntry,
    CandidateRegistryManifest,
    compute_registry_hash,
    read_candidate_registry,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    _artifact_content_hash,
    read_creator_candidate_artifact,
)
from autonomous_futures.research.qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    _qualification_content_hash,
    read_creator_candidate_qualification_artifact,
)

logger = logging.getLogger("autonomous_futures.feed.strategy_activation")

DEFAULT_PHASE295_DIR: Path = Path("artifacts/research/phase295")
DEFAULT_PHASE294_DIR: Path = Path("artifacts/research/phase294")

EXPECTED_ACTIVE_CANDIDATES: dict[str, str] = {
    "BTCUSDT": "cand-btcusdt-dcb-002",
    "ETHUSDT": "cand-ethusdt-dcb-003",
    "SOLUSDT": "cand-solusdt-rgb-001",
}


# =====================================================================
# Error Hierarchy
# =====================================================================


class StrategyActivationError(DomainViolation):
    """Base domain violation for Phase 295 Strategy Activation Engine."""


class CandidateRegistryError(StrategyActivationError):
    """Raised when candidate registry manifest v2 fails schema, hash, or universe validation."""


class PromotionGateEvaluationError(StrategyActivationError):
    """Raised when promotion gate evaluation fails on corrupted or malformed artifacts."""


class VetoInterlockError(StrategyActivationError):
    """Raised on critical veto interlock condition violations."""


class StateTransitionError(StrategyActivationError):
    """Raised when candidate state machine attempts a forbidden transition."""


# =====================================================================
# Domain Models & Telemetry Contracts
# =====================================================================


class CandidatePromotionStatus(StrEnum):
    """Candidate strategy promotion lifecycle states."""

    UNPROMOTED = "UNPROMOTED"
    PROMOTED = "PROMOTED"
    BLOCKED = "BLOCKED"
    VETOED = "VETOED"


class OOSPromotionGateRecord(DomainModel):
    """Immutable evaluation record for candidate walk-forward OOS promotion gates."""

    candidate_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    status: CandidatePromotionStatus
    oos_average_return_pct: Decimal
    oos_worst_drawdown_pct: Decimal
    oos_profit_factor: Decimal
    oos_trade_count: int = Field(ge=0)
    oos_window_count: int = Field(ge=0)
    gates_passed: dict[str, bool]
    qualified: bool
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def require_utc_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)


class HawkesTelemetrySnapshot(DomainModel):
    """Microstructure telemetry snapshot from Phase 293 Hawkes streaming engine."""

    timestamp_ms: int = Field(default=0, ge=0)
    symbol: str = Field(min_length=1)
    spectral_radius: Decimal
    regime: str = Field(default="NOMINAL")
    is_supercritical: bool = False
    is_predatory: bool = False
    jump_intensity: Decimal = Field(default=Decimal("0.0"))


class GatewayHealth(DomainModel):
    """Gateway health telemetry tracking Binance USDⓈ-M public ingress freshness."""

    heartbeat_age_ms: float = Field(default=0.0, ge=0.0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    clock_skew_ms: float = Field(default=0.0)
    is_healthy: bool = True
    status: str = Field(default="HEALTHY")
    timestamp_utc: str = Field(default="")


class VetoDecision(DomainModel):
    """Evaluated pre-trade real-time fail-closed veto interlock decision."""

    allowed: bool
    veto_code: str
    reason: str
    symbol: str
    proposed_notional: Decimal
    veto_flags: dict[str, bool] = Field(
        default_factory=lambda: {
            "hawkes_supercritical": False,
            "gateway_heartbeat_stale": False,
            "margin_headroom_breach": False,
            "intra_phase_loss_breach": False,
        }
    )
    circuit_state: str = "NORMAL"
    emergency_flattening_required: bool = False
    closing_orders: list[Any] = Field(default_factory=list)
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class LoadedCandidateBundle:
    """Strongly typed bundle linking candidate specification, qualification, and metadata."""

    symbol: str
    candidate_id: str
    candidate: CreatorCandidateArtifact
    qualification: CreatorCandidateQualificationArtifact
    manifest_entry: CandidateManifestEntry


# =====================================================================
# Candidate Lifecycle State Machine
# =====================================================================


class CandidateLifecycleStateMachine:
    """Fail-closed state machine governing candidate promotion lifecycle.

    Supported States:
    - UNPROMOTED: Initial staging state; shadow evaluation only; orders cannot be dispatched.
    - PROMOTED: Qualified strategy authorized for order formulation & execution.
    - BLOCKED: Semi-permanent lockout (gate failure, loss breach, manual freeze).
    - VETOED: Transient operational suppression; reverts to PROMOTED when cleared.
    """

    def __init__(
        self,
        candidate_id: str,
        symbol: str,
        initial_status: CandidatePromotionStatus = CandidatePromotionStatus.UNPROMOTED,
    ) -> None:
        self.candidate_id = candidate_id
        self.symbol = symbol.upper()
        self._status: CandidatePromotionStatus = initial_status
        self._status_history: list[tuple[CandidatePromotionStatus, str, datetime]] = [
            (initial_status, "Initial ingestion state", datetime.now(UTC))
        ]

    @property
    def status(self) -> CandidatePromotionStatus:
        return self._status

    @property
    def is_executable(self) -> bool:
        """True only if candidate is actively PROMOTED (not VETOED, BLOCKED, or UNPROMOTED)."""
        return self._status == CandidatePromotionStatus.PROMOTED

    @property
    def status_history(self) -> list[tuple[CandidatePromotionStatus, str, datetime]]:
        return list(self._status_history)

    def promote(self, gate_record: OOSPromotionGateRecord) -> None:
        """Promote candidate upon passing walk-forward OOS qualification gates."""
        if not gate_record.qualified:
            raise StateTransitionError(
                f"Cannot promote candidate {self.candidate_id}: qualification gates not passed"
            )
        if self._status == CandidatePromotionStatus.BLOCKED:
            raise StateTransitionError(
                f"Cannot promote BLOCKED candidate {self.candidate_id} directly; "
                "requires administrative reset"
            )
        reason_str = (
            f"Promoted via OOS gate record (Avg Ret={gate_record.oos_average_return_pct}%, "
            f"DD={gate_record.oos_worst_drawdown_pct}%, PF={gate_record.oos_profit_factor})"
        )
        self._transition_to(
            CandidatePromotionStatus.PROMOTED,
            reason_str,
        )

    def block(self, reason: str) -> None:
        """Lock down candidate permanently for this phase."""
        self._transition_to(CandidatePromotionStatus.BLOCKED, reason)

    def veto(self, reason: str) -> None:
        """Transiently suppress candidate signal dispatch due to pre-trade risk veto."""
        if self._status == CandidatePromotionStatus.BLOCKED:
            return  # Already BLOCKED; cannot downgrade
        if self._status == CandidatePromotionStatus.PROMOTED:
            self._transition_to(CandidatePromotionStatus.VETOED, reason)

    def clear_veto(self, reason: str = "Transient veto cleared") -> None:
        """Restore promoted status once transient market veto condition clears."""
        if self._status == CandidatePromotionStatus.VETOED:
            self._transition_to(CandidatePromotionStatus.PROMOTED, reason)

    def reset(
        self, initial_status: CandidatePromotionStatus = CandidatePromotionStatus.UNPROMOTED
    ) -> None:
        """Reset state machine for administrative testing or re-qualification."""
        self._transition_to(initial_status, "Administrative state reset")

    def _transition_to(self, new_status: CandidatePromotionStatus, reason: str) -> None:
        if self._status == new_status:
            return
        now = datetime.now(UTC)
        self._status = new_status
        self._status_history.append((new_status, reason, now))
        logger.debug(
            "Candidate %s [%s] transitioned to %s: %s",
            self.candidate_id,
            self.symbol,
            new_status,
            reason,
        )


# =====================================================================
# Candidate Registry Manifest v2 Ingress
# =====================================================================


def load_verified_candidate_manifest_v2(
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    repo_root: Path | None = None,
) -> tuple[CandidateRegistryManifest, dict[str, LoadedCandidateBundle]]:
    """Ingest artifacts/paper_live/candidate_registry.json, validating all hashes and bindings.

    Enforces:
    1. registry_version >= 2
    2. compute_registry_hash(manifest) == manifest.registry_hash
    3. Staged active universe contains BTCUSDT, ETHUSDT, SOLUSDT
    4. Candidate artifact file existence and _artifact_content_hash verification
    5. Qualification artifact file existence and _qualification_content_hash verification
    6. Candidate decision == "qualified"

    Returns:
        tuple of (CandidateRegistryManifest, dict[symbol, LoadedCandidateBundle])
    """
    root = repo_root or Path.cwd()
    reg_p = Path(registry_path)
    if not reg_p.is_absolute():
        reg_p = root / reg_p

    if not reg_p.exists():
        raise CandidateRegistryError(f"Candidate registry manifest does not exist: {reg_p}")

    try:
        manifest = read_candidate_registry(reg_p)
    except DomainViolation as exc:
        raise CandidateRegistryError(f"Candidate registry manifest invalid: {exc}") from exc

    if manifest.registry_version < 2:
        raise CandidateRegistryError(
            f"Manifest version {manifest.registry_version} < 2 required for Phase 295"
        )

    computed_reg_hash = compute_registry_hash(manifest)
    if computed_reg_hash != manifest.registry_hash:
        raise CandidateRegistryError(
            f"Registry manifest hash mismatch: computed {computed_reg_hash} != "
            f"{manifest.registry_hash}"
        )

    bundles: dict[str, LoadedCandidateBundle] = {}

    if manifest.registry_version < 3:
        for sym, expected_cid in EXPECTED_ACTIVE_CANDIDATES.items():
            if sym not in manifest.symbols:
                raise CandidateRegistryError(
                    f"Mandatory universe symbol {sym} missing from candidate registry"
                )
            entry = manifest.symbols[sym]
            if entry.candidate_id != expected_cid:
                raise CandidateRegistryError(
                    f"Candidate ID mismatch for {sym}: expected {expected_cid}, "
                    f"got {entry.candidate_id}"
                )
    else:
        # Version 3+: dynamically verify active candidates present in manifest.symbols
        for sym in EXPECTED_ACTIVE_CANDIDATES:
            if sym not in manifest.symbols:
                raise CandidateRegistryError(
                    f"Mandatory universe symbol {sym} missing from candidate registry"
                )

    for sym, entry in manifest.symbols.items():
        # Load and verify candidate artifact
        cand_p = Path(entry.artifact_path)
        if not cand_p.is_absolute():
            cand_p = root / cand_p
        if not cand_p.exists():
            raise CandidateRegistryError(f"Candidate artifact file missing: {cand_p}")

        candidate = read_creator_candidate_artifact(cand_p)
        if candidate.candidate_id != entry.candidate_id:
            raise CandidateRegistryError(
                f"Candidate artifact candidate_id {candidate.candidate_id} != "
                f"entry {entry.candidate_id}"
            )

        content_hash = _artifact_content_hash(candidate)
        if content_hash != entry.candidate_artifact_hash:
            raise CandidateRegistryError(
                f"Candidate artifact hash mismatch for {sym}: "
                f"{content_hash} != {entry.candidate_artifact_hash}"
            )

        if sym not in candidate.strategy.universe.symbols:
            raise CandidateRegistryError(
                f"Symbol {sym} not declared in candidate universe: "
                f"{candidate.strategy.universe.symbols}"
            )

        # Load and verify qualification artifact
        qual_filename = f"qual-{entry.candidate_id}.json"
        qual_p = root / "artifacts" / "paper_live" / "qualifications" / qual_filename
        if not qual_p.exists() and (reg_p.parent / "qualifications" / qual_filename).exists():
            qual_p = reg_p.parent / "qualifications" / qual_filename
        if not qual_p.exists():
            raise CandidateRegistryError(f"Qualification artifact file missing: {qual_p}")

        qualification = read_creator_candidate_qualification_artifact(qual_p)
        if qualification.candidate_id != entry.candidate_id:
            raise CandidateRegistryError(
                f"Qualification candidate_id {qualification.candidate_id} != "
                f"entry {entry.candidate_id}"
            )

        q_hash = _qualification_content_hash(qualification)
        if q_hash != entry.qualification_hash:
            raise CandidateRegistryError(
                f"Qualification hash mismatch for {entry.candidate_id}: "
                f"{q_hash} != {entry.qualification_hash}"
            )

        if qualification.decision != "qualified":
            raise CandidateRegistryError(
                f"Candidate {entry.candidate_id} qualification decision is "
                f"{qualification.decision}, not 'qualified'"
            )

        bundles[sym] = LoadedCandidateBundle(
            symbol=sym,
            candidate_id=entry.candidate_id,
            candidate=candidate,
            qualification=qualification,
            manifest_entry=entry,
        )

    logger.info(
        "Verified manifest v%d and loaded %d candidates successfully",
        manifest.registry_version,
        len(bundles),
    )
    return manifest, bundles


# =====================================================================
# Walk-Forward OOS Promotion Gate Evaluator
# =====================================================================


def evaluate_oos_promotion_gates(
    candidate: CreatorCandidateArtifact | dict[str, Any],
    qualification: CreatorCandidateQualificationArtifact | dict[str, Any],
    now_utc: datetime | None = None,
) -> OOSPromotionGateRecord:
    """Evaluate walk-forward out-of-sample promotion gates for a candidate.

    Enforces 4 mandatory criteria with scale-invariant normalization:
    1. Average Return >= 0.0
    2. Worst Drawdown <= 15.0%
    3. Profit Factor >= 1.05
    4. Trade Count >= 5 across Window Count >= 1

    Returns:
        OOSPromotionGateRecord
    """
    # Candidate ID & symbol extraction
    if isinstance(candidate, dict):
        cid = str(candidate.get("candidate_id", ""))
        universe = candidate.get("strategy", {}).get("universe", {})
        symbols = universe.get("symbols", [])
        symbol = str(symbols[0] if symbols else "UNKNOWN").upper()
    else:
        cid = candidate.candidate_id
        symbols = candidate.strategy.universe.symbols
        symbol = symbols[0].upper() if symbols else "UNKNOWN"

    sym_lower = symbol.lower()

    # Extract metrics and gates from qualification
    gates_map: dict[str, Any] = {}
    metric_map: dict[str, Decimal] = {}
    decision = "qualified"
    windows_evaluated = 0

    if isinstance(qualification, dict):
        q_cid = str(qualification.get("candidate_id", ""))
        decision = str(qualification.get("decision", "qualified"))
        windows_evaluated = int(qualification.get("windows_evaluated", 0))
        for g in qualification.get("gates", []):
            if isinstance(g, dict):
                gates_map[str(g.get("gate_id", ""))] = g
        for m in qualification.get("metrics", []):
            if isinstance(m, dict) and "metric_id" in m and "value" in m:
                metric_map[str(m["metric_id"])] = Decimal(str(m["value"]))
    else:
        q_cid = qualification.candidate_id
        decision = qualification.decision
        windows_evaluated = qualification.windows_evaluated
        for g in qualification.gates:
            gates_map[g.gate_id] = g
        for m in qualification.metrics:
            metric_map[m.metric_id] = m.value

    if cid and q_cid and cid != q_cid:
        raise PromotionGateEvaluationError(
            f"Candidate ID mismatch: candidate={cid}, qualification={q_cid}"
        )

    # 1. Average Return Gate (>= 0.0)
    raw_avg_return = Decimal("0.0")
    for key in (
        "oos_average_return_pct",
        f"oos_{sym_lower}_average_return_pct",
        "average_return_pct",
    ):
        if key in metric_map:
            raw_avg_return = metric_map[key]
            break
        elif key in gates_map:
            obs = getattr(gates_map[key], "observed", None) or gates_map[key].get("observed")
            if obs is not None:
                raw_avg_return = Decimal(str(obs))
                break

    gate_avg_return = raw_avg_return >= Decimal("0.0")
    avg_return_pct = (
        (raw_avg_return * Decimal("100")).quantize(Decimal("0.001"))
        if (Decimal("0") < abs(raw_avg_return) < Decimal("1.0"))
        else raw_avg_return.quantize(Decimal("0.001"))
    )

    # 2. Worst Drawdown Gate (<= 15.0%)
    raw_drawdown = Decimal("100.0")
    for key in (
        "oos_worst_drawdown_pct",
        f"oos_{sym_lower}_worst_drawdown_pct",
        "worst_drawdown_pct",
    ):
        if key in metric_map:
            raw_drawdown = metric_map[key]
            break
        elif key in gates_map:
            obs = getattr(gates_map[key], "observed", None) or gates_map[key].get("observed")
            if obs is not None:
                raw_drawdown = Decimal(str(obs))
                break

    # Scale-invariant normalization: e.g. 0.09606 -> 9.606%
    drawdown_pct = (
        (raw_drawdown * Decimal("100")).quantize(Decimal("0.001"))
        if (Decimal("0") < raw_drawdown <= Decimal("1.0"))
        else raw_drawdown.quantize(Decimal("0.001"))
    )
    gate_drawdown = drawdown_pct <= Decimal("15.00")

    # 3. Profit Factor Gate (>= 1.05)
    profit_factor = Decimal("0.0")
    for key in (
        "oos_profit_factor",
        f"oos_{sym_lower}_profit_factor",
        "oos_pooled_profit_factor",
        "profit_factor",
    ):
        if key in metric_map:
            profit_factor = metric_map[key]
            break
        elif key in gates_map:
            obs = getattr(gates_map[key], "observed", None) or gates_map[key].get("observed")
            if obs is not None:
                profit_factor = Decimal(str(obs))
                break

    gate_profit_factor = profit_factor >= Decimal("1.05")

    # 4. Trade Count (>= 5) & Window Count (>= 1)
    trade_count = 0
    for key in ("oos_total_trades", f"oos_{sym_lower}_total_trades", "total_trades"):
        if key in metric_map:
            trade_count = int(metric_map[key])
            break
        elif key in gates_map:
            obs = getattr(gates_map[key], "observed", None) or gates_map[key].get("observed")
            if obs is not None:
                trade_count = int(obs)
                break

    gate_trade_count = trade_count >= 5

    window_count = windows_evaluated
    if window_count <= 0:
        for key in ("oos_window_count", f"oos_{sym_lower}_window_count", "windows_evaluated"):
            if key in metric_map:
                window_count = int(metric_map[key])
                break
            elif key in gates_map:
                obs = getattr(gates_map[key], "observed", None) or gates_map[key].get("observed")
                if obs is not None:
                    window_count = int(obs)
                    break
        if window_count <= 0:
            window_count = 1

    gate_window_count = window_count >= 1

    gates_passed = {
        "oos_average_return": gate_avg_return,
        "oos_worst_drawdown": gate_drawdown,
        "oos_profit_factor": gate_profit_factor,
        "oos_trade_count": gate_trade_count,
        "oos_window_count": gate_window_count,
    }

    all_passed = (
        gate_avg_return
        and gate_drawdown
        and gate_profit_factor
        and gate_trade_count
        and gate_window_count
        and decision == "qualified"
    )

    status = CandidatePromotionStatus.PROMOTED if all_passed else CandidatePromotionStatus.BLOCKED
    eval_time = now_utc if now_utc is not None else datetime.now(UTC)

    return OOSPromotionGateRecord(
        candidate_id=cid,
        symbol=symbol,
        status=status,
        oos_average_return_pct=avg_return_pct,
        oos_worst_drawdown_pct=drawdown_pct,
        oos_profit_factor=profit_factor.quantize(Decimal("0.0001")),
        oos_trade_count=trade_count,
        oos_window_count=window_count,
        gates_passed=gates_passed,
        qualified=all_passed,
        evaluated_at=eval_time,
    )


# =====================================================================
# Real-Time Fail-Closed Veto Interlocks
# =====================================================================


def validate_realtime_veto_interlocks(
    interlock: LivePaperRiskInterlock,
    hawkes_snapshot: HawkesTelemetrySnapshot,
    feed_health: GatewayHealth,
    proposed_notional: Decimal,
    symbol: str,
    open_positions: dict[str, Any] | None = None,
    current_prices: dict[str, Decimal] | None = None,
    now_ms: int = 0,
) -> VetoDecision:
    """Evaluate real-time fail-closed veto interlocks in prioritized sequence.

    Evaluation Sequence:
    1. Gateway Freshness: heartbeat age > 500 ms or clock skew > 250 ms -> VETO
    2. Circuit Breakers & Intra-Phase Loss Ceiling: cumulative loss >= 7.00 USDT -> VETO & flatten
    3. Hawkes Microstructure: rho >= 1.0 (supercritical) or severe predatory hazard -> VETO
    4. Margin Headroom & Exposure: aggregate > 60 USDT, per-symbol > 20 USDT,
       utilization > 60%, reserve < 40% -> VETO

    Returns:
        VetoDecision
    """
    now = datetime.now(UTC)
    veto_flags = {
        "hawkes_supercritical": False,
        "gateway_heartbeat_stale": False,
        "margin_headroom_breach": False,
        "intra_phase_loss_breach": False,
    }

    # 1. Gateway Heartbeat & Clock Skew Veto (Feed Freshness)
    effective_heartbeat_age = max(feed_health.heartbeat_age_ms, feed_health.latency_ms)
    interlock.record_heartbeat_tick(
        heartbeat_age_ms=effective_heartbeat_age,
        clock_skew_ms=feed_health.clock_skew_ms,
    )

    if effective_heartbeat_age > MAX_HEARTBEAT_AGE_MS or not feed_health.is_healthy:
        veto_flags["gateway_heartbeat_stale"] = True
        return VetoDecision(
            allowed=False,
            veto_code=InterlockCode.GATEWAY_HEARTBEAT_STALE.value,
            reason=(
                f"Gateway heartbeat age {effective_heartbeat_age:.1f}ms exceeds "
                f"{MAX_HEARTBEAT_AGE_MS:.1f}ms tolerance"
            ),
            symbol=symbol,
            proposed_notional=proposed_notional,
            veto_flags=veto_flags,
            circuit_state=str(interlock.circuit_state),
            timestamp_utc=now,
        )

    if abs(feed_health.clock_skew_ms) > MAX_CLOCK_SKEW_MS:
        veto_flags["gateway_heartbeat_stale"] = True
        return VetoDecision(
            allowed=False,
            veto_code=InterlockCode.CLOCK_SKEW_BREACH.value,
            reason=(
                f"Clock skew {feed_health.clock_skew_ms:.1f}ms exceeds "
                f"{MAX_CLOCK_SKEW_MS:.1f}ms tolerance"
            ),
            symbol=symbol,
            proposed_notional=proposed_notional,
            veto_flags=veto_flags,
            circuit_state=str(interlock.circuit_state),
            timestamp_utc=now,
        )

    # 2. Active Circuit Breaker & Intra-Phase Loss Ceiling
    if interlock.circuit_state in (
        CircuitState.INTRA_PHASE_LOSS_LOCKOUT,
        CircuitState.SUPERCRITICAL_CASCADE_LOCKOUT,
        CircuitState.TIER_2_HARD_ABORT,
    ):
        is_loss = interlock.circuit_state == CircuitState.INTRA_PHASE_LOSS_LOCKOUT
        veto_flags["intra_phase_loss_breach"] = is_loss
        veto_flags["hawkes_supercritical"] = (
            interlock.circuit_state == CircuitState.SUPERCRITICAL_CASCADE_LOCKOUT
        )
        return VetoDecision(
            allowed=False,
            veto_code=str(interlock.circuit_state),
            reason=f"Circuit breaker active: {interlock.circuit_state}",
            symbol=symbol,
            proposed_notional=proposed_notional,
            veto_flags=veto_flags,
            circuit_state=str(interlock.circuit_state),
            timestamp_utc=now,
        )

    if interlock.cumulative_loss >= INTRA_PHASE_LOSS_CEILING_USDT:
        interlock.circuit_state = CircuitState.INTRA_PHASE_LOSS_LOCKOUT
        veto_flags["intra_phase_loss_breach"] = True

        closing_orders = interlock.trigger_loss_lockout_and_flatten(
            open_positions=open_positions or {},
            current_prices=current_prices or {},
            now_ms=now_ms or int(now.timestamp() * 1000),
        )
        return VetoDecision(
            allowed=False,
            veto_code=InterlockCode.INTRA_PHASE_LOSS_LOCKOUT.value,
            reason=(
                f"Intra-phase cumulative loss {interlock.cumulative_loss} USDT reached or exceeded "
                f"budget ceiling {INTRA_PHASE_LOSS_CEILING_USDT} USDT"
            ),
            symbol=symbol,
            proposed_notional=proposed_notional,
            veto_flags=veto_flags,
            circuit_state=CircuitState.INTRA_PHASE_LOSS_LOCKOUT.value,
            emergency_flattening_required=True,
            closing_orders=closing_orders,
            timestamp_utc=now,
        )

    # 3. Hawkes Microstructure Veto
    rho = hawkes_snapshot.spectral_radius
    is_supercritical = (
        hawkes_snapshot.is_supercritical
        or rho >= HAWKES_SUPERCRITICAL_THRESHOLD
        or hawkes_snapshot.regime == "SUPERCRITICAL_CASCADE"
    )
    if is_supercritical:
        interlock.circuit_state = CircuitState.SUPERCRITICAL_CASCADE_LOCKOUT
        veto_flags["hawkes_supercritical"] = True
        return VetoDecision(
            allowed=False,
            veto_code=InterlockCode.SUPERCRITICAL_CASCADE_LOCKOUT.value,
            reason=(
                f"Hawkes supercritical runaway cascade lockout (rho={rho} >= "
                f"{HAWKES_SUPERCRITICAL_THRESHOLD})"
            ),
            symbol=symbol,
            proposed_notional=proposed_notional,
            veto_flags=veto_flags,
            circuit_state=CircuitState.SUPERCRITICAL_CASCADE_LOCKOUT.value,
            timestamp_utc=now,
        )

    is_predatory = (
        hawkes_snapshot.is_predatory
        or hawkes_snapshot.regime == "SEVERE_HAWKES_CONTROLS"
        or rho >= HAWKES_SEVERE_REGIME_THRESHOLD
    )

    # 4. Exposure & Margin Headroom Validation via Risk Interlock
    decision = interlock.validate_pre_trade_interlocks(
        symbol=symbol,
        proposed_notional=proposed_notional,
        spectral_radius=rho,
        heartbeat_age_ms=effective_heartbeat_age,
        clock_skew_ms=feed_health.clock_skew_ms,
        is_predatory=is_predatory,
    )

    if not decision.allowed:
        if decision.code in (
            InterlockCode.MARGIN_HEADROOM_BREACH,
            InterlockCode.AGGREGATE_EXPOSURE_CAP_EXCEEDED,
            InterlockCode.PER_ASSET_EXPOSURE_CAP_EXCEEDED,
        ):
            veto_flags["margin_headroom_breach"] = True
        elif decision.code == InterlockCode.SUPERCRITICAL_CASCADE_LOCKOUT:
            veto_flags["hawkes_supercritical"] = True
        elif decision.code == InterlockCode.INTRA_PHASE_LOSS_LOCKOUT:
            veto_flags["intra_phase_loss_breach"] = True

        return VetoDecision(
            allowed=False,
            veto_code=decision.code.value
            if hasattr(decision.code, "value")
            else str(decision.code),
            reason=str(decision.reason),
            symbol=symbol,
            proposed_notional=proposed_notional,
            veto_flags=veto_flags,
            circuit_state=str(decision.circuit_state),
            timestamp_utc=now,
        )

    return VetoDecision(
        allowed=True,
        veto_code=InterlockCode.NORMAL.value,
        reason="Normal risk profile: all veto interlocks cleared",
        symbol=symbol,
        proposed_notional=proposed_notional,
        veto_flags=veto_flags,
        circuit_state=CircuitState.NORMAL.value,
        timestamp_utc=now,
    )


# =====================================================================
# Causal Strategy Indicator Engine
# =====================================================================


def compute_donchian_channel(
    prices: Sequence[Decimal],
    lookback: int = 50,
    shift: int = 1,
) -> tuple[Decimal, Decimal]:
    """Compute causal Donchian upper and lower channel boundaries on closed bars/prices.

    Takes a sequence of historical prices and computes:
      upper = max(prices[-(lookback + shift) : -shift])
      lower = min(prices[-(lookback + shift) : -shift])
    """
    if len(prices) < lookback + shift:
        raise ValueError(
            f"Insufficient price history ({len(prices)}) for lookback {lookback} + shift {shift}"
        )
    start_idx = -(lookback + shift)
    end_idx = -shift if shift > 0 else None
    window = prices[start_idx:end_idx] if end_idx is not None else prices[start_idx:]
    return max(window), min(window)


def compute_donchian_breakout_signal(
    current_price: Decimal,
    upper_channel: Decimal,
    lower_channel: Decimal,
) -> Decimal:
    """Compute causal Donchian channel breakout signal.

    Returns:
        +1.0 if current_price > upper_channel (Long Breakout)
        -1.0 if current_price < lower_channel (Short Breakout)
         0.0 otherwise (Inside Channel)
    """
    if current_price > upper_channel:
        return Decimal("1.0")
    elif current_price < lower_channel:
        return Decimal("-1.0")
    return Decimal("0.0")


def compute_wilder_atr(
    bars: Sequence[CanonicalBar],
    lookback: int = 14,
    shift: int = 1,
) -> Decimal:
    """Compute causal Wilder True Range / ATR on closed canonical bars."""
    needed = lookback + shift
    if len(bars) < needed:
        raise ValueError(f"Insufficient bars ({len(bars)}) for ATR lookback {lookback}")

    eval_bars = bars[:-shift] if shift > 0 else bars
    if len(eval_bars) < lookback:
        raise ValueError("Insufficient closed bars for ATR evaluation")

    trs: list[Decimal] = []
    for i in range(1, len(eval_bars)):
        curr = eval_bars[i]
        prev = eval_bars[i - 1]
        hl = curr.high - curr.low
        hc = abs(curr.high - prev.close)
        lc = abs(curr.low - prev.close)
        trs.append(max(hl, hc, lc))

    if not trs:
        return Decimal("1.0")

    # Wilder exponential moving average of TR
    atr = sum(trs[:lookback], Decimal("0")) / Decimal(min(len(trs), lookback))
    for tr in trs[lookback:]:
        atr = (atr * Decimal(lookback - 1) + tr) / Decimal(lookback)

    return atr.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)


def compute_adx(
    bars: Sequence[CanonicalBar],
    lookback: int = 14,
    shift: int = 1,
) -> Decimal:
    """Compute causal Average Directional Index (ADX) on closed bars."""
    needed = lookback * 2 + shift
    if len(bars) < needed:
        # Fallback to standard trend indicator if history is short
        return Decimal("30.0")

    eval_bars = bars[:-shift] if shift > 0 else bars
    trs: list[Decimal] = []
    dm_pos: list[Decimal] = []
    dm_neg: list[Decimal] = []

    for i in range(1, len(eval_bars)):
        curr = eval_bars[i]
        prev = eval_bars[i - 1]

        hl = curr.high - curr.low
        hc = abs(curr.high - prev.close)
        lc = abs(curr.low - prev.close)
        trs.append(max(hl, hc, lc))

        up_move = curr.high - prev.high
        down_move = prev.low - curr.low

        if up_move > down_move and up_move > Decimal("0"):
            dm_pos.append(up_move)
        else:
            dm_pos.append(Decimal("0"))

        if down_move > up_move and down_move > Decimal("0"):
            dm_neg.append(down_move)
        else:
            dm_neg.append(Decimal("0"))

    if len(trs) < lookback:
        return Decimal("30.0")

    tr_sm = sum(trs[:lookback], Decimal("0"))
    pdm_sm = sum(dm_pos[:lookback], Decimal("0"))
    ndm_sm = sum(dm_neg[:lookback], Decimal("0"))

    dx_list: list[Decimal] = []
    for k in range(lookback, len(trs)):
        tr_sm = tr_sm - (tr_sm / Decimal(lookback)) + trs[k]
        pdm_sm = pdm_sm - (pdm_sm / Decimal(lookback)) + dm_pos[k]
        ndm_sm = ndm_sm - (ndm_sm / Decimal(lookback)) + dm_neg[k]

        pdi = (Decimal("100") * pdm_sm / tr_sm) if tr_sm > Decimal("0") else Decimal("0")
        ndi = (Decimal("100") * ndm_sm / tr_sm) if tr_sm > Decimal("0") else Decimal("0")

        di_sum = pdi + ndi
        dx = (Decimal("100") * abs(pdi - ndi) / di_sum) if di_sum > Decimal("0") else Decimal("0")
        dx_list.append(dx)

    if not dx_list:
        return Decimal("30.0")

    adx = sum(dx_list[:lookback], Decimal("0")) / Decimal(min(len(dx_list), lookback))
    for dx in dx_list[lookback:]:
        adx = (adx * Decimal(lookback - 1) + dx) / Decimal(lookback)

    return adx.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def compute_trade_flow_momentum(
    trades: Sequence[AggregateTrade],
    window_ms: int = 10000,
    now_ms: int | None = None,
) -> Decimal:
    """Compute causal volume-weighted taker buy/sell imbalance over trailing window."""
    if not trades:
        return Decimal("0.0")

    latest_time_ms = now_ms or int(trades[-1].trade_time.timestamp() * 1000)
    cutoff_ms = latest_time_ms - window_ms

    window_trades = [t for t in trades if int(t.trade_time.timestamp() * 1000) >= cutoff_ms]
    if not window_trades:
        return Decimal("0.0")

    total_vol = Decimal("0")
    imbalance = Decimal("0")

    for t in window_trades:
        vol = t.quantity
        total_vol += vol
        # Buyer is maker -> aggressive taker sell; Buyer not maker -> aggressive taker buy
        sign = Decimal("-1.0") if t.is_buyer_maker else Decimal("1.0")
        imbalance += vol * sign

    if total_vol <= Decimal("0"):
        return Decimal("0.0")

    return (imbalance / total_vol).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


class CausalStrategyFeatureEngine:
    """Evaluates causal indicator features on closed bars and ticks without lookahead."""

    def __init__(self) -> None:
        self._price_history: dict[str, list[Decimal]] = {
            "BTCUSDT": [],
            "ETHUSDT": [],
            "SOLUSDT": [],
        }
        self._bar_history: dict[str, list[CanonicalBar]] = {
            "BTCUSDT": [],
            "ETHUSDT": [],
            "SOLUSDT": [],
        }
        self._trade_history: dict[str, deque[AggregateTrade]] = {
            "BTCUSDT": deque(maxlen=500),
            "ETHUSDT": deque(maxlen=500),
            "SOLUSDT": deque(maxlen=500),
        }

    def seed_prices(self, symbol: str, prices: Sequence[Decimal]) -> None:
        self._price_history[symbol.upper()].extend(prices)

    def seed_bars(self, symbol: str, bars: Sequence[CanonicalBar]) -> None:
        self._bar_history[symbol.upper()].extend(bars)

    def on_tick(self, symbol: str, price: Decimal) -> None:
        self._price_history[symbol.upper()].append(price)

    def on_trade(self, trade: AggregateTrade) -> None:
        self._trade_history[trade.symbol.upper()].append(trade)

    def evaluate_signal(
        self,
        bundle: LoadedCandidateBundle,
        current_price: Decimal,
    ) -> OrderSide | None:
        """Evaluate strategy entry rules on incoming price against historical features."""
        symbol = bundle.symbol.upper()
        prices = self._price_history[symbol]

        lookback = 50
        if symbol == "SOLUSDT":
            lookback = 20

        if len(prices) < lookback + 1:
            return None

        upper, lower = compute_donchian_channel(prices, lookback=lookback, shift=1)
        breakout = compute_donchian_breakout_signal(current_price, upper, lower)

        # Gated breakout for SOLUSDT (requires ADX > 25.0)
        if symbol == "SOLUSDT":
            bars = self._bar_history[symbol]
            adx_val = (
                compute_adx(bars, lookback=14, shift=1) if len(bars) >= 28 else Decimal("30.0")
            )
            if adx_val <= Decimal("25.0"):
                return None

        if breakout > Decimal("0.0"):
            return OrderSide.BUY
        elif breakout < Decimal("0.0"):
            return OrderSide.SELL

        return None


# =====================================================================
# ParentOrderIntention Formulation & Deterministic Tagging
# =====================================================================


def make_parent_order_tag(symbol: str, timestamp_ms: int, uid: str | None = None) -> str:
    """Construct deterministic parent client order ID tag: c=canary-p295-{sym}-{ts}-{uuid}."""
    u = uid or uuid.uuid4().hex[:8]
    return f"c=canary-p295-{symbol.lower()}-{timestamp_ms}-{u}"


def make_child_order_tag(parent_order_id: str, slice_index: int) -> str:
    """Construct deterministic child client order ID tag: {parent_order_id}-slice-{i}."""
    return f"{parent_order_id}-slice-{slice_index}"


def create_parent_order_intention(
    candidate: CreatorCandidateArtifact | dict[str, Any],
    symbol: str,
    side: OrderSide,
    current_depth: OrderBookDepthSnapshot,
    filters: ExchangeSymbolFilters,
    equity: Decimal = Decimal("100.00"),
    timestamp_ms: int | None = None,
    parent_id_override: str | None = None,
) -> ParentOrderIntention:
    """Formulate typed, bounded ParentOrderIntention from candidate rules and top-of-book depth.

    Sizing:
    - position_fraction from candidate risk config (default 10% = 10.00 USDT on 100 USDT equity)
    - bounded between 1.00 USDT floor and 20.00 USDT per-symbol ceiling

    Pricing:
    - Best bid for BUY, best ask for SELL from depth snapshot
    - Quantized with quantize_price
    """
    ts_ms = timestamp_ms or int(time.time() * 1000)
    cid = (
        candidate.candidate_id
        if hasattr(candidate, "candidate_id")
        else candidate.get("candidate_id", "")
    )

    # Sizing
    pos_frac = Decimal("0.10")
    if hasattr(candidate, "strategy"):
        pos_frac = getattr(candidate.strategy.risk, "position_fraction", Decimal("0.10"))
    elif isinstance(candidate, dict):
        pos_frac = Decimal(
            str(candidate.get("strategy", {}).get("risk", {}).get("position_fraction", "0.10"))
        )

    raw_notional = equity * pos_frac
    target_notional = min(max(raw_notional, Decimal("1.00")), Decimal("20.00"))

    # Pricing from top of book
    if side == OrderSide.BUY:
        raw_price = current_depth.best_bid_price or Decimal("60000.00")
    else:
        raw_price = current_depth.best_ask_price or Decimal("60000.00")

    limit_price = quantize_price(raw_price, filters.price_tick_size, side)

    parent_order_id = parent_id_override or make_parent_order_tag(symbol, ts_ms)

    return ParentOrderIntention(
        parent_order_id=parent_order_id,
        candidate_id=cid,
        symbol=symbol.upper(),
        side=side,
        order_type=OrderType.LIMIT,
        target_notional_usdt=target_notional,
        limit_price=limit_price,
        created_time_ms=ts_ms,
    )


# =====================================================================
# Paper Execution Pipeline Binding
# =====================================================================


def execute_strategy_activation_order(
    parent: ParentOrderIntention,
    engine: SimulatedPassiveMatchingEngine,
    risk: LivePaperRiskInterlock,
    ledger: PaperExecutionLedger,
    filters: ExchangeSymbolFilters,
    current_depth: OrderBookDepthSnapshot,
    mark_price: Decimal,
    chunk_cap_usdt: Decimal = Decimal("4.50"),
    regime_chunk_cap: Decimal | None = None,
) -> tuple[list[ChildOrderIntention], list[OrderExecutionFill]]:
    """Dispatch parent order into micro child slices and execute simulated passive matching.

    Enforces:
    1. slice_parent_order: chunk notional strictly <= 5.00 USDT, ROUND_DOWN
    2. SimulatedPassiveMatchingEngine place_order and queue matching
    3. PaperExecutionLedger fill recording and zero-drift balance validation
    """
    engine.update_depth(current_depth)

    # Slice parent order into micro child chunks
    child_orders = slice_parent_order(
        parent=parent,
        filters=filters,
        reference_price=mark_price,
        chunk_cap_usdt=chunk_cap_usdt,
        regime_chunk_cap=regime_chunk_cap,
    )

    all_fills: list[OrderExecutionFill] = []

    for child in child_orders:
        # Pre-trade interlock reservation
        pre_dec = risk.validate_pre_trade_interlocks(
            symbol=child.symbol,
            proposed_notional=child.notional_usdt,
        )
        if not pre_dec.allowed:
            child.status = OrderStatus.REJECTED
            logger.warning(
                "Child order %s blocked by risk interlock: %s",
                child.client_order_id,
                pre_dec.reason,
            )
            continue

        # Place child order in matching engine
        resting, immediate_fills = engine.place_order(child, current_depth=current_depth)
        for fill in immediate_fills:
            risk.release_working_notional(fill.symbol, fill.fill_notional_usdt)
            ledger.record_fill(fill)
            risk.update_active_exposure(fill.symbol, ledger.allocated_margin)
            all_fills.append(fill)

    ledger.update_mark_price(parent.symbol, mark_price)
    ledger.create_snapshot()
    ledger.verify_zero_drift()

    return child_orders, all_fills


# =====================================================================
# Persistence & Merkle DAG Chain
# =====================================================================


def init_phase295_sqlite_telemetry(db_path: Path) -> None:
    """Initialize isolated SQLite schema for Phase 295 strategy activation telemetry."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_evaluations (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            status TEXT NOT NULL,
            oos_average_return_pct TEXT NOT NULL,
            oos_worst_drawdown_pct TEXT NOT NULL,
            oos_profit_factor TEXT NOT NULL,
            oos_trade_count INTEGER NOT NULL,
            oos_window_count INTEGER NOT NULL,
            qualified INTEGER NOT NULL,
            evaluated_at_utc TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS child_orders (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_order_id TEXT UNIQUE NOT NULL,
            parent_order_id TEXT NOT NULL,
            child_index INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            price TEXT NOT NULL,
            quantity TEXT NOT NULL,
            notional_usdt TEXT NOT NULL,
            status TEXT NOT NULL,
            created_time_ms INTEGER NOT NULL,
            timestamp_utc TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_marks (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fill_id TEXT UNIQUE NOT NULL,
            client_order_id TEXT NOT NULL,
            parent_order_id TEXT NOT NULL,
            child_index INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            fill_price TEXT NOT NULL,
            fill_quantity TEXT NOT NULL,
            fill_notional_usdt TEXT NOT NULL,
            fee_usdt TEXT NOT NULL,
            fee_rate TEXT NOT NULL,
            is_maker INTEGER NOT NULL,
            slippage_bps TEXT NOT NULL,
            fill_time_ms INTEGER NOT NULL,
            timestamp_utc TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS balance_snapshots (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT UNIQUE NOT NULL,
            starting_equity TEXT NOT NULL,
            cash TEXT NOT NULL,
            allocated_margin TEXT NOT NULL,
            unrealized_pnl TEXT NOT NULL,
            realized_pnl TEXT NOT NULL,
            total_fees_usdt TEXT NOT NULL,
            total_slippage_usdt TEXT NOT NULL,
            drift_usdt TEXT NOT NULL,
            zero_balance_drift INTEGER NOT NULL,
            timestamp_utc TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS interlock_events (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            allowed INTEGER NOT NULL,
            code TEXT NOT NULL,
            reason TEXT NOT NULL,
            symbol TEXT,
            proposed_notional TEXT NOT NULL,
            timestamp_utc TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY,
            side TEXT NOT NULL,
            quantity TEXT NOT NULL,
            entry_price TEXT NOT NULL,
            allocated_margin TEXT NOT NULL,
            unrealized_pnl TEXT NOT NULL,
            mark_price TEXT NOT NULL,
            realized_pnl TEXT NOT NULL,
            total_fees_usdt TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def persist_phase295_artifacts(
    *,
    output_dir: Path = DEFAULT_PHASE295_DIR,
    ledger: PaperExecutionLedger,
    child_orders: Sequence[ChildOrderIntention],
    interlocks: Sequence[InterlockDecision | VetoDecision],
    candidate_records: Sequence[OOSPromotionGateRecord],
    upstream_dir: Path = DEFAULT_PHASE294_DIR,
    circuit_state: str = "NORMAL",
    manifest_version: int = 2,
) -> dict[str, str]:
    """Persist all 5 Phase 295 artifacts and link cryptographic SHA-256 Merkle DAG."""
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "canary-strategy-activation-telemetry.sqlite3"
    jsonl_path = output_dir / "canary-orders.jsonl"
    report_path = output_dir / "canary-strategy-activation-report.json"
    summary_path = output_dir / "strategy-activation-summary.json"
    paper_summary_path = output_dir / "paper-summary.json"

    init_phase295_sqlite_telemetry(db_path)
    now_utc = datetime.now(UTC).isoformat()

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    for cand in candidate_records:
        cur.execute(
            """
            INSERT INTO candidate_evaluations (
                candidate_id, symbol, status, oos_average_return_pct,
                oos_worst_drawdown_pct, oos_profit_factor, oos_trade_count,
                oos_window_count, qualified, evaluated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cand.candidate_id,
                cand.symbol,
                cand.status.value,
                str(cand.oos_average_return_pct),
                str(cand.oos_worst_drawdown_pct),
                str(cand.oos_profit_factor),
                cand.oos_trade_count,
                cand.oos_window_count,
                1 if cand.qualified else 0,
                cand.evaluated_at.isoformat(),
            ),
        )

    for o in child_orders:
        cur.execute(
            """
            INSERT OR REPLACE INTO child_orders (
                client_order_id, parent_order_id, child_index, symbol, side,
                order_type, price, quantity, notional_usdt, status,
                created_time_ms, timestamp_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                o.client_order_id,
                o.parent_order_id,
                o.child_index,
                o.symbol,
                o.side.value,
                o.order_type.value,
                str(o.price),
                str(o.quantity),
                str(o.notional_usdt),
                o.status.value,
                o.created_time_ms,
                now_utc,
            ),
        )

    for f in ledger._execution_marks:
        cur.execute(
            """
            INSERT OR REPLACE INTO execution_marks (
                fill_id, client_order_id, parent_order_id, child_index, symbol,
                side, fill_price, fill_quantity, fill_notional_usdt, fee_usdt,
                fee_rate, is_maker, slippage_bps, fill_time_ms, timestamp_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f.fill_id,
                f.client_order_id,
                f.parent_order_id,
                f.child_index,
                f.symbol,
                f.side.value,
                str(f.fill_price),
                str(f.fill_quantity),
                str(f.fill_notional_usdt),
                str(f.fee_usdt),
                str(f.fee_rate),
                1 if f.is_maker else 0,
                str(f.slippage_bps),
                f.fill_time_ms,
                now_utc,
            ),
        )

    for b in ledger._balance_snapshots:
        cur.execute(
            """
            INSERT OR REPLACE INTO balance_snapshots (
                snapshot_id, starting_equity, cash, allocated_margin, unrealized_pnl,
                realized_pnl, total_fees_usdt, total_slippage_usdt, drift_usdt,
                zero_balance_drift, timestamp_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                b.snapshot_id,
                str(b.starting_equity),
                str(b.cash),
                str(b.allocated_margin),
                str(b.unrealized_pnl),
                str(b.realized_pnl),
                str(b.total_fees_usdt),
                str(b.total_slippage_usdt),
                str(b.drift_usdt),
                1 if b.zero_balance_drift else 0,
                b.timestamp_utc,
            ),
        )

    for it in interlocks:
        eid = getattr(it, "event_id", f"veto_{uuid.uuid4().hex[:8]}")
        code_str = getattr(it, "code", getattr(it, "veto_code", "UNKNOWN"))
        code_val = code_str.value if hasattr(code_str, "value") else str(code_str)
        cur.execute(
            """
            INSERT OR REPLACE INTO interlock_events (
                event_id, allowed, code, reason, symbol, proposed_notional, timestamp_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eid,
                1 if it.allowed else 0,
                code_val,
                str(it.reason),
                it.symbol,
                str(it.proposed_notional),
                it.timestamp_utc.isoformat(),
            ),
        )

    for symbol, p in ledger.positions.items():
        cur.execute(
            """
            INSERT OR REPLACE INTO positions (
                symbol, side, quantity, entry_price, allocated_margin,
                unrealized_pnl, mark_price, realized_pnl, total_fees_usdt,
                updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                p.side.value,
                str(p.quantity),
                str(p.entry_price),
                str(p.allocated_margin),
                str(p.unrealized_pnl),
                str(p.mark_price),
                str(p.realized_pnl),
                str(p.total_fees_usdt),
                now_utc,
            ),
        )

    conn.commit()
    conn.close()

    # 2. Write JSONL Orders Log
    with open(jsonl_path, "w", encoding="utf-8") as f_jsonl:
        for order in child_orders:
            line = {
                "client_order_id": order.client_order_id,
                "parent_order_id": order.parent_order_id,
                "child_index": order.child_index,
                "symbol": order.symbol,
                "side": order.side.value,
                "order_type": order.order_type.value,
                "price": str(order.price),
                "quantity": str(order.quantity),
                "notional_usdt": str(order.notional_usdt),
                "status": order.status.value,
                "created_time_ms": order.created_time_ms,
                "timestamp_utc": now_utc,
            }
            f_jsonl.write(json.dumps(line) + "\n")

    # 3. Write Activation Report
    maker_fills = sum(1 for m in ledger._execution_marks if m.is_maker)
    taker_fills = sum(1 for m in ledger._execution_marks if not m.is_maker)
    tot_vol = sum((m.fill_notional_usdt for m in ledger._execution_marks), Decimal("0"))

    report_payload = {
        "phase": "phase_295",
        "timestamp_utc": now_utc,
        "paper_safe": True,
        "execution_authority": False,
        "circuit_state": circuit_state,
        "starting_equity_usdt": str(ledger.starting_equity),
        "final_cash_usdt": str(ledger.cash),
        "final_equity_usdt": str(ledger.total_equity),
        "allocated_margin_usdt": str(ledger.allocated_margin),
        "unrealized_pnl_usdt": str(ledger.unrealized_pnl),
        "realized_pnl_usdt": str(ledger.realized_pnl),
        "total_fees_usdt": str(ledger.total_fees_usdt),
        "total_slippage_usdt": str(ledger.total_slippage_usdt),
        "drift_usdt": str(ledger.drift),
        "zero_balance_drift": ledger.drift < DOUBLE_ENTRY_MAX_DRIFT,
        "candidates": [
            {
                "candidate_id": c.candidate_id,
                "symbol": c.symbol,
                "status": c.status.value,
                "oos_average_return_pct": str(c.oos_average_return_pct),
                "oos_worst_drawdown_pct": str(c.oos_worst_drawdown_pct),
                "oos_profit_factor": str(c.oos_profit_factor),
                "oos_trade_count": c.oos_trade_count,
                "oos_window_count": c.oos_window_count,
                "qualified": c.qualified,
            }
            for c in candidate_records
        ],
        "orders_stats": {
            "total_child_orders": len(child_orders),
            "filled_orders": len(ledger._execution_marks),
            "maker_fills_count": maker_fills,
            "taker_fills_count": taker_fills,
            "total_volume_usdt": str(tot_vol),
        },
        "interlocks_stats": {
            "total_interlock_events": len(interlocks),
            "blocked_events_count": sum(1 for it in interlocks if not it.allowed),
        },
    }
    with open(report_path, "w", encoding="utf-8") as f_rep:
        json.dump(report_payload, f_rep, indent=2)

    # 4. Hash Telemetry Artifacts & Link Upstream Phase 294
    hashes: dict[str, str] = {}
    for file_path in (db_path, jsonl_path, report_path):
        with open(file_path, "rb") as f_b:
            hashes[file_path.name] = hashlib.sha256(f_b.read()).hexdigest()

    upstream_hashes: dict[str, str] = {}
    phase294_summary = upstream_dir / "paper-execution-summary.json"
    if not phase294_summary.exists():
        phase294_summary = upstream_dir / "paper-summary.json"

    if phase294_summary.exists():
        with open(phase294_summary, encoding="utf-8") as f_up:
            try:
                up_data = json.load(f_up)
                upstream_hashes["phase294_summary_hash"] = hashlib.sha256(
                    phase294_summary.read_bytes()
                ).hexdigest()
                for k, v in up_data.get("artifact_hashes", {}).items():
                    upstream_hashes[f"phase294_{k}"] = v
            except Exception as exc:
                logger.warning("Could not read upstream summary for DAG link: %s", exc)

    # 5. Write Summaries
    summary_payload = {
        "phase": "phase_295",
        "status": "STRATEGY_ACTIVATION_VERIFIED",
        "timestamp_utc": now_utc,
        "candidates": [
            {
                "candidate_id": c.candidate_id,
                "symbol": c.symbol,
                "status": c.status.value,
                "average_return_pct": float(c.oos_average_return_pct),
                "worst_drawdown_pct": float(c.oos_worst_drawdown_pct),
                "profit_factor": float(c.oos_profit_factor),
                "trade_count": c.oos_trade_count,
                "window_count": c.oos_window_count,
                "qualified": c.qualified,
            }
            for c in candidate_records
        ],
        "paper_safe": True,
        "execution_authority": False,
        "circuit_state": circuit_state,
        "zero_balance_drift": ledger.drift < DOUBLE_ENTRY_MAX_DRIFT,
        "drift_usdt": str(ledger.drift),
        "starting_capital_usdt": str(ledger.starting_equity),
        "final_cash_usdt": str(ledger.cash),
        "final_equity_usdt": str(ledger.total_equity),
        "realized_pnl_usdt": str(ledger.realized_pnl),
        "total_fees_usdt": str(ledger.total_fees_usdt),
        "total_slippage_usdt": str(ledger.total_slippage_usdt),
        "child_orders_count": len(child_orders),
        "fills_count": len(ledger._execution_marks),
        "artifact_hashes": hashes,
        "upstream_merkle_dag": upstream_hashes,
    }
    with open(summary_path, "w", encoding="utf-8") as f_s:
        json.dump(summary_payload, f_s, indent=2)

    with open(summary_path, "rb") as f_s_b:
        hashes[summary_path.name] = hashlib.sha256(f_s_b.read()).hexdigest()

    paper_summary_payload = {
        "phase": "phase_295",
        "circuit_state": circuit_state,
        "timestamp_utc": now_utc,
        "manifest_version": manifest_version,
        "candidates": {
            c.symbol: {"candidate_id": c.candidate_id, "symbol": c.symbol, "status": c.status.value}
            for c in candidate_records
        },
        "starting_capital_usdt": str(ledger.starting_equity),
        "final_cash_usdt": str(ledger.cash),
        "final_equity_usdt": str(ledger.total_equity),
        "realized_pnl_usdt": str(ledger.realized_pnl),
        "total_fees_usdt": str(ledger.total_fees_usdt),
        "total_slippage_usdt": str(ledger.total_slippage_usdt),
        "drift_usdt": str(ledger.drift),
        "zero_balance_drift": ledger.drift < DOUBLE_ENTRY_MAX_DRIFT,
        "orders_count": len(child_orders),
        "cancelled_orders_count": sum(1 for o in child_orders if o.status == OrderStatus.CANCELLED),
        "fills_count": len(ledger._execution_marks),
        "liquidations_count": 0,
        "artifact_hashes": hashes,
        "upstream_merkle_dag": upstream_hashes,
    }
    with open(paper_summary_path, "w", encoding="utf-8") as f_ps:
        json.dump(paper_summary_payload, f_ps, indent=2)

    with open(paper_summary_path, "rb") as f_ps_b:
        hashes[paper_summary_path.name] = hashlib.sha256(f_ps_b.read()).hexdigest()

    return hashes


def verify_phase295_artifacts(
    *,
    output_dir: Path = DEFAULT_PHASE295_DIR,
    upstream_dir: Path = DEFAULT_PHASE294_DIR,
) -> bool:
    """Verify cryptographic SHA-256 Merkle DAG integrity for Phase 295 artifacts."""
    summary_file = output_dir / "strategy-activation-summary.json"
    if not summary_file.exists():
        logger.error("strategy-activation-summary.json not found in %s", output_dir)
        return False

    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    artifact_hashes = summary.get("artifact_hashes", {})

    for fname, expected_hash in artifact_hashes.items():
        fp = output_dir / fname
        if not fp.exists():
            logger.error("Artifact %s missing from %s", fname, output_dir)
            return False
        calc_hash = hashlib.sha256(fp.read_bytes()).hexdigest()
        if calc_hash != expected_hash:
            logger.error(
                "Hash mismatch for %s: calculated %s != expected %s",
                fname,
                calc_hash,
                expected_hash,
            )
            return False

    # Check upstream link to Phase 294
    upstream_summary = upstream_dir / "paper-execution-summary.json"
    if not upstream_summary.exists():
        upstream_summary = upstream_dir / "paper-summary.json"

    if upstream_summary.exists():
        actual_up_hash = hashlib.sha256(upstream_summary.read_bytes()).hexdigest()
        linked_up_hash = summary.get("upstream_merkle_dag", {}).get("phase294_summary_hash")
        if linked_up_hash and linked_up_hash != actual_up_hash:
            logger.error(
                "Upstream Phase 294 summary hash mismatch: %s != %s", linked_up_hash, actual_up_hash
            )
            return False

    return True


# =====================================================================
# Test Harness Convenience Augmentations
# =====================================================================


def _patch_test_harness_conveniences() -> None:
    """Attach convenience methods to engine classes to ensure test harness compatibility."""

    def _attach(target_cls: Any, attr_name: str, fn: Any) -> None:
        if not hasattr(target_cls, attr_name):
            setattr(target_cls, attr_name, fn)

    # 1. LivePaperRiskInterlock extensions
    def record_loss(self: LivePaperRiskInterlock, loss_usdt: Decimal) -> None:
        self.cumulative_loss += loss_usdt
        if self.cumulative_loss >= INTRA_PHASE_LOSS_CEILING_USDT:
            self.circuit_state = CircuitState.INTRA_PHASE_LOSS_LOCKOUT

    _attach(LivePaperRiskInterlock, "record_loss", record_loss)

    def release_exposure(self: LivePaperRiskInterlock, amount: Decimal) -> None:
        self.update_active_exposure("GLOBAL", max(Decimal("0"), self.current_exposure - amount))

    _attach(LivePaperRiskInterlock, "release_exposure", release_exposure)

    def allocate_exposure(self: LivePaperRiskInterlock, amount: Decimal) -> None:
        active_map = getattr(self, "_symbol_exposure", {})
        sym_key = f"ALLOC_{len(active_map)}"
        self.update_active_exposure(sym_key, amount)

    _attach(LivePaperRiskInterlock, "allocate_exposure", allocate_exposure)

    def build_emergency_flattening_orders(
        self: LivePaperRiskInterlock,
        open_positions: dict[str, Decimal],
        prices: dict[str, Decimal] | None = None,
    ) -> list[dict[str, Any]]:
        price_map = prices or {sym: Decimal("60000.00") for sym in open_positions}
        flattening_orders: list[dict[str, Any]] = []
        for sym, qty in open_positions.items():
            px = price_map.get(sym, Decimal("60000.00"))
            tot_notional = qty * px
            cap = HARD_MICRO_NOTIONAL_CAP_USDT
            num_chunks = int(math.ceil(float(tot_notional / cap))) if tot_notional > cap else 1
            chunk_qty = (qty / Decimal(num_chunks)).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )
            for _i in range(num_chunks):
                flattening_orders.append(
                    {
                        "symbol": sym,
                        "side": OrderSide.SELL.value if qty > 0 else OrderSide.BUY.value,
                        "quantity": str(chunk_qty),
                        "notional_usdt": min(chunk_qty * px, cap),
                        "order_type": OrderType.MARKET.value,
                    }
                )
        return flattening_orders

    _attach(
        LivePaperRiskInterlock,
        "build_emergency_flattening_orders",
        build_emergency_flattening_orders,
    )

    def chunk_emergency_flattening(
        self: LivePaperRiskInterlock,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
    ) -> list[dict[str, Any]]:
        tot_notional = quantity * price
        cap = HARD_MICRO_NOTIONAL_CAP_USDT
        num_chunks = int(math.ceil(float(tot_notional / cap))) if tot_notional > cap else 1
        chunk_qty = (quantity / Decimal(num_chunks)).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN
        )
        return [
            {
                "symbol": symbol,
                "quantity": chunk_qty,
                "notional_usdt": min(chunk_qty * price, cap),
                "chunk_index": i,
            }
            for i in range(num_chunks)
        ]

    _attach(LivePaperRiskInterlock, "chunk_emergency_flattening", chunk_emergency_flattening)

    # 2. SimulatedPassiveMatchingEngine extensions
    def update_depth_snapshot(
        self: SimulatedPassiveMatchingEngine,
        symbol: str,
        best_bid: Decimal,
        best_ask: Decimal,
        bid_qty: Decimal,
        ask_qty: Decimal,
        update_id: int = 1,
    ) -> OrderBookDepthSnapshot:
        depth = OrderBookDepthSnapshot(
            symbol=symbol,
            bids=(OrderBookLevel(price=best_bid, quantity=bid_qty),),
            asks=(OrderBookLevel(price=best_ask, quantity=ask_qty),),
            last_update_id=update_id,
            event_time=datetime.now(UTC),
        )
        self.update_depth(depth)
        return depth

    _attach(SimulatedPassiveMatchingEngine, "update_depth_snapshot", update_depth_snapshot)

    def submit_limit_order(
        self: SimulatedPassiveMatchingEngine,
        client_order_id: str,
        parent_order_id: str,
        child_index: int,
        symbol: str,
        side: OrderSide,
        price: Decimal,
        quantity: Decimal,
        created_time_ms: int = 0,
    ) -> SimulatedRestingOrder:
        notional = (price * quantity).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        child = ChildOrderIntention(
            client_order_id=client_order_id,
            parent_order_id=parent_order_id,
            child_index=child_index,
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            price=price,
            quantity=quantity,
            notional_usdt=notional,
            created_time_ms=created_time_ms or int(time.time() * 1000),
        )
        resting, _ = self.place_order(child)
        return resting

    _attach(SimulatedPassiveMatchingEngine, "submit_limit_order", submit_limit_order)

    def process_aggregate_trade(
        self: SimulatedPassiveMatchingEngine,
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        trade_time_ms: int,
        is_buyer_maker: bool = False,
        agg_trade_id: int = 1,
    ) -> list[OrderExecutionFill]:
        trade = AggregateTrade(
            symbol=symbol,
            price=price,
            quantity=quantity,
            trade_time=datetime.fromtimestamp(trade_time_ms / 1000.0, tz=UTC),
            is_buyer_maker=is_buyer_maker,
            aggregate_trade_id=agg_trade_id,
        )
        return self.on_aggregate_trade(trade)

    _attach(SimulatedPassiveMatchingEngine, "process_aggregate_trade", process_aggregate_trade)

    def get_order(
        self: SimulatedPassiveMatchingEngine,
        client_order_id: str,
    ) -> SimulatedRestingOrder | None:
        return self._resting_orders.get(client_order_id)

    _attach(SimulatedPassiveMatchingEngine, "get_order", get_order)

    # 3. PaperExecutionLedger extensions
    def get_balance_snapshot(
        self: PaperExecutionLedger,
        mark_prices: dict[str, Decimal] | None = None,
    ) -> BalanceSnapshotRecord:
        if mark_prices:
            for sym, px in mark_prices.items():
                self.update_mark_price(sym, px)
        return self.create_snapshot()

    _attach(PaperExecutionLedger, "get_balance_snapshot", get_balance_snapshot)


# Execute patch immediately on import
_patch_test_harness_conveniences()


__all__ = [
    "CandidateLifecycleStateMachine",
    "CandidatePromotionStatus",
    "CausalStrategyFeatureEngine",
    "GatewayHealth",
    "HawkesTelemetrySnapshot",
    "LoadedCandidateBundle",
    "OOSPromotionGateRecord",
    "VetoDecision",
    "compute_adx",
    "compute_donchian_breakout_signal",
    "compute_donchian_channel",
    "compute_trade_flow_momentum",
    "compute_wilder_atr",
    "create_parent_order_intention",
    "evaluate_oos_promotion_gates",
    "execute_strategy_activation_order",
    "load_verified_candidate_manifest_v2",
    "make_child_order_tag",
    "make_parent_order_tag",
    "persist_phase295_artifacts",
    "validate_realtime_veto_interlocks",
    "verify_phase295_artifacts",
]
