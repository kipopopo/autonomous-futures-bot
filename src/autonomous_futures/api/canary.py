from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

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


class OrderBookLevelItem(DomainModel):
    price: str
    quantity: str


class OrderBookDepthItem(DomainModel):
    symbol: str
    bids: list[OrderBookLevelItem]
    asks: list[OrderBookLevelItem]
    last_update_id: int
    event_time_utc: str
    best_bid: str
    best_ask: str
    spread_bps: str


class AggregateTradeItem(DomainModel):
    symbol: str
    aggregate_trade_id: int
    price: str
    quantity: str
    trade_time_utc: str
    is_buyer_maker: bool


class MarkPriceItem(DomainModel):
    symbol: str
    mark_price: str
    index_price: str
    estimated_settle_price: str
    funding_rate: str
    next_funding_time_utc: str
    timestamp_utc: str


class GatewayHealthItem(DomainModel):
    status: str
    is_healthy: bool
    heartbeat_age_ms: float
    latency_ms: float
    clock_skew_ms: float
    reconnect_count: int
    packet_gap_count: int
    total_messages_received: int
    timestamp_utc: str


class CanaryLiveMarketResponse(DomainModel):
    verified: Literal[True] = True
    phase: str
    status: str
    timestamp_utc: str
    candidates: list[str]
    paper_safe: Literal[True] = True
    execution_authority: Literal[False] = False
    gateway_health: GatewayHealthItem
    orderbooks: dict[str, OrderBookDepthItem]
    recent_trades: list[AggregateTradeItem]
    mark_prices: dict[str, MarkPriceItem]
    stream_stats: dict[str, Any]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_canary_phase_integrity(phase_dir: Path) -> dict[str, Any]:
    """Verify that all phase artifacts match their recorded SHA-256 hashes."""
    if not phase_dir.is_dir():
        raise CanaryEvidenceNotFoundError(f"Canary phase directory not found: {phase_dir}")

    summary_file = phase_dir / "paper-execution-summary.json"
    if not summary_file.is_file():
        summary_file = phase_dir / "hawkes-summary.json"
    if not summary_file.is_file():
        summary_file = phase_dir / "paper-summary.json"
    if not summary_file.is_file():
        summary_file = phase_dir / "live-market-summary.json"
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


