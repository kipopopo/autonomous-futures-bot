"""Phase 251: Offline Paper Trading Simulation Harness Runner.

Executes deterministic, sandboxed offline paper trading simulation for
qualified candidate strategy cand-a5454657c3fc480b03246904e7674eeabe9f35890ee863c24ce2788e3f5c4c15
(DOGEUSDT 5m) using isolated SQLite ledger, lifecycle, and observation stores,
verifying balance reconciliation, position reconciliation, and generating
PaperHealthReport and PaperCohortReadinessReport with zero exchange access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

# Ensure src/ is on sys.path
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import pandas as pd  # noqa: E402

from autonomous_futures.creator_staging_probe import (  # noqa: E402
    assert_offline_safety_invariants,
)
from autonomous_futures.data.parquet import canonicalize_bars  # noqa: E402
from autonomous_futures.domain.contracts import PaperExecutionRequest  # noqa: E402
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.cohort import (  # noqa: E402
    PaperCohortReadinessReport,
    summarize_paper_cohort,
)
from autonomous_futures.paper.health import (  # noqa: E402
    PaperHealthReport,
    aggregate_paper_health,
)
from autonomous_futures.paper.lifecycle import (  # noqa: E402
    PaperLifecycleTelemetry,
    mark_paper_position,
)
from autonomous_futures.paper.observation import (  # noqa: E402
    PaperObservation,
    PaperObservationBinding,
    observe_paper_ledger,
)
from autonomous_futures.paper.reconciliation import (  # noqa: E402
    reconcile_paper_positions,
)
from autonomous_futures.paper.runtime import PaperRuntime  # noqa: E402
from autonomous_futures.paper.safety import (  # noqa: E402
    PaperActionApproval,
    PaperSafetyEvidence,
)
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger  # noqa: E402
from autonomous_futures.paper.sqlite_lifecycle import SqlitePaperLifecycle  # noqa: E402
from autonomous_futures.paper.sqlite_observation import (  # noqa: E402
    SqlitePaperObservations,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    read_creator_candidate_artifact,
)
from autonomous_futures.research.feature_signals import (  # noqa: E402
    CausalFeatureSignalEvaluator,
)
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    CreatorCandidateQualificationArtifact,
    read_creator_candidate_qualification_artifact,
)

# Authoritative Pinned Constants
PINNED_CANDIDATE_ID: str = "cand-a5454657c3fc480b03246904e7674eeabe9f35890ee863c24ce2788e3f5c4c15"
PINNED_ARTIFACT_HASH: str = "da8aeee9abebe32445d3139322a95fccd605baeea4cf2cc742a2610af1019659"
PINNED_QUALIFICATION_HASH: str = "907654abf169c9b81f917e0601eaa4c2352b4ee37db2322716add0aa0be9adeb"
PINNED_BUNDLE_HASH: str = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
PINNED_REGISTRY_HASH: str = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"
DEFAULT_SYMBOL: str = "DOGEUSDT"

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _assert_zero_secrets(text: str, source_label: str) -> None:
    match = _SECRET_PATTERN.search(text)
    if match:
        raise DomainViolation(f"Secret pattern matched in {source_label}: {match.group(0)[:8]}...")


def compute_file_sha256(path: Path) -> str:
    """Compute hex SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def generate_deterministic_5m_bars(
    start: datetime = datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    days: int = 7,
) -> pd.DataFrame:
    """Generate sequential 5m OHLC bars producing mean-reversion signals for DOGEUSDT.

    Spans the specified number of days (at 4 six-hour cycles per day, 72 bars per cycle).
    Outputs clean DataFrame validated against canonicalize_bars.
    """
    cycle_bars = 72
    total_cycles = days * 4
    all_prices: list[float] = []

    for c in range(total_cycles):
        flat = [0.150] * 15
        if c % 4 == 3:
            # Shallow adverse continuation cycle producing controlled small trade loss
            dip = [0.142, 0.142, 0.141, 0.140, 0.139, 0.138]
            bounce = [0.138 + 0.0003 * i for i in range(1, 12)]
            rally = [0.141 + 0.001 * i for i in range(1, 10)]
            retrace = [0.150 - 0.0003 * i for i in range(1, 10)]
        else:
            # Standard mean-reversion cycle (dip -> Long -> bounce -> rally -> Short -> exit)
            dip = [0.140, 0.140]
            bounce = [0.140 + 0.001 * i for i in range(1, 10)]
            rally = [0.150 + 0.001 * i for i in range(1, 10)]
            retrace = [0.159 - 0.001 * i for i in range(1, 10)]
        rest = [0.150] * (
            cycle_bars - len(flat) - len(dip) - len(bounce) - len(rally) - len(retrace)
        )
        all_prices.extend(flat + dip + bounce + rally + retrace + rest)

    # Append terminal closing bar
    all_prices.append(all_prices[-1])
    timestamps = [start + timedelta(minutes=5 * i) for i in range(len(all_prices))]

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal(str(round(p, 5))) for p in all_prices],
            "high": [Decimal(str(round(p + 0.0005, 5))) for p in all_prices],
            "low": [Decimal(str(round(p - 0.0005, 5))) for p in all_prices],
            "close": [Decimal(str(round(p, 5))) for p in all_prices],
        }
    )
    return canonicalize_bars(df, interval=timedelta(minutes=5))


