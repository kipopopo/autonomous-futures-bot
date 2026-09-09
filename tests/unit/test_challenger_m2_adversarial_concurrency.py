"""Empirical Challenger 2 Test Suite for Milestone 2 (R2).

Validates:
1. Tampered / Corrupted Registry Files during Daemon Polling:
   - Corrupt JSON syntax (malformed tokens, truncated strings, binary garbage)
   - Tampered registry_hash (valid JSON schema, cryptographic mismatch)
   - Non-existent candidate artifact path
   - Artifact content hash mismatch (_artifact_content_hash mismatch)
   - Candidate with mismatched universe symbols
   - All-or-nothing atomic pre-admission batching (zero partial admission on failure)
   - Zero-byte / empty manifest resilience
   - Daemon logs warnings, sets last_reload_status = "FAILED_...", never crashes,
     and preserves running candidates intact
2. Concurrent Reader/Writer Stress under Windows NTFS:
   - Simulated cycle runner atomically publishing while daemon heartbeat loop polls
     check_and_reload()
   - Windows NTFS PermissionError [WinError 5 / WinError 32] contention retry
   - Zero-byte intermediate read prevention and fail-closed handling
3. Health Checkpoint Telemetry Integrity:
   - Complete lifecycle validation of active_candidates and last_registry_reload
   - Live async run_heartbeat_loop testing with dynamic hot-reload and corrupted manifest
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import TickerSnapshot
from autonomous_futures.paper.candidate_registry import (
    CandidateManifestEntry,
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

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_phase_259_live_paper_daemon import (  # noqa: E402
    emit_daemon_health_checkpoint,
    run_heartbeat_loop,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_QUAL = "c" * 64
NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def _build_test_candidate(
    candidate_id: str,
    symbol: str = "BTCUSDT",
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
    trail_mult: str = "1.0",
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


def _setup_engine(
    tmp_path: Path, candidates: dict[str, CreatorCandidateArtifact]
) -> LivePaperEngine:
    engine = LivePaperEngine(
        symbols=tuple(sorted(candidates.keys())),
        candidates=candidates,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
    for sym in candidates:
        engine.latest_tickers[sym] = TickerSnapshot(
            symbol=sym,
            best_bid_price=Decimal("50000"),
            best_bid_qty=Decimal("2"),
            best_ask_price=Decimal("50001"),
            best_ask_qty=Decimal("2"),
            transaction_time=NOW,
            event_time=NOW,
        )
    return engine


# ==============================================================================
# SECTION 1: Tampered & Corrupted Registry Files during Daemon Polling
# ==============================================================================


def test_adversarial_corrupt_json_syntax(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Daemon must reject corrupt JSON syntax fail-closed, log warnings, and preserve candidates."""
    manifest_path = tmp_path / "candidate_registry.json"
    manifest_path.write_text(
        '{"registry_version": 1, "symbols": { INVALID_JSON_TOKENS ...', encoding="utf-8"
    )

    cand_orig = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_orig})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    with caplog.at_level(logging.WARNING):
        result = reloader.check_and_reload()

    assert result is False
    assert reloader.last_reload_status == "FAILED_CORRUPT"
    assert reloader.reload_count == 0
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"
    assert (
        "Validation failed for candidate registry" in caplog.text
        or "Unexpected error reading" in caplog.text
    )

    active_cands, last_reload = reloader.get_telemetry()
    assert active_cands == {"BTCUSDT": "cand-btc-001"}
    assert last_reload["reload_status"] == "FAILED_CORRUPT"
    assert last_reload["reload_count"] == 0


