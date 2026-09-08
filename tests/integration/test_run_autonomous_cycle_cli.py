"""Integration tests for scripts/run_autonomous_cycle.py CLI runner."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)

# Ensure repository root is on sys.path for scripts import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_autonomous_cycle import main as run_cli_main  # noqa: E402

PARQUET_PATH = Path("research/immutable-data/5m/canonical/BTCUSDT-5m.parquet")
BUNDLE_HASH = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
REGISTRY_HASH = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _build_candidate(
    cand_id: str,
    stop_atr: str = "1.0",
    tp_atr: str = "2.0",
    symbol: str = "BTCUSDT",
) -> CreatorCandidateArtifact:
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=cand_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=3, shift=1),),
        entry=EntryExit(long="returns > 0.001", short="returns < -0.001"),
        exit=EntryExit(long="returns < 0.0", short="returns > 0.0"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal(stop_atr),
            take_profit_atr_multiplier=Decimal(tp_atr),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=cand_id,
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="run-cli-001",
        research_seed=42,
        created_at=NOW - timedelta(days=1),
    )


def _init_test_ledger(
    db_path: Path, cand: CreatorCandidateArtifact, symbol: str = "BTCUSDT"
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_artifact_hash TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                fill_price TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                approval_id TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                slippage_cost TEXT,
                gross_pnl TEXT,
                net_pnl TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES (
                1, 'open', 'trade-fail-001', ?, ?, ?, 'LONG', '0.002', '50000.0',
                ?, 'app-01', '0.05', NULL, '0.01', NULL, NULL
            );
            """,
            (
                cand.candidate_id,
                cand.artifact_hash,
                symbol,
                (NOW - timedelta(hours=1)).isoformat(),
            ),
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES (
                2, 'close', 'trade-fail-001', ?, ?, ?, 'LONG', '0.002', '45000.0',
                ?, 'app-02', '0.05', '0.05', '0.01', '-10.0', '-10.1'
            );
            """,
            (cand.candidate_id, cand.artifact_hash, symbol, NOW.isoformat()),
        )


def test_cli_help_flag():
    """Verify that --help exits with code 0."""
    result = subprocess.run(
        [sys.executable, "scripts/run_autonomous_cycle.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Autonomous Cycle CLI Runner" in result.stdout


def test_cli_invalid_arguments_exit_code_2():
    """Verify that missing required arguments exit with code 2."""
    ret = run_cli_main(["--symbol", "INVALID_LOWER_CASE"])
    assert ret == 2


def test_cli_missing_database_exit_code_3(tmp_path: Path):
    """Verify that missing ledger DB file exits with code 3."""
    ret = run_cli_main(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(tmp_path / "nonexistent.sqlite3"),
            "--parquet-path",
            str(PARQUET_PATH),
        ]
    )
    assert ret == 3


def test_cli_end_to_end_real_data(tmp_path: Path):
    """Full execution of CLI runner with real BTCUSDT 5m Parquet data."""
    cand = _build_candidate("cand-cli-init-001", stop_atr="0.5")
    cand_path = tmp_path / "cand-cli-init-001.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "cycle_output"
    args = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(ledger_db),
        "--parquet-path",
        str(PARQUET_PATH),
        "--output-dir",
        str(output_dir),
        "--candidate-path",
        str(cand_path),
        "--cycle-id",
        "cycle-cli-e2e-001",
        "--windows-count",
        "1",
        "--min-windows",
        "1",
        "--min-profit-factor",
        "0.10",
        "--min-trades",
        "10",
        "--max-drawdown-pct",
        "50.0",
        "--min-average-return-pct",
        "-10.0",
        "--now",
        "2026-08-06T06:00:00Z",
    ]

    ret = run_cli_main(args)
    assert ret == 0

    result_file = output_dir / "autonomous-cycle-result.json"
    audit_file = output_dir / "cycle-audit.json"
    assert result_file.exists()
    assert audit_file.exists()

    result_data = json.loads(result_file.read_text(encoding="utf-8"))
    assert result_data["cycle_status"] == "completed_admitted"
    assert result_data["qualification_decision"] == "qualified"
    assert result_data["admission_decision"] == "admitted"
    assert result_data["data_source"] == "cached_only"
    assert result_data["execution_authority"] is False


def test_cli_idempotent_reexecution(tmp_path: Path):
    """Running CLI twice into the same output directory produces identical audit hashes."""
    cand = _build_candidate("cand-cli-init-001", stop_atr="0.5")
    cand_path = tmp_path / "cand-cli-init-001.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "cycle_output"
    args = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(ledger_db),
        "--parquet-path",
        str(PARQUET_PATH),
        "--output-dir",
        str(output_dir),
        "--candidate-path",
        str(cand_path),
        "--cycle-id",
        "cycle-cli-idempotent-001",
        "--windows-count",
        "1",
        "--min-windows",
        "1",
        "--min-profit-factor",
        "0.10",
        "--min-trades",
        "10",
        "--max-drawdown-pct",
        "50.0",
        "--min-average-return-pct",
        "-10.0",
        "--now",
        "2026-08-06T06:00:00Z",
    ]

    ret1 = run_cli_main(args)
    assert ret1 == 0
    audit1 = json.loads((output_dir / "cycle-audit.json").read_text(encoding="utf-8"))

    ret2 = run_cli_main(args)
    assert ret2 == 0
    audit2 = json.loads((output_dir / "cycle-audit.json").read_text(encoding="utf-8"))

    assert audit1["audit_hash"] == audit2["audit_hash"]
    assert audit1["cycle_hash"] == audit2["cycle_hash"]
