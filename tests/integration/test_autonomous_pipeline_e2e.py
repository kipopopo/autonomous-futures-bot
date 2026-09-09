"""Phase 4 / Milestone 10: End-to-End Autonomous Closed-Loop Integration Test Suite.

Target Component: tests/integration/test_autonomous_pipeline_e2e.py
Authoritative Specifications:
- ORIGINAL_REQUEST.md (§## 2026-09-09T04:57:45Z, R1)
- .agents/teamwork_preview_worker_m10/DISPATCH.md
- .agents/teamwork_preview_explorer_survey7_1/report.md
- .agents/teamwork_preview_explorer_survey7_1/handoff.md

Scenarios Covered:
1. test_autonomous_closed_loop_breach_to_hot_reload_e2e:
   - Baseline Ingestion: Direct bootstrap of LivePaperEngine in isolated temporary directory
     with Candidate A and mock market feed.
   - Trading & Feedback Accumulation: Execute simulated losing trades recording entries and exits
     into paper-ledger.sqlite3 and paper-lifecycle.sqlite3.
   - Trigger Activation: run_autonomous_scheduler.py detects performance breach via
     PaperFeedbackExtractor and fires early evaluation cycle.
   - Cycle Execution: Scheduler spawns run_autonomous_cycle.py in --provider demo mode,
     qualifies revised Candidate B, and hot-publishes to candidate_registry.json.
   - Zero-Downtime Hot-Reload: CandidateRegistryHotReloader detects updated registry and admits
     Candidate B into running engine without process restart.
   - Open-Trade Immutability Invariant: In-flight trade opened under Candidate A continues
     evaluating exit rules against Candidate A, while subsequent trade adopts Candidate B.
   - Telemetry Parity: Verify candidate ID and cryptographic hashes match across
     scheduler-health.json, paper-daemon-health.json, cycle-audit.json, and candidate_registry.json.

2. test_autonomous_closed_loop_interval_trigger_e2e:
   - Verify periodic interval trigger with fresh market data executes cycle and hot-reloads
     without performance breach.

3. test_e2e_open_trade_tick_atr_trailing_stop_immutability:
   - Verify tick-level ATR trailing stop price calculation on an active trade evaluates using
     original Candidate A's trailing ATR multiplier even after Candidate B (with different
     multiplier) is admitted.

4. test_e2e_tampered_manifest_fail_closed_resilience:
   - Corrupted / tampered candidate_registry.json (syntax error, SHA-256 hash mismatch,
     missing artifact, tampered artifact content, universe symbol mismatch) is rejected fail-closed
     without mutating engine state or disrupting running positions.
"""

from __future__ import annotations

import json
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

from pydantic import Field

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.run_phase_259_live_paper_daemon as daemon_mod  # noqa: E402
from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    DomainModel,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    CandidateManifestEntry,
    CandidateRegistryHotReloader,
    build_candidate_registry_manifest,
    publish_candidate_admission,
    read_candidate_registry,
    write_candidate_registry,
)
from autonomous_futures.paper.feedback_extractor import (  # noqa: E402
    extract_paper_feedback,
)
from autonomous_futures.paper.live_engine import LivePaperEngine  # noqa: E402
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)

SCHEDULER_SCRIPT = _REPO_ROOT / "scripts" / "run_autonomous_scheduler.py"
CYCLE_SCRIPT = _REPO_ROOT / "scripts" / "run_autonomous_cycle.py"
CANONICAL_PARQUET = (
    _REPO_ROOT / "research" / "immutable-data" / "5m" / "canonical" / "BTCUSDT-5m.parquet"
)

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
QUAL_HASH = "c" * 64


# ==============================================================================
# FORMAL PYDANTIC TELEMETRY MODELS (INDEPENDENT VALIDATION)
# ==============================================================================


SchedulerStatus = Literal["IDLE", "RUNNING_CYCLE", "BACKOFF", "STOPPED"]
TriggerType = Literal["interval", "breach", "manual_once"]


class LastCycleResult(DomainModel):
    """Execution telemetry schema from the most recently executed autonomous cycle."""

    cycle_id: str | None = Field(default=None, description="Unique cycle execution identifier")
    trigger_type: TriggerType = Field(description="Cause of cycle trigger")
    status: str = Field(
        description="Result status string: completed_admitted, completed_rejected, failed, timeout"
    )
    exit_code: int = Field(description="Subprocess exit code (0, 2, 3, etc.)")
    candidate_id: str | None = Field(default=None, description="Admitted candidate ID if admitted")
    admitted: bool = Field(default=False, description="True if candidate achieved admission")
    executed_at: str = Field(description="ISO-8601 UTC timestamp of cycle start")
    duration_seconds: float = Field(
        default=0.0, ge=0.0, description="Elapsed execution duration in seconds"
    )
    error_message: str | None = Field(
        default=None, description="Sanitized failure diagnostic message"
    )