def test_adversarial_tampered_registry_hash(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Daemon must reject tampered registry_hash fail-closed and retain running candidates."""
    manifest_path = tmp_path / "candidate_registry.json"
    manifest = build_candidate_registry_manifest(updated_at=NOW)
    # Tamper hash to arbitrary invalid SHA-256
    tampered_manifest = manifest.model_copy(update={"registry_hash": "e" * 64})
    manifest_path.write_text(
        json.dumps(tampered_manifest.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )

    cand_orig = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_orig})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    with caplog.at_level(logging.WARNING):
        result = reloader.check_and_reload()

    assert result is False
    assert reloader.last_reload_status == "FAILED_HASH_MISMATCH"
    assert reloader.reload_count == 0
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"
    assert "Validation failed for candidate registry" in caplog.text

    active_cands, last_reload = reloader.get_telemetry()
    assert active_cands == {"BTCUSDT": "cand-btc-001"}
    assert last_reload["reload_status"] == "FAILED_HASH_MISMATCH"


def test_adversarial_non_existent_candidate_artifact(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Manifest referencing missing artifact must fail closed without mutating candidates."""
    manifest_path = tmp_path / "candidate_registry.json"
    non_existent = tmp_path / "ghost_candidate_artifact.json"

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id="cand-ghost-999",
        candidate_artifact_hash="7" * 64,
        artifact_path=non_existent,
        qualification_hash="6" * 64,
        admitted_at=NOW,
    )

    cand_orig = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_orig})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    with caplog.at_level(logging.WARNING):
        result = reloader.check_and_reload()

    assert result is False
    assert reloader.last_reload_status == "FAILED_ARTIFACT_MISSING"
    assert reloader.reload_count == 0
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"
    assert "Candidate artifact file missing" in caplog.text

    active_cands, last_reload = reloader.get_telemetry()
    assert active_cands == {"BTCUSDT": "cand-btc-001"}
    assert last_reload["reload_status"] == "FAILED_ARTIFACT_MISSING"


def test_adversarial_modified_candidate_artifact_content_hash_mismatch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Modified artifact content must fail closed with FAILED_ARTIFACT_HASH_MISMATCH."""
    manifest_path = tmp_path / "candidate_registry.json"
    cand_b = _build_test_candidate("cand-btc-002", stop_mult="1.5")
    cand_b_file = tmp_path / "cand-btc-002.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    # Publish with genuine hash
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="5" * 64,
        admitted_at=NOW,
    )

    # Adversarially overwrite artifact file with different candidate content
    cand_b_modified = _build_test_candidate("cand-btc-002", stop_mult="2.5")
    cand_b_file.write_text(
        json.dumps(cand_b_modified.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )

    cand_orig = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_orig})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    with caplog.at_level(logging.WARNING):
        result = reloader.check_and_reload()

    assert result is False
    assert reloader.last_reload_status == "FAILED_ARTIFACT_HASH_MISMATCH"
    assert reloader.reload_count == 0
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"
    assert "Candidate artifact verification failed" in caplog.text

    active_cands, last_reload = reloader.get_telemetry()
    assert active_cands == {"BTCUSDT": "cand-btc-001"}
    assert last_reload["reload_status"] == "FAILED_ARTIFACT_HASH_MISMATCH"


def test_adversarial_inner_artifact_content_hash_tampering(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Altered candidate parameters with spoofed artifact_hash caught by content hash."""
    manifest_path = tmp_path / "candidate_registry.json"
    cand_b = _build_test_candidate("cand-btc-002", stop_mult="1.5")
    cand_b_file = tmp_path / "cand-btc-002.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="5" * 64,
        admitted_at=NOW,
    )

    # Attacker alters stop_mult to 2.5, but fakes the artifact_hash string to match the original
    cand_b_modified = _build_test_candidate("cand-btc-002", stop_mult="2.5")
    tampered_dict = cand_b_modified.model_dump(mode="json")
    tampered_dict["artifact_hash"] = cand_b.artifact_hash  # Spoof hash field
    cand_b_file.write_text(json.dumps(tampered_dict, indent=2), encoding="utf-8")

    cand_orig = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_orig})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    with caplog.at_level(logging.WARNING):
        result = reloader.check_and_reload()

    assert result is False
    assert reloader.last_reload_status == "FAILED_ARTIFACT_HASH_MISMATCH"
    assert reloader.reload_count == 0
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"
    assert "Candidate artifact verification failed" in caplog.text


