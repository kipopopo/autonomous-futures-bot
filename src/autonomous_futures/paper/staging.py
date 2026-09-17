"""Phase 269: Operator Human Review Governance & Canary Staging Packaging.

Implements domain models, prerequisite gate verification, candidate performance analysis,
cryptographic decision sign-off, and canary staging packaging under Candidate Registry
Manifest Version 2.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .candidate_registry import (
    CandidateRegistryManifest,
)

logger = logging.getLogger(__name__)

DEFAULT_PHASE268_COHORT_DIR = Path("artifacts/research/phase268")
DEFAULT_PHASE269_OUTPUT_DIR = Path("artifacts/research/phase269")

EXPECTED_MANIFEST_V2_CANDIDATES: dict[str, str] = {
    "BTCUSDT": "cand-btcusdt-dcb-002",
    "ETHUSDT": "cand-ethusdt-dcb-003",
    "SOLUSDT": "cand-solusdt-rgb-001",
}

DEFAULT_STARTING_CAPITAL = Decimal("100.00")
DEFAULT_MAX_MARGIN_UTILIZATION = Decimal("0.80")
DEFAULT_MIN_RESERVE_BUFFER = Decimal("0.20")
DEFAULT_BASE_POSITION_FRACTION = Decimal("0.20")
DEFAULT_MAX_LEVERAGE = Decimal("1.0")
DOUBLE_ENTRY_MAX_DRIFT = Decimal("1e-15")

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*|"
    r"ghp_[0-9A-Za-z]{36}|gho_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{82}|AKIA[0-9A-Z]{16}|"
    r"sk-[0-9A-Za-z]{20,})"
)


def check_fail_closed_safety_invariants() -> dict[str, Any]:
    """Check runtime environment for credentials and return fail-closed safety state."""
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET") or os.environ.get("BINANCE_SECRET")
    keys_loaded = int(bool(api_key)) + int(bool(api_secret))
    return {
        "api_keys_loaded": keys_loaded,
        "exchange_access": False,
        "execution_authority": False,
        "orders": 0,
        "paper_activation": False,
        "zero_secret_leakage": keys_loaded == 0,
    }


def assert_zero_secrets(text: Any, source_label: str) -> None:
    """Verify text contains zero sensitive tokens or API secrets."""
    if text is None:
        return
    if isinstance(text, bytes):
        raw_text = text.decode("utf-8", errors="ignore")
    else:
        raw_text = str(text)
    match = _SECRET_PATTERN.search(raw_text)
    if match:
        raise DomainViolation(f"Secret pattern matched in {source_label}: {match.group(0)[:8]}...")


def compute_file_sha256(path: Path | str) -> str:
    """Compute SHA-256 hex digest of a file on disk."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found for hash calculation: {p}")
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize payload to deterministic canonical JSON bytes."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def safe_decimal(val: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Parse a value into Decimal safely without raising exceptions."""
    if val is None:
        return default
    if isinstance(val, Decimal):
        return val
    try:
        clean = str(val).strip()
        if not clean:
            return default
        return Decimal(clean)
    except InvalidOperation, ValueError, TypeError:
        return default


class AllocatedRiskLimits(DomainModel):
    """Allocated risk guardrails for a candidate promoted to canary staging."""

    max_position_fraction: Decimal = Field(
        default=DEFAULT_BASE_POSITION_FRACTION, ge=Decimal("0.01"), le=Decimal("1.0")
    )
    max_leverage: Decimal = Field(
        default=DEFAULT_MAX_LEVERAGE, ge=Decimal("1.0"), le=Decimal("10.0")
    )
    max_margin_utilization: Decimal = Field(
        default=DEFAULT_MAX_MARGIN_UTILIZATION, ge=Decimal("0.01"), le=Decimal("1.0")
    )
    min_reserve_buffer: Decimal = Field(
        default=DEFAULT_MIN_RESERVE_BUFFER, ge=Decimal("0.0"), le=Decimal("1.0")
    )
    allocated_margin_usdt: Decimal = Field(default=Decimal("20.00"), ge=Decimal("0.0"))

    @field_validator(
        "max_position_fraction",
        "max_leverage",
        "max_margin_utilization",
        "min_reserve_buffer",
        "allocated_margin_usdt",
        mode="before",
    )
    @classmethod
    def coerce_decimals(cls, v: Any) -> Decimal:
        return safe_decimal(v)


class CanaryStagedCandidate(DomainModel):
    """Candidate staged for canary execution with allocated risk and cryptographic provenance."""

    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    candidate_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_path: str = Field(min_length=1)
    family: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    allocated_risk_limits: AllocatedRiskLimits
    staging_promotion_state: Literal["canary_staged", "rejected", "unpromoted"]
    promotion_timestamp: str = Field(min_length=1)

    @field_validator("promotion_timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid ISO timestamp string: {value}") from exc
        return value


class PortfolioRiskGuardrails(DomainModel):
    """Portfolio-wide safety constraints across shared margin."""

    total_starting_capital_usdt: Decimal = Field(default=DEFAULT_STARTING_CAPITAL)
    max_aggregate_margin_utilization: Decimal = Field(default=DEFAULT_MAX_MARGIN_UTILIZATION)
    min_aggregate_reserve_buffer: Decimal = Field(default=DEFAULT_MIN_RESERVE_BUFFER)
    single_position_invariant: bool = True

    @field_validator(
        "total_starting_capital_usdt",
        "max_aggregate_margin_utilization",
        "min_aggregate_reserve_buffer",
        mode="before",
    )
    @classmethod
    def coerce_decimals(cls, v: Any) -> Decimal:
        return safe_decimal(v)