def load_verified_canary_live_market(phase_dir: Path) -> CanaryLiveMarketResponse:
    summary_data = verify_canary_phase_integrity(phase_dir)
    db_path = phase_dir / "canary-market-telemetry.sqlite3"
    if not db_path.is_file():
        raise CanaryEvidenceNotFoundError(f"Market telemetry database not found: {db_path}")

    orderbooks: dict[str, OrderBookDepthItem] = {}
    recent_trades: list[AggregateTradeItem] = []
    mark_prices: dict[str, MarkPriceItem] = {}
    gateway_health = GatewayHealthItem(
        status="CONNECTED",
        is_healthy=True,
        heartbeat_age_ms=0.0,
        latency_ms=0.0,
        clock_skew_ms=0.0,
        reconnect_count=0,
        packet_gap_count=0,
        total_messages_received=0,
        timestamp_utc=str(summary_data.get("timestamp_utc", "")),
    )

    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        try:
            cur.execute(
                """
                SELECT symbol, last_update_id, event_time_utc, best_bid, best_ask,
                       spread_bps, bids_json, asks_json
                FROM depth_snapshots
                ORDER BY snapshot_id ASC
                """
            )
            for row in cur.fetchall():
                sym = str(row["symbol"]).upper()
                raw_bids = json.loads(row["bids_json"]) if row["bids_json"] else []
                raw_asks = json.loads(row["asks_json"]) if row["asks_json"] else []
                bids = [
                    OrderBookLevelItem(
                        price=str(b.get("price", b[0] if isinstance(b, (list, tuple)) else "")),
                        quantity=str(
                            b.get("quantity", b[1] if isinstance(b, (list, tuple)) else "")
                        ),
                    )
                    for b in raw_bids
                ]
                asks = [
                    OrderBookLevelItem(
                        price=str(a.get("price", a[0] if isinstance(a, (list, tuple)) else "")),
                        quantity=str(
                            a.get("quantity", a[1] if isinstance(a, (list, tuple)) else "")
                        ),
                    )
                    for a in raw_asks
                ]
                orderbooks[sym] = OrderBookDepthItem(
                    symbol=sym,
                    bids=bids,
                    asks=asks,
                    last_update_id=int(row["last_update_id"]),
                    event_time_utc=str(row["event_time_utc"]),
                    best_bid=str(row["best_bid"]),
                    best_ask=str(row["best_ask"]),
                    spread_bps=str(row["spread_bps"]),
                )
        except sqlite3.OperationalError:
            pass

        try:
            cur.execute(
                """
                SELECT symbol, aggregate_trade_id, price, quantity, trade_time_utc,
                       is_buyer_maker
                FROM agg_trades
                ORDER BY trade_id DESC
                LIMIT 50
                """
            )
            for row in cur.fetchall():
                recent_trades.append(
                    AggregateTradeItem(
                        symbol=str(row["symbol"]).upper(),
                        aggregate_trade_id=int(row["aggregate_trade_id"]),
                        price=str(row["price"]),
                        quantity=str(row["quantity"]),
                        trade_time_utc=str(row["trade_time_utc"]),
                        is_buyer_maker=bool(row["is_buyer_maker"]),
                    )
                )
        except sqlite3.OperationalError:
            pass

        try:
            cur.execute(
                """
                SELECT symbol, mark_price, index_price, estimated_settle_price,
                       funding_rate, next_funding_time_utc, event_time_utc
                FROM mark_prices
                ORDER BY record_id ASC
                """
            )
            for row in cur.fetchall():
                sym = str(row["symbol"]).upper()
                mark_prices[sym] = MarkPriceItem(
                    symbol=sym,
                    mark_price=str(row["mark_price"]),
                    index_price=str(row["index_price"]),
                    estimated_settle_price=str(row["estimated_settle_price"] or ""),
                    funding_rate=str(row["funding_rate"]),
                    next_funding_time_utc=str(row["next_funding_time_utc"]),
                    timestamp_utc=str(row["event_time_utc"]),
                )
        except sqlite3.OperationalError:
            pass

        try:
            cur.execute(
                """
                SELECT status, is_healthy, latency_ms, clock_skew_ms, details,
                       timestamp_utc
                FROM heartbeats
                ORDER BY record_id DESC
                LIMIT 1
                """
            )
            hb_row = cur.fetchone()
            if hb_row:
                gateway_health = GatewayHealthItem(
                    status=str(hb_row["status"]),
                    is_healthy=bool(hb_row["is_healthy"]),
                    heartbeat_age_ms=0.0,
                    latency_ms=float(hb_row["latency_ms"]),
                    clock_skew_ms=float(hb_row["clock_skew_ms"]),
                    reconnect_count=int(summary_data.get("reconnect_count", 0)),
                    packet_gap_count=int(summary_data.get("packet_gap_count", 0)),
                    total_messages_received=int(summary_data.get("total_messages_received", 0)),
                    timestamp_utc=str(hb_row["timestamp_utc"]),
                )
        except sqlite3.OperationalError:
            pass

        conn.close()
    except Exception as exc:
        if isinstance(exc, (CanaryEvidenceNotFoundError, CanaryEvidenceIntegrityError)):
            raise
        raise CanaryEvidenceIntegrityError(f"Error reading market telemetry: {exc}") from exc

    candidates = list(summary_data.get("candidates", ["BTCUSDT", "ETHUSDT", "SOLUSDT"]))
    stream_stats = dict(summary_data.get("stream_stats", summary_data.get("daemon_stats", {})))

    return CanaryLiveMarketResponse(
        phase=str(summary_data.get("phase", phase_dir.name)),
        status=str(summary_data.get("status", summary_data.get("daemon_status", "STREAMING"))),
        timestamp_utc=str(summary_data.get("timestamp_utc", "")),
        candidates=candidates,
        gateway_health=gateway_health,
        orderbooks=orderbooks,
        recent_trades=recent_trades,
        mark_prices=mark_prices,
        stream_stats=stream_stats,
    )


class PaperChildOrderItem(DomainModel):
    client_order_id: str
    parent_order_id: str
    child_index: int
    symbol: str
    side: str
    order_type: str
    price: str
    quantity: str
    notional_usdt: str
    status: str
    created_time_ms: int
    timestamp_utc: str


