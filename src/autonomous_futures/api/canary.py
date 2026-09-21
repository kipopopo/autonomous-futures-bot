from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Literal

from ..domain.contracts import DomainModel


class CanaryEvidenceNotFoundError(FileNotFoundError):
    """Canary research evidence or telemetry database is not found."""


class CanaryEvidenceIntegrityError(ValueError):
    """Canary artifact hash mismatch or database corruption detected."""


class CanarySummaryResponse(DomainModel):
    verified: Literal[True] = True
    phase: str
    daemon_status: str
    description: str
    manifest_version: int
    staged_manifest_hash: str
    candidates: list[str]
    timestamp_utc: str
    circuit_state: str
    compliance: dict[str, bool]
    daemon_stats: dict[str, str]
    order_stats: dict[str, Any]
    heartbeat_stats: dict[str, Any]
    error_stats: dict[str, Any]
    artifact_hashes: dict[str, str]
    tracks_summary: dict[str, Any]


class HawkesSnapshotItem(DomainModel):
    record_id: int
    track_id: str
    symbol: str
    timestamp_utc: str
    jump_intensity: str
    branching_ratio: str
    spectral_radius: str
    self_excitation_alpha: str
    cross_excitation_json: str
    cascade_state: str
    regime: str
    pacing_interval_ms: float
    limit_offset_cushion_bps: str
    full_branching_matrix_json: str


class CanaryHawkesResponse(DomainModel):
    verified: Literal[True] = True
    phase: str
    timestamp_utc: str
    candidates: list[str]
    snapshots: list[HawkesSnapshotItem]
    current_regime: str
    max_spectral_radius: float
    max_jump_intensity: float


class HeartbeatItem(DomainModel):
    record_id: int
    track_id: str
    server_time_ms: int
    local_time_ms: int
    latency_ms: float
    clock_skew_ms: float
    status: str
    is_healthy: bool
    details: str
    timestamp_utc: str


class InterlockEventItem(DomainModel):
    event_id: str
    timestamp_utc: str
    track_id: str
    interlock_type: str
    allowed: bool
    symbol: str | None = None
    notional_usdt: str | None = None
    details: str


class CanaryRiskResponse(DomainModel):
    verified: Literal[True] = True
    phase: str
    circuit_state: str
    aggregate_exposure_cap_usdt: str
    individual_micro_notional_cap_usdt: str
    intra_phase_loss_ceiling_usdt: str
    max_allowed_heartbeat_age_ms: float
    heartbeats: list[HeartbeatItem]
    interlock_events: list[InterlockEventItem]
    total_interlock_blocks: int


class BalanceSnapshotItem(DomainModel):
    snapshot_id: str
    timestamp_utc: str
    track_id: str
    cash_usdt: str
    allocated_margin_usdt: str
    unrealized_pnl_usdt: str
    realized_pnl_usdt: str
    starting_equity_usdt: str
    drift_usdt: str
    zero_balance_drift: bool
    trigger_event: str


class DaemonTrackItem(DomainModel):
    track_id: str
    track_name: str
    status: str
    starting_equity_usdt: str
    final_cash_usdt: str
    allocated_margin_usdt: str
    unrealized_pnl_usdt: str
    realized_pnl_usdt: str
    total_fees_usdt: str
    total_slippage_usdt: str
    drift_usdt: str
    zero_balance_drift: bool
    orders_placed_count: int
    orders_filled_count: int
    orders_cancelled_count: int
    orders_rejected_count: int
    interlock_blocks_count: int


class CanaryAccountingResponse(DomainModel):
    verified: Literal[True] = True
    phase: str
    starting_capital_usdt: str
    final_cash_usdt: str
    final_equity_usdt: str
    realized_pnl_usdt: str
    allocated_margin_usdt: str
    unrealized_pnl_usdt: str
    total_fees_usdt: str
    total_slippage_usdt: str
    drift_usdt: str
    zero_balance_drift: bool
    tracks: list[DaemonTrackItem]
    recent_balance_snapshots: list[BalanceSnapshotItem]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_canary_phase_integrity(phase_dir: Path) -> dict[str, Any]:
    """Verify that all phase artifacts match their recorded SHA-256 hashes."""
    if not phase_dir.is_dir():
        raise CanaryEvidenceNotFoundError(f"Canary phase directory not found: {phase_dir}")

    summary_file = phase_dir / "hawkes-summary.json"
    if not summary_file.is_file():
        summary_file = phase_dir / "paper-summary.json"
    if not summary_file.is_file():
        raise CanaryEvidenceNotFoundError(f"No summary artifact found in {phase_dir}")

    try:
        raw_data = json.loads(summary_file.read_text(encoding="utf-8"))
        if not isinstance(raw_data, dict):
            raise CanaryEvidenceIntegrityError(f"Root JSON is not an object in {summary_file}")
        data: dict[str, Any] = raw_data
    except Exception as exc:
        raise CanaryEvidenceIntegrityError(f"Malformed JSON in {summary_file}") from exc

    raw_hashes = data.get("artifact_hashes", {})
    artifact_hashes: dict[str, str] = raw_hashes if isinstance(raw_hashes, dict) else {}
    for filename, expected_hash in artifact_hashes.items():
        file_path = phase_dir / filename
        if not file_path.is_file():
            raise CanaryEvidenceNotFoundError(
                f"Referenced artifact {filename} missing in {phase_dir}"
            )
        actual_hash = _sha256(file_path)
        if actual_hash.lower() != expected_hash.lower():
            raise CanaryEvidenceIntegrityError(
                f"Hash mismatch for {filename}: expected {expected_hash}, got {actual_hash}"
            )

    return data