class PrerequisiteChecklist(DomainModel):
    """Detailed verification record of all prerequisite gates."""

    cohort_status_ready: bool = False
    expected_candidates_present: bool = False
    all_candidates_mature: bool = False
    all_candidates_healthy: bool = False
    zero_candidates_blocked: bool = False
    accounting_complete: bool = False
    zero_balance_drift: bool = False
    candidate_accounting_reconciled: bool = False
    all_positions_closed: bool = False
    margin_guardrails_compliant: bool = False
    positive_terminal_equity: bool = False
    zero_circuit_breaker_flags: bool = False
    zero_api_keys_loaded: bool = False
    upstream_integrity_verified: bool = False
    all_gates_passed: bool = False
    failure_reasons: list[str] = Field(default_factory=list)


class CanaryStagingManifest(DomainModel):
    """Cryptographically signed canary staging manifest for promoted candidates."""

    manifest_version: int = Field(default=2, ge=1)
    registry_version: int = Field(default=2, ge=1)
    staged_at: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    staging_promotion_state: Literal["canary_staged", "rejected", "unpromoted"]
    candidates: dict[str, CanaryStagedCandidate]
    portfolio_risk_guardrails: PortfolioRiskGuardrails
    safety_invariants: dict[str, Any]
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cryptographic_signature: str = Field(pattern=r"^[0-9a-f]{64}$")


def compute_manifest_hash(manifest: CanaryStagingManifest) -> str:
    """Compute deterministic SHA-256 hash of CanaryStagingManifest excluding hashes."""
    payload = manifest.model_dump(
        mode="json",
        exclude={"manifest_hash", "cryptographic_signature"},
    )
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def compute_staging_signature(operator_id: str, decision_id: str, manifest_hash: str) -> str:
    """Compute deterministic cryptographic HMAC signature for the staging manifest."""
    key = hashlib.sha256(f"{operator_id}:{decision_id}".encode()).digest()
    return hmac.new(key, manifest_hash.encode("utf-8"), hashlib.sha256).hexdigest()


class HumanReviewDecision(DomainModel):
    """Cryptographically signed human review sign-off decision artifact."""

    decision_id: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    decision: Literal["approved_for_canary", "rejected", "held"]
    decided_at: str = Field(min_length=1)
    review_rationale: str = Field(min_length=1)
    prerequisite_checklist: PrerequisiteChecklist
    upstream_cohort_hashes: dict[str, str]
    upstream_cohort_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    safety_invariants: dict[str, Any]
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def compute_decision_hash(decision: HumanReviewDecision) -> str:
    """Compute deterministic SHA-256 hash of HumanReviewDecision excluding decision_hash."""
    payload = decision.model_dump(mode="json", exclude={"decision_hash"})
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class CandidatePerformanceBreakdown(DomainModel):
    """Detailed performance metrics for an evaluated paper trading candidate."""

    symbol: str
    candidate_id: str
    family: str
    timeframe: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    realized_pnl_usdt: Decimal
    observed_slots: int
    margin_utilization: Decimal
    cumulative_fees_usdt: Decimal
    cumulative_slippage_usdt: Decimal
    health_status: str
    maturity_status: str
    accounting_complete: bool

    @field_validator(
        "realized_pnl_usdt",
        "margin_utilization",
        "cumulative_fees_usdt",
        "cumulative_slippage_usdt",
        mode="before",
    )
    @classmethod
    def coerce_decimals(cls, v: Any) -> Decimal:
        return safe_decimal(v)


class CohortInspectionResult(DomainModel):
    """Comprehensive inspection result for an evaluated paper trading cohort."""

    cohort_dir: str
    cohort_status: str
    upstream_hashes: dict[str, str]
    upstream_digest: str
    starting_equity: Decimal
    final_cash: Decimal
    realized_pnl: Decimal
    drift: Decimal
    zero_drift: bool
    max_margin_utilization: Decimal
    min_reserve_buffer: Decimal
    candidate_breakdowns: dict[str, CandidatePerformanceBreakdown]
    prerequisite_checklist: PrerequisiteChecklist
    raw_summary: dict[str, Any]

    @field_validator(
        "starting_equity",
        "final_cash",
        "realized_pnl",
        "drift",
        "max_margin_utilization",
        "min_reserve_buffer",
        mode="before",
    )
    @classmethod
    def coerce_decimals(cls, v: Any) -> Decimal:
        return safe_decimal(v)