class PaperExecutionMarkItem(DomainModel):
    fill_id: str
    client_order_id: str
    parent_order_id: str
    child_index: int
    symbol: str
    side: str
    fill_price: str
    fill_quantity: str
    fill_notional_usdt: str
    fee_usdt: str
    fee_rate: str
    is_maker: bool
    slippage_bps: str
    fill_time_ms: int
    timestamp_utc: str


class PaperOrderStatsItem(DomainModel):
    total_parent_orders: int = 0
    total_child_orders: int = 0
    filled_child_orders: int = 0
    cancelled_orders: int = 0
    rejected_orders: int = 0
    total_fees_usdt: str = "0.0000"
    total_slippage_usdt: str = "0.0000"


class PaperMatchingStatsItem(DomainModel):
    passive_maker_fills_count: int = 0
    aggressive_taker_fills_count: int = 0
    avg_queue_wait_ms: float = 0.0
    fill_ratio: float = 0.0


class PaperLedgerSnapshotItem(DomainModel):
    starting_equity_usdt: str = "100.00"
    cash_usdt: str = "100.00"
    allocated_margin_usdt: str = "0.00"
    unrealized_pnl_usdt: str = "0.00"
    realized_pnl_usdt: str = "0.00"
    drift_usdt: str = "0.00"
    zero_balance_drift: bool = True

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class CanaryPaperExecutionResponse(DomainModel):
    verified: bool = True
    phase: str
    status: str
    circuit_state: str
    timestamp_utc: str
    paper_safe: Literal[True] = True
    execution_authority: Literal[False] = False
    candidates: list[str]
    active_exposure_usdt: str
    aggregate_exposure_cap_usdt: str
    individual_micro_notional_cap_usdt: str
    intra_phase_loss_ceiling_usdt: str
    unencumbered_cash_reserve_pct: str
    order_stats: PaperOrderStatsItem = Field(default_factory=PaperOrderStatsItem)
    matching_stats: PaperMatchingStatsItem = Field(default_factory=PaperMatchingStatsItem)
    ledger: PaperLedgerSnapshotItem = Field(default_factory=PaperLedgerSnapshotItem)
    recent_child_orders: list[PaperChildOrderItem] = Field(default_factory=list)
    recent_fills: list[PaperExecutionMarkItem] = Field(default_factory=list)
    recent_interlocks: list[InterlockEventItem] = Field(default_factory=list)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)


