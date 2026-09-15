"""Phase 263 Multi-Asset Higher-Timeframe Deterministic Paper Replay under Manifest Version 2.

Simulates multi-asset strategy execution across a synchronized 15-minute clock for 7 days
under Candidate Registry Manifest Version 2, featuring:
1. BTCUSDT: cand-btcusdt-dcb-002 (15m Donchian Breakout, lookback 50, 1h context)
2. ETHUSDT: cand-ethusdt-dcb-003 (15m Calibrated Donchian Breakout, stop 1.5 ATR, trail 1.2 ATR)
3. SOLUSDT: cand-solusdt-rgb-001 (1h Regime Gated Breakout, lookback 20 + ADX > 25, 4h context)

Enforces:
- Shared margin account (100.00 USDT initial equity, 80% ceiling, 20% unencumbered buffer).
- Adverse execution modeling: 2.0 bps slippage, 0.04% taker fee.
- At most one position per symbol, no negative cash, and exact SQLite ledger reconciliation.
- Complete accounting proof showing zero balance drift (< 1e-15).
- Fail-closed runtime: paper_activation=False, execution_authority=False, exchange_access=False.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.creator_staging_probe import (  # noqa: E402
    assert_offline_safety_invariants,
)
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    read_candidate_registry,
    validate_manifest_candidate_artifacts,
)
from scripts.run_phase_262_paper_simulation import (  # noqa: E402
    DEFAULT_DAYS,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_START_TIME,
    DEFAULT_STARTING_EQUITY,
    DEFAULT_TAKER_FEE_RATE,
    Phase262SimulationResult,
    run_phase_262_simulation,
)

logger = logging.getLogger("run_phase_263_paper_simulation")

DEFAULT_PHASE263_OUTPUT_DIR = Path("artifacts/research/phase263")

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _assert_zero_secrets(text: str, source_label: str) -> None:
    match = _SECRET_PATTERN.search(text)
    if match:
        raise DomainViolation(f"Secret pattern matched in {source_label}: {match.group(0)[:8]}...")


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class Phase263SimulationResult(Phase262SimulationResult):
    registry_version: int = 2


def run_phase_263_simulation(
    output_dir: Path = DEFAULT_PHASE263_OUTPUT_DIR,
    *,
    registry_path: Path = DEFAULT_CANDIDATE_REGISTRY_PATH,
    start_time: datetime = DEFAULT_START_TIME,
    days: int = DEFAULT_DAYS,
    starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
    fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
) -> Phase263SimulationResult:
    """Execute Phase 263 multi-asset paper simulation replay under Manifest v2."""
    assert_offline_safety_invariants()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Validate Candidate Registry Manifest v2
    manifest = read_candidate_registry(registry_path, verify_hash=True)
    if manifest.registry_version < 2:
        raise DomainViolation(
            f"Phase 263 requires candidate registry version >= 2, got {manifest.registry_version}"
        )

    eth_entry = manifest.symbols.get("ETHUSDT")
    if eth_entry is None or eth_entry.candidate_id != "cand-ethusdt-dcb-003":
        raise DomainViolation(
            f"Phase 263 requires calibrated ETHUSDT candidate cand-ethusdt-dcb-003, "
            f"got {eth_entry.candidate_id if eth_entry else 'missing'}"
        )

    validate_manifest_candidate_artifacts(manifest)

    # 2. Run simulation using verified multi-asset synchronized harness
    base_res = run_phase_262_simulation(
        output_dir=output_dir,
        registry_path=registry_path,
        start_time=start_time,
        days=days,
        starting_equity=starting_equity,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
    )

    # 3. Customize paper-summary.json for Phase 263
    summary_path = output_dir / "paper-summary.json"
    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_data["phase"] = "phase_263"
    summary_data["description"] = (
        "Phase 263 Multi-Asset Higher-Timeframe Deterministic Paper Replay under Manifest v2"
    )
    summary_data["registry_version"] = manifest.registry_version
    summary_json = json.dumps(summary_data, indent=2, sort_keys=True)
    _assert_zero_secrets(summary_json, str(summary_path))
    summary_path.write_text(summary_json, encoding="utf-8")

    # 4. Update artifact hashes
    artifact_hashes = dict(base_res.artifact_hashes)
    artifact_hashes["paper-summary.json"] = compute_file_sha256(summary_path)

    return Phase263SimulationResult(
        output_dir=base_res.output_dir,
        total_bars=base_res.total_bars,
        total_trades=base_res.total_trades,
        winning_trades=base_res.winning_trades,
        losing_trades=base_res.losing_trades,
        win_rate=base_res.win_rate,
        starting_equity=base_res.starting_equity,
        final_cash=base_res.final_cash,
        realized_pnl=base_res.realized_pnl,
        cumulative_fees=base_res.cumulative_fees,
        cumulative_slippage=base_res.cumulative_slippage,
        max_margin_utilization=base_res.max_margin_utilization,
        candidate_summaries=base_res.candidate_summaries,
        health_reports=base_res.health_reports,
        cohort_report=base_res.cohort_report,
        positions_reconciled=base_res.positions_reconciled,
        accounting_reconciled=base_res.accounting_reconciled,
        artifact_hashes=artifact_hashes,
        summary_path=summary_path,
        registry_version=manifest.registry_version,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 263 Multi-Asset Deterministic Paper Replay under Manifest v2"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE263_OUTPUT_DIR,
        help="Directory to store simulation output artifacts",
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=DEFAULT_CANDIDATE_REGISTRY_PATH,
        help="Path to candidate registry manifest (must be version >= 2)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help="Number of days to simulate (default: 7)",
    )
    parser.add_argument(
        "--starting-equity",
        type=Decimal,
        default=DEFAULT_STARTING_EQUITY,
        help="Starting cash in USDT (default: 100.00)",
    )
    parser.add_argument(
        "--fee-rate",
        type=Decimal,
        default=DEFAULT_TAKER_FEE_RATE,
        help="Taker fee rate (default: 0.0004)",
    )
    parser.add_argument(
        "--slippage-bps",
        type=Decimal,
        default=DEFAULT_SLIPPAGE_BPS,
        help="Adverse slippage in basis points (default: 2.0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON summary",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    res = run_phase_263_simulation(
        output_dir=args.output_dir,
        registry_path=args.registry_path,
        days=args.days,
        starting_equity=args.starting_equity,
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
    )

    if args.json:
        sys.stdout.write(res.summary_path.read_text(encoding="utf-8"))
        return 0

    sys.stdout.write("\n=== PHASE 263 DETERMINISTIC PAPER REPLAY COMPLETED ===\n")
    sys.stdout.write(f"Output Directory:       {res.output_dir}\n")
    sys.stdout.write(f"Registry Version:       {res.registry_version}\n")
    sys.stdout.write(f"Days Evaluated:         {args.days} ({res.total_bars} 15m intervals)\n")
    sys.stdout.write(f"Starting Equity:        {res.starting_equity:.2f} USDT\n")
    sys.stdout.write(f"Final Cash Balance:     {res.final_cash:.4f} USDT\n")
    sys.stdout.write(f"Net Realized PnL:       {res.realized_pnl:+.4f} USDT\n")
    sys.stdout.write(
        f"Trades:                 {res.total_trades} total "
        f"({res.winning_trades} wins, {res.losing_trades} losses, "
        f"{res.win_rate * 100:.1f}% win rate)\n"
    )
    sys.stdout.write(f"Cumulative Fees:        {res.cumulative_fees:.4f} USDT\n")
    sys.stdout.write(f"Cumulative Slippage:    {res.cumulative_slippage:.4f} USDT\n")
    sys.stdout.write(f"Max Margin Utilization: {res.max_margin_utilization * 100:.2f}%\n")
    sys.stdout.write(f"Positions Reconciled:   {res.positions_reconciled}\n")
    sys.stdout.write(f"Accounting Reconciled:  {res.accounting_reconciled}\n")
    sys.stdout.write(f"Cohort Readiness:       {res.cohort_report.cohort_status}\n\n")

    sys.stdout.write(
        f"{'Symbol':<10} {'Candidate ID':<24} {'Timeframe':<10} {'Trades':<8} "
        f"{'Realized PnL':<15} {'Health':<10}\n"
    )
    sys.stdout.write("-" * 80 + "\n")
    for sym, c_sum in res.candidate_summaries.items():
        h = res.health_reports[sym]
        pnl_val = Decimal(str(c_sum["realized_pnl_usdt"]))
        sys.stdout.write(
            f"{sym:<10} {c_sum['candidate_id']:<24} "
            f"{c_sum['timeframe']:<10} "
            f"{c_sum['trades_count']:<8} "
            f"{pnl_val:+.4f} USDT   "
            f"{h.health_status:<10}\n"
        )
    sys.stdout.write("-" * 80 + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