class SchedulerHealthCheckpoint(DomainModel):
    """Durable runtime telemetry schema matching scheduler-health.json."""

    status: SchedulerStatus = Field(description="Current daemon operational status")
    pid: int | None = Field(default=None, description="OS process ID of daemon; None when stopped")
    started_at: str = Field(description="ISO-8601 UTC timestamp when scheduler started")
    updated_at: str = Field(description="ISO-8601 UTC timestamp of latest update")
    last_run_at: str | None = Field(
        default=None, description="ISO-8601 UTC timestamp when last cycle started"
    )
    next_run_at: str | None = Field(
        default=None, description="ISO-8601 UTC timestamp for next scheduled cycle"
    )
    consecutive_failures: int = Field(default=0, ge=0, description="Count of consecutive failures")
    total_cycles_executed: int = Field(default=0, ge=0, description="Total cycle runs attempted")
    admitted_candidates_count: int = Field(default=0, ge=0, description="Total candidates admitted")
    last_cycle_result: LastCycleResult | None = Field(
        default=None, description="Result of most recent cycle"
    )
    symbol: str = Field(description="Target market symbol")
    lockfile: str = Field(description="Path to active process lockfile")
    mode: Literal["daemon", "once"] = Field(default="daemon", description="Execution mode")


# ==============================================================================
# FIXTURES & HELPERS
# ==============================================================================


def _build_test_candidate(
    candidate_id: str,
    symbol: str = "BTCUSDT",
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
    trail_mult: str = "1.0",
    entry_rule: str = "rsi <= 35",
    exit_rule: str = "rsi >= 55",
) -> CreatorCandidateArtifact:
    """Construct a valid CreatorCandidateArtifact with explicit risk and signal rules."""
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,),
            timeframe="5m",
            regime_context_timeframe="15m",
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long=entry_rule, short="rsi >= 70"),
        exit=EntryExit(long=exit_rule, short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal(stop_mult),
            take_profit_atr_multiplier=Decimal(tp_mult),
            trailing_atr_multiplier=Decimal(trail_mult),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        creator_run_id=f"run-{candidate_id}",
        research_seed=42,
        created_at=NOW,
    )


def _setup_engine(
    storage_dir: Path,
    candidates: dict[str, CreatorCandidateArtifact],
    starting_capital: Decimal = Decimal("100.00"),
) -> LivePaperEngine:
    """Initialize a LivePaperEngine with real SQLite stores and initial simulated tickers."""
    symbols = tuple(sorted(candidates.keys()))
    engine = LivePaperEngine(
        symbols=symbols,
        candidates=candidates,
        starting_capital=starting_capital,
        ledger_db=storage_dir / "paper-ledger.sqlite3",
        lifecycle_db=storage_dir / "paper-lifecycle.sqlite3",
        observations_db=storage_dir / "paper-observations.sqlite3",
    )
    for sym in symbols:
        engine.monitor._rolling_atrs[sym] = Decimal("100.0")
        engine.monitor._baseline_atrs[sym] = Decimal("100.0")
        engine.latest_tickers[sym] = TickerSnapshot(
            symbol=sym,
            best_bid_price=Decimal("50000.00"),
            best_bid_qty=Decimal("2.0"),
            best_ask_price=Decimal("50001.00"),
            best_ask_qty=Decimal("2.0"),
            transaction_time=NOW,
            event_time=NOW,
        )
    return engine


def _seed_warmup_bars(
    engine: LivePaperEngine,
    symbol: str = "BTCUSDT",
    count: int = 25,
    base_price: Decimal = Decimal("50000.00"),
) -> None:
    """Seed historical 5m bars to ensure feature evaluators (RSI) have sufficient history."""
    engine._bar_history[symbol].clear()
    for i in range(count):
        bar_time = NOW - timedelta(minutes=5 * (count - 1 - i))
        engine._bar_history[symbol].append(
            {
                "timestamp": bar_time,
                "open": base_price,
                "high": base_price + Decimal("20"),
                "low": base_price - Decimal("20"),
                "close": base_price,
                "volume": Decimal("10.0"),
            }
        )


def _emit_daemon_health(
    health_file: Path,
    engine: LivePaperEngine,
    reloader: CandidateRegistryHotReloader,
) -> dict[str, Any]:
    """Emit durable paper-daemon-health.json reflecting live engine and reloader telemetry."""
    active_cands, last_reload = reloader.get_telemetry()
    cur_eq = engine.current_equity()
    positions = {
        sym: {
            "side": pos.side,
            "quantity": str(pos.quantity),
            "entry_price": str(pos.open_entry.fill_price),
            "leverage": str(pos.leverage),
        }
        for sym, pos in engine.active_trades.items()
    }
    daemon_mod.emit_daemon_health_checkpoint(
        output_path=health_file,
        status="RUNNING",
        uptime_seconds=15.0,
        started_at=NOW.isoformat(),
        symbols=list(engine.symbols),
        starting_capital=engine.account.starting_capital,
        current_cash=engine.account.cash,
        current_equity=cur_eq,
        margin_utilization_pct=float(engine.account.margin_utilization(cur_eq)) * 100.0,
        reserve_buffer_pct=float(engine.account.unencumbered_reserve_buffer(cur_eq)) * 100.0,
        active_positions=positions,
        total_trades=engine.total_closed_trades,
        circuit_breaker_status="NORMAL",
        feed_messages_received=120,
        reconnect_count=0,
        active_candidates=active_cands,
        last_registry_reload=last_reload,
    )
    payload: dict[str, Any] = json.loads(health_file.read_text(encoding="utf-8"))
    return payload