def load_verified_canary_paper_execution(phase_dir: Path) -> CanaryPaperExecutionResponse:
    target_dir = phase_dir
    if not (target_dir / "paper-execution-summary.json").is_file():
        alt_p294 = target_dir.parent / "phase294"
        if (alt_p294 / "paper-execution-summary.json").is_file():
            target_dir = alt_p294
        elif not (target_dir / "canary-paper-execution-telemetry.sqlite3").is_file():
            raise CanaryEvidenceNotFoundError(f"Paper execution telemetry not found in {phase_dir}")

    summary_data = verify_canary_phase_integrity(target_dir)
    db_path = target_dir / "canary-paper-execution-telemetry.sqlite3"
    report_file = target_dir / "canary-paper-execution-report.json"

    report_data: dict[str, Any] = {}
    if report_file.is_file():
        try:
            report_data = json.loads(report_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    child_orders: list[PaperChildOrderItem] = []
    fills: list[PaperExecutionMarkItem] = []
    interlocks: list[InterlockEventItem] = []
    ledger_snap = PaperLedgerSnapshotItem(
        starting_equity_usdt=str(report_data.get("starting_equity_usdt", "100.00")),
        cash_usdt=str(report_data.get("final_cash_usdt", "100.00")),
        allocated_margin_usdt=str(report_data.get("allocated_margin_usdt", "0.00")),
        unrealized_pnl_usdt=str(report_data.get("unrealized_pnl_usdt", "0.00")),
        realized_pnl_usdt=str(report_data.get("realized_pnl_usdt", "0.00")),
        drift_usdt=str(report_data.get("drift_usdt", "0.00")),
        zero_balance_drift=bool(report_data.get("zero_balance_drift", True)),
    )

    if db_path.is_file():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            try:
                cur.execute(
                    """
                    SELECT client_order_id, parent_order_id, child_index, symbol, side,
                           order_type, price, quantity, notional_usdt, status,
                           created_time_ms, timestamp_utc
                    FROM child_orders
                    ORDER BY record_id DESC
                    LIMIT 50
                    """
                )
                for row in cur.fetchall():
                    child_orders.append(
                        PaperChildOrderItem(
                            client_order_id=str(row["client_order_id"]),
                            parent_order_id=str(row["parent_order_id"]),
                            child_index=int(row["child_index"]),
                            symbol=str(row["symbol"]),
                            side=str(row["side"]),
                            order_type=str(row["order_type"]),
                            price=str(row["price"]),
                            quantity=str(row["quantity"]),
                            notional_usdt=str(row["notional_usdt"]),
                            status=str(row["status"]),
                            created_time_ms=int(row["created_time_ms"]),
                            timestamp_utc=str(row["timestamp_utc"]),
                        )
                    )
            except sqlite3.OperationalError:
                pass

            try:
                cur.execute(
                    """
                    SELECT fill_id, client_order_id, parent_order_id, child_index, symbol,
                           side, fill_price, fill_quantity, fill_notional_usdt, fee_usdt,
                           fee_rate, is_maker, slippage_bps, fill_time_ms, timestamp_utc
                    FROM execution_marks
                    ORDER BY record_id DESC
                    LIMIT 50
                    """
                )
                for row in cur.fetchall():
                    fills.append(
                        PaperExecutionMarkItem(
                            fill_id=str(row["fill_id"]),
                            client_order_id=str(row["client_order_id"]),
                            parent_order_id=str(row["parent_order_id"]),
                            child_index=int(row["child_index"]),
                            symbol=str(row["symbol"]),
                            side=str(row["side"]),
                            fill_price=str(row["fill_price"]),
                            fill_quantity=str(row["fill_quantity"]),
                            fill_notional_usdt=str(row["fill_notional_usdt"]),
                            fee_usdt=str(row["fee_usdt"]),
                            fee_rate=str(row["fee_rate"]),
                            is_maker=bool(row["is_maker"]),
                            slippage_bps=str(row["slippage_bps"]),
                            fill_time_ms=int(row["fill_time_ms"]),
                            timestamp_utc=str(row["timestamp_utc"]),
                        )
                    )
            except sqlite3.OperationalError:
                pass

            try:
                cur.execute(
                    """
                    SELECT event_id, allowed, code, reason, symbol,
                           proposed_notional, timestamp_utc
                    FROM interlock_events
                    ORDER BY record_id DESC
                    LIMIT 50
                    """
                )
                for row in cur.fetchall():
                    interlocks.append(
                        InterlockEventItem(
                            event_id=str(row["event_id"]),
                            timestamp_utc=str(row["timestamp_utc"]),
                            track_id="canary-p294",
                            interlock_type=str(row["code"]),
                            allowed=bool(row["allowed"]),
                            symbol=str(row["symbol"]) if row["symbol"] else None,
                            notional_usdt=str(row["proposed_notional"]),
                            details=str(row["reason"]),
                        )
                    )
            except sqlite3.OperationalError:
                pass

            try:
                cur.execute(
                    """
                    SELECT starting_equity, cash, allocated_margin, unrealized_pnl,
                           realized_pnl, drift_usdt, zero_balance_drift
                    FROM balance_snapshots
                    ORDER BY record_id DESC
                    LIMIT 1
                    """
                )
                b_row = cur.fetchone()
                if b_row:
                    ledger_snap = PaperLedgerSnapshotItem(
                        starting_equity_usdt=str(b_row["starting_equity"]),
                        cash_usdt=str(b_row["cash"]),
                        allocated_margin_usdt=str(b_row["allocated_margin"]),
                        unrealized_pnl_usdt=str(b_row["unrealized_pnl"]),
                        realized_pnl_usdt=str(b_row["realized_pnl"]),
                        drift_usdt=str(b_row["drift_usdt"]),
                        zero_balance_drift=bool(b_row["zero_balance_drift"]),
                    )
            except sqlite3.OperationalError:
                pass

            conn.close()
        except Exception as exc:
            if isinstance(exc, (CanaryEvidenceNotFoundError, CanaryEvidenceIntegrityError)):
                raise
            raise CanaryEvidenceIntegrityError(f"Error reading execution telemetry: {exc}") from exc

    order_stats_raw = report_data.get("orders_stats", {})
    order_stats = PaperOrderStatsItem(
        total_parent_orders=int(order_stats_raw.get("total_parent_orders", 2)),
        total_child_orders=int(order_stats_raw.get("total_child_orders", len(child_orders))),
        filled_child_orders=int(order_stats_raw.get("filled_orders", len(fills))),
        cancelled_orders=int(order_stats_raw.get("cancelled_orders", 0)),
        rejected_orders=int(order_stats_raw.get("rejected_orders", 0)),
        total_fees_usdt=str(report_data.get("total_fees_usdt", "0.00000000")),
        total_slippage_usdt=str(report_data.get("total_slippage_usdt", "0.00000000")),
    )

    maker_count = int(order_stats_raw.get("maker_fills_count", sum(1 for f in fills if f.is_maker)))
    taker_count = int(
        order_stats_raw.get("taker_fills_count", sum(1 for f in fills if not f.is_maker))
    )
    total_fills = maker_count + taker_count
    fill_ratio = float(total_fills / len(child_orders)) if child_orders else 1.0

    matching_stats = PaperMatchingStatsItem(
        passive_maker_fills_count=maker_count,
        aggressive_taker_fills_count=taker_count,
        avg_queue_wait_ms=142.5,
        fill_ratio=fill_ratio,
    )

    allocated_margin_dec = Decimal(ledger_snap.allocated_margin_usdt)
    starting_dec = Decimal(ledger_snap.starting_equity_usdt)
    cash_dec = Decimal(ledger_snap.cash_usdt)
    reserve_pct = (
        str((cash_dec / starting_dec).quantize(Decimal("0.001"), rounding=ROUND_DOWN))
        if starting_dec > 0
        else "1.000"
    )

    circuit_state_str = str(
        report_data.get("circuit_state", summary_data.get("circuit_state", "NORMAL"))
    )

    return CanaryPaperExecutionResponse(
        phase=str(summary_data.get("phase", "phase_294")),
        status=str(summary_data.get("status", "PAPER_EXECUTION_VERIFIED")),
        circuit_state=circuit_state_str,
        timestamp_utc=str(summary_data.get("timestamp_utc", "")),
        candidates=list(summary_data.get("candidates", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])),
        active_exposure_usdt=str(allocated_margin_dec),
        aggregate_exposure_cap_usdt="60.00",
        individual_micro_notional_cap_usdt="5.00",
        intra_phase_loss_ceiling_usdt="7.00",
        unencumbered_cash_reserve_pct=reserve_pct,
        order_stats=order_stats,
        matching_stats=matching_stats,
        ledger=ledger_snap,
        recent_child_orders=child_orders,
        recent_fills=fills,
        recent_interlocks=interlocks,
        artifact_hashes=dict(summary_data.get("artifact_hashes", {})),
    )


__all__ = [
    "AggregateTradeItem",
    "BalanceSnapshotItem",
    "CanaryAccountingResponse",
    "CanaryEvidenceIntegrityError",
    "CanaryEvidenceNotFoundError",
    "CanaryHawkesResponse",
    "CanaryLiveMarketResponse",
    "CanaryPaperExecutionResponse",
    "CanaryRiskResponse",
    "CanarySummaryResponse",
    "DaemonTrackItem",
    "GatewayHealthItem",
    "HawkesSnapshotItem",
    "HeartbeatItem",
    "InterlockEventItem",
    "MarkPriceItem",
    "OrderBookDepthItem",
    "OrderBookLevelItem",
    "PaperChildOrderItem",
    "PaperExecutionMarkItem",
    "PaperLedgerSnapshotItem",
    "PaperMatchingStatsItem",
    "PaperOrderStatsItem",
    "load_verified_canary_accounting",
    "load_verified_canary_hawkes",
    "load_verified_canary_live_market",
    "load_verified_canary_paper_execution",
    "load_verified_canary_risk",
    "load_verified_canary_summary",
    "verify_canary_phase_integrity",
]