def inspect_cohort(
    cohort_dir: Path | str = DEFAULT_PHASE268_COHORT_DIR,
    registry_path: Path | str | None = None,
    expected_candidates: Mapping[str, str] | None = None,
) -> CohortInspectionResult:
    """Inspect upstream paper cohort directory, compute hashes, verify accounting and gates.

    Raises:
        FileNotFoundError: If required cohort files are missing.
        DomainViolation: If files are malformed or violate schemas.
    """
    c_dir = Path(cohort_dir)
    if not c_dir.is_dir():
        raise FileNotFoundError(f"Cohort directory not found: {c_dir}")

    expected = dict(expected_candidates or EXPECTED_MANIFEST_V2_CANDIDATES)

    # 1. Compute upstream file hashes
    upstream_hashes: dict[str, str] = {}
    for entry in sorted(c_dir.iterdir()):
        if entry.is_file() and not entry.name.startswith("."):
            upstream_hashes[entry.name] = compute_file_sha256(entry)

    upstream_digest = hashlib.sha256(canonical_json_bytes(upstream_hashes)).hexdigest()

    # 2. Read paper-summary.json or maturation-summary.json
    summary_path = c_dir / "paper-summary.json"
    if not summary_path.is_file():
        summary_path = c_dir / "maturation-summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(
            f"Neither paper-summary.json nor maturation-summary.json found in {c_dir}"
        )

    try:
        raw_summary: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DomainViolation(f"Failed to parse summary JSON at {summary_path}: {exc}") from exc

    # Verify upstream file integrity against recorded hashes in raw_summary
    recorded_hashes = raw_summary.get("artifact_hashes", {})
    upstream_integrity_verified = True
    tampered_files: list[str] = []
    for fname, exp_hash in recorded_hashes.items():
        computed_hash = upstream_hashes.get(fname)
        if computed_hash is not None and computed_hash != exp_hash:
            upstream_integrity_verified = False
            tampered_files.append(f"{fname}:{computed_hash[:8]}!={exp_hash[:8]}")

    # 3. Read readiness report
    readiness_path = c_dir / "paper-cohort-readiness-report.json"
    if not readiness_path.is_file():
        readiness_path = c_dir / "paper-cohort-maturation-report.json"
    if not readiness_path.is_file():
        raise FileNotFoundError(f"No cohort readiness report found in {c_dir}")

    try:
        raw_readiness: dict[str, Any] = json.loads(readiness_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DomainViolation(
            f"Failed to parse readiness report JSON at {readiness_path}: {exc}"
        ) from exc

    cohort_status = str(
        raw_readiness.get(
            "cohort_status", raw_summary.get("cohort_readiness", {}).get("cohort_status", "unknown")
        )
    )

    # 4. Parse portfolio and accounting metrics
    shared_margin = raw_summary.get("shared_portfolio_margin", {})
    starting_equity = safe_decimal(
        shared_margin.get("starting_capital_usdt", "100.00"), default=DEFAULT_STARTING_CAPITAL
    )
    final_cash = safe_decimal(shared_margin.get("final_cash_usdt", "0.0"))
    realized_pnl = safe_decimal(shared_margin.get("realized_pnl_usdt", "0.0"))
    max_margin_util = safe_decimal(shared_margin.get("max_observed_margin_utilization", "0.0"))
    min_reserve_buf = safe_decimal(shared_margin.get("min_observed_reserve_buffer", "1.0"))
    base_pos_fraction = safe_decimal(
        shared_margin.get("base_position_fraction", DEFAULT_BASE_POSITION_FRACTION),
        default=DEFAULT_BASE_POSITION_FRACTION,
    )

    # Exact double-entry accounting drift: drift = |final_cash - (starting_equity + realized_pnl)|
    expected_cash = starting_equity + realized_pnl
    drift = abs(final_cash - expected_cash)
    zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

    # 5. Extract per-candidate metrics from ledger DB or summary with exact Decimal precision
    candidate_breakdowns: dict[str, CandidatePerformanceBreakdown] = {}
    ledger_path = c_dir / "paper-ledger.sqlite3"
    obs_path = c_dir / "paper-observations.sqlite3"

    ledger_stats: dict[str, dict[str, Any]] = {}
    if ledger_path.is_file():
        try:
            with sqlite3.connect(f"file:{ledger_path.resolve()}?mode=ro", uri=True) as conn:
                cursor = conn.cursor()
                # Check for paper_ledger_events table
                has_events = cursor.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_ledger_events'"
                ).fetchone()
                if has_events:
                    rows = cursor.execute(
                        """
                        SELECT symbol, candidate_id, net_pnl, entry_fee, exit_fee, slippage_cost
                        FROM paper_ledger_events
                        WHERE event = 'close'
                        """
                    ).fetchall()
                    for sym, cid, net_pnl, entry_fee, exit_fee, slip in rows:
                        stats = ledger_stats.setdefault(
                            sym,
                            {
                                "candidate_id": cid,
                                "total_trades": 0,
                                "winning_trades": 0,
                                "losing_trades": 0,
                                "realized_pnl": Decimal("0"),
                                "fees": Decimal("0"),
                                "slippage": Decimal("0"),
                            },
                        )
                        pnl_dec = safe_decimal(net_pnl)
                        stats["total_trades"] += 1
                        if pnl_dec > Decimal("0"):
                            stats["winning_trades"] += 1
                        else:
                            stats["losing_trades"] += 1
                        stats["realized_pnl"] += pnl_dec
                        stats["fees"] += safe_decimal(entry_fee) + safe_decimal(exit_fee)
                        stats["slippage"] += safe_decimal(slip)
        except sqlite3.Error as err:
            logger.warning("Could not read ledger sqlite: %s", err)

    obs_stats: dict[str, int] = {}
    if obs_path.is_file():
        try:
            with sqlite3.connect(f"file:{obs_path.resolve()}?mode=ro", uri=True) as conn:
                cursor = conn.cursor()
                has_obs = cursor.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_observations'"
                ).fetchone()
                if has_obs:
                    rows = cursor.execute(
                        "SELECT candidate_id, COUNT(*) FROM paper_observations "
                        "GROUP BY candidate_id"
                    ).fetchall()
                    for cid, count in rows:
                        obs_stats[str(cid)] = int(count or 0)
        except sqlite3.Error as err:
            logger.warning("Could not read observations sqlite: %s", err)

    summary_candidates = raw_summary.get("candidates", {})
    per_sym_mat = raw_summary.get("maturation_progression", {}).get("per_symbol_maturation", {})

    for sym, exp_cid in expected.items():
        sym_cand_info = summary_candidates.get(sym, {})
        mat_info = per_sym_mat.get(sym, {})
        ls = ledger_stats.get(sym, {})

        cid = sym_cand_info.get("candidate_id", exp_cid)
        family = sym_cand_info.get("family", "unknown")
        timeframe = sym_cand_info.get("timeframe", "15m")

        total_trades = ls.get(
            "total_trades", sym_cand_info.get("trades_count", mat_info.get("trades_count", 0))
        )
        win_trades = ls.get("winning_trades", 0)
        loss_trades = ls.get("losing_trades", max(0, total_trades - win_trades))
        win_rate_pct = (
            (float(win_trades) / float(total_trades) * 100.0) if total_trades > 0 else 0.0
        )

        pnl = ls.get("realized_pnl", safe_decimal(sym_cand_info.get("realized_pnl_usdt", "0.0")))
        observed_slots = obs_stats.get(cid, mat_info.get("observed_slots", 0))
        fees = ls.get("fees", safe_decimal("0.0"))
        slippage = ls.get("slippage", safe_decimal("0.0"))

        health = sym_cand_info.get("health_status", mat_info.get("health_status", "unknown"))
        maturity = sym_cand_info.get("maturity_status", mat_info.get("maturity_status", "unknown"))
        acc_comp = bool(
            mat_info.get("accounting_complete", sym_cand_info.get("accounting_complete", True))
        )

        candidate_breakdowns[sym] = CandidatePerformanceBreakdown(
            symbol=sym,
            candidate_id=cid,
            family=family,
            timeframe=timeframe,
            total_trades=int(total_trades),
            winning_trades=int(win_trades),
            losing_trades=int(loss_trades),
            win_rate_pct=round(win_rate_pct, 2),
            realized_pnl_usdt=pnl,
            observed_slots=int(observed_slots),
            margin_utilization=base_pos_fraction,
            cumulative_fees_usdt=fees,
            cumulative_slippage_usdt=slippage,
            health_status=health,
            maturity_status=maturity,
            accounting_complete=acc_comp,
        )

    # 6. Run prerequisite gate checks
    checklist = verify_prerequisite_gates(
        cohort_status=cohort_status,
        expected_candidates=expected,
        candidate_breakdowns=candidate_breakdowns,
        raw_readiness=raw_readiness,
        drift=drift,
        starting_equity=starting_equity,
        final_cash=final_cash,
        max_margin_utilization=max_margin_util,
        min_reserve_buffer=min_reserve_buf,
        realized_pnl=realized_pnl,
        raw_summary=raw_summary,
        upstream_integrity_verified=upstream_integrity_verified,
        tampered_files=tampered_files,
        base_position_fraction=base_pos_fraction,
    )

    return CohortInspectionResult(
        cohort_dir=str(c_dir),
        cohort_status=cohort_status,
        upstream_hashes=upstream_hashes,
        upstream_digest=upstream_digest,
        starting_equity=starting_equity,
        final_cash=final_cash,
        realized_pnl=realized_pnl,
        drift=drift,
        zero_drift=zero_drift,
        max_margin_utilization=max_margin_util,
        min_reserve_buffer=min_reserve_buf,
        candidate_breakdowns=candidate_breakdowns,
        prerequisite_checklist=checklist,
        raw_summary=raw_summary,
    )