def spawn_scheduler(
    args: list[str],
    cwd: Path = _REPO_ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    """Spawn run_autonomous_scheduler.py in background with Windows process group support."""
    cmd = [sys.executable, str(SCHEDULER_SCRIPT)] + args
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
        env=env,
    )


def terminate_scheduler(
    proc: subprocess.Popen[str],
    timeout: float = 6.0,
) -> int:
    """Gracefully terminate scheduler daemon via CTRL_BREAK (Win32) or SIGINT (POSIX)."""
    if proc.poll() is not None:
        return proc.returncode
    try:
        if sys.platform == "win32":
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:
                proc.terminate()
        else:
            proc.send_signal(signal.SIGINT)
        proc.wait(timeout=timeout)
    except Exception:
        proc.kill()
        proc.wait(timeout=2.0)
    return proc.returncode


def poll_health_checkpoint(
    health_file: Path,
    timeout: float = 14.0,
    expected_status: str | None = None,
    min_cycles: int | None = None,
    proc: subprocess.Popen[str] | None = None,
) -> SchedulerHealthCheckpoint:
    """Poll scheduler-health.json handling Windows NTFS concurrent file locks."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None and proc.returncode != 0:
            stdout, stderr = proc.communicate()
            raise RuntimeError(
                f"Scheduler process exited prematurely with code {proc.returncode}.\n"
                f"Stdout: {stdout}\nStderr: {stderr}"
            )
        if health_file.is_file():
            try:
                content = health_file.read_text(encoding="utf-8")
                if content.strip():
                    data = SchedulerHealthCheckpoint.model_validate_json(content)
                    if expected_status is not None and data.status != expected_status:
                        time.sleep(0.03)
                        continue
                    if min_cycles is not None and data.total_cycles_executed < min_cycles:
                        time.sleep(0.03)
                        continue
                    return data
            except (OSError, ValueError, PermissionError) as err:
                last_err = err
        time.sleep(0.03)
    msg = (
        f"Health checkpoint {health_file} timed out after {timeout}s "
        f"(status={expected_status}, min_cycles={min_cycles}). Last error: {last_err}"
    )
    raise TimeoutError(msg)


def poll_json_file(
    file_path: Path,
    timeout: float = 6.0,
) -> dict[str, Any]:
    """Poll a JSON file handling Windows NTFS concurrent write locks."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8")
                if content.strip():
                    raw = json.loads(content)
                    if isinstance(raw, dict):
                        return raw
            except (OSError, ValueError, PermissionError) as err:
                last_err = err
        time.sleep(0.03)
    raise TimeoutError(f"Timed out waiting for valid JSON at {file_path}. Last error: {last_err}")


# ==============================================================================
# INTEGRATION TESTS: 4 EXHAUSTIVE SCENARIOS
# ==============================================================================


