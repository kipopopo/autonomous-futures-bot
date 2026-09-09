"""Empirical Challenger 2 Test Suite for Milestone 1 (R1).

Validates:
1. Windows filesystem constraints & atomic replacement:
   - Temp file unlinking on errors (fsync failure, replace failure, PermissionError / file lock).
   - Destination file integrity preserved when write fails.
   - Zero-byte intermediate state prevention under concurrent read/write stress.
2. CLI integration with scripts/run_autonomous_cycle.py:
   - Admitted cycles publish to explicit --candidate-registry-path.
   - Non-admitted cycles do NOT publish (no file creation, no modification of existing registry).
   - Multi-symbol preservation across cycles.
   - Fail-closed behavior when existing registry is corrupted.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.paper.candidate_registry import (
    CandidateManifestEntry,
    CandidateRegistryManifest,
    compute_registry_hash,
    publish_candidate_admission,
    read_candidate_registry,
    verify_candidate_manifest_entry,
    verify_candidate_registry_manifest,
    write_candidate_registry,
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

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_QUAL = "c" * 64
NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
NOW_ISO = NOW.isoformat()

PARQUET_PATH = Path("research/immutable-data/5m/canonical/BTCUSDT-5m.parquet")


def _make_candidate(
    candidate_id: str = "cand-btc-001",
    symbol: str = "BTCUSDT",
    stop_atr: str = "0.5",
    tp_atr: str = "3.0",
) -> CreatorCandidateArtifact:
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
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal(stop_atr),
            take_profit_atr_multiplier=Decimal(tp_atr),
            trailing_atr_multiplier=Decimal("1.0"),
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


def _make_entry(
    candidate_id: str = "cand-btc-001",
    candidate_artifact_hash: str = HASH_A,
    artifact_path: str = "artifacts/candidates/cand-btc-001.json",
    qualification_hash: str = HASH_QUAL,
    admitted_at: str = NOW_ISO,
) -> CandidateManifestEntry:
    return CandidateManifestEntry(
        candidate_id=candidate_id,
        candidate_artifact_hash=candidate_artifact_hash,
        artifact_path=artifact_path,
        qualification_hash=qualification_hash,
        admitted_at=admitted_at,
    )


def _make_manifest(
    symbols: dict[str, CandidateManifestEntry] | None = None,
    updated_at: str = NOW_ISO,
    version: int = 1,
) -> CandidateRegistryManifest:
    syms = symbols if symbols is not None else {"BTCUSDT": _make_entry()}
    provisional = CandidateRegistryManifest(
        registry_version=version,
        updated_at=updated_at,
        symbols=syms,
        registry_hash="0" * 64,
    )
    return provisional.model_copy(update={"registry_hash": compute_registry_hash(provisional)})


def _init_test_ledger(db_path: Path, candidate: CreatorCandidateArtifact) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE closed_trades (
            trade_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            candidate_artifact_hash TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL NOT NULL,
            pnl REAL NOT NULL,
            net_pnl REAL NOT NULL,
            pnl_pct REAL NOT NULL,
            fee REAL NOT NULL,
            entry_timestamp TEXT NOT NULL,
            exit_timestamp TEXT NOT NULL,
            exit_reason TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        INSERT INTO closed_trades VALUES
        (
            't1', 'BTCUSDT', ?, ?, 'long', 50000.0, 49000.0,
            -100.0, -110.0, -0.02, 10.0,
            '2026-08-01T00:00:00Z', '2026-08-01T01:00:00Z', 'stop_loss'
        ),
        (
            't2', 'BTCUSDT', ?, ?, 'long', 49000.0, 48000.0,
            -100.0, -110.0, -0.02, 10.0,
            '2026-08-01T02:00:00Z', '2026-08-01T03:00:00Z', 'stop_loss'
        )
        """,
        (
            candidate.candidate_id,
            candidate.artifact_hash,
            candidate.candidate_id,
            candidate.artifact_hash,
        ),
    )
    conn.commit()
    conn.close()


