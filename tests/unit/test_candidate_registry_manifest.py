"""Unit tests for Candidate Registry Manifest specification, hashing, and atomic publishing."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.paper.candidate_registry import (
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    CandidateManifestEntry,
    CandidateRegistryManifest,
    build_candidate_registry_manifest,
    compute_registry_hash,
    publish_admitted_candidate,
    publish_candidate_admission,
    read_candidate_registry,
    validate_manifest_candidate_artifacts,
    verify_candidate_manifest_entry,
    verify_candidate_registry_manifest,
    write_candidate_registry,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_QUAL = "c" * 64
NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
NOW_ISO = NOW.isoformat()


def _make_candidate(
    candidate_id: str = "cand-btc-001",
    symbol: str = "BTCUSDT",
    stop_atr: str = "1.5",
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


class TestCandidateRegistrySchemaValidation:
    """Suite 1: Formal Schema Specification & Validation Rules."""

    def test_valid_entry_schema(self) -> None:
        entry = _make_entry()
        assert entry.candidate_id == "cand-btc-001"
        assert entry.candidate_artifact_hash == HASH_A
        assert entry.artifact_path == "artifacts/candidates/cand-btc-001.json"
        assert entry.qualification_hash == HASH_QUAL
        assert entry.admitted_at == NOW_ISO

    def test_entry_rejects_malformed_candidate_id(self) -> None:
        with pytest.raises(ValidationError):
            _make_entry(candidate_id="")
        with pytest.raises(ValidationError):
            _make_entry(candidate_id="invalid id with spaces")
        with pytest.raises(ValidationError):
            _make_entry(candidate_id="cand$invalid#chars")

    def test_entry_rejects_malformed_hashes(self) -> None:
        with pytest.raises(ValidationError):
            _make_entry(candidate_artifact_hash="tooshort")
        with pytest.raises(ValidationError):
            _make_entry(candidate_artifact_hash="G" * 64)
        with pytest.raises(ValidationError):
            _make_entry(qualification_hash="12345")
        with pytest.raises(ValidationError):
            _make_entry(qualification_hash="Z" * 64)

    def test_entry_rejects_path_traversal(self) -> None:
        with pytest.raises(ValidationError, match="directory traversal"):
            _make_entry(artifact_path="../etc/passwd.json")
        with pytest.raises(ValidationError, match="directory traversal"):
            _make_entry(artifact_path="artifacts/../../candidate.json")

    def test_entry_rejects_non_json_artifact_path(self) -> None:
        with pytest.raises(ValidationError, match=r"\.json"):
            _make_entry(artifact_path="artifacts/candidate.txt")
        with pytest.raises(ValidationError, match=r"\.json"):
            _make_entry(artifact_path="artifacts/candidate.yaml")

    def test_entry_rejects_invalid_timestamp(self) -> None:
        with pytest.raises(ValidationError, match="valid ISO-8601"):
            _make_entry(admitted_at="invalid-date")
        with pytest.raises(ValidationError, match="valid ISO-8601"):
            _make_entry(admitted_at="2026/09/09 12:00:00")

    def test_manifest_rejects_invalid_symbol_keys(self) -> None:
        entry = _make_entry()
        with pytest.raises(ValidationError, match="uppercase alphanumeric"):
            CandidateRegistryManifest(
                registry_version=1,
                updated_at=NOW_ISO,
                symbols={"btcusdt": entry},
                registry_hash=HASH_A,
            )
        with pytest.raises(ValidationError, match="uppercase alphanumeric"):
            CandidateRegistryManifest(
                registry_version=1,
                updated_at=NOW_ISO,
                symbols={"BTC-USDT": entry},
                registry_hash=HASH_A,
            )

    def test_manifest_rejects_invalid_registry_version(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(version=0)
        with pytest.raises(ValidationError):
            _make_manifest(version=-1)

    def test_manifest_forbids_extra_fields(self) -> None:
        entry_dict = _make_entry().model_dump(mode="json")
        entry_dict["extra_field"] = "injected"
        with pytest.raises(ValidationError):
            CandidateManifestEntry.model_validate(entry_dict)

        manifest_dict = _make_manifest().model_dump(mode="json")
        manifest_dict["unauthorized_field"] = "bad"
        with pytest.raises(ValidationError):
            CandidateRegistryManifest.model_validate(manifest_dict)


class TestDeterministicRegistryHashing:
    """Suite 2: Deterministic Cryptographic Hashing & Tamper Evidence."""

    def test_compute_registry_hash_deterministic_reproduction(self) -> None:
        manifest1 = _make_manifest()
        manifest2 = _make_manifest()
        assert compute_registry_hash(manifest1) == compute_registry_hash(manifest2)
        assert len(compute_registry_hash(manifest1)) == 64

    def test_registry_hash_independent_of_symbol_dict_insertion_order(self) -> None:
        entry_btc = _make_entry(candidate_id="cand-btc-001", artifact_path="cand-btc.json")
        entry_eth = _make_entry(candidate_id="cand-eth-001", artifact_path="cand-eth.json")

        manifest_order1 = CandidateRegistryManifest(
            registry_version=1,
            updated_at=NOW_ISO,
            symbols={"BTCUSDT": entry_btc, "ETHUSDT": entry_eth},
            registry_hash="0" * 64,
        )
        manifest_order2 = CandidateRegistryManifest(
            registry_version=1,
            updated_at=NOW_ISO,
            symbols={"ETHUSDT": entry_eth, "BTCUSDT": entry_btc},
            registry_hash="0" * 64,
        )
        assert compute_registry_hash(manifest_order1) == compute_registry_hash(manifest_order2)

    def test_tampered_candidate_id_detected(self) -> None:
        manifest = _make_manifest()
        tampered = manifest.model_copy(deep=True)
        tampered.symbols["BTCUSDT"].candidate_id = "cand-btc-tampered"
        assert compute_registry_hash(tampered) != manifest.registry_hash

    def test_tampered_artifact_hash_detected(self) -> None:
        manifest = _make_manifest()
        tampered = manifest.model_copy(deep=True)
        tampered.symbols["BTCUSDT"].candidate_artifact_hash = "f" * 64
        assert compute_registry_hash(tampered) != manifest.registry_hash

    def test_tampered_qualification_hash_detected(self) -> None:
        manifest = _make_manifest()
        tampered = manifest.model_copy(deep=True)
        tampered.symbols["BTCUSDT"].qualification_hash = "9" * 64
        assert compute_registry_hash(tampered) != manifest.registry_hash

    def test_tampered_updated_at_detected(self) -> None:
        manifest = _make_manifest()
        new_time = (NOW + timedelta(hours=1)).isoformat()
        tampered = manifest.model_copy(update={"updated_at": new_time})
        assert compute_registry_hash(tampered) != manifest.registry_hash

    def test_tampered_registry_hash_detected(self, tmp_path: Path) -> None:
        manifest = _make_manifest()
        path = tmp_path / "candidate_registry.json"
        write_candidate_registry(path, manifest)

        # Mutate the hash in the file by 1 character
        raw_json = json.loads(path.read_text(encoding="utf-8"))
        raw_json["registry_hash"] = (
            "f" + raw_json["registry_hash"][1:]
            if raw_json["registry_hash"][0] != "f"
            else "e" + raw_json["registry_hash"][1:]
        )
        path.write_text(json.dumps(raw_json), encoding="utf-8")

        with pytest.raises(DomainViolation, match="hash mismatch"):
            read_candidate_registry(path, verify_hash=True)

    def test_tampered_added_symbol_detected(self) -> None:
        manifest = _make_manifest()
        tampered = manifest.model_copy(deep=True)
        tampered.symbols["SOLUSDT"] = _make_entry(candidate_id="cand-sol-001")
        assert compute_registry_hash(tampered) != manifest.registry_hash


class TestRegistryFileIO:
    """Suite 3: Serialization, Deserialization & File I/O."""

    def test_roundtrip_write_and_read_manifest(self, tmp_path: Path) -> None:
        manifest = _make_manifest()
        path = tmp_path / "candidate_registry.json"
        written = write_candidate_registry(path, manifest)
        assert written.registry_hash == manifest.registry_hash
        assert path.is_file()

        loaded = read_candidate_registry(path, verify_hash=True)
        assert loaded == manifest
        assert verify_candidate_registry_manifest(loaded) is True

    def test_read_candidate_registry_file_not_found(self, tmp_path: Path) -> None:
        path = tmp_path / "missing_registry.json"
        with pytest.raises(FileNotFoundError):
            read_candidate_registry(path)

    def test_read_candidate_registry_truncated_json(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.json"
        path.write_text('{"registry_version": 1, "symbols": {', encoding="utf-8")
        with pytest.raises(DomainViolation, match="Invalid candidate registry"):
            read_candidate_registry(path)

    def test_read_candidate_registry_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text("   \n", encoding="utf-8")
        with pytest.raises(DomainViolation, match="is empty"):
            read_candidate_registry(path)

    def test_verify_hash_flag_can_bypass_or_enforce(self, tmp_path: Path) -> None:
        manifest = _make_manifest()
        path = tmp_path / "tampered.json"
        write_candidate_registry(path, manifest)

        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["registry_hash"] = "0" * 64
        path.write_text(json.dumps(raw), encoding="utf-8")

        # Enforced raises DomainViolation
        with pytest.raises(DomainViolation, match="hash mismatch"):
            read_candidate_registry(path, verify_hash=True)

        # Bypassed returns the object
        loaded = read_candidate_registry(path, verify_hash=False)
        assert loaded.registry_hash == "0" * 64


class TestAtomicPublisherOperations:
    """Suite 4: Atomic Publisher Operations."""

    def test_publish_initializes_manifest_when_absent(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "nested" / "candidate_registry.json"
        manifest = publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id="cand-btc-001",
            candidate_artifact_hash=HASH_A,
            artifact_path="artifacts/candidates/cand-btc-001.json",
            qualification_hash=HASH_QUAL,
            admitted_at=NOW_ISO,
        )
        assert manifest_path.is_file()
        assert manifest.registry_version == 1
        assert "BTCUSDT" in manifest.symbols
        assert manifest.symbols["BTCUSDT"].candidate_id == "cand-btc-001"
        assert verify_candidate_registry_manifest(manifest) is True

    def test_publish_updates_existing_symbol(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "candidate_registry.json"
        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id="cand-btc-001",
            candidate_artifact_hash=HASH_A,
            artifact_path="artifacts/candidates/cand-btc-001.json",
            qualification_hash=HASH_QUAL,
            admitted_at=NOW_ISO,
        )

        later_time = (NOW + timedelta(hours=2)).isoformat()
        manifest_v2 = publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id="cand-btc-002",
            candidate_artifact_hash=HASH_B,
            artifact_path="artifacts/candidates/cand-btc-002.json",
            qualification_hash=HASH_A,
            admitted_at=later_time,
        )
        assert manifest_v2.symbols["BTCUSDT"].candidate_id == "cand-btc-002"
        assert manifest_v2.symbols["BTCUSDT"].candidate_artifact_hash == HASH_B
        assert manifest_v2.updated_at == later_time
        assert verify_candidate_registry_manifest(manifest_v2) is True

    def test_publish_preserves_other_symbols(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "candidate_registry.json"
        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id="cand-btc-001",
            candidate_artifact_hash=HASH_A,
            artifact_path="cand-btc.json",
            qualification_hash=HASH_QUAL,
            admitted_at=NOW_ISO,
        )
        manifest2 = publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="ETHUSDT",
            candidate_id="cand-eth-001",
            candidate_artifact_hash=HASH_B,
            artifact_path="cand-eth.json",
            qualification_hash=HASH_A,
            admitted_at=NOW_ISO,
        )

        assert "BTCUSDT" in manifest2.symbols
        assert "ETHUSDT" in manifest2.symbols
        assert manifest2.symbols["BTCUSDT"].candidate_id == "cand-btc-001"
        assert manifest2.symbols["ETHUSDT"].candidate_id == "cand-eth-001"
        assert verify_candidate_registry_manifest(manifest2) is True

    def test_atomic_write_leaves_no_temp_files(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "candidate_registry.json"
        manifest = _make_manifest()
        write_candidate_registry(manifest_path, manifest)

        # Check directory contains ONLY candidate_registry.json and no .tmp files
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "candidate_registry.json"

    def test_atomic_write_cleans_up_tempfile_on_error(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "candidate_registry.json"
        manifest = _make_manifest()

        with patch("pathlib.Path.replace", side_effect=OSError("Disk full simulation")):
            with pytest.raises(OSError, match="Disk full simulation"):
                write_candidate_registry(manifest_path, manifest)

        # Ensure no dangling temporary file left in directory
        tmp_files = [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
        assert len(tmp_files) == 0

    def test_publish_admitted_candidate_alias(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "alias_registry.json"
        manifest = publish_admitted_candidate(
            manifest_path=manifest_path,
            symbol="SOLUSDT",
            candidate_id="cand-sol-001",
            candidate_artifact_hash=HASH_A,
            artifact_path="cand-sol.json",
            qualification_hash=HASH_QUAL,
            admitted_at=NOW_ISO,
        )
        assert "SOLUSDT" in manifest.symbols
        assert manifest.symbols["SOLUSDT"].candidate_id == "cand-sol-001"


class TestCandidateArtifactCrossValidation:
    """Suite 5: Filesystem Artifact Cross-Validation & Fail-Closed Behavior."""

    def test_verify_candidate_manifest_entry_success(self, tmp_path: Path) -> None:
        cand = _make_candidate("cand-btc-001", "BTCUSDT")
        cand_path = tmp_path / "cand-btc-001.json"
        write_creator_candidate_artifact(cand_path, cand)

        entry = _make_entry(
            candidate_id=cand.candidate_id,
            candidate_artifact_hash=cand.artifact_hash,
            artifact_path=str(cand_path),
        )
        assert verify_candidate_manifest_entry(entry) is True

    def test_verify_candidate_manifest_entry_file_missing(self, tmp_path: Path) -> None:
        entry = _make_entry(artifact_path=str(tmp_path / "missing.json"))
        with pytest.raises(FileNotFoundError):
            verify_candidate_manifest_entry(entry)

    def test_verify_candidate_manifest_entry_id_mismatch(self, tmp_path: Path) -> None:
        cand = _make_candidate("cand-btc-001", "BTCUSDT")
        cand_path = tmp_path / "cand-btc-001.json"
        write_creator_candidate_artifact(cand_path, cand)

        entry = _make_entry(
            candidate_id="cand-btc-other",
            candidate_artifact_hash=cand.artifact_hash,
            artifact_path=str(cand_path),
        )
        with pytest.raises(DomainViolation, match="Candidate ID mismatch"):
            verify_candidate_manifest_entry(entry)

    def test_verify_candidate_manifest_entry_hash_mismatch(self, tmp_path: Path) -> None:
        cand = _make_candidate("cand-btc-001", "BTCUSDT")
        cand_path = tmp_path / "cand-btc-001.json"
        write_creator_candidate_artifact(cand_path, cand)

        entry = _make_entry(
            candidate_id=cand.candidate_id,
            candidate_artifact_hash="f" * 64,
            artifact_path=str(cand_path),
        )
        with pytest.raises(DomainViolation, match="Candidate artifact hash mismatch"):
            verify_candidate_manifest_entry(entry)

    def test_verify_candidate_manifest_entry_content_tampered(self, tmp_path: Path) -> None:
        cand = _make_candidate("cand-btc-001", "BTCUSDT")
        cand_path = tmp_path / "cand-btc-001.json"
        write_creator_candidate_artifact(cand_path, cand)

        # Tamper content directly on disk without updating artifact_hash
        raw = json.loads(cand_path.read_text(encoding="utf-8"))
        raw["research_seed"] = 99999
        cand_path.write_text(json.dumps(raw), encoding="utf-8")

        entry = _make_entry(
            candidate_id=cand.candidate_id,
            candidate_artifact_hash=cand.artifact_hash,
            artifact_path=str(cand_path),
        )
        with pytest.raises(DomainViolation, match="creator candidate artifact hash mismatch"):
            verify_candidate_manifest_entry(entry)

    def test_validate_manifest_candidate_artifacts_success(self, tmp_path: Path) -> None:
        cand_btc = _make_candidate("cand-btc-001", "BTCUSDT")
        path_btc = tmp_path / "cand-btc-001.json"
        write_creator_candidate_artifact(path_btc, cand_btc)

        cand_eth = _make_candidate("cand-eth-001", "ETHUSDT")
        path_eth = tmp_path / "cand-eth-001.json"
        write_creator_candidate_artifact(path_eth, cand_eth)

        entry_btc = _make_entry(
            candidate_id=cand_btc.candidate_id,
            candidate_artifact_hash=cand_btc.artifact_hash,
            artifact_path=str(path_btc),
        )
        entry_eth = _make_entry(
            candidate_id=cand_eth.candidate_id,
            candidate_artifact_hash=cand_eth.artifact_hash,
            artifact_path=str(path_eth),
        )

        manifest = build_candidate_registry_manifest(
            symbols={"BTCUSDT": entry_btc, "ETHUSDT": entry_eth},
            updated_at=NOW_ISO,
        )

        loaded = validate_manifest_candidate_artifacts(manifest)
        assert len(loaded) == 2
        assert loaded["BTCUSDT"].candidate_id == "cand-btc-001"
        assert loaded["ETHUSDT"].candidate_id == "cand-eth-001"

    def test_validate_manifest_fails_when_symbol_not_in_candidate_universe(
        self, tmp_path: Path
    ) -> None:
        cand_btc = _make_candidate("cand-btc-001", "BTCUSDT")
        path_btc = tmp_path / "cand-btc-001.json"
        write_creator_candidate_artifact(path_btc, cand_btc)

        # Bind BTC candidate to ETHUSDT in manifest
        entry_misbound = _make_entry(
            candidate_id=cand_btc.candidate_id,
            candidate_artifact_hash=cand_btc.artifact_hash,
            artifact_path=str(path_btc),
        )

        manifest = build_candidate_registry_manifest(
            symbols={"ETHUSDT": entry_misbound},
            updated_at=NOW_ISO,
        )
        with pytest.raises(DomainViolation, match="not present in candidate universe symbols"):
            validate_manifest_candidate_artifacts(manifest)

    def test_default_registry_path(self) -> None:
        assert DEFAULT_CANDIDATE_REGISTRY_PATH == Path(
            "artifacts/paper_live/candidate_registry.json"
        )