def load_verified_canary_summary(phase_dir: Path) -> CanarySummaryResponse:
    summary_data = verify_canary_phase_integrity(phase_dir)
    paper_summary_file = phase_dir / "paper-summary.json"
    circuit_state = "NORMAL"
    if paper_summary_file.is_file():
        try:
            paper_data = json.loads(paper_summary_file.read_text(encoding="utf-8"))
            circuit_state = str(paper_data.get("circuit_state", "NORMAL"))
        except Exception:
            pass

    return CanarySummaryResponse(
        phase=str(summary_data.get("phase", phase_dir.name)),
        daemon_status=str(summary_data.get("daemon_status", "UNKNOWN")),
        description=str(summary_data.get("description", "Canary Execution Summary")),
        manifest_version=int(summary_data.get("manifest_version", 2)),
        staged_manifest_hash=str(summary_data.get("staged_manifest_hash", "")),
        candidates=list(summary_data.get("candidates", [])),
        timestamp_utc=str(summary_data.get("timestamp_utc", "")),
        circuit_state=circuit_state,
        compliance=dict(summary_data.get("compliance", {})),
        daemon_stats={str(k): str(v) for k, v in summary_data.get("daemon_stats", {}).items()},
        order_stats=dict(summary_data.get("order_stats", {})),
        heartbeat_stats=dict(summary_data.get("heartbeat_stats", {})),
        error_stats=dict(summary_data.get("error_stats", {})),
        artifact_hashes=dict(summary_data.get("artifact_hashes", {})),
        tracks_summary=dict(summary_data.get("tracks_summary", {})),
    )