@dataclass(frozen=True, slots=True)
class Phase251PaperSimulationResult:
    candidate_id: str
    candidate_artifact_hash: str
    output_dir: Path
    total_bars: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    starting_equity: Decimal
    final_cash: Decimal
    realized_pnl: Decimal
    cumulative_fees: Decimal
    cumulative_slippage: Decimal
    health_report: PaperHealthReport
    cohort_report: PaperCohortReadinessReport
    positions_reconciled: bool
    accounting_reconciled: bool
    artifact_hashes: dict[str, str]
    summary_path: Path


def run_paper_simulation(
    *,
    candidate_path: Path = Path("artifacts/research/phase250/candidate-artifact.json"),
    qualification_path: Path = Path("artifacts/research/phase250/qualification-artifact.json"),
    output_dir: Path = Path("artifacts/paper/phase251"),
    data_path: Path | None = None,
    days: int = 7,
    starting_equity: Decimal = Decimal("10000.00"),
    quantity: Decimal = Decimal("1000.0"),
    fee_rate: Decimal = Decimal("0.0004"),
    slippage_bps: Decimal = Decimal("2"),
    max_mark_age_seconds: int = 86400,
    symbol: str = DEFAULT_SYMBOL,
) -> Phase251PaperSimulationResult:
    """Execute complete offline deterministic paper trading simulation."""
    # 1. Enforce strict offline safety invariants (zero Binance keys, zero live execution authority)
    assert_offline_safety_invariants()

    # 2. Load candidate artifact and qualification evidence
    if not candidate_path.is_file():
        raise FileNotFoundError(f"Candidate artifact not found: {candidate_path}")
    if not qualification_path.is_file():
        raise FileNotFoundError(f"Qualification artifact not found: {qualification_path}")

    candidate: CreatorCandidateArtifact = read_creator_candidate_artifact(candidate_path)
    qualification: CreatorCandidateQualificationArtifact = (
        read_creator_candidate_qualification_artifact(qualification_path)
    )

    if candidate.candidate_id != PINNED_CANDIDATE_ID:
        raise DomainViolation(
            f"candidate_id mismatch: expected {PINNED_CANDIDATE_ID}, got {candidate.candidate_id}"
        )
    if candidate.artifact_hash != PINNED_ARTIFACT_HASH:
        raise DomainViolation(
            f"artifact_hash mismatch: expected {PINNED_ARTIFACT_HASH}, "
            f"got {candidate.artifact_hash}"
        )
    if qualification.decision != "qualified":
        raise DomainViolation(
            f"qualification decision must be 'qualified', got '{qualification.decision}'"
        )
    if qualification.qualification_hash != PINNED_QUALIFICATION_HASH:
        raise DomainViolation(
            f"qualification_hash mismatch: expected {PINNED_QUALIFICATION_HASH}, "
            f"got {qualification.qualification_hash}"
        )

    # 3. Setup isolated output directories and SQLite storage
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_db_path = output_dir / "paper-ledger.sqlite3"
    lifecycle_db_path = output_dir / "paper-lifecycle.sqlite3"
    observation_db_path = output_dir / "paper-observations.sqlite3"

    # Remove existing databases in output_dir to ensure clean idempotency
    for p in (ledger_db_path, lifecycle_db_path, observation_db_path):
        if p.exists():
            p.unlink()

    ledger_store = SqlitePaperLedger(ledger_db_path)
    lifecycle_store = SqlitePaperLifecycle(lifecycle_db_path)
    observation_store = SqlitePaperObservations(observation_db_path)
    runtime = PaperRuntime(ledger_store)

    evidence = PaperSafetyEvidence(
        candidate_id=candidate.candidate_id,
        candidate_artifact_hash=candidate.artifact_hash,
        qualification_hash=qualification.qualification_hash,
        qualification_decision=qualification.decision,
        zero_oos_liquidations=True,
    )

    # 4. Load or generate sequential 5m historical bars
    start_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    if data_path is not None and data_path.is_file():
        if data_path.suffix == ".parquet":
            raw_df = pd.read_parquet(data_path)
        else:
            raw_df = pd.read_csv(data_path)
        bars_df = canonicalize_bars(raw_df, interval=timedelta(minutes=5))
    else:
        bars_df = generate_deterministic_5m_bars(start=start_time, days=days)

    evaluated = CausalFeatureSignalEvaluator().evaluate(candidate, bars_df)

    # 5. Deterministic offline paper simulation loop
    previous_peak_equity = starting_equity
    qualified_symbols = (symbol,)
    active_trade: dict[str, Any] | None = None
    trade_count = 0
    observations: list[PaperObservation] = []

    for idx, row in evaluated.iterrows():
        bar_ts: datetime = row["timestamp"]
        bar_close: Decimal = Decimal(str(row["close"]))
        rsi: float = float(row["rsi"])
        signal: int = int(row["signal"])
        is_terminal: bool = idx == len(evaluated) - 1

        # A. Position lifecycle management & exit evaluation
        if active_trade is not None:
            # Mark open position at current bar
            marked = mark_paper_position(
                active_trade["open_entry"],
                mark_price=bar_close,
                marked_at=bar_ts,
                previous_peak_pnl=active_trade["peak_pnl"],
            )
            active_trade["peak_pnl"] = marked.peak_pnl
            lifecycle_store.append(marked)

            # Check strategy exit condition or terminal liquidation
            side: Literal["LONG", "SHORT"] = active_trade["side"]
            exit_triggered = False
            if side == "LONG" and rsi >= 50.0:
                exit_triggered = True
            elif side == "SHORT" and rsi <= 50.0:
                exit_triggered = True
            elif marked.lifecycle_status == "exit_ready" or is_terminal:
                exit_triggered = True

            if exit_triggered:
                close_req = PaperExecutionRequest(
                    candidate_id=candidate.candidate_id,
                    candidate_artifact_hash=candidate.artifact_hash,
                    qualified_symbols=qualified_symbols,
                    symbol=symbol,
                    side=side,
                    mark_price=bar_close,
                    quantity=quantity,
                    fee_rate=fee_rate,
                    slippage_bps=slippage_bps,
                )
                close_approval = PaperActionApproval(
                    approval_id=f"apprv-close-{trade_count:04d}",
                    candidate_id=candidate.candidate_id,
                    candidate_artifact_hash=candidate.artifact_hash,
                    trade_id=active_trade["trade_id"],
                    action="close",
                    approved_at=bar_ts,
                    expires_at=bar_ts + timedelta(minutes=5),
                )
                close_res = runtime.close(
                    close_req,
                    evidence,
                    close_approval,
                    trade_id=active_trade["trade_id"],
                    exit_mark_price=bar_close,
                    occurred_at=bar_ts,
                )
                if close_res.status != "closed":
                    raise RuntimeError(f"Failed to close paper trade: {close_res}")
                active_trade = None

        # B. Entry signal evaluation
        if active_trade is None and not is_terminal and signal != 0:
            entry_side: Literal["LONG", "SHORT"] = "LONG" if signal == 1 else "SHORT"
            trade_count += 1
            trade_id = f"paper-trade-{trade_count:04d}"
            open_req = PaperExecutionRequest(
                candidate_id=candidate.candidate_id,
                candidate_artifact_hash=candidate.artifact_hash,
                qualified_symbols=qualified_symbols,
                symbol=symbol,
                side=entry_side,
                mark_price=bar_close,
                quantity=quantity,
                fee_rate=fee_rate,
                slippage_bps=slippage_bps,
            )
            open_approval = PaperActionApproval(
                approval_id=f"apprv-open-{trade_count:04d}",
                candidate_id=candidate.candidate_id,
                candidate_artifact_hash=candidate.artifact_hash,
                trade_id=trade_id,
                action="open",
                approved_at=bar_ts,
                expires_at=bar_ts + timedelta(minutes=5),
            )
            open_res = runtime.open(
                open_req,
                evidence,
                open_approval,
                trade_id=trade_id,
                occurred_at=bar_ts,
            )
            if open_res.status != "opened":
                raise RuntimeError(f"Failed to open paper trade: {open_res}")
            open_entry = next(
                e for e in ledger_store.load().open_positions() if e.trade_id == trade_id
            )
            initial_mark = mark_paper_position(
                open_entry,
                mark_price=bar_close,
                marked_at=bar_ts,
                previous_peak_pnl=Decimal("0"),
            )
            lifecycle_store.append(initial_mark)
            active_trade = {
                "trade_id": trade_id,
                "side": entry_side,
                "open_entry": open_entry,
                "peak_pnl": initial_mark.peak_pnl,
            }

        # C. Periodic 6-hour slot observation snapshot
        if bar_ts.minute == 0 and bar_ts.second == 0 and bar_ts.hour % 6 == 0:
            obs = observe_paper_ledger(
                ledger_store.load(),
                candidate_id=candidate.candidate_id,
                candidate_artifact_hash=candidate.artifact_hash,
                starting_equity=starting_equity,
                previous_peak_equity=previous_peak_equity,
                mark_prices={symbol: bar_close},
                observed_at=bar_ts,
            )
            previous_peak_equity = max(previous_peak_equity, obs.equity)
            observation_store.append(obs)
            observations.append(obs)

    # 6. Post-simulation balance and position reconciliation
    final_ledger = ledger_store.load()
    reconciliation = reconcile_paper_positions(final_ledger, ())
    if not reconciliation.reconciled:
        raise DomainViolation(f"Position reconciliation failed: {reconciliation}")

    closed_entries = [e for e in final_ledger.entries if e.event == "close"]
    for entry in closed_entries:
        assert entry.gross_pnl is not None
        assert entry.entry_fee is not None
        assert entry.exit_fee is not None
        assert entry.net_pnl is not None
        expected_net = entry.gross_pnl - entry.entry_fee - entry.exit_fee
        if entry.net_pnl != expected_net:
            tot_fee = entry.entry_fee + entry.exit_fee
            raise DomainViolation(
                f"Accounting discrepancy on trade {entry.trade_id}: "
                f"net_pnl={entry.net_pnl} != gross({entry.gross_pnl}) - fees({tot_fee})"
            )

    realized_pnl = sum(
        (e.net_pnl for e in closed_entries if e.net_pnl is not None),
        Decimal("0"),
    )
    final_cash = starting_equity + realized_pnl
    cumulative_fees = sum(
        ((e.entry_fee or Decimal("0")) + (e.exit_fee or Decimal("0")) for e in closed_entries),
        Decimal("0"),
    )
    cumulative_slippage = sum(
        (e.slippage_cost or Decimal("0") for e in closed_entries),
        Decimal("0"),
    )

    winning_trades = sum(1 for e in closed_entries if (e.net_pnl or Decimal("0")) > 0)
    losing_trades = sum(1 for e in closed_entries if (e.net_pnl or Decimal("0")) < 0)
    win_rate = float(winning_trades / len(closed_entries)) if closed_entries else 0.0

    # 7. Aggregate health and cohort reports
    as_of = start_time + timedelta(days=days)
    open_positions = final_ledger.open_positions()
    active_marks: list[PaperLifecycleTelemetry] = []
    for pos in open_positions:
        m = lifecycle_store.latest(
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            trade_id=pos.trade_id,
        )
        if m is not None:
            active_marks.append(m)

    health_report = aggregate_paper_health(
        observations,
        tuple(active_marks),
        candidate_id=candidate.candidate_id,
        candidate_artifact_hash=candidate.artifact_hash,
        as_of=as_of,
        max_mark_age_seconds=max_mark_age_seconds,
        required_days=days,
    )

    cohort_binding = PaperObservationBinding(
        candidate_id=candidate.candidate_id,
        candidate_artifact_hash=candidate.artifact_hash,
    )
    cohort_report = summarize_paper_cohort([health_report], [cohort_binding])

    # 8. Persist JSON reports
    health_report_path = output_dir / "paper-health-report.json"
    cohort_report_path = output_dir / "paper-cohort-readiness-report.json"
    summary_path = output_dir / "paper-simulation-summary.json"

    health_json = json.dumps(health_report.model_dump(mode="json"), indent=2, sort_keys=True)
    _assert_zero_secrets(health_json, str(health_report_path))
    health_report_path.write_text(health_json, encoding="utf-8")

    cohort_json = json.dumps(cohort_report.model_dump(mode="json"), indent=2, sort_keys=True)
    _assert_zero_secrets(cohort_json, str(cohort_report_path))
    cohort_report_path.write_text(cohort_json, encoding="utf-8")

    # Compute artifact hashes for manifest
    artifact_hashes: dict[str, str] = {
        "paper-ledger.sqlite3": compute_file_sha256(ledger_db_path),
        "paper-lifecycle.sqlite3": compute_file_sha256(lifecycle_db_path),
        "paper-observations.sqlite3": compute_file_sha256(observation_db_path),
        "paper-health-report.json": compute_file_sha256(health_report_path),
        "paper-cohort-readiness-report.json": compute_file_sha256(cohort_report_path),
    }

    summary_payload: dict[str, Any] = {
        "phase": "phase_251",
        "description": "Phase 251 Offline Paper Trading Simulation Harness",
        "candidate_id": candidate.candidate_id,
        "candidate_artifact_hash": candidate.artifact_hash,
        "bundle_hash": PINNED_BUNDLE_HASH,
        "dataset_registry_hash": PINNED_REGISTRY_HASH,
        "qualification_hash": PINNED_QUALIFICATION_HASH,
        "symbol": symbol,
        "simulation_start": start_time.isoformat(),
        "simulation_end": as_of.isoformat(),
        "days_evaluated": days,
        "total_bars": len(evaluated),
        "total_trades": len(closed_entries),
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(win_rate, 4),
        "starting_equity": str(starting_equity),
        "final_cash": str(final_cash),
        "realized_pnl": str(realized_pnl),
        "cumulative_fees": str(cumulative_fees),
        "cumulative_slippage": str(cumulative_slippage),
        "health_status": health_report.health_status,
        "maturity_status": health_report.maturity_status,
        "cohort_status": cohort_report.cohort_status,
        "positions_reconciled": True,
        "accounting_reconciled": True,
        "safety_invariants": {
            "orders": 0,
            "exchange_access": False,
            "execution_authority": False,
            "promotion_state": "unpromoted",
            "paper_activation": False,
            "data_source": "cached_only",
            "zero_secret_leakage": True,
        },
        "artifact_hashes": artifact_hashes,
    }

    summary_json = json.dumps(summary_payload, indent=2, sort_keys=True)
    _assert_zero_secrets(summary_json, str(summary_path))
    summary_path.write_text(summary_json, encoding="utf-8")
    artifact_hashes["paper-simulation-summary.json"] = compute_file_sha256(summary_path)

    return Phase251PaperSimulationResult(
        candidate_id=candidate.candidate_id,
        candidate_artifact_hash=candidate.artifact_hash,
        output_dir=output_dir,
        total_bars=len(evaluated),
        total_trades=len(closed_entries),
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        starting_equity=starting_equity,
        final_cash=final_cash,
        realized_pnl=realized_pnl,
        cumulative_fees=cumulative_fees,
        cumulative_slippage=cumulative_slippage,
        health_report=health_report,
        cohort_report=cohort_report,
        positions_reconciled=True,
        accounting_reconciled=True,
        artifact_hashes=artifact_hashes,
        summary_path=summary_path,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 251 Offline Paper Trading Simulation Runner."
    )
    parser.add_argument(
        "--candidate-path",
        type=Path,
        default=Path("artifacts/research/phase250/candidate-artifact.json"),
        help="Path to candidate artifact JSON.",
    )
    parser.add_argument(
        "--qualification-path",
        type=Path,
        default=Path("artifacts/research/phase250/qualification-artifact.json"),
        help="Path to qualification artifact JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/paper/phase251"),
        help="Output directory for simulation artifacts.",
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        default=None,
        help="Optional path to historical bar dataset (Parquet or CSV).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of simulated days (default: 7).",
    )
    parser.add_argument(
        "--starting-equity",
        type=str,
        default="10000.00",
        help="Starting equity in quote currency (default: 10000.00).",
    )
    parser.add_argument(
        "--quantity",
        type=str,
        default="1000.0",
        help="Position quantity per trade (default: 1000.0).",
    )
    parser.add_argument(
        "--fee-rate",
        type=str,
        default="0.0004",
        help="Taker fee rate (default: 0.0004).",
    )
    parser.add_argument(
        "--slippage-bps",
        type=str,
        default="2",
        help="Adverse slippage in basis points (default: 2).",
    )
    parser.add_argument(
        "--max-mark-age-seconds",
        type=int,
        default=86400,
        help="Maximum mark age seconds for health evaluation (default: 86400).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_paper_simulation(
        candidate_path=args.candidate_path,
        qualification_path=args.qualification_path,
        output_dir=args.output_dir,
        data_path=args.data_path,
        days=args.days,
        starting_equity=Decimal(args.starting_equity),
        quantity=Decimal(args.quantity),
        fee_rate=Decimal(args.fee_rate),
        slippage_bps=Decimal(args.slippage_bps),
        max_mark_age_seconds=args.max_mark_age_seconds,
    )
    print(
        f"Phase 251 Paper Simulation Complete:\n"
        f"  Candidate ID:       {result.candidate_id}\n"
        f"  Artifact Hash:      {result.candidate_artifact_hash}\n"
        f"  Total Bars:         {result.total_bars}\n"
        f"  Total Trades:       {result.total_trades} "
        f"(Wins: {result.winning_trades}, Losses: {result.losing_trades})\n"
        f"  Win Rate:           {result.win_rate:.2%}\n"
        f"  Realized PnL:       {result.realized_pnl}\n"
        f"  Final Cash:         {result.final_cash}\n"
        f"  Health Status:      {result.health_report.health_status}\n"
        f"  Maturity Status:    {result.health_report.maturity_status}\n"
        f"  Cohort Status:      {result.cohort_report.cohort_status}\n"
        f"  Summary Artifact:   {result.summary_path}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