def test_adversarial_corrupt_candidate_artifact_schema(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Manifest pointing to artifact with corrupt syntax must fail closed with FAILED_CORRUPT."""
    manifest_path = tmp_path / "candidate_registry.json"
    cand_b = _build_test_candidate("cand-btc-002")
    cand_b_file = tmp_path / "cand-btc-002.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="5" * 64,
        admitted_at=NOW,
    )

    # Corrupt artifact JSON syntax on disk
    cand_b_file.write_text('{"bad_candidate": invalid_json', encoding="utf-8")

    cand_orig = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_orig})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    with caplog.at_level(logging.WARNING):
        result = reloader.check_and_reload()

    assert result is False
    assert reloader.last_reload_status == "FAILED_CORRUPT"
    assert reloader.reload_count == 0
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"

    active_cands, last_reload = reloader.get_telemetry()
    assert active_cands == {"BTCUSDT": "cand-btc-001"}
    assert last_reload["reload_status"] == "FAILED_CORRUPT"


def test_adversarial_candidate_mismatched_universe_symbols(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Candidate trained for ETHUSDT assigned to BTCUSDT in manifest rejected fail-closed."""
    cand_eth = _build_test_candidate("cand-eth-001", symbol="ETHUSDT")
    cand_eth_file = tmp_path / "cand-eth-001.json"
    write_creator_candidate_artifact(cand_eth_file, cand_eth)

    manifest_path = tmp_path / "candidate_registry.json"
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",  # Mismatch: key is BTCUSDT but strategy universe is ETHUSDT
        candidate_id=cand_eth.candidate_id,
        candidate_artifact_hash=cand_eth.artifact_hash,
        artifact_path=cand_eth_file,
        qualification_hash="4" * 64,
        admitted_at=NOW,
    )

    cand_orig = _build_test_candidate("cand-btc-001", symbol="BTCUSDT")
    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_orig})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    with caplog.at_level(logging.WARNING):
        result = reloader.check_and_reload()

    assert result is False
    assert reloader.last_reload_status == "FAILED_UNIVERSE_MISMATCH"
    assert reloader.reload_count == 0
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"
    assert "not present in candidate universe symbols" in caplog.text


def test_adversarial_all_or_nothing_multi_symbol_atomic_preservation(tmp_path: Path) -> None:
    """If one symbol update fails, NO candidates are admitted (atomic batch invariant)."""
    cand_btc_valid = _build_test_candidate("cand-btc-valid", symbol="BTCUSDT")
    cand_btc_file = tmp_path / "cand-btc-valid.json"
    write_creator_candidate_artifact(cand_btc_file, cand_btc_valid)

    # ETH candidate has a non-existent artifact file
    missing_eth_file = tmp_path / "cand-eth-missing.json"

    manifest_path = tmp_path / "candidate_registry.json"
    # Publish BTC admission
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_btc_valid.candidate_id,
        candidate_artifact_hash=cand_btc_valid.artifact_hash,
        artifact_path=cand_btc_file,
        qualification_hash="1" * 64,
        admitted_at=NOW,
    )
    # Add corrupted ETH entry into same manifest
    manifest = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id=cand_btc_valid.candidate_id,
                candidate_artifact_hash=cand_btc_valid.artifact_hash,
                artifact_path=str(cand_btc_file),
                qualification_hash="1" * 64,
                admitted_at=NOW.isoformat(),
            ),
            "ETHUSDT": CandidateManifestEntry(
                candidate_id="cand-eth-corrupt",
                candidate_artifact_hash="3" * 64,
                artifact_path=str(missing_eth_file),
                qualification_hash="2" * 64,
                admitted_at=NOW.isoformat(),
            ),
        },
        updated_at=NOW,
    )
    write_candidate_registry(manifest_path, manifest)

    cand_btc_orig = _build_test_candidate("cand-btc-orig", symbol="BTCUSDT")
    cand_eth_orig = _build_test_candidate("cand-eth-orig", symbol="ETHUSDT")
    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_btc_orig, "ETHUSDT": cand_eth_orig})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    # Attempt reload
    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_ARTIFACT_MISSING"
    assert reloader.reload_count == 0

    # CRITICAL INVARIANT: BTCUSDT MUST NOT HAVE BEEN ADMITTED!
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-orig"
    assert engine.candidates["ETHUSDT"].candidate_id == "cand-eth-orig"