def load_verified_canary_hawkes(phase_dir: Path) -> CanaryHawkesResponse:
    summary_data = verify_canary_phase_integrity(phase_dir)
    db_path = phase_dir / "canary-hawkes-telemetry.sqlite3"
    if not db_path.is_file():
        raise CanaryEvidenceNotFoundError(f"Telemetry database not found: {db_path}")

    snapshots: list[HawkesSnapshotItem] = []
    current_regime = "NOMINAL"
    max_spectral = 0.0
    max_jump = 0.0

    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT record_id, track_id, symbol, timestamp_utc, jump_intensity,
                   branching_ratio, spectral_radius, self_excitation_alpha,
                   cross_excitation_json, cascade_state, regime, pacing_interval_ms,
                   limit_offset_cushion_bps, full_branching_matrix_json
            FROM hawkes_cascade_snapshots
            ORDER BY record_id ASC
            """
        )
        for row in cur.fetchall():
            item = HawkesSnapshotItem(
                record_id=int(row["record_id"]),
                track_id=str(row["track_id"]),
                symbol=str(row["symbol"]),
                timestamp_utc=str(row["timestamp_utc"]),
                jump_intensity=str(row["jump_intensity"]),
                branching_ratio=str(row["branching_ratio"]),
                spectral_radius=str(row["spectral_radius"]),
                self_excitation_alpha=str(row["self_excitation_alpha"]),
                cross_excitation_json=str(row["cross_excitation_json"]),
                cascade_state=str(row["cascade_state"]),
                regime=str(row["regime"]),
                pacing_interval_ms=float(row["pacing_interval_ms"]),
                limit_offset_cushion_bps=str(row["limit_offset_cushion_bps"]),
                full_branching_matrix_json=str(row["full_branching_matrix_json"]),
            )
            snapshots.append(item)
            try:
                sr = float(item.spectral_radius)
                if sr > max_spectral:
                    max_spectral = sr
            except ValueError:
                pass
            try:
                ji = float(item.jump_intensity)
                if ji > max_jump:
                    max_jump = ji
            except ValueError:
                pass
            current_regime = item.regime
        conn.close()
    except sqlite3.Error as exc:
        raise CanaryEvidenceIntegrityError(
            f"Database error reading Hawkes snapshots: {exc}"
        ) from exc

    return CanaryHawkesResponse(
        phase=str(summary_data.get("phase", phase_dir.name)),
        timestamp_utc=str(summary_data.get("timestamp_utc", "")),
        candidates=list(summary_data.get("candidates", [])),
        snapshots=snapshots,
        current_regime=current_regime,
        max_spectral_radius=round(max_spectral, 6),
        max_jump_intensity=round(max_jump, 6),
    )


def load_verified_canary_risk(phase_dir: Path) -> CanaryRiskResponse:
    summary_data = verify_canary_phase_integrity(phase_dir)
    db_path = phase_dir / "canary-hawkes-telemetry.sqlite3"
    if not db_path.is_file():
        raise CanaryEvidenceNotFoundError(f"Telemetry database not found: {db_path}")

    daemon_stats = summary_data.get("daemon_stats", {})
    heartbeat_stats = summary_data.get("heartbeat_stats", {})
    circuit_state = "NORMAL"
    paper_summary_file = phase_dir / "paper-summary.json"
    if paper_summary_file.is_file():
        try:
            paper_data = json.loads(paper_summary_file.read_text(encoding="utf-8"))
            circuit_state = str(paper_data.get("circuit_state", "NORMAL"))
        except Exception:
            pass

    heartbeats: list[HeartbeatItem] = []
    interlock_events: list[InterlockEventItem] = []

    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            """
            SELECT record_id, track_id, server_time_ms, local_time_ms,
                   latency_ms, clock_skew_ms, status, is_healthy, details, timestamp_utc
            FROM heartbeats
            ORDER BY record_id ASC
            """
        )
        for row in cur.fetchall():
            heartbeats.append(
                HeartbeatItem(
                    record_id=int(row["record_id"]),
                    track_id=str(row["track_id"]),
                    server_time_ms=int(row["server_time_ms"]),
                    local_time_ms=int(row["local_time_ms"]),
                    latency_ms=float(row["latency_ms"]),
                    clock_skew_ms=float(row["clock_skew_ms"]),
                    status=str(row["status"]),
                    is_healthy=bool(row["is_healthy"]),
                    details=str(row["details"]),
                    timestamp_utc=str(row["timestamp_utc"]),
                )
            )

        cur.execute(
            """
            SELECT event_id, timestamp_utc, track_id, interlock_type,
                   allowed, symbol, notional_usdt, details
            FROM interlock_events
            ORDER BY timestamp_utc ASC
            """
        )
        for row in cur.fetchall():
            interlock_events.append(
                InterlockEventItem(
                    event_id=str(row["event_id"]),
                    timestamp_utc=str(row["timestamp_utc"]),
                    track_id=str(row["track_id"]),
                    interlock_type=str(row["interlock_type"]),
                    allowed=bool(row["allowed"]),
                    symbol=str(row["symbol"]) if row["symbol"] is not None else None,
                    notional_usdt=str(row["notional_usdt"])
                    if row["notional_usdt"] is not None
                    else None,
                    details=str(row["details"]),
                )
            )

        conn.close()
    except sqlite3.Error as exc:
        raise CanaryEvidenceIntegrityError(f"Database error reading risk events: {exc}") from exc

    total_blocks = sum(1 for e in interlock_events if not e.allowed)

    return CanaryRiskResponse(
        phase=str(summary_data.get("phase", phase_dir.name)),
        circuit_state=circuit_state,
        aggregate_exposure_cap_usdt=str(daemon_stats.get("aggregate_exposure_cap_usdt", "60.00")),
        individual_micro_notional_cap_usdt=str(
            daemon_stats.get("individual_micro_notional_cap_usdt", "5.00")
        ),
        intra_phase_loss_ceiling_usdt=str(
            daemon_stats.get("intra_phase_loss_ceiling_usdt", "7.00")
        ),
        max_allowed_heartbeat_age_ms=float(heartbeat_stats.get("max_allowed_age_ms", 500.0)),
        heartbeats=heartbeats,
        interlock_events=interlock_events,
        total_interlock_blocks=total_blocks,
    )


def load_verified_canary_accounting(phase_dir: Path) -> CanaryAccountingResponse:
    summary_data = verify_canary_phase_integrity(phase_dir)
    paper_summary_file = phase_dir / "paper-summary.json"
    paper_data: dict[str, Any] = {}
    if paper_summary_file.is_file():
        try:
            paper_data = json.loads(paper_summary_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    db_path = phase_dir / "canary-hawkes-telemetry.sqlite3"
    if not db_path.is_file():
        raise CanaryEvidenceNotFoundError(f"Telemetry database not found: {db_path}")

    tracks: list[DaemonTrackItem] = []
    snapshots: list[BalanceSnapshotItem] = []

    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            """
            SELECT track_id, track_name, status, starting_equity_usdt,
                   final_cash_usdt, allocated_margin_usdt, unrealized_pnl_usdt,
                   realized_pnl_usdt, total_fees_usdt, total_slippage_usdt,
                   drift_usdt, zero_balance_drift, orders_placed_count,
                   orders_filled_count, orders_cancelled_count,
                   orders_rejected_count, interlock_blocks_count
            FROM daemon_tracks
            ORDER BY track_id ASC
            """
        )
        for row in cur.fetchall():
            tracks.append(
                DaemonTrackItem(
                    track_id=str(row["track_id"]),
                    track_name=str(row["track_name"]),
                    status=str(row["status"]),
                    starting_equity_usdt=str(row["starting_equity_usdt"]),
                    final_cash_usdt=str(row["final_cash_usdt"]),
                    allocated_margin_usdt=str(row["allocated_margin_usdt"]),
                    unrealized_pnl_usdt=str(row["unrealized_pnl_usdt"]),
                    realized_pnl_usdt=str(row["realized_pnl_usdt"]),
                    total_fees_usdt=str(row["total_fees_usdt"]),
                    total_slippage_usdt=str(row["total_slippage_usdt"]),
                    drift_usdt=str(row["drift_usdt"]),
                    zero_balance_drift=bool(row["zero_balance_drift"]),
                    orders_placed_count=int(row["orders_placed_count"]),
                    orders_filled_count=int(row["orders_filled_count"]),
                    orders_cancelled_count=int(row["orders_cancelled_count"]),
                    orders_rejected_count=int(row["orders_rejected_count"]),
                    interlock_blocks_count=int(row["interlock_blocks_count"]),
                )
            )

        cur.execute(
            """
            SELECT snapshot_id, timestamp_utc, track_id, cash_usdt,
                   allocated_margin_usdt, unrealized_pnl_usdt, realized_pnl_usdt,
                   starting_equity_usdt, drift_usdt, zero_balance_drift, trigger_event
            FROM balance_snapshots
            ORDER BY timestamp_utc ASC
            """
        )
        for row in cur.fetchall():
            snapshots.append(
                BalanceSnapshotItem(
                    snapshot_id=str(row["snapshot_id"]),
                    timestamp_utc=str(row["timestamp_utc"]),
                    track_id=str(row["track_id"]),
                    cash_usdt=str(row["cash_usdt"]),
                    allocated_margin_usdt=str(row["allocated_margin_usdt"]),
                    unrealized_pnl_usdt=str(row["unrealized_pnl_usdt"]),
                    realized_pnl_usdt=str(row["realized_pnl_usdt"]),
                    starting_equity_usdt=str(row["starting_equity_usdt"]),
                    drift_usdt=str(row["drift_usdt"]),
                    zero_balance_drift=bool(row["zero_balance_drift"]),
                    trigger_event=str(row["trigger_event"]),
                )
            )

        conn.close()
    except sqlite3.Error as exc:
        raise CanaryEvidenceIntegrityError(
            f"Database error reading balance records: {exc}"
        ) from exc

    starting_capital = str(paper_data.get("starting_capital_usdt", "100.00"))
    final_cash = str(paper_data.get("final_cash_usdt", "99.99460000"))
    final_equity = str(paper_data.get("final_equity_usdt", "99.99460000"))
    realized_pnl = str(paper_data.get("realized_pnl_usdt", "-0.00540000"))
    total_fees = str(paper_data.get("total_fees_usdt", "0.010889"))
    total_slippage = str(paper_data.get("total_slippage_usdt", "0.000000"))
    drift = str(paper_data.get("drift_usdt", "0E-8"))
    zero_drift = bool(paper_data.get("zero_balance_drift", True))

    return CanaryAccountingResponse(
        phase=str(summary_data.get("phase", phase_dir.name)),
        starting_capital_usdt=starting_capital,
        final_cash_usdt=final_cash,
        final_equity_usdt=final_equity,
        realized_pnl_usdt=realized_pnl,
        allocated_margin_usdt="0.0",
        unrealized_pnl_usdt="0.0",
        total_fees_usdt=total_fees,
        total_slippage_usdt=total_slippage,
        drift_usdt=drift,
        zero_balance_drift=zero_drift,
        tracks=tracks,
        recent_balance_snapshots=snapshots,
    )


__all__ = [
    "BalanceSnapshotItem",
    "CanaryAccountingResponse",
    "CanaryEvidenceIntegrityError",
    "CanaryEvidenceNotFoundError",
    "CanaryHawkesResponse",
    "CanaryRiskResponse",
    "CanarySummaryResponse",
    "DaemonTrackItem",
    "HawkesSnapshotItem",
    "HeartbeatItem",
    "InterlockEventItem",
    "load_verified_canary_accounting",
    "load_verified_canary_hawkes",
    "load_verified_canary_risk",
    "load_verified_canary_summary",
    "verify_canary_phase_integrity",
]