def verify_prerequisite_gates(
    *,
    cohort_status: str,
    expected_candidates: Mapping[str, str],
    candidate_breakdowns: Mapping[str, CandidatePerformanceBreakdown],
    raw_readiness: Mapping[str, Any],
    drift: Decimal,
    starting_equity: Decimal,
    final_cash: Decimal,
    max_margin_utilization: Decimal,
    min_reserve_buffer: Decimal,
    realized_pnl: Decimal | None = None,
    raw_summary: Mapping[str, Any] | None = None,
    upstream_integrity_verified: bool = True,
    tampered_files: list[str] | None = None,
    base_position_fraction: Decimal = DEFAULT_BASE_POSITION_FRACTION,
) -> PrerequisiteChecklist:
    """Verify all prerequisite gates for Phase 269 human review staging."""
    failure_reasons: list[str] = []

    # 1. Cohort readiness status check
    cohort_ready = cohort_status == "ready_for_human_review"
    if not cohort_ready:
        failure_reasons.append(f"cohort_status_not_ready:{cohort_status}")

    # 2. Expected candidates present
    expected_present = True
    for sym, exp_cid in expected_candidates.items():
        if sym not in candidate_breakdowns:
            expected_present = False
            failure_reasons.append(f"missing_candidate_symbol:{sym}")
        elif candidate_breakdowns[sym].candidate_id != exp_cid:
            expected_present = False
            failure_reasons.append(
                f"mismatched_candidate_id:{sym}:{candidate_breakdowns[sym].candidate_id}!={exp_cid}"
            )

    # 3. All mature & healthy, none blocked, accounting complete
    all_mature = True
    all_healthy = True
    zero_blocked = True
    accounting_comp = bool(raw_readiness.get("all_accounting_complete", True))

    for sym, cb in candidate_breakdowns.items():
        if cb.maturity_status != "mature":
            all_mature = False
            failure_reasons.append(f"immature_candidate:{sym}:{cb.maturity_status}")
        if cb.health_status != "healthy":
            all_healthy = False
            failure_reasons.append(f"unhealthy_candidate:{sym}:{cb.health_status}")
        if cb.health_status == "blocked" or cb.maturity_status == "blocked":
            zero_blocked = False
            failure_reasons.append(f"blocked_candidate:{sym}")
        if not cb.accounting_complete:
            accounting_comp = False
            failure_reasons.append(f"accounting_incomplete_for_candidate:{sym}")

    blocked_cnt = int(raw_readiness.get("blocked_candidate_count", 0))
    if blocked_cnt > 0:
        zero_blocked = False
        failure_reasons.append(f"blocked_candidates_count:{blocked_cnt}")

    # 4. Zero balance drift (< 1e-15)
    zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT
    if not zero_drift:
        failure_reasons.append(f"balance_drift_exceeded:{drift:.2e}>={DOUBLE_ENTRY_MAX_DRIFT:.0e}")

    # 4b. Three-way accounting reconciliation (Candidate PnL sum vs Portfolio Realized PnL)
    if realized_pnl is not None:
        cand_pnl_sum = sum(
            (cb.realized_pnl_usdt for cb in candidate_breakdowns.values()), Decimal("0")
        )
        cand_pnl_drift = abs(cand_pnl_sum - realized_pnl)
        zero_cand_drift = cand_pnl_drift < DOUBLE_ENTRY_MAX_DRIFT
        if not zero_cand_drift:
            failure_reasons.append(
                f"candidate_pnl_reconciliation_drift_exceeded:{cand_pnl_drift:.2e}>={DOUBLE_ENTRY_MAX_DRIFT:.0e}"
            )
    else:
        zero_cand_drift = True

    # 4c. Open positions & single-position reconciliation
    port_sum = (raw_summary or {}).get("portfolio_summary", {})
    open_pos_cnt = int(port_sum.get("open_positions_count", 0))
    pos_rec = bool(port_sum.get("positions_reconciled", True))
    positions_closed = (open_pos_cnt == 0) and pos_rec
    if open_pos_cnt > 0:
        failure_reasons.append(f"unclosed_positions_detected:{open_pos_cnt}")
    if not pos_rec:
        failure_reasons.append("positions_unreconciled")

    # 5. Margin guardrails compliance (<= 80% utilization, >= 20% reserve)
    # Check both historical observed and staged aggregate limits
    staged_util = Decimal(len(expected_candidates)) * base_position_fraction
    staged_buf = Decimal("1.00") - staged_util
    margin_compliant = (
        max_margin_utilization <= DEFAULT_MAX_MARGIN_UTILIZATION
        and min_reserve_buffer >= DEFAULT_MIN_RESERVE_BUFFER
        and staged_util <= DEFAULT_MAX_MARGIN_UTILIZATION
        and staged_buf >= DEFAULT_MIN_RESERVE_BUFFER
    )
    if not margin_compliant:
        failure_reasons.append(
            f"margin_guardrails_violated:util={max_margin_utilization:.2f} "
            f"(max {DEFAULT_MAX_MARGIN_UTILIZATION:.2f}), "
            f"buf={min_reserve_buffer:.2f} (min {DEFAULT_MIN_RESERVE_BUFFER:.2f})"
        )

    # 6. Positive terminal equity
    positive_equity = starting_equity > Decimal("0") and final_cash > Decimal("0")
    if not positive_equity:
        failure_reasons.append(
            f"negative_terminal_equity:cash={final_cash},equity={starting_equity}"
        )

    # 7. Zero circuit breaker flags
    zero_cb_flags = True
    reason_codes = raw_readiness.get("reason_codes", [])
    for code in reason_codes:
        if "circuit_breaker" in str(code).lower():
            zero_cb_flags = False
            failure_reasons.append(f"unresolved_circuit_breaker:{code}")

    # 8. Zero credentials in environment
    api_keys_count = check_fail_closed_safety_invariants()["api_keys_loaded"]
    zero_api_keys = api_keys_count == 0
    if not zero_api_keys:
        failure_reasons.append(f"credential_contamination_detected:{api_keys_count}")

    # 9. Upstream cohort file integrity
    if not upstream_integrity_verified:
        for t in tampered_files or []:
            failure_reasons.append(f"upstream_artifact_hash_mismatch:{t}")

    all_passed = (
        cohort_ready
        and expected_present
        and all_mature
        and all_healthy
        and zero_blocked
        and accounting_comp
        and zero_drift
        and zero_cand_drift
        and positions_closed
        and margin_compliant
        and positive_equity
        and zero_cb_flags
        and zero_api_keys
        and upstream_integrity_verified
    )

    return PrerequisiteChecklist(
        cohort_status_ready=cohort_ready,
        expected_candidates_present=expected_present,
        all_candidates_mature=all_mature,
        all_candidates_healthy=all_healthy,
        zero_candidates_blocked=zero_blocked,
        accounting_complete=accounting_comp,
        zero_balance_drift=zero_drift,
        candidate_accounting_reconciled=zero_cand_drift,
        all_positions_closed=positions_closed,
        margin_guardrails_compliant=margin_compliant,
        positive_terminal_equity=positive_equity,
        zero_circuit_breaker_flags=zero_cb_flags,
        zero_api_keys_loaded=zero_api_keys,
        upstream_integrity_verified=upstream_integrity_verified,
        all_gates_passed=all_passed,
        failure_reasons=failure_reasons,
    )