def test_adversarial_zero_byte_empty_file_polling(tmp_path: Path) -> None:
    """Empty 0-byte file must be handled fail-closed as FAILED_CORRUPT without crashing."""
    manifest_path = tmp_path / "candidate_registry.json"
    manifest_path.write_bytes(b"")

    cand_orig = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_orig})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_CORRUPT"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"


def test_adversarial_binary_garbage_manifest_rejection(tmp_path: Path) -> None:
    """Arbitrary non-UTF8 binary data must be handled fail-closed without crashing daemon."""
    manifest_path = tmp_path / "candidate_registry.json"
    manifest_path.write_bytes(
        b"\x80\x03c__main__\nFakeObject\nq\x00)Rq\x01.\xff\xfe\x00\x01\x88\x99"
    )

    cand_orig = _build_test_candidate("cand-btc-001")
    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_orig})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_CORRUPT"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"


# ==============================================================================
# SECTION 2: Concurrent Reader/Writer Stress under Windows NTFS
# ==============================================================================


def test_concurrent_writer_publisher_and_daemon_reloader_stress(tmp_path: Path) -> None:
    """Simulate cycle runner publishing while daemon polls check_and_reload() concurrently."""
    manifest_path = tmp_path / "candidate_registry.json"

    # Pre-generate 4 candidates
    candidates = [
        _build_test_candidate(f"cand-btc-cycle-{i}", stop_mult=f"{1.0 + i * 0.5}") for i in range(4)
    ]
    cand_files = []
    for cand in candidates:
        f = tmp_path / f"{cand.candidate_id}.json"
        write_creator_candidate_artifact(f, cand)
        cand_files.append(f)

    # Initial admission of cand 0
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=candidates[0].candidate_id,
        candidate_artifact_hash=candidates[0].artifact_hash,
        artifact_path=cand_files[0],
        qualification_hash="0" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(tmp_path, {"BTCUSDT": candidates[0]})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload()
    assert engine.candidates["BTCUSDT"].candidate_id == candidates[0].candidate_id

    stop_event = threading.Event()
    writer_errors: list[Exception] = []
    reader_errors: list[Exception] = []
    successful_reloads: list[str] = []

    def writer_loop() -> None:
        idx = 1
        while not stop_event.is_set():
            cand = candidates[idx % len(candidates)]
            c_file = cand_files[idx % len(candidates)]
            try:
                publish_candidate_admission(
                    manifest_path=manifest_path,
                    symbol="BTCUSDT",
                    candidate_id=cand.candidate_id,
                    candidate_artifact_hash=cand.artifact_hash,
                    artifact_path=c_file,
                    qualification_hash=f"{idx:064d}",
                    admitted_at=datetime.now(UTC),
                )
            except Exception as e:
                writer_errors.append(e)
            idx += 1
            time.sleep(0.005)

    def reader_loop() -> None:
        while not stop_event.is_set():
            try:
                reloaded = reloader.check_and_reload()
                if reloaded:
                    successful_reloads.append(engine.candidates["BTCUSDT"].candidate_id)
            except Exception as e:
                reader_errors.append(e)
            time.sleep(0.003)

    writer_t = threading.Thread(target=writer_loop, name="cycle_writer")
    reader_t = threading.Thread(target=reader_loop, name="daemon_reader")

    writer_t.start()
    reader_t.start()

    # Run heavy concurrent read/write contention for 1.5 seconds
    time.sleep(1.5)
    stop_event.set()
    writer_t.join(timeout=3.0)
    reader_t.join(timeout=3.0)

    # Invariants under Windows NTFS contention:
    # 1. Neither writer nor reader threw unhandled exceptions
    assert not writer_errors, f"Writer encountered unhandled exceptions: {writer_errors}"
    assert not reader_errors, f"Reader encountered unhandled exceptions: {reader_errors}"

    # 2. Reloader successfully observed updates
    assert len(successful_reloads) > 0, "No reloads succeeded during concurrent execution"

    # 3. Final state is valid and consistent
    final_manifest = reloader.manifest_path.read_text(encoding="utf-8")
    parsed = json.loads(final_manifest)
    assert "registry_hash" in parsed
    assert reloader.last_reload_status in ("RELOADED", "NONE")