def test_autonomous_closed_loop_breach_to_hot_reload_e2e(tmp_path: Path) -> None:
    """Scenario 1: Full E2E Closed Loop from Feedback Breach to Hot-Reload.

    Sequence:
    1. Baseline Ingestion: LivePaperEngine instantiated with Candidate A in isolated directory.
    2. Feedback Accumulation: 5 genuine simulated losing trades executed and committed into
       paper-ledger.sqlite3 and paper-lifecycle.sqlite3.
    3. Trigger Activation: run_autonomous_scheduler.py monitors ledger, detects performance breach
       via PaperFeedbackExtractor, and fires cycle ahead of schedule.
    4. Cycle Execution: Scheduler spawns run_autonomous_cycle.py in --provider demo mode,
       qualifies Candidate B, and publishes to candidate_registry.json.
    5. Zero-Downtime Hot-Reload: CandidateRegistryHotReloader admits Candidate B into the running
       engine without downtime.
    6. Open-Trade Immutability Invariant: An in-flight trade opened under Candidate A continues
       evaluating exit rules against Candidate A, while subsequent trade adopts Candidate B.
    7. Telemetry Parity: Exact candidate ID and cryptographic hash parity verified across
       scheduler-health.json, paper-daemon-health.json, cycle-audit.json, and
       candidate_registry.json.
    """
    storage_dir = tmp_path / "paper_live"
    storage_dir.mkdir(parents=True, exist_ok=True)
    scheduler_out = tmp_path / "scheduler_out"
    scheduler_out.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"
    scheduler_health_file = scheduler_out / "scheduler-health.json"
    daemon_health_file = storage_dir / "paper-daemon-health.json"

    # Step 1: Baseline Ingestion with Candidate A
    cand_a = _build_test_candidate(
        "cand-btc-alpha-e2e",
        symbol="BTCUSDT",
        stop_mult="1.5",
        tp_mult="5.0",
        trail_mult="1.0",
        entry_rule="rsi <= 35",
        exit_rule="rsi >= 55",
    )
    cand_a_file = storage_dir / f"{cand_a.candidate_id}.json"
    write_creator_candidate_artifact(cand_a_file, cand_a)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_a.candidate_id,
        candidate_artifact_hash=cand_a.artifact_hash,
        artifact_path=cand_a_file,
        qualification_hash=QUAL_HASH,
        admitted_at=NOW,
    )

    engine = _setup_engine(storage_dir, {"BTCUSDT": cand_a})
    _seed_warmup_bars(engine, "BTCUSDT", count=25)
    reloader = CandidateRegistryHotReloader(manifest_path, engine, base_dir=storage_dir)
    assert reloader.check_and_reload() is True
    assert engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id

    # Emit initial daemon health
    daemon_health_init = _emit_daemon_health(daemon_health_file, engine, reloader)
    assert daemon_health_init["active_candidates"]["BTCUSDT"] == cand_a.candidate_id

    # Step 2: Trading & Feedback Accumulation (5 consecutive losing trades)
    for i in range(5):
        t_open = NOW - timedelta(minutes=60 - (i * 10))
        t_close = t_open + timedelta(minutes=5)
        # Open at $50,001.00
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("50000.00"),
            best_bid_qty=Decimal("2.0"),
            best_ask_price=Decimal("50001.00"),
            best_ask_qty=Decimal("2.0"),
            transaction_time=t_open,
            event_time=t_open,
        )
        opened = engine.execute_open(
            "BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=t_open
        )
        assert opened is not None

        # Close lower at $45,000.00 -> negative net PnL loss
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("45000.00"),
            best_bid_qty=Decimal("2.0"),
            best_ask_price=Decimal("45001.00"),
            best_ask_qty=Decimal("2.0"),
            transaction_time=t_close,
            event_time=t_close,
        )
        closed = engine.execute_close("BTCUSDT", exit_reason="stop_loss_hit", event_time=t_close)
        assert closed is not None

    assert engine.total_closed_trades == 5

    # Verify PaperFeedbackExtractor directly flags the performance breach
    fb = extract_paper_feedback(
        ledger_path=storage_dir / "paper-ledger.sqlite3",
        symbol="BTCUSDT",
        candidate_id=cand_a.candidate_id,
        candidate_artifact_path=cand_a_file,
    )
    assert fb is not None
    assert any(g.gate_id != "paper_trades_min" for g in fb.failed_gates)

    # Step 3: Open an In-Flight Trade under Candidate A before triggering cycle
    t_inflight = NOW - timedelta(minutes=5)
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50000.00"),
        best_bid_qty=Decimal("2.0"),
        best_ask_price=Decimal("50001.00"),
        best_ask_qty=Decimal("2.0"),
        transaction_time=t_inflight,
        event_time=t_inflight,
    )
    inflight_trade = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=t_inflight
    )
    assert inflight_trade is not None
    assert "BTCUSDT" in engine.active_trades
    trade_inflight = engine.active_trades["BTCUSDT"]
    assert trade_inflight.candidate_id == cand_a.candidate_id
    assert trade_inflight.trailing_atr_multiplier == Decimal("1.0")

    # Step 4: Trigger Activation & Autonomous Cycle Execution
    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(scheduler_out),
            "--health-file",
            str(scheduler_health_file),
            "--parquet-path",
            str(CANONICAL_PARQUET),
            "--ledger-db",
            str(storage_dir / "paper-ledger.sqlite3"),
            "--lifecycle-db",
            str(storage_dir / "paper-lifecycle.sqlite3"),
            "--candidate-registry-path",
            str(manifest_path),
            "--interval-seconds",
            "3600",
            "--min-cooldown-seconds",
            "0.2",
            "--poll-interval-seconds",
            "0.1",
            "--check-breach-interval-seconds",
            "0.2",
            "--provider",
            "demo",
            "--windows-count",
            "1",
            "--bars-per-window",
            "100",
            "--min-trades",
            "1",
            "--min-windows",
            "1",
            "--min-profit-factor",
            "0.10",
            "--max-drawdown-pct",
            "50.0",
            "--min-average-return-pct",
            "-10.0",
        ]
    )

    try:
        # Wait until scheduler detects breach, executes cycle, and qualifies Candidate B
        health = poll_health_checkpoint(
            scheduler_health_file, timeout=14.0, min_cycles=1, proc=proc
        )
        assert health.total_cycles_executed >= 1
        assert health.last_cycle_result is not None
        assert health.last_cycle_result.trigger_type == "breach"
        assert health.last_cycle_result.status == "completed_admitted"
        assert health.last_cycle_result.admitted is True
        cand_b_id = health.last_cycle_result.candidate_id
        assert cand_b_id is not None
        assert cand_b_id != cand_a.candidate_id
    finally:
        terminate_scheduler(proc)

    # Step 5: Zero-Downtime Hot-Reload in Engine
    reloaded = reloader.check_and_reload()
    assert reloaded is True
    assert reloader.last_reload_status == "RELOADED"
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b_id

    # Step 6: Open-Trade Immutability Invariant Verification
    # Active in-flight trade MUST strictly retain Candidate A binding
    assert "BTCUSDT" in engine.active_trades
    retained_trade = engine.active_trades["BTCUSDT"]
    assert retained_trade.candidate_id == cand_a.candidate_id
    assert retained_trade.candidate is not None
    assert retained_trade.candidate.candidate_id == cand_a.candidate_id
    assert retained_trade.trailing_atr_multiplier == Decimal("1.0")

    # Feed exit bar evaluated strictly against Candidate A's exit rule
    with patch(
        "autonomous_futures.paper.live_engine.evaluate_strategy_exit",
        side_effect=lambda row, side, long_exit_expr, short_exit_expr: (
            long_exit_expr == cand_a.strategy.exit.long
        ),
    ):
        exit_bar = CanonicalBar(
            symbol="BTCUSDT",
            interval="5m",
            timestamp=NOW,
            close_time=NOW,
            open=Decimal("50000"),
            high=Decimal("50200"),
            low=Decimal("49900"),
            close=Decimal("50150"),
            volume=Decimal("15"),
            quote_volume=Decimal("752250"),
            trades=150,
            taker_buy_base=Decimal("8"),
            taker_buy_quote=Decimal("401200"),
            is_closed=True,
        )
        engine._process_closed_bar(exit_bar)

    # Verify in-flight trade closed cleanly under Candidate A rules
    assert "BTCUSDT" not in engine.active_trades
    assert engine.total_closed_trades == 6

    # Verify SQLite ledger permanently attributes Candidate A to trade 6 close
    with sqlite3.connect(f"file:{storage_dir / 'paper-ledger.sqlite3'}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT sequence, event, trade_id, candidate_id "
            "FROM paper_ledger_events ORDER BY sequence ASC"
        ).fetchall()
    # 5 pairs + 1 in-flight pair = 12 events
    assert len(rows) == 12
    assert rows[-2][1] == "open"
    assert rows[-2][3] == cand_a.candidate_id
    assert rows[-1][1] == "close"
    assert rows[-1][3] == cand_a.candidate_id

    # Subsequent Trade Adoption: Open subsequent trade which must adopt Candidate B
    opened_subsequent = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=NOW + timedelta(minutes=10)
    )
    assert opened_subsequent is not None
    subsequent_trade = engine.active_trades["BTCUSDT"]
    assert subsequent_trade.candidate_id == cand_b_id
    assert subsequent_trade.candidate is not None
    assert subsequent_trade.candidate.candidate_id == cand_b_id

    # Verify SQLite ledger open event for subsequent trade attributes Candidate B
    with sqlite3.connect(f"file:{storage_dir / 'paper-ledger.sqlite3'}?mode=ro", uri=True) as conn:
        latest_row = conn.execute(
            "SELECT sequence, event, candidate_id FROM paper_ledger_events "
            "ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
    assert latest_row[1] == "open"
    assert latest_row[2] == cand_b_id

    # Step 7: Telemetry Parity across all 4 Runtime State Artifacts
    daemon_health = _emit_daemon_health(daemon_health_file, engine, reloader)

    cycle_id = health.last_cycle_result.cycle_id
    assert cycle_id is not None
    cycle_audit_file = scheduler_out / "cycles" / cycle_id / "cycle-audit.json"
    audit_data = poll_json_file(cycle_audit_file)
    result_file = scheduler_out / "cycles" / cycle_id / "autonomous-cycle-result.json"
    cycle_result = poll_json_file(result_file)

    manifest = read_candidate_registry(manifest_path, verify_hash=True)
    reg_entry = manifest.symbols["BTCUSDT"]

    audit_candidate_id = audit_data.get("candidate_id") or audit_data["lineage"]["candidate_id"]
    audit_candidate_hash = (
        audit_data.get("candidate_artifact_hash")
        or audit_data["lineage"]["candidate_artifact_hash"]
    )
    audit_qualification_hash = (
        audit_data.get("qualification_hash") or audit_data["lineage"]["qualification_hash"]
    )
    audit_admission = (
        audit_data.get("admission_decision") or audit_data["lineage"]["admission_decision"]
    )

    # 1. Candidate ID parity
    assert (
        health.last_cycle_result.candidate_id
        == daemon_health["active_candidates"]["BTCUSDT"]
        == audit_candidate_id
        == cycle_result["candidate_id"]
        == reg_entry.candidate_id
        == cand_b_id
    )

    # 2. Cryptographic hash parity
    assert daemon_health["last_registry_reload"]["registry_hash"] == manifest.registry_hash
    assert (
        audit_candidate_hash
        == cycle_result["candidate_artifact_hash"]
        == reg_entry.candidate_artifact_hash
    )
    assert (
        audit_qualification_hash
        == cycle_result["qualification_hash"]
        == reg_entry.qualification_hash
    )

    # 3. Status parity
    assert health.admitted_candidates_count >= 1
    assert daemon_health["last_registry_reload"]["reload_status"] == "RELOADED"
    assert audit_admission == "admitted"
    assert audit_data["cycle_status"] == "completed_admitted"
    assert cycle_result["cycle_status"] == "completed_admitted"
    assert cycle_result["admission_decision"] == "admitted"


def test_autonomous_closed_loop_interval_trigger_e2e(tmp_path: Path) -> None:
    """Scenario 2: Interval Timer Trigger with Fresh Market Data Executes & Hot-Reloads.

    Sequence:
    1. Baseline Ingestion: LivePaperEngine initialized with Candidate A.
    2. Fresh Market Data: Canonical 5m Parquet loaded.
    3. Ledger State: Empty ledger with zero performance breach.
    4. Trigger: Autonomous scheduler executes cycle on scheduled interval expiration.
    5. Admission & Reload: Candidate B qualified, published, and hot-reloaded into engine.
    6. Subsequent Trade: Engine immediately adopts Candidate B.
    """
    storage_dir = tmp_path / "paper_live_interval"
    storage_dir.mkdir(parents=True, exist_ok=True)
    scheduler_out = tmp_path / "scheduler_out_interval"
    scheduler_out.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"
    scheduler_health_file = scheduler_out / "scheduler-health.json"

    # Pre-stage Candidate A
    cand_a = _build_test_candidate("cand-interval-alpha", symbol="BTCUSDT")
    cand_a_file = storage_dir / f"{cand_a.candidate_id}.json"
    write_creator_candidate_artifact(cand_a_file, cand_a)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_a.candidate_id,
        candidate_artifact_hash=cand_a.artifact_hash,
        artifact_path=cand_a_file,
        qualification_hash=QUAL_HASH,
        admitted_at=NOW,
    )

    engine = _setup_engine(storage_dir, {"BTCUSDT": cand_a})
    _seed_warmup_bars(engine, "BTCUSDT", count=25)
    reloader = CandidateRegistryHotReloader(manifest_path, engine, base_dir=storage_dir)
    assert reloader.check_and_reload() is True
    assert engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id

    # Spawn scheduler with short interval (1s integer) and disabled breach checking (100.0s)
    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(scheduler_out),
            "--health-file",
            str(scheduler_health_file),
            "--parquet-path",
            str(CANONICAL_PARQUET),
            "--ledger-db",
            str(storage_dir / "paper-ledger.sqlite3"),
            "--candidate-registry-path",
            str(manifest_path),
            "--interval-seconds",
            "1",
            "--min-cooldown-seconds",
            "0.1",
            "--poll-interval-seconds",
            "0.1",
            "--check-breach-interval-seconds",
            "100.0",
            "--provider",
            "demo",
            "--windows-count",
            "1",
            "--bars-per-window",
            "100",
            "--min-trades",
            "1",
            "--min-windows",
            "1",
            "--min-profit-factor",
            "0.10",
            "--max-drawdown-pct",
            "50.0",
            "--min-average-return-pct",
            "-10.0",
        ]
    )

    try:
        health = poll_health_checkpoint(
            scheduler_health_file, timeout=14.0, min_cycles=1, proc=proc
        )
        assert health.total_cycles_executed >= 1
        assert health.last_cycle_result is not None
        assert health.last_cycle_result.trigger_type == "interval"
        assert health.last_cycle_result.status == "completed_admitted"
        assert health.last_cycle_result.admitted is True
        cand_b_id = health.last_cycle_result.candidate_id
        assert cand_b_id is not None
        assert cand_b_id != cand_a.candidate_id
    finally:
        terminate_scheduler(proc)

    # Hot-reload admitted candidate into engine
    assert reloader.check_and_reload() is True
    assert reloader.last_reload_status == "RELOADED"
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b_id

    # Subsequent trade opens and adopts Candidate B
    opened = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=datetime.now(UTC)
    )
    assert opened is not None
    trade = engine.active_trades["BTCUSDT"]
    assert trade.candidate_id == cand_b_id
    assert engine.reconcile_balances()["zero_balance_drift"] is True


