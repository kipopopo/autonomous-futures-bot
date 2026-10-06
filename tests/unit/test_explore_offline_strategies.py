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


@pytest.fixture
def synthetic_catalog(monkeypatch):
    import scripts.explore_offline_strategies as cli
    from tests.strategy_fixtures import synthetic_rsi_candidate

    def catalog(symbol, *, timeframe="5m"):
        return (
            synthetic_rsi_candidate(
                symbol=symbol,
                timeframe=timeframe,
                bundle_hash=cli.DEFAULT_BUNDLE_HASH,
                dataset_registry_hash=cli.DEFAULT_REGISTRY_HASH,
            ),
        )

    monkeypatch.setattr(cli, "generate_candidate_catalog", catalog)


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


def test_run_strategy_exploration_blocks_unverified_local_catalog(tmp_path: Path) -> None:
    """Cached bars without verified funding cannot produce qualification output."""
    from autonomous_futures.data.parquet import DataQualityError

    parquet_dir = REPO_ROOT / "research" / "immutable-data" / "5m" / "canonical"
    if not (parquet_dir / "BTCUSDT-5m.parquet").is_file():
        pytest.skip("Canonical BTCUSDT parquet not found")

    out_dir = tmp_path / "exploration_out"
    with pytest.raises(DataQualityError, match="verified market-data catalog is unavailable"):
        run_strategy_exploration(
            symbols=["BTCUSDT"],
            parquet_dir=parquet_dir,
            windows_count=2,
            bars_per_window=50,
            output_dir=out_dir,
        )
    assert not out_dir.exists()


def test_cli_runner_json_output(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """CLI reports unavailable rather than success for unverified bars."""
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
    assert exit_code == 3
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "UNAVAILABLE"
    assert report["error_code"] == "verified_data_unavailable"
    assert not (tmp_path / "exploration_summary.json").exists()


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


def test_run_strategy_exploration_15m_blocks_unverified_local_catalog(tmp_path: Path) -> None:
    """15m cached bars also require verified funding evidence."""
    from autonomous_futures.data.parquet import DataQualityError

    p_15m_dir = REPO_ROOT / "research" / "immutable-data" / "15m" / "canonical"
    if not (p_15m_dir / "ETHUSDT-15m.parquet").is_file():
        pytest.skip("Canonical ETHUSDT 15m parquet not found")

    out_dir = tmp_path / "exploration_15m"
    with pytest.raises(DataQualityError, match="verified market-data catalog is unavailable"):
        run_strategy_exploration(
            symbols=["ETHUSDT"],
            parquet_dir=p_15m_dir,
            timeframe="15m",
            windows_count=2,
            bars_per_window=40,
            output_dir=out_dir,
        )
    assert not out_dir.exists()


def test_original_catalog_opaque_veto_fails_closed() -> None:
    import pandas as pd

    from autonomous_futures.data.parquet import DataQualityError
    from autonomous_futures.research.feature_signals import evaluate_entry_vetoes

    for candidate in generate_candidate_catalog("BTCUSDT"):
        with pytest.raises(DataQualityError, match="bounded comparisons"):
            evaluate_entry_vetoes(
                pd.DataFrame(index=[0]),
                candidate.strategy.vetoes,
                declared_features=tuple(feature.name for feature in candidate.strategy.features),
            )


def test_exploration_rejects_missing_requested_market_data_before_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "unavailable-exploration"

    with pytest.raises(FileNotFoundError, match="market data missing"):
        run_strategy_exploration(
            symbols=("BTCUSDT",),
            parquet_dir=tmp_path / "empty-data",
            output_dir=output_dir,
        )

    assert not output_dir.exists()


def test_exploration_rejects_unverified_cached_bars_before_candidate_evaluation(
    tmp_path: Path,
) -> None:
    import pandas as pd

    from autonomous_futures.data.parquet import DataQualityError, write_canonical_parquet

    start = pd.Timestamp("2026-08-07T00:00:00Z")
    frame = pd.DataFrame(
        {
            "timestamp": [start + pd.Timedelta(minutes=5 * index) for index in range(25)],
            "open": [100.0] * 25,
            "high": [101.0] * 25,
            "low": [99.0] * 25,
            "close": [100.0] * 25,
        }
    )
    parquet_dir = tmp_path / "canonical"
    parquet_dir.mkdir()
    write_canonical_parquet(
        frame,
        parquet_dir / "BTCUSDT-5m.parquet",
        interval=pd.Timedelta(minutes=5).to_pytimedelta(),
    )
    output_dir = tmp_path / "unverified-exploration"

    with pytest.raises(DataQualityError, match="verified market-data catalog is unavailable"):
        run_strategy_exploration(
            symbols=("BTCUSDT",),
            parquet_dir=parquet_dir,
            windows_count=1,
            bars_per_window=25,
            output_dir=output_dir,
        )

    assert not output_dir.exists()


def test_exploration_cli_reports_missing_verified_data_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "cli-unavailable"
    exit_code = cli_main(
        [
            "--symbols",
            "BTCUSDT",
            "--parquet-dir",
            str(tmp_path / "empty-data"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 3
    assert "market data missing" in capsys.readouterr().err.lower()
    assert not output_dir.exists()