class TestWindowsAtomicReplacementAndTempCleanup:
    """Challenge 1: Stress-testing Windows atomic file replacement and temp file cleanup."""

    def test_cleanup_when_fsync_fails(self, tmp_path: Path) -> None:
        """Verify temporary file is removed when fsync raises OSError."""
        manifest_path = tmp_path / "candidate_registry.json"
        manifest = _make_manifest()

        with patch("os.fsync", side_effect=OSError("Simulated EIO on fsync")):
            with pytest.raises(OSError, match="Simulated EIO on fsync"):
                write_candidate_registry(manifest_path, manifest)

        # Confirm no temp files remain
        tmp_files = list(tmp_path.glob(".*.tmp"))
        assert len(tmp_files) == 0, f"Dangling temp files found: {tmp_files}"
        assert not manifest_path.exists(), "Target file should not have been created"

    def test_cleanup_and_target_preserved_when_replace_fails(self, tmp_path: Path) -> None:
        """Verify target file is preserved and temp file is unlinked when replace fails."""
        manifest_path = tmp_path / "candidate_registry.json"
        initial_manifest = _make_manifest(version=1)
        write_candidate_registry(manifest_path, initial_manifest)

        # Update manifest
        new_manifest = _make_manifest(version=2)

        with patch("pathlib.Path.replace", side_effect=PermissionError("File locked on Windows")):
            with pytest.raises(PermissionError, match="File locked on Windows"):
                write_candidate_registry(manifest_path, new_manifest)

        # Confirm temp files cleaned up
        tmp_files = list(tmp_path.glob(".*.tmp"))
        assert len(tmp_files) == 0, f"Dangling temp files found: {tmp_files}"

        # Confirm target file is untouched and still passes hash verification
        preserved = read_candidate_registry(manifest_path, verify_hash=True)
        assert preserved.registry_version == 1
        assert preserved == initial_manifest

    def test_cleanup_when_file_write_interrupted(self, tmp_path: Path) -> None:
        """Verify temp file unlinked when an unhandled exception occurs inside write context."""
        manifest_path = tmp_path / "candidate_registry.json"
        manifest = _make_manifest()

        # Simulate exception during json dump/write
        with patch("json.dumps", side_effect=RuntimeError("Memory pressure during serialization")):
            with pytest.raises(RuntimeError, match="Memory pressure during serialization"):
                write_candidate_registry(manifest_path, manifest)

        tmp_files = list(tmp_path.glob(".*.tmp"))
        assert len(tmp_files) == 0, f"Dangling temp files found: {tmp_files}"
        assert not manifest_path.exists()

    def test_concurrent_readers_never_see_zero_byte_or_corrupt_manifest(
        self, tmp_path: Path
    ) -> None:
        """Stress test: Periodic polling readers vs continuous writer.

        Simulates LivePaperDaemon polling heartbeat (mtime/read) alongside autonomous cycles.
        Invariants:
        1. No reader ever observes 0-byte file size.
        2. No reader ever observes malformed JSON or hash mismatch.
        3. No partial/corrupted state is observed during Windows atomic replace.
        """
        manifest_path = tmp_path / "candidate_registry.json"
        initial = _make_manifest(version=1)
        write_candidate_registry(manifest_path, initial)

        stop_event = threading.Event()
        observed_zero_bytes = 0
        reader_domain_violations: list[Exception] = []
        successful_reads = 0
        lock = threading.Lock()

        def reader_loop() -> None:
            nonlocal observed_zero_bytes, successful_reads
            while not stop_event.is_set():
                try:
                    # Check physical size
                    size = manifest_path.stat().st_size
                    if size == 0:
                        with lock:
                            observed_zero_bytes += 1

                    manifest = read_candidate_registry(manifest_path, verify_hash=True)
                    assert manifest.registry_version >= 1
                    with lock:
                        successful_reads += 1
                except DomainViolation as dv:
                    # DomainViolation on schema or hash mismatch is a critical violation
                    if "Permission denied" not in str(dv):
                        with lock:
                            reader_domain_violations.append(dv)
                except Exception:
                    pass
                threading.Event().wait(0.005)

        readers = [threading.Thread(target=reader_loop) for _ in range(3)]
        for r in readers:
            r.start()

        writer_errors: list[Exception] = []
        successful_writes = 0

        for v in range(2, 22):
            threading.Event().wait(0.01)
            try:
                manifest_v = _make_manifest(
                    updated_at=(NOW + timedelta(seconds=v)).isoformat(),
                    version=v,
                )
                write_candidate_registry(manifest_path, manifest_v)
                successful_writes += 1
            except Exception as exc:
                writer_errors.append(exc)

        stop_event.set()
        for r in readers:
            r.join(timeout=5.0)

        assert observed_zero_bytes == 0, "Reader observed 0-byte intermediate state!"
        assert len(reader_domain_violations) == 0, (
            f"Readers caught schema/hash DomainViolation: {reader_domain_violations}"
        )
        assert successful_reads > 0, "Expected successful reads"
        assert successful_writes > 0, "Expected successful writes"

    def test_windows_file_locking_exclusive_contention_and_cleanup(self, tmp_path: Path) -> None:
        """Empirically test Windows file locking: open handle blocks replace, temp cleaned up.

        Under Windows NTFS semantics, an open read handle blocks os.replace with PermissionError.
        Verify:
        1. write_candidate_registry raises PermissionError when destination has open handle.
        2. Temporary file .*.tmp is cleanly unlinked.
        3. Destination file remains unmodified, readable, and cryptographically verified.
        """
        manifest_path = tmp_path / "candidate_registry.json"
        initial = _make_manifest(version=1)
        write_candidate_registry(manifest_path, initial)
        initial_bytes = manifest_path.read_bytes()

        updated_manifest = _make_manifest(version=2)

        # Hold open handle on manifest_path
        with open(manifest_path, encoding="utf-8") as _handle:
            with pytest.raises(PermissionError):
                write_candidate_registry(manifest_path, updated_manifest)

        # Invariant 1: No temp files left
        tmp_files = list(tmp_path.glob(".*.tmp"))
        assert len(tmp_files) == 0, f"Dangling temp file left on PermissionError: {tmp_files}"

        # Invariant 2: Original file untouched and valid
        current_bytes = manifest_path.read_bytes()
        assert current_bytes == initial_bytes, "Destination file was corrupted by failed replace!"
        loaded = read_candidate_registry(manifest_path, verify_hash=True)
        assert loaded.registry_version == 1