def test_windows_permission_error_winerror_5_retry_in_reloader(tmp_path: Path) -> None:
    """Windows WinError 5 during read_candidate_registry must trigger retry loop."""
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

    engine = _setup_engine(tmp_path, {"BTCUSDT": cand})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    attempts = 0
    from autonomous_futures.paper.candidate_registry import read_candidate_registry as real_read

    def flaky_read(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            # WinError 5 Access is denied
            raise PermissionError(13, "Access is denied (WinError 5)")
        return real_read(*args, **kwargs)

    with patch(
        "autonomous_futures.paper.candidate_registry.read_candidate_registry",
        side_effect=flaky_read,
    ):
        assert reloader.check_and_reload()
        assert attempts == 3
        assert reloader.last_reload_status == "RELOADED"

    # If all 3 attempts fail with WinError 5, reloader must fail closed without crashing
    attempts = 0

    def always_blocked(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        raise PermissionError(13, "Access is denied (WinError 5)")

    # Force mtime change detection
    reloader.last_mtime_ns = 0
    with patch(
        "autonomous_futures.paper.candidate_registry.read_candidate_registry",
        side_effect=always_blocked,
    ):
        assert not reloader.check_and_reload()
        assert attempts == 3
        assert reloader.last_reload_status == "FAILED_FILE_CONTENTION"


def test_windows_permission_error_winerror_5_retry_in_writer(tmp_path: Path) -> None:
    """Windows WinError 5 during temp_path.replace must trigger 5-attempt retry loop."""
    manifest_path = tmp_path / "candidate_registry.json"
    manifest = build_candidate_registry_manifest(updated_at=NOW)

    attempts = 0
    real_replace = Path.replace

    def flaky_replace(self: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts < 5:
            raise PermissionError(13, "Access is denied (WinError 5)")
        return real_replace(self, target)

    with patch.object(Path, "replace", flaky_replace):
        written = write_candidate_registry(manifest_path, manifest)
        assert written.registry_hash == manifest.registry_hash
        assert attempts == 5
        assert manifest_path.exists()

    # If all 5 attempts fail, PermissionError is raised and temp file is cleaned up
    attempts = 0

    def always_fail(self: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        raise PermissionError(13, "Access is denied (WinError 5)")

    with patch.object(Path, "replace", always_fail):
        with pytest.raises(PermissionError):
            write_candidate_registry(manifest_path, manifest)
        assert attempts == 5

    # Verify no leaked .tmp files in directory
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert not tmp_files, f"Leaked temp files found: {tmp_files}"


# ==============================================================================
# SECTION 3: Health Checkpoint Telemetry Integrity
# ==============================================================================


def test_health_checkpoint_telemetry_across_reload_lifecycle(tmp_path: Path) -> None:
    """Verify health checkpoint JSON reflects active_candidates and last_registry_reload."""
    health_file = tmp_path / "paper-daemon-health.json"
    manifest_path = tmp_path / "candidate_registry.json"

    cand_a = _build_test_candidate("cand-btc-001")
    cand_a_file = tmp_path / "cand-btc-001.json"
    write_creator_candidate_artifact(cand_a_file, cand_a)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_a.candidate_id,
        candidate_artifact_hash=cand_a.artifact_hash,
        artifact_path=cand_a_file,
        qualification_hash="1" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_a})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    # 1. Initial state before reload
    active_cands, last_reload = reloader.get_telemetry()
    assert active_cands == {"BTCUSDT": "cand-btc-001"}
    assert last_reload == {
        "reloaded_at": None,
        "registry_hash": None,
        "reload_status": "NONE",
        "reload_count": 0,
    }

    emit_daemon_health_checkpoint(
        output_path=health_file,
        status="RUNNING",
        uptime_seconds=10.0,
        started_at=NOW.isoformat(),
        symbols=["BTCUSDT"],
        starting_capital=Decimal("10000"),
        current_cash=Decimal("10000"),
        current_equity=Decimal("10000"),
        margin_utilization_pct=0.0,
        reserve_buffer_pct=100.0,
        active_positions={},
        total_trades=0,
        circuit_breaker_status="NORMAL",
        feed_messages_received=100,
        reconnect_count=0,
        active_candidates=active_cands,
        last_registry_reload=last_reload,
    )

    checkpoint_data = json.loads(health_file.read_text(encoding="utf-8"))
    assert checkpoint_data["active_candidates"] == {"BTCUSDT": "cand-btc-001"}
    assert checkpoint_data["last_registry_reload"]["reload_status"] == "NONE"
    assert checkpoint_data["last_registry_reload"]["reload_count"] == 0

    # 2. Hot reload Candidate B
    cand_b = _build_test_candidate("cand-btc-002")
    cand_b_file = tmp_path / "cand-btc-002.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="2" * 64,
        admitted_at=NOW,
    )

    assert reloader.check_and_reload()
    active_cands, last_reload = reloader.get_telemetry()
    assert active_cands == {"BTCUSDT": "cand-btc-002"}
    assert last_reload["reload_status"] == "RELOADED"
    assert last_reload["reload_count"] == 1
    assert last_reload["reloaded_at"] is not None
    assert last_reload["registry_hash"] is not None

    emit_daemon_health_checkpoint(
        output_path=health_file,
        status="RUNNING",
        uptime_seconds=20.0,
        started_at=NOW.isoformat(),
        symbols=["BTCUSDT"],
        starting_capital=Decimal("10000"),
        current_cash=Decimal("10000"),
        current_equity=Decimal("10000"),
        margin_utilization_pct=0.0,
        reserve_buffer_pct=100.0,
        active_positions={},
        total_trades=0,
        circuit_breaker_status="NORMAL",
        feed_messages_received=200,
        reconnect_count=0,
        active_candidates=active_cands,
        last_registry_reload=last_reload,
    )

    checkpoint_data = json.loads(health_file.read_text(encoding="utf-8"))
    assert checkpoint_data["active_candidates"] == {"BTCUSDT": "cand-btc-002"}
    assert checkpoint_data["last_registry_reload"]["reload_status"] == "RELOADED"
    assert checkpoint_data["last_registry_reload"]["reload_count"] == 1
    assert checkpoint_data["last_registry_reload"]["registry_hash"] == last_reload["registry_hash"]

    # 3. Tampered manifest reload attempt
    manifest = build_candidate_registry_manifest(updated_at=NOW)
    tampered = manifest.model_copy(update={"registry_hash": "9" * 64})
    manifest_path.write_text(json.dumps(tampered.model_dump(mode="json")), encoding="utf-8")

    assert not reloader.check_and_reload()
    active_cands, last_reload = reloader.get_telemetry()
    # Candidate remains cand-btc-002
    assert active_cands == {"BTCUSDT": "cand-btc-002"}
    assert last_reload["reload_status"] == "FAILED_HASH_MISMATCH"
    # reload_count did not increment
    assert last_reload["reload_count"] == 1

    emit_daemon_health_checkpoint(
        output_path=health_file,
        status="RUNNING",
        uptime_seconds=30.0,
        started_at=NOW.isoformat(),
        symbols=["BTCUSDT"],
        starting_capital=Decimal("10000"),
        current_cash=Decimal("10000"),
        current_equity=Decimal("10000"),
        margin_utilization_pct=0.0,
        reserve_buffer_pct=100.0,
        active_positions={},
        total_trades=0,
        circuit_breaker_status="NORMAL",
        feed_messages_received=300,
        reconnect_count=0,
        active_candidates=active_cands,
        last_registry_reload=last_reload,
    )

    checkpoint_data = json.loads(health_file.read_text(encoding="utf-8"))
    assert checkpoint_data["active_candidates"] == {"BTCUSDT": "cand-btc-002"}
    assert checkpoint_data["last_registry_reload"]["reload_status"] == "FAILED_HASH_MISMATCH"
    assert checkpoint_data["last_registry_reload"]["reload_count"] == 1


@pytest.mark.anyio
async def test_heartbeat_loop_periodic_execution_and_telemetry_emission(tmp_path: Path) -> None:
    """Verify live run_heartbeat_loop dynamically detects updates and emits checkpoints."""
    health_file = tmp_path / "paper-daemon-health.json"
    manifest_path = tmp_path / "candidate_registry.json"

    cand_a = _build_test_candidate("cand-btc-001")
    cand_a_file = tmp_path / "cand-btc-001.json"
    write_creator_candidate_artifact(cand_a_file, cand_a)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_a.candidate_id,
        candidate_artifact_hash=cand_a.artifact_hash,
        artifact_path=cand_a_file,
        qualification_hash="1" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(tmp_path, {"BTCUSDT": cand_a})
    account = MagicMock()
    account.starting_capital = Decimal("10000")
    account.cash = Decimal("10000")
    account.margin_utilization.return_value = Decimal("0.0")
    account.unencumbered_reserve_buffer.return_value = Decimal("1.0")
    account.current_state = "NORMAL"

    telemetry = MagicMock()
    telemetry.total_messages = 42

    feed_client = MagicMock()
    feed_client.reconnect_count = 0

    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    stop_event = asyncio.Event()

    loop_task = asyncio.create_task(
        run_heartbeat_loop(
            health_file=health_file,
            engine=engine,
            account=account,
            telemetry=telemetry,
            feed_client=feed_client,
            symbols=["BTCUSDT"],
            interval=0.04,  # Fast 40ms ticks for test
            stop_event=stop_event,
            start_time=time.monotonic(),
            started_at_str=NOW.isoformat(),
            hot_reloader=reloader,
        )
    )

    try:
        # Wait 100ms for first heartbeat
        await asyncio.sleep(0.10)
        assert health_file.exists()
        cp = json.loads(health_file.read_text(encoding="utf-8"))
        assert cp["active_candidates"] == {"BTCUSDT": "cand-btc-001"}
        assert cp["last_registry_reload"]["reload_status"] == "RELOADED"
        assert cp["last_registry_reload"]["reload_count"] == 1

        # Now dynamically publish Candidate B while heartbeat loop is running
        cand_b = _build_test_candidate("cand-btc-002")
        cand_b_file = tmp_path / "cand-btc-002.json"
        write_creator_candidate_artifact(cand_b_file, cand_b)

        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id=cand_b.candidate_id,
            candidate_artifact_hash=cand_b.artifact_hash,
            artifact_path=cand_b_file,
            qualification_hash="2" * 64,
            admitted_at=datetime.now(UTC),
        )

        # Wait 120ms for heartbeat to pick it up
        await asyncio.sleep(0.12)
        cp2 = json.loads(health_file.read_text(encoding="utf-8"))
        assert cp2["active_candidates"] == {"BTCUSDT": "cand-btc-002"}
        assert cp2["last_registry_reload"]["reload_status"] == "RELOADED"
        assert cp2["last_registry_reload"]["reload_count"] == 2
        assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-002"

        # Now write corrupt JSON while heartbeat is running
        manifest_path.write_text('{"bad": JSON', encoding="utf-8")
        await asyncio.sleep(0.12)
        cp3 = json.loads(health_file.read_text(encoding="utf-8"))
        # Daemon still running, status reflects FAILED_CORRUPT, running candidate intact
        assert cp3["active_candidates"] == {"BTCUSDT": "cand-btc-002"}
        assert cp3["last_registry_reload"]["reload_status"] == "FAILED_CORRUPT"
        assert cp3["last_registry_reload"]["reload_count"] == 2
        assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-002"

    finally:
        stop_event.set()
        await loop_task