def test_e2e_open_trade_tick_atr_trailing_stop_immutability(tmp_path: Path) -> None:
    """Scenario 3: Tick-Level ATR Trailing Stop Price Immutability Invariant.

    Verifies that:
    1. Active trade retains Candidate A's trailing ATR multiplier (1.0x) bound at trade entry.
    2. Hot-reload admits Candidate B with a wider trailing ATR multiplier (3.5x).
    3. During subsequent market price advancement and pullback, the active trade calculates
       its ratcheted trailing stop price strictly using Candidate A's 1.0x multiplier,
       triggering a trailing stop exit when Candidate B's wider 3.5x stop would not.
    4. Subsequent trade adopts Candidate B and evaluates the wider 3.5x trailing stop.
    """
    storage_dir = tmp_path / "paper_live_tick_immutability"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    # Candidate A: tight trail (1.0x ATR)
    cand_a = _build_test_candidate("cand-a-tick-e2e", trail_mult="1.0")
    cand_a_file = storage_dir / f"{cand_a.candidate_id}.json"
    write_creator_candidate_artifact(cand_a_file, cand_a)

    # Candidate B: wide trail (3.5x ATR)
    cand_b = _build_test_candidate("cand-b-tick-e2e", trail_mult="3.5")
    cand_b_file = storage_dir / f"{cand_b.candidate_id}.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_a.candidate_id,
        candidate_artifact_hash=cand_a.artifact_hash,
        artifact_path=cand_a_file,
        qualification_hash=QUAL_HASH,
        admitted_at=NOW,
    )

    engine = _setup_engine(storage_dir, {"BTCUSDT": cand_a})
    _seed_warmup_bars(engine, "BTCUSDT", count=25)
    reloader = CandidateRegistryHotReloader(manifest_path, engine, base_dir=storage_dir)
    assert reloader.check_and_reload() is True

    # 1. Open Trade 1 at $50,001.00 under Candidate A (ATR = 100.00)
    opened = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW)
    assert opened is not None
    trade_1 = engine.active_trades["BTCUSDT"]
    assert trade_1.candidate_id == cand_a.candidate_id
    assert trade_1.trailing_atr_multiplier == Decimal("1.0")

    # 2. Hot-reload Candidate B into engine candidate pool
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="2" * 64,
        admitted_at=NOW + timedelta(seconds=2),
    )
    assert reloader.check_and_reload() is True
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id

    # INVARIANT: Trade 1 still strictly bound to Candidate A multiplier (1.0x)
    assert trade_1.trailing_atr_multiplier == Decimal("1.0")

    # 3. Step A: Price rallies to $50,200.00 (ratchets trailing stop)
    tick_up = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50200.00"),
        best_bid_qty=Decimal("1.0"),
        best_ask_price=Decimal("50201.00"),
        best_ask_qty=Decimal("1.0"),
        transaction_time=NOW + timedelta(seconds=10),
        event_time=NOW + timedelta(seconds=10),
    )
    engine.latest_tickers["BTCUSDT"] = tick_up
    engine._evaluate_tick_stops("BTCUSDT", tick_up)

    # Under Candidate A (1.0x ATR): 50,200.00 - (1.0 * 100.00) = $50,100.00
    # (Under Candidate B (3.5x ATR): 50,200.00 - (3.5 * 100.00) = $49,850.00)
    assert trade_1.trailing_stop_price == Decimal("50100.00")

    # 4. Step B: Price pulls back to $50,050.00 (breaches Candidate A's $50,100.00 stop)
    tick_down = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50050.00"),
        best_bid_qty=Decimal("1.0"),
        best_ask_price=Decimal("50051.00"),
        best_ask_qty=Decimal("1.0"),
        transaction_time=NOW + timedelta(seconds=20),
        event_time=NOW + timedelta(seconds=20),
    )
    engine.latest_tickers["BTCUSDT"] = tick_down
    engine._evaluate_tick_stops("BTCUSDT", tick_down)

    # Trade 1 exits on trailing_stop_hit
    assert "BTCUSDT" not in engine.active_trades
    assert engine.total_closed_trades == 1

    # Verify terminal lifecycle mark records trailing_stop_hit
    with sqlite3.connect(
        f"file:{storage_dir / 'paper-lifecycle.sqlite3'}?mode=ro", uri=True
    ) as conn:
        marks = conn.execute(
            "SELECT payload FROM paper_lifecycle_marks ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
    assert marks is not None
    mark_payload = json.loads(marks[0])
    assert mark_payload.get("lifecycle_status") == "closed"
    assert "trailing_stop_hit" in mark_payload.get("reason_codes", [])

    # 5. Step C: Subsequent Trade 2 opens and adopts Candidate B with 3.5x multiplier
    opened_2 = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW + timedelta(seconds=30)
    )
    assert opened_2 is not None
    trade_2 = engine.active_trades["BTCUSDT"]
    assert trade_2.candidate_id == cand_b.candidate_id
    assert trade_2.trailing_atr_multiplier == Decimal("3.5")
    assert engine.reconcile_balances()["zero_balance_drift"] is True