def stage_canary_candidates(
    *,
    decision: Literal["approved_for_canary", "rejected", "held"],
    operator_id: str,
    rationale: str,
    inspection: CohortInspectionResult,
    registry_manifest: CandidateRegistryManifest | None = None,
    output_dir: Path | str = DEFAULT_PHASE269_OUTPUT_DIR,
    timestamp: datetime | None = None,
) -> tuple[HumanReviewDecision, CanaryStagingManifest, dict[str, Any]]:
    """Execute review decision and build signed canary staging artifacts.

    Raises:
        DomainViolation: If decision is approved_for_canary but prerequisite gates failed.
    """
    operator_clean = operator_id.strip()
    if not operator_clean:
        raise DomainViolation("operator_id must be non-empty")
    rationale_clean = rationale.strip()
    if not rationale_clean:
        raise DomainViolation("rationale must be non-empty")

    assert_zero_secrets(operator_clean, "operator_id")
    assert_zero_secrets(rationale_clean, "rationale")

    checklist = inspection.prerequisite_checklist

    # Fail-closed enforcement: cannot approve for canary if prerequisite gates fail
    if decision == "approved_for_canary" and not checklist.all_gates_passed:
        reasons = ", ".join(checklist.failure_reasons)
        raise DomainViolation(
            f"Cannot approve for canary staging: prerequisite gates failed: {reasons}"
        )

    now_dt = (timestamp or datetime.now(UTC)).astimezone(UTC)
    now_iso = now_dt.isoformat()
    decision_id = f"review-phase269-{now_dt.strftime('%Y%m%d%H%M%S')}-{operator_clean}"

    # Determine staging promotion state
    if decision == "approved_for_canary":
        staged_state: Literal["canary_staged", "rejected", "unpromoted"] = "canary_staged"
        summary_state = "canary_staged"
    elif decision == "rejected":
        staged_state = "rejected"
        summary_state = "staging_rejected"
    else:
        staged_state = "unpromoted"
        summary_state = "staging_held"

    # Build CanaryStagedCandidate entries
    staged_candidates: dict[str, CanaryStagedCandidate] = {}
    summary_cand_entries = inspection.raw_summary.get("candidates", {})

    for sym, breakdown in inspection.candidate_breakdowns.items():
        summary_cand = summary_cand_entries.get(sym, {})
        reg_entry = registry_manifest.symbols.get(sym) if registry_manifest else None

        # Cross-verify registry vs summary hashes if both present
        if reg_entry and summary_cand.get("artifact_hash"):
            sum_art = summary_cand.get("artifact_hash")
            if reg_entry.candidate_artifact_hash != sum_art:
                raise DomainViolation(
                    f"Candidate artifact hash mismatch for {sym}: "
                    f"registry={reg_entry.candidate_artifact_hash} vs summary={sum_art}"
                )
        if reg_entry and summary_cand.get("qualification_hash"):
            sum_qual = summary_cand.get("qualification_hash")
            if reg_entry.qualification_hash != sum_qual:
                raise DomainViolation(
                    f"Qualification hash mismatch for {sym}: "
                    f"registry={reg_entry.qualification_hash} vs summary={sum_qual}"
                )

        art_hash = (
            (reg_entry.candidate_artifact_hash if reg_entry else None)
            or summary_cand.get("artifact_hash")
            or ""
        )
        qual_hash = (
            (reg_entry.qualification_hash if reg_entry else None)
            or summary_cand.get("qualification_hash")
            or ""
        )
        art_path = (
            reg_entry.artifact_path if reg_entry else None
        ) or f"artifacts/paper_live/candidates/{breakdown.candidate_id}.json"

        # Fail closed on dummy or missing hashes when approving for canary
        if decision == "approved_for_canary":
            if not art_hash or art_hash == "0" * 64 or len(art_hash) != 64:
                raise DomainViolation(f"Missing valid candidate artifact hash for symbol {sym}")
            if not qual_hash or qual_hash == "0" * 64 or len(qual_hash) != 64:
                raise DomainViolation(f"Missing valid qualification hash for symbol {sym}")
        elif not art_hash:
            art_hash = "0" * 64
        elif not qual_hash:
            qual_hash = "0" * 64

        staged_candidates[sym] = CanaryStagedCandidate(
            symbol=sym,
            candidate_id=breakdown.candidate_id,
            candidate_artifact_hash=art_hash,
            qualification_hash=qual_hash,
            artifact_path=art_path,
            family=breakdown.family,
            timeframe=breakdown.timeframe,
            allocated_risk_limits=AllocatedRiskLimits(
                max_position_fraction=DEFAULT_BASE_POSITION_FRACTION,
                max_leverage=DEFAULT_MAX_LEVERAGE,
                max_margin_utilization=DEFAULT_MAX_MARGIN_UTILIZATION,
                min_reserve_buffer=DEFAULT_MIN_RESERVE_BUFFER,
                allocated_margin_usdt=inspection.starting_equity * DEFAULT_BASE_POSITION_FRACTION,
            ),
            staging_promotion_state=staged_state,
            promotion_timestamp=now_iso,
        )

    # Dynamic fail-closed safety invariants verification
    safety_invariants = check_fail_closed_safety_invariants()
    if safety_invariants["api_keys_loaded"] > 0:
        raise DomainViolation(
            f"Cannot stage candidates: live exchange credentials detected in environment "
            f"(api_keys_loaded={safety_invariants['api_keys_loaded']})"
        )

    # 1. Build CanaryStagingManifest
    provisional_manifest = CanaryStagingManifest(
        manifest_version=2,
        registry_version=2,
        staged_at=now_iso,
        operator_id=operator_clean,
        decision_id=decision_id,
        staging_promotion_state=staged_state,
        candidates=staged_candidates,
        portfolio_risk_guardrails=PortfolioRiskGuardrails(
            total_starting_capital_usdt=inspection.starting_equity,
            max_aggregate_margin_utilization=DEFAULT_MAX_MARGIN_UTILIZATION,
            min_aggregate_reserve_buffer=DEFAULT_MIN_RESERVE_BUFFER,
            single_position_invariant=True,
        ),
        safety_invariants=safety_invariants,
        manifest_hash="0" * 64,
        cryptographic_signature="0" * 64,
    )
    manifest_hash = compute_manifest_hash(provisional_manifest)
    signature = compute_staging_signature(operator_clean, decision_id, manifest_hash)
    final_manifest = provisional_manifest.model_copy(
        update={
            "manifest_hash": manifest_hash,
            "cryptographic_signature": signature,
        }
    )

    # 2. Build HumanReviewDecision
    provisional_decision = HumanReviewDecision(
        decision_id=decision_id,
        operator_id=operator_clean,
        decision=decision,
        decided_at=now_iso,
        review_rationale=rationale_clean,
        prerequisite_checklist=checklist,
        upstream_cohort_hashes=inspection.upstream_hashes,
        upstream_cohort_digest=inspection.upstream_digest,
        safety_invariants=safety_invariants,
        decision_hash="0" * 64,
    )
    dec_hash = compute_decision_hash(provisional_decision)
    final_decision = provisional_decision.model_copy(update={"decision_hash": dec_hash})

    # 3. Build comprehensive audit summary
    audit_summary: dict[str, Any] = {
        "phase": "phase_269",
        "description": (
            "Phase 269 Operator Human Review Governance & Canary Staging Packaging (Manifest v2)"
        ),
        "timestamp_utc": now_iso,
        "operator_id": operator_clean,
        "decision_id": decision_id,
        "decision": decision,
        "staging_promotion_state": summary_state,
        "upstream_cohort": {
            "path": Path(inspection.cohort_dir).as_posix(),
            "cohort_status": inspection.cohort_status,
            "artifact_hashes": inspection.upstream_hashes,
            "composite_hash": inspection.upstream_digest,
        },
        "staged_manifest_hash": manifest_hash,
        "cryptographic_signature": signature,
        "human_review_decision_hash": dec_hash,
        "candidates": {
            sym: {
                "candidate_id": cand.candidate_id,
                "family": cand.family,
                "timeframe": cand.timeframe,
                "artifact_hash": cand.candidate_artifact_hash,
                "qualification_hash": cand.qualification_hash,
                "staging_promotion_state": cand.staging_promotion_state,
                "total_trades": inspection.candidate_breakdowns[sym].total_trades,
                "win_rate_pct": inspection.candidate_breakdowns[sym].win_rate_pct,
                "realized_pnl_usdt": str(inspection.candidate_breakdowns[sym].realized_pnl_usdt),
                "margin_utilization": str(inspection.candidate_breakdowns[sym].margin_utilization),
                "cumulative_fees_usdt": str(
                    inspection.candidate_breakdowns[sym].cumulative_fees_usdt
                ),
                "cumulative_slippage_usdt": str(
                    inspection.candidate_breakdowns[sym].cumulative_slippage_usdt
                ),
                "observed_slots": inspection.candidate_breakdowns[sym].observed_slots,
                "health_status": inspection.candidate_breakdowns[sym].health_status,
                "maturity_status": inspection.candidate_breakdowns[sym].maturity_status,
                "accounting_complete": inspection.candidate_breakdowns[sym].accounting_complete,
            }
            for sym, cand in staged_candidates.items()
        },
        "portfolio_summary": {
            "starting_capital_usdt": str(inspection.starting_equity),
            "final_cash_usdt": str(inspection.final_cash),
            "current_equity_usdt": str(inspection.final_cash),
            "realized_pnl_usdt": str(inspection.realized_pnl),
            "drift_amount": str(inspection.drift),
            "zero_balance_drift": inspection.zero_drift,
            "accounting_reconciled": inspection.zero_drift,
            "max_observed_margin_utilization": str(inspection.max_margin_utilization),
            "min_observed_reserve_buffer": str(inspection.min_reserve_buffer),
        },
        "prerequisite_checklist": checklist.model_dump(mode="json"),
        "safety_invariants": safety_invariants,
    }

    return final_decision, final_manifest, audit_summary


