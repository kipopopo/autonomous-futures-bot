"""Unit tests for CandidateRegistryHotReloader and live paper engine hot-reloading."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot
from autonomous_futures.paper.candidate_registry import (
    CandidateRegistryHotReloader,
    build_candidate_registry_manifest,
    publish_candidate_admission,
    write_candidate_registry,
)
from autonomous_futures.paper.live_engine import LivePaperEngine
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def _build_test_candidate(
    candidate_id: str,
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
    trail_mult: str = "1.0",
    symbol: str = "BTCUSDT",
    entry_rule: str = "rsi <= 30",
    exit_rule: str = "rsi >= 50",
) -> CreatorCandidateArtifact:
    feats = (FeatureRef(name="rsi", lookback=14, shift=1),)
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,),
            timeframe="5m",
            regime_context_timeframe="15m",
        ),
        features=feats,
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


def _setup_engine(tmp_path: Path, candidate: CreatorCandidateArtifact) -> LivePaperEngine:
    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": candidate},
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50000"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50001"),
        best_ask_qty=Decimal("2"),
        transaction_time=NOW,
        event_time=NOW,
    )
    return engine


def test_hot_reloader_initial_state(tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate_registry.json"
    engine = MagicMock()
    engine.candidates = {}

    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.manifest_path == manifest_path
    assert reloader.engine is engine
    assert reloader.last_mtime_ns is None
    assert reloader.last_size is None
    assert reloader.last_registry_hash is None
    assert reloader.last_reloaded_at is None
    assert reloader.last_reload_status == "NONE"
    assert reloader.reload_count == 0

    active_cands, last_reload = reloader.get_telemetry()
    assert active_cands == {}
    assert last_reload["reload_status"] == "NONE"
    assert last_reload["reload_count"] == 0

    # Non-existent manifest returns False cleanly
    assert not reloader.check_and_reload()
    assert reloader.reload_count == 0


def test_stat_first_polling_skips_io_when_unchanged(tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate_registry.json"
    cand = _build_test_candidate("cand-btc-001")
    cand_file = tmp_path / "cand-btc-001.json"
    write_creator_candidate_artifact(cand_file, cand)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand.candidate_id,
        candidate_artifact_hash=cand.artifact_hash,
        artifact_path=cand_file,
        qualification_hash="1" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(tmp_path, cand)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    # First check: reloads from disk
    assert reloader.check_and_reload()
    assert reloader.reload_count == 1
    assert reloader.last_reload_status == "RELOADED"
    assert reloader.last_mtime_ns is not None
    assert reloader.last_size is not None

    # Second check without file change: stat-first polling returns False immediately
    with patch("autonomous_futures.paper.candidate_registry.read_candidate_registry") as mock_read:
        assert not reloader.check_and_reload()
        mock_read.assert_not_called()


def test_hot_reload_skips_when_registry_hash_identical(tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate_registry.json"
    cand = _build_test_candidate("cand-btc-001")
    cand_file = tmp_path / "cand-btc-001.json"
    write_creator_candidate_artifact(cand_file, cand)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand.candidate_id,
        candidate_artifact_hash=cand.artifact_hash,
        artifact_path=cand_file,
        qualification_hash="1" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(tmp_path, cand)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload()
    assert reloader.reload_count == 1

    # Simulate mtime change with identical content
    # Reset last_mtime_ns to force read
    reloader.last_mtime_ns = 0
    with patch.object(engine, "admit_candidate") as mock_admit:
        assert not reloader.check_and_reload()
        mock_admit.assert_not_called()
    assert reloader.reload_count == 1


def test_hot_reload_success_updates_engine_candidates(tmp_path: Path) -> None:
    cand_a = _build_test_candidate("cand-btc-001", stop_mult="1.5")
    cand_b = _build_test_candidate("cand-btc-002", stop_mult="2.5")
    cand_b_file = tmp_path / "cand-btc-002.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    manifest_path = tmp_path / "candidate_registry.json"
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="2" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(tmp_path, cand_a)
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"

    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload()
    assert reloader.reload_count == 1
    assert reloader.last_reload_status == "RELOADED"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-002"

    active_cands, last_reload = reloader.get_telemetry()
    assert active_cands == {"BTCUSDT": "cand-btc-002"}
    assert last_reload["reload_status"] == "RELOADED"
    assert last_reload["reload_count"] == 1


def test_empty_registry_clears_stale_entry_candidates_without_closing_trade(
    tmp_path: Path,
) -> None:
    cand_a = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, cand_a)
    assert engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW) is not None

    manifest_path = tmp_path / "candidate_registry.json"
    write_candidate_registry(manifest_path, build_candidate_registry_manifest(updated_at=NOW))
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    assert reloader.check_and_reload()
    assert engine.candidates == {}
    assert engine.qualified_symbols == ()
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id


def test_open_trade_immutability_during_hot_reload(tmp_path: Path) -> None:
    """Verify active trade retains Candidate A rules and stops while Candidate B is admitted."""
    cand_a = _build_test_candidate(
        "cand-btc-alpha",
        stop_mult="1.5",
        tp_mult="3.0",
        trail_mult="1.0",
        exit_rule="rsi >= 50",
    )
    cand_b = _build_test_candidate(
        "cand-btc-beta",
        stop_mult="3.0",
        tp_mult="5.0",
        trail_mult="2.5",
        exit_rule="rsi >= 80",
    )
    cand_b_file = tmp_path / "cand-btc-beta.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    manifest_path = tmp_path / "candidate_registry.json"
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="b" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(tmp_path, cand_a)
    # Open trade under Candidate A
    opened = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    assert opened is not None
    active_trade = engine.active_trades["BTCUSDT"]
    assert active_trade.candidate_id == cand_a.candidate_id
    assert active_trade.trailing_atr_multiplier == Decimal("1.0")
    original_stop = active_trade.stop_price

    # Hot-reload Candidate B
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload()

    # Engine candidates updated to B for future entries
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id

    # Active trade strictly retains Candidate A
    retained_trade = engine.active_trades["BTCUSDT"]
    assert retained_trade.candidate_id == cand_a.candidate_id
    assert retained_trade.candidate is not None
    assert retained_trade.candidate.candidate_id == cand_a.candidate_id
    assert retained_trade.trailing_atr_multiplier == Decimal("1.0")
    assert retained_trade.stop_price == original_stop

    # Close active trade
    engine.execute_close("BTCUSDT", "take_profit_hit", NOW)
    assert "BTCUSDT" not in engine.active_trades

    # Open next trade: adopts Candidate B
    opened_b = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    assert opened_b is not None
    trade_b = engine.active_trades["BTCUSDT"]
    assert trade_b.candidate_id == cand_b.candidate_id
    assert trade_b.trailing_atr_multiplier == Decimal("2.5")


def test_fail_closed_on_corrupt_json(tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate_registry.json"
    manifest_path.write_text('{"registry_version": 1, "symbols": {', encoding="utf-8")

    cand_a = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, cand_a)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_CORRUPT"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"
    assert reloader.reload_count == 0


def test_fail_closed_on_hash_mismatch(tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate_registry.json"
    manifest = build_candidate_registry_manifest(updated_at=NOW)
    tampered_manifest = manifest.model_copy(update={"registry_hash": "f" * 64})
    manifest_path.write_text(
        json.dumps(tampered_manifest.model_dump(mode="json")), encoding="utf-8"
    )

    cand_a = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, cand_a)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_HASH_MISMATCH"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"


def test_fail_closed_on_missing_candidate_artifact(tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate_registry.json"
    missing_file = tmp_path / "non_existent_candidate.json"

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id="cand-btc-missing",
        candidate_artifact_hash="9" * 64,
        artifact_path=missing_file,
        qualification_hash="8" * 64,
        admitted_at=NOW,
    )

    cand_a = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, cand_a)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_ARTIFACT_MISSING"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"


def test_fail_closed_on_artifact_hash_mismatch(tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate_registry.json"
    cand_b = _build_test_candidate("cand-btc-002")
    cand_b_file = tmp_path / "cand-btc-002.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    # Publish with wrong candidate_artifact_hash
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash="0" * 64,
        artifact_path=cand_b_file,
        qualification_hash="8" * 64,
        admitted_at=NOW,
    )

    cand_a = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, cand_a)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_ARTIFACT_HASH_MISMATCH"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"


def test_fail_closed_on_universe_mismatch(tmp_path: Path) -> None:
    cand_eth = _build_test_candidate("cand-eth-001", symbol="ETHUSDT")
    cand_eth_file = tmp_path / "cand-eth-001.json"
    write_creator_candidate_artifact(cand_eth_file, cand_eth)

    # Attempt to assign an ETH-only candidate to BTCUSDT in manifest
    manifest_path = tmp_path / "candidate_registry.json"
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_eth.candidate_id,
        candidate_artifact_hash=cand_eth.artifact_hash,
        artifact_path=cand_eth_file,
        qualification_hash="8" * 64,
        admitted_at=NOW,
    )

    cand_a = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, cand_a)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_UNIVERSE_MISMATCH"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"


def test_windows_contention_retry_in_reloader(tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate_registry.json"
    cand = _build_test_candidate("cand-btc-001")
    cand_file = tmp_path / "cand-btc-001.json"
    write_creator_candidate_artifact(cand_file, cand)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand.candidate_id,
        candidate_artifact_hash=cand.artifact_hash,
        artifact_path=cand_file,
        qualification_hash="1" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(tmp_path, cand)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    attempts = 0
    from autonomous_futures.paper.candidate_registry import (
        read_candidate_registry as real_read,
    )

    def flaky_read(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("Access is denied")
        return real_read(*args, **kwargs)

    with patch(
        "autonomous_futures.paper.candidate_registry.read_candidate_registry",
        side_effect=flaky_read,
    ):
        assert reloader.check_and_reload()
        assert attempts == 3
        assert reloader.last_reload_status == "RELOADED"


def test_windows_contention_retry_in_write_candidate_registry(tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate_registry.json"
    manifest = build_candidate_registry_manifest(updated_at=NOW)

    attempts = 0
    real_replace = Path.replace

    def flaky_replace(self, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("WinError 32: file in use")
        return real_replace(self, target)

    with patch.object(Path, "replace", flaky_replace):
        written = write_candidate_registry(manifest_path, manifest)
        assert written.registry_hash == manifest.registry_hash
        assert attempts == 3
        assert manifest_path.exists()


def test_admit_candidate_optional_qualification(tmp_path: Path) -> None:
    cand_a = _build_test_candidate("cand-btc-001")
    cand_b = _build_test_candidate("cand-btc-002")

    engine = _setup_engine(tmp_path, cand_a)
    # 1. Admit candidate without qualification artifact
    decision = engine.admit_candidate(
        candidate=cand_b,
        qualification=None,
        qualification_hash="e" * 64,
        require_flat=False,
    )
    assert decision.decision == "admitted"
    assert decision.qualification_hash == "e" * 64
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-002"

    # 2. While active trade is open with require_flat=True
    engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    cand_c = _build_test_candidate("cand-btc-003")
    deferred_decision = engine.admit_candidate(
        candidate=cand_c,
        qualification=None,
        qualification_hash="f" * 64,
        require_flat=True,
    )
    assert deferred_decision.decision == "deferred_active_position"
    # Candidate C not admitted due to require_flat=True
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-002"


def test_resilient_exit_evaluation_when_new_candidate_fails(tmp_path: Path) -> None:
    """Verify active trade exits cleanly even if newly admitted candidate has evaluation errors."""
    cand_a = _build_test_candidate("cand-btc-alpha", exit_rule="rsi >= 50")
    engine = _setup_engine(tmp_path, cand_a)

    # Populate 25 bars in engine history
    for i in range(25):
        bar_time = NOW - timedelta(minutes=5 * (25 - i))
        engine._bar_history["BTCUSDT"].append(
            {
                "timestamp": bar_time,
                "open": Decimal("50000.0"),
                "high": Decimal("50100.0"),
                "low": Decimal("49900.0"),
                "close": Decimal("50000.0"),
                "volume": Decimal("10.0"),
            }
        )

    # Open trade for Candidate A
    engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    assert "BTCUSDT" in engine.active_trades

    # Candidate B is admitted
    cand_b = _build_test_candidate("cand-btc-beta")
    engine.candidates["BTCUSDT"] = cand_b

    # Mock signal_evaluator so Candidate B raises an error, but Candidate A evaluates cleanly
    real_evaluate = engine.signal_evaluator.evaluate

    def selective_evaluate(cand, df):
        if cand.candidate_id == cand_b.candidate_id:
            raise RuntimeError("Candidate B feature calculation failure")
        return real_evaluate(cand, df)

    test_bar = CanonicalBar(
        symbol="BTCUSDT",
        interval="5m",
        timestamp=NOW,
        close_time=NOW,
        open=Decimal("50000"),
        high=Decimal("50200"),
        low=Decimal("49900"),
        close=Decimal("50100"),
        volume=Decimal("10"),
        quote_volume=Decimal("500000"),
        trades=100,
        taker_buy_base=Decimal("5"),
        taker_buy_quote=Decimal("250000"),
        is_closed=True,
    )

    with patch(
        "autonomous_futures.research.feature_signals.CausalFeatureSignalEvaluator.evaluate",
        side_effect=selective_evaluate,
    ):
        with patch(
            "autonomous_futures.paper.live_engine.evaluate_strategy_exit",
            return_value=True,
        ):
            # Bar triggers exit on Candidate A despite Candidate B raising RuntimeError
            engine._process_closed_bar(test_bar)
            assert "BTCUSDT" not in engine.active_trades