def test_e2e_tampered_manifest_fail_closed_resilience(tmp_path: Path) -> None:
    """Scenario 4: Tampered Candidate Manifest Fail-Closed Resilience.

    Verifies that corrupted, invalid, or maliciously altered candidate_registry.json
    manifests are safely rejected fail-closed without crashing the engine, mutating
    active candidates, or altering open trades:
    - Vector 1: Truncated JSON syntax error
    - Vector 2: SHA-256 cryptographic hash mismatch
    - Vector 3: Missing candidate artifact on disk
    - Vector 4: Tampered candidate artifact content (content hash mismatch)
    - Vector 5: Strategy universe symbol mismatch
    - Recovery: Valid Candidate C artifact publishes and reloads cleanly.
    """
    storage_dir = tmp_path / "paper_live_tamper"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    # Baseline: Pre-stage Candidate A
    cand_a = _build_test_candidate("cand-tamper-init", symbol="BTCUSDT")
    cand_a_file = storage_dir / f"{cand_a.candidate_id}.json"
    write_creator_candidate_artifact(cand_a_file, cand_a)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_a.candidate_id,
        candidate_artifact_hash=cand_a.artifact_hash,
        artifact_path=cand_a_file,
        qualification_hash=QUAL_HASH,
        admitted_at=NOW,
    )

    engine = _setup_engine(storage_dir, {"BTCUSDT": cand_a})
    _seed_warmup_bars(engine, "BTCUSDT", count=25)
    reloader = CandidateRegistryHotReloader(manifest_path, engine, base_dir=storage_dir)
    assert reloader.check_and_reload() is True
    assert engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id

    # Open active trade under Candidate A
    opened = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW)
    assert opened is not None
    assert "BTCUSDT" in engine.active_trades
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id

    # --- Vector 1: Truncated JSON syntax ---
    manifest_path.write_text('{"registry_version": 2, "symbols": {', encoding="utf-8")
    assert reloader.check_and_reload() is False
    assert reloader.last_reload_status == "FAILED_CORRUPT"
    assert engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id

    # --- Vector 2: SHA-256 cryptographic hash mismatch ---
    manifest_tampered_hash = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id=cand_a.candidate_id,
                candidate_artifact_hash=cand_a.artifact_hash,
                artifact_path=str(cand_a_file),
                qualification_hash=QUAL_HASH,
                admitted_at=NOW.isoformat(),
            )
        },
        updated_at=NOW.isoformat(),
    )
    tampered_dict = manifest_tampered_hash.model_dump(mode="json")
    tampered_dict["registry_hash"] = "e" * 64  # Invalid hash
    manifest_path.write_text(json.dumps(tampered_dict), encoding="utf-8")
    assert reloader.check_and_reload() is False
    assert reloader.last_reload_status == "FAILED_HASH_MISMATCH"
    assert engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id

    # --- Vector 3: Missing candidate artifact file on disk ---
    manifest_missing_artifact = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id="cand-ghost-missing",
                candidate_artifact_hash="7" * 64,
                artifact_path=str(storage_dir / "ghost_file_missing.json"),
                qualification_hash=QUAL_HASH,
                admitted_at=NOW.isoformat(),
            )
        },
        updated_at=NOW.isoformat(),
    )
    write_candidate_registry(manifest_path, manifest_missing_artifact)
    assert reloader.check_and_reload() is False
    assert reloader.last_reload_status == "FAILED_ARTIFACT_MISSING"
    assert engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id

    # --- Vector 4: Tampered candidate artifact content (content hash mismatch) ---
    cand_tampered = _build_test_candidate("cand-content-tampered", symbol="BTCUSDT")
    cand_tampered_file = storage_dir / f"{cand_tampered.candidate_id}.json"
    write_creator_candidate_artifact(cand_tampered_file, cand_tampered)

    manifest_bad_content_hash = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id=cand_tampered.candidate_id,
                candidate_artifact_hash="f" * 64,  # Does not match file content hash
                artifact_path=str(cand_tampered_file),
                qualification_hash=QUAL_HASH,
                admitted_at=NOW.isoformat(),
            )
        },
        updated_at=NOW.isoformat(),
    )
    write_candidate_registry(manifest_path, manifest_bad_content_hash)
    assert reloader.check_and_reload() is False
    assert reloader.last_reload_status in ("FAILED_ARTIFACT_HASH_MISMATCH", "FAILED_CORRUPT")
    assert engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id

    # --- Vector 5: Strategy universe symbol mismatch ---
    cand_eth = _build_test_candidate("cand-eth-only", symbol="ETHUSDT")
    cand_eth_file = storage_dir / f"{cand_eth.candidate_id}.json"
    write_creator_candidate_artifact(cand_eth_file, cand_eth)

    manifest_symbol_mismatch = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id=cand_eth.candidate_id,
                candidate_artifact_hash=cand_eth.artifact_hash,
                artifact_path=str(cand_eth_file),
                qualification_hash=QUAL_HASH,
                admitted_at=NOW.isoformat(),
            )
        },
        updated_at=NOW.isoformat(),
    )
    write_candidate_registry(manifest_path, manifest_symbol_mismatch)
    assert reloader.check_and_reload() is False
    assert reloader.last_reload_status in ("FAILED_UNIVERSE_MISMATCH", "FAILED_CORRUPT")
    assert engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id

    # --- Recovery: Publish valid Candidate C manifest ---
    cand_c = _build_test_candidate("cand-valid-recovery", symbol="BTCUSDT")
    cand_c_file = storage_dir / f"{cand_c.candidate_id}.json"
    write_creator_candidate_artifact(cand_c_file, cand_c)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_c.candidate_id,
        candidate_artifact_hash=cand_c.artifact_hash,
        artifact_path=cand_c_file,
        qualification_hash=QUAL_HASH,
        admitted_at=NOW + timedelta(seconds=10),
    )
    assert reloader.check_and_reload() is True
    assert reloader.last_reload_status == "RELOADED"
    assert engine.candidates["BTCUSDT"].candidate_id == cand_c.candidate_id

    # Original trade STILL retained under Candidate A
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id

    # Close original trade and open subsequent trade -> adopts Candidate C
    engine.execute_close(
        "BTCUSDT", exit_reason="strategy_exit", event_time=NOW + timedelta(minutes=15)
    )
    assert "BTCUSDT" not in engine.active_trades

    opened_c = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW + timedelta(minutes=20)
    )
    assert opened_c is not None
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_c.candidate_id
    assert engine.reconcile_balances()["zero_balance_drift"] is True