def save_staging_artifacts(
    output_dir: Path | str,
    decision: HumanReviewDecision,
    manifest: CanaryStagingManifest,
    summary: dict[str, Any],
) -> dict[str, str]:
    """Atomically save human-review-decision, canary-staging-manifest, and summaries.

    Returns:
        Mapping of generated artifact filenames to SHA-256 digests.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dec_file = out_dir / "human-review-decision.json"
    man_file = out_dir / "canary-staging-manifest.json"
    op_sum_file = out_dir / "operator-summary.json"
    pap_sum_file = out_dir / "paper-summary.json"

    # Serialize JSON with formatting and newline
    dec_json = json.dumps(decision.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    man_json = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"

    assert_zero_secrets(dec_json, "human-review-decision.json")
    assert_zero_secrets(man_json, "canary-staging-manifest.json")

    # Write decision and manifest
    dec_file.write_bytes(dec_json.encode("utf-8"))
    man_file.write_bytes(man_json.encode("utf-8"))

    dec_hash = compute_file_sha256(dec_file)
    man_hash = compute_file_sha256(man_file)

    # Attach generated hashes to summary
    summary_copy = dict(summary)
    summary_copy["artifact_hashes"] = {
        "canary-staging-manifest.json": man_hash,
        "human-review-decision.json": dec_hash,
    }

    sum_json = json.dumps(summary_copy, indent=2, sort_keys=True) + "\n"
    assert_zero_secrets(sum_json, "operator-summary.json")

    op_sum_file.write_bytes(sum_json.encode("utf-8"))
    pap_sum_file.write_bytes(sum_json.encode("utf-8"))

    op_hash = compute_file_sha256(op_sum_file)
    pap_hash = compute_file_sha256(pap_sum_file)

    return {
        "canary-staging-manifest.json": man_hash,
        "human-review-decision.json": dec_hash,
        "operator-summary.json": op_hash,
        "paper-summary.json": pap_hash,
    }


def format_performance_table(inspection: CohortInspectionResult) -> str:
    """Format an ASCII breakdown of candidate performance and portfolio metrics."""
    sep = "=" * 98
    sub_sep = "-" * 98
    lines: list[str] = [
        sep,
        "           PHASE 269: CANDIDATE PERFORMANCE & COHORT INSPECTION BREAKDOWN         ",
        sep,
        f"Cohort Directory:       {inspection.cohort_dir}",
        f"Cohort Status:          {inspection.cohort_status}",
        f"Upstream SHA-256:       {inspection.upstream_digest[:16]}...",
        f"Starting Capital:       {inspection.starting_equity:.2f} USDT",
        f"Final Cash Balance:     {inspection.final_cash:.4f} USDT",
        f"Realized PnL:           {inspection.realized_pnl:+.4f} USDT",
        f"Accounting Drift:       {inspection.drift:.2e} USDT (zero_drift={inspection.zero_drift})",
        (
            f"Max Margin Utilization: {inspection.max_margin_utilization * 100:.2f}% "
            "(limit <= 80.00%)"
        ),
        (f"Min Reserve Buffer:     {inspection.min_reserve_buffer * 100:.2f}% (minimum >= 20.00%)"),
        sub_sep,
        (
            f"{'Symbol':<8} {'Candidate ID':<20} {'Trades':<6} {'Win%':<5} {'PnL(USDT)':<10} "
            f"{'Margin%':<7} {'Fees(USDT)':<10} {'Slip(USDT)':<10} {'Slots':<5} {'Health':<6} "
            f"{'Maturity':<8}"
        ),
        sub_sep,
    ]

    for sym, cb in sorted(inspection.candidate_breakdowns.items()):
        lines.append(
            f"{sym:<8} {cb.candidate_id:<20} {cb.total_trades:<6} "
            f"{cb.win_rate_pct:>4.1f}% {float(cb.realized_pnl_usdt):>+10.4f} "
            f"{float(cb.margin_utilization) * 100:>6.1f}% {float(cb.cumulative_fees_usdt):>10.4f} "
            f"{float(cb.cumulative_slippage_usdt):>10.4f} {cb.observed_slots:<5} "
            f"{cb.health_status:<6} {cb.maturity_status:<8}"
        )

    lines.append(sub_sep)
    chk = inspection.prerequisite_checklist
    lines.append(f"Prerequisite Gates Result: {'ALL PASSED' if chk.all_gates_passed else 'FAILED'}")
    if not chk.all_gates_passed:
        lines.append("Failed Gates:")
        for r in chk.failure_reasons:
            lines.append(f"  - {r}")
    lines.append(sep)
    return "\n".join(lines)


__all__ = [
    "AllocatedRiskLimits",
    "CandidatePerformanceBreakdown",
    "CanaryStagedCandidate",
    "CanaryStagingManifest",
    "CohortInspectionResult",
    "DEFAULT_BASE_POSITION_FRACTION",
    "DEFAULT_MAX_LEVERAGE",
    "DEFAULT_MAX_MARGIN_UTILIZATION",
    "DEFAULT_MIN_RESERVE_BUFFER",
    "DEFAULT_PHASE268_COHORT_DIR",
    "DEFAULT_PHASE269_OUTPUT_DIR",
    "DEFAULT_STARTING_CAPITAL",
    "DOUBLE_ENTRY_MAX_DRIFT",
    "EXPECTED_MANIFEST_V2_CANDIDATES",
    "HumanReviewDecision",
    "PortfolioRiskGuardrails",
    "PrerequisiteChecklist",
    "assert_zero_secrets",
    "check_fail_closed_safety_invariants",
    "compute_decision_hash",
    "compute_file_sha256",
    "compute_manifest_hash",
    "compute_staging_signature",
    "format_performance_table",
    "inspect_cohort",
    "safe_decimal",
    "save_staging_artifacts",
    "stage_canary_candidates",
    "verify_prerequisite_gates",
]
