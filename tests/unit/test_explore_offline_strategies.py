"""Unit tests for offline strategy exploration runner (scripts/explore_offline_strategies.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.explore_offline_strategies import (  # noqa: E402
    _check_forbidden_credential_flags,
    generate_candidate_catalog,
    load_and_slice_windows,
    main,
    run_strategy_exploration,
)

cli_main = main


def test_forbidden_credential_flags_rejected() -> None:
    """Verify that any credential flag triggers immediate rejection."""
    assert _check_forbidden_credential_flags(["--symbols", "BTCUSDT", "--api-key=secret"]) is True
    assert _check_forbidden_credential_flags(["--gemini-api-key", "key"]) is True
    assert _check_forbidden_credential_flags(["--token", "abc"]) is True
    assert (
        _check_forbidden_credential_flags(["--symbols", "BTCUSDT", "--windows-count", "3"]) is False
    )


def test_candidate_catalog_structure() -> None:
    """Verify generated candidates conform strictly to CreatorCandidateArtifact schema."""
    catalog = generate_candidate_catalog("BTCUSDT")
    assert len(catalog) >= 6

    seen_ids = set()
    for cand in catalog:
        assert cand.candidate_id.startswith("cand-btcusdt-")
        assert cand.candidate_id not in seen_ids
        seen_ids.add(cand.candidate_id)

        # Strategy Spec invariants
        assert cand.strategy.dsl_version == 2
        assert cand.strategy.risk is not None
        assert cand.strategy.universe.symbols == ("BTCUSDT",)
        assert cand.strategy.universe.timeframe == "5m"
        assert cand.strategy.universe.regime_context_timeframe == "15m"
        assert len(cand.strategy.features) >= 1
        for feat in cand.strategy.features:
            assert feat.shift >= 1  # strictly causal


def test_load_and_slice_windows(tmp_path: Path) -> None:
    """Verify parquet slicing produces contiguous non-overlapping windows."""
    parquet_path = (
        REPO_ROOT / "research" / "immutable-data" / "5m" / "canonical" / "BTCUSDT-5m.parquet"
    )
    if not parquet_path.is_file():
        pytest.skip("Canonical BTCUSDT parquet not found")

    windows = load_and_slice_windows(
        parquet_path,
        symbol="BTCUSDT",
        windows_count=3,
        bars_per_window=50,
    )
    assert len(windows) == 3
    for i, w in enumerate(windows):
        assert w.spec.window_id == f"window-btcusdt-{i + 1:03d}"
        assert len(w.frame) == 50
        assert w.spec.symbol == "BTCUSDT"

    # Verify temporal continuity
    assert windows[0].spec.time_end == windows[1].spec.time_start
    assert windows[1].spec.time_end == windows[2].spec.time_start


def test_run_strategy_exploration_end_to_end(tmp_path: Path) -> None:
    """Verify full offline strategy exploration runner and artifact generation."""
    parquet_dir = REPO_ROOT / "research" / "immutable-data" / "5m" / "canonical"
    if not (parquet_dir / "BTCUSDT-5m.parquet").is_file():
        pytest.skip("Canonical BTCUSDT parquet not found")

    out_dir = tmp_path / "exploration_out"
    results = run_strategy_exploration(
        symbols=["BTCUSDT"],
        parquet_dir=parquet_dir,
        windows_count=2,
        bars_per_window=50,
        output_dir=out_dir,
    )
    assert results["status"] == "completed"
    assert results["symbols_evaluated"] == ["BTCUSDT"]
    assert results["total_candidates"] >= 6
    assert (out_dir / "exploration_summary.json").is_file()

    # Read back and verify summary JSON
    saved = json.loads((out_dir / "exploration_summary.json").read_text(encoding="utf-8"))
    assert saved["total_candidates"] == results["total_candidates"]
    assert len(saved["leaderboard"]) == results["total_candidates"]


def test_cli_runner_json_output(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Verify CLI main entrypoint outputs valid JSON when --json is passed."""
    parquet_dir = REPO_ROOT / "research" / "immutable-data" / "5m" / "canonical"
    if not (parquet_dir / "BTCUSDT-5m.parquet").is_file():
        pytest.skip("Canonical BTCUSDT parquet not found")

    exit_code = cli_main(
        [
            "--symbols",
            "BTCUSDT",
            "--parquet-dir",
            str(parquet_dir),
            "--windows-count",
            "2",
            "--bars-per-window",
            "50",
            "--output-dir",
            str(tmp_path),
            "--json",
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "completed"
    assert report["total_candidates"] >= 6


def test_candidate_catalog_timeframes() -> None:
    """Verify catalog generation supports 15m and 1h timeframes correctly."""
    catalog_15m = generate_candidate_catalog("ETHUSDT", timeframe="15m")
    assert len(catalog_15m) >= 8
    for cand in catalog_15m:
        assert cand.strategy.universe.timeframe == "15m"
        assert cand.strategy.universe.regime_context_timeframe == "1h"

    catalog_1h = generate_candidate_catalog("SOLUSDT", timeframe="1h")
    assert len(catalog_1h) >= 8
    for cand in catalog_1h:
        assert cand.strategy.universe.timeframe == "1h"
        assert cand.strategy.universe.regime_context_timeframe == "4h"


def test_load_and_slice_windows_15m_and_1h() -> None:
    """Verify slicing works for 15m and 1h canonical parquet files."""
    p_15m = REPO_ROOT / "research" / "immutable-data" / "15m" / "canonical" / "BTCUSDT-15m.parquet"
    if p_15m.is_file():
        windows = load_and_slice_windows(
            p_15m,
            symbol="BTCUSDT",
            timeframe="15m",
            windows_count=2,
            bars_per_window=40,
        )
        assert len(windows) == 2
        assert windows[0].spec.timeframe == "15m"
        assert windows[0].spec.time_end == windows[1].spec.time_start

    p_1h = REPO_ROOT / "research" / "immutable-data" / "1h" / "canonical" / "BTCUSDT-1h.parquet"
    if p_1h.is_file():
        windows = load_and_slice_windows(
            p_1h,
            symbol="BTCUSDT",
            timeframe="1h",
            windows_count=2,
            bars_per_window=30,
        )
        assert len(windows) == 2
        assert windows[0].spec.timeframe == "1h"
        assert windows[0].spec.time_end == windows[1].spec.time_start


def test_run_strategy_exploration_15m_timeframe(tmp_path: Path) -> None:
    """Verify 15m offline exploration executes and outputs results."""
    p_15m_dir = REPO_ROOT / "research" / "immutable-data" / "15m" / "canonical"
    if not (p_15m_dir / "ETHUSDT-15m.parquet").is_file():
        pytest.skip("Canonical ETHUSDT 15m parquet not found")

    out_dir = tmp_path / "exploration_15m"
    results = run_strategy_exploration(
        symbols=["ETHUSDT"],
        parquet_dir=p_15m_dir,
        timeframe="15m",
        windows_count=2,
        bars_per_window=40,
        output_dir=out_dir,
    )
    assert results["status"] == "completed"
    assert results["timeframe"] == "15m"
    assert results["total_candidates"] >= 8
    assert (out_dir / "exploration_summary.json").is_file()