class TestCliCandidateRegistryIntegration:
    """Challenge 2: Testing CLI runner scripts/run_autonomous_cycle.py registry integration."""

    def test_cli_publishes_to_explicit_registry_path_on_admission(self, tmp_path: Path) -> None:
        """Verify CLI admits candidate and publishes to explicit --candidate-registry-path."""
        cand = _make_candidate("cand-cli-adm-001", stop_atr="0.5")
        cand_path = tmp_path / "cand-cli-adm-001.json"
        write_creator_candidate_artifact(cand_path, cand)

        ledger_db = tmp_path / "ledger.sqlite3"
        _init_test_ledger(ledger_db, cand)

        custom_reg_path = tmp_path / "registries" / "custom_candidate_registry.json"
        output_dir = tmp_path / "cycle_output_admitted"

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
            "cycle-cli-adm-001",
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
            "--candidate-registry-path",
            str(custom_reg_path),
        ]

        ret = run_cli_main(args)
        assert ret == 0, "CLI run should succeed with exit code 0"

        assert custom_reg_path.is_file(), "Manifest should have been published"
        manifest = read_candidate_registry(custom_reg_path, verify_hash=True)
        assert manifest.registry_version == 1
        assert "BTCUSDT" in manifest.symbols

        btc_entry = manifest.symbols["BTCUSDT"]
        assert btc_entry.candidate_id.startswith("cand-")
        assert len(btc_entry.candidate_artifact_hash) == 64
        assert len(btc_entry.qualification_hash) == 64
        assert verify_candidate_manifest_entry(btc_entry) is True

    def test_cli_does_not_publish_when_cycle_not_admitted_fresh_registry(
        self, tmp_path: Path
    ) -> None:
        """When candidate fails qualification, registry manifest MUST NOT be created."""
        cand = _make_candidate("cand-cli-fail-001", stop_atr="0.5")
        cand_path = tmp_path / "cand-cli-fail-001.json"
        write_creator_candidate_artifact(cand_path, cand)

        ledger_db = tmp_path / "ledger.sqlite3"
        _init_test_ledger(ledger_db, cand)

        custom_reg_path = tmp_path / "never_created_registry.json"
        output_dir = tmp_path / "cycle_output_rejected"

        # Impossible qualification threshold: min profit factor 999.0
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
            "cycle-cli-fail-001",
            "--windows-count",
            "1",
            "--min-windows",
            "1",
            "--min-profit-factor",
            "999.0",
            "--candidate-registry-path",
            str(custom_reg_path),
        ]

        ret = run_cli_main(args)
        # Verify cycle completed without admission
        assert ret == 0

        # Invariant: registry file MUST NOT be created
        assert not custom_reg_path.exists(), (
            f"Non-admitted cycle created candidate registry manifest at {custom_reg_path}!"
        )

        result_path = output_dir / "autonomous-cycle-result.json"
        assert result_path.is_file()
        result_data = json.loads(result_path.read_text(encoding="utf-8"))
        assert result_data["admission_decision"] != "admitted"
        assert result_data["cycle_status"] != "completed_admitted"

    def test_cli_does_not_mutate_existing_registry_when_cycle_not_admitted(
        self, tmp_path: Path
    ) -> None:
        """When cycle is not admitted, an existing registry must remain completely unmutated."""
        cand = _make_candidate("cand-cli-fail-002", stop_atr="0.5")
        cand_path = tmp_path / "cand-cli-fail-002.json"
        write_creator_candidate_artifact(cand_path, cand)

        ledger_db = tmp_path / "ledger.sqlite3"
        _init_test_ledger(ledger_db, cand)

        # Pre-seed candidate registry with existing SOLUSDT entry
        existing_reg_path = tmp_path / "existing_registry.json"
        existing_manifest = publish_candidate_admission(
            manifest_path=existing_reg_path,
            symbol="SOLUSDT",
            candidate_id="cand-sol-incumbent",
            candidate_artifact_hash=HASH_A,
            artifact_path="cand-sol.json",
            qualification_hash=HASH_QUAL,
            admitted_at=NOW_ISO,
        )
        assert existing_reg_path.is_file()
        initial_hash = existing_manifest.registry_hash
        initial_bytes = existing_reg_path.read_bytes()

        output_dir = tmp_path / "cycle_output_fail_preserve"

        # Impossible qualification threshold: min profit factor 999.0
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
            "cycle-cli-fail-002",
            "--windows-count",
            "1",
            "--min-windows",
            "1",
            "--min-profit-factor",
            "999.0",
            "--candidate-registry-path",
            str(existing_reg_path),
        ]

        ret = run_cli_main(args)
        assert ret == 0

        # Invariant: registry file bytes and hash must remain strictly identical
        current_bytes = existing_reg_path.read_bytes()
        assert current_bytes == initial_bytes, (
            "Existing registry was mutated by non-admitted cycle!"
        )

        current_manifest = read_candidate_registry(existing_reg_path, verify_hash=True)
        assert current_manifest.registry_hash == initial_hash
        assert list(current_manifest.symbols.keys()) == ["SOLUSDT"]

    def test_cli_preserves_other_symbols_across_successive_cycle_admissions(
        self, tmp_path: Path
    ) -> None:
        """Verify cycle runs for different symbols preserve all symbols in registry."""
        cand_btc = _make_candidate("cand-cli-btc-001", symbol="BTCUSDT", stop_atr="0.5")
        cand_btc_path = tmp_path / "cand-cli-btc-001.json"
        write_creator_candidate_artifact(cand_btc_path, cand_btc)

        ledger_db = tmp_path / "ledger.sqlite3"
        _init_test_ledger(ledger_db, cand_btc)

        registry_path = tmp_path / "shared_registry.json"

        # Pre-seed ETHUSDT in the registry
        publish_candidate_admission(
            manifest_path=registry_path,
            symbol="ETHUSDT",
            candidate_id="cand-eth-incumbent",
            candidate_artifact_hash=HASH_B,
            artifact_path="cand-eth.json",
            qualification_hash=HASH_QUAL,
            admitted_at=NOW_ISO,
        )

        output_dir = tmp_path / "cycle_output_btc"
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
            str(cand_btc_path),
            "--cycle-id",
            "cycle-cli-btc-001",
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
            "--candidate-registry-path",
            str(registry_path),
        ]

        ret = run_cli_main(args)
        assert ret == 0

        manifest = read_candidate_registry(registry_path, verify_hash=True)
        assert "ETHUSDT" in manifest.symbols
        assert "BTCUSDT" in manifest.symbols
        assert manifest.symbols["ETHUSDT"].candidate_id == "cand-eth-incumbent"
        assert manifest.symbols["BTCUSDT"].candidate_id.startswith("cand-")
        assert verify_candidate_registry_manifest(manifest) is True

    def test_cli_fails_closed_when_existing_registry_corrupted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify CLI exits code 3 fail-closed and preserves corrupt registry file."""
        cand = _make_candidate("cand-cli-adm-002", stop_atr="0.5")
        cand_path = tmp_path / "cand-cli-adm-002.json"
        write_creator_candidate_artifact(cand_path, cand)

        ledger_db = tmp_path / "ledger.sqlite3"
        _init_test_ledger(ledger_db, cand)

        initial_corrupt_content = json.dumps(
            {
                "registry_version": 1,
                "updated_at": NOW_ISO,
                "symbols": {},
                "registry_hash": "f" * 64,  # Invalid hash
            }
        )
        corrupt_reg_path = tmp_path / "corrupt_candidate_registry.json"
        corrupt_reg_path.write_text(initial_corrupt_content, encoding="utf-8")

        output_dir = tmp_path / "cycle_output_corrupt"
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
            "cycle-cli-corrupt-001",
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
            "--candidate-registry-path",
            str(corrupt_reg_path),
        ]

        # 1. Verify CLI returns exit code 3 (structured error)
        ret = run_cli_main(args)
        assert ret == 3

        captured = capsys.readouterr()
        err_json = json.loads(captured.out)
        assert err_json["error_code"] == "autonomous_cycle_data_error"
        assert "Candidate registry manifest hash mismatch" in err_json["message"]

        # 2. Invariant: corrupt registry was NOT clobbered or overwritten
        assert corrupt_reg_path.read_text(encoding="utf-8") == initial_corrupt_content

        # 3. Direct function invocation must raise DomainViolation
        from scripts.run_autonomous_cycle import build_parser, run_autonomous_cycle

        args_direct = list(args)
        output_dir_direct = tmp_path / "cycle_output_corrupt_direct"
        args_direct[args_direct.index(str(output_dir))] = str(output_dir_direct)
        args_direct[args_direct.index("cycle-cli-corrupt-001")] = "cycle-cli-corrupt-002"

        parsed_args = build_parser().parse_args(args_direct)
        with pytest.raises(DomainViolation, match="Candidate registry manifest hash mismatch"):
            run_autonomous_cycle(parsed_args)
