"""Empirical adversarial stress test harness for Candidate Registry Manifest & Publisher (M1).

Adversarially evaluates:
1. Malformed & tampered manifest resistance:
   - Truncated JSON at multiple byte boundaries (including cutting closing braces/quotes).
   - Corrupt syntax, unclosed brackets, null bytes, invalid UTF-8 bytes.
   - Empty files, whitespace-only files.
   - Injected extra keys at root level and entry level (Pydantic extra="forbid").
   - Corrupted hash digests (length, non-hex, bit-flips, case).
   - Corrupted timestamps and invalid registry versions (<=0, non-integers, garbage strings).
   - Pre-existing corrupt manifest fail-closed defense.
2. Path traversal & injection attempts:
   - artifact_path traversal (../, ..\\, nested escaping).
   - artifact_path non-json file extensions.
   - Symbol injection (lowercase, traversal, SQL/shell characters, null bytes).
   - candidate_id injection and special character attacks.
   - Hash field regex evasion attempts.
3. Rapid sequential & multi-symbol updates, retention & determinism:
   - Multi-symbol sequential lifecycle across 8+ symbols.
   - Preserving untouched symbols when updating an existing symbol.
   - Cryptographic hash determinism across arbitrary dictionary key permutations.
   - 100 rapid sequential updates with zero temporary file leakage.
   - Atomic replacement failure handling & cleanup.
4. Fail-closed behavior on artifact tampering & disk inconsistencies:
   - Missing candidate artifact on disk.
   - Candidate artifact parameter tampering (content hash mismatch).
   - Candidate ID and artifact hash mismatches.
   - Strategy universe symbol mismatch.
   - Tampered manifest rejected during candidate loading.
5. Lineage & publisher boundary validation:
   - Nested directory creation on demand.
   - Candidate artifact hash verification prior to publishing.
   - Timestamp format flexibility (Z and +00:00 offsets).
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

# Ensure src and research are on python path
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "research"))

from pydantic import ValidationError  # noqa: E402

from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    CandidateManifestEntry,
    CandidateRegistryManifest,
    build_candidate_registry_manifest,
    compute_registry_hash,
    publish_candidate_admission,
    read_candidate_registry,
    validate_manifest_candidate_artifacts,
    verify_candidate_manifest_entry,
    verify_candidate_registry_manifest,
    write_candidate_registry,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
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
    symbols: Mapping[str, CandidateManifestEntry] | None = None,
    updated_at: str = NOW_ISO,
    version: int = 1,
) -> CandidateRegistryManifest:
    syms = dict(symbols) if symbols is not None else {"BTCUSDT": _make_entry()}
    provisional = CandidateRegistryManifest(
        registry_version=version,
        updated_at=updated_at,
        symbols=syms,
        registry_hash="0" * 64,
    )
    return provisional.model_copy(update={"registry_hash": compute_registry_hash(provisional)})


# =========================================================================
# SUITE 1: MALFORMED & TAMPERED MANIFEST RESISTANCE
# =========================================================================


def test_1_1_truncated_json_boundaries(tmp_path: Path) -> None:
    """Verify truncated JSON at various byte offsets raises DomainViolation fail-closed."""
    manifest = _make_manifest()
    path = tmp_path / "candidate_registry.json"
    write_candidate_registry(path, manifest)
    # Strip trailing whitespace/newlines so cutoffs strictly truncate JSON tokens
    full_json = path.read_text(encoding="utf-8").rstrip("\r\n")
    full_len = len(full_json)

    cutoffs = [5, 15, 30, 50, 80, 120, 180, 250, full_len - 1, full_len - 5]
    for cut in cutoffs:
        if cut >= full_len:
            continue
        truncated = full_json[:cut]
        path.write_text(truncated, encoding="utf-8")
        try:
            read_candidate_registry(path, verify_hash=True)
            raise AssertionError(f"Expected DomainViolation on truncated JSON at {cut} bytes")
        except DomainViolation as exc:
            assert "Invalid candidate registry manifest" in str(exc) or "empty" in str(exc)


def test_1_2_corrupt_json_syntax(tmp_path: Path) -> None:
    """Verify syntax corruptions (unclosed braces, garbage, null bytes) raise DomainViolation."""
    path = tmp_path / "candidate_registry.json"

    corruptions = [
        '{"registry_version": 1, "symbols": ',
        '{"registry_version": 1, "symbols": {}} trailing garbage',
        '{"registry_version": 1, "updated_at": "2026-09-09",,}',
        '{"registry_version": 1\x00, "updated_at": "2026-09-09"}',
        "<<<NOT_JSON>>>",
        '{"registry_version": 1, "symbols": {"BTC": {"cand": "foo"}}}',
    ]

    for corrupted in corruptions:
        path.write_text(corrupted, encoding="utf-8")
        try:
            read_candidate_registry(path, verify_hash=True)
            raise AssertionError(f"Expected DomainViolation on corrupted JSON: {corrupted[:20]}")
        except DomainViolation as exc:
            assert "Invalid candidate registry manifest" in str(exc)


def test_1_3_empty_and_whitespace_files(tmp_path: Path) -> None:
    """Verify 0-byte and whitespace files raise DomainViolation with descriptive message."""
    path = tmp_path / "candidate_registry.json"

    for whitespace in ["", " ", "   \n\t  \r\n", "\n\n\n"]:
        path.write_text(whitespace, encoding="utf-8")
        try:
            read_candidate_registry(path, verify_hash=True)
            raise AssertionError("Expected DomainViolation on empty/whitespace manifest")
        except DomainViolation as exc:
            assert "is empty" in str(exc)


def test_1_4_extra_root_key_injection(tmp_path: Path) -> None:
    """Verify extra root keys are forbidden (Pydantic DomainModel extra='forbid')."""
    manifest = _make_manifest()
    path = tmp_path / "candidate_registry.json"
    write_candidate_registry(path, manifest)

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["injected_malicious_field"] = "exploit"
    path.write_text(json.dumps(raw), encoding="utf-8")

    try:
        read_candidate_registry(path, verify_hash=True)
        raise AssertionError("Expected DomainViolation on injected root key")
    except DomainViolation as exc:
        assert (
            "extra_forbidden" in str(exc).lower()
            or "extra fields not permitted" in str(exc).lower()
            or "invalid" in str(exc).lower()
        )


def test_1_5_extra_entry_key_injection(tmp_path: Path) -> None:
    """Verify extra keys inside symbol entry are rejected fail-closed."""
    manifest = _make_manifest()
    path = tmp_path / "candidate_registry.json"
    write_candidate_registry(path, manifest)

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["symbols"]["BTCUSDT"]["backdoor_flag"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")

    try:
        read_candidate_registry(path, verify_hash=True)
        raise AssertionError("Expected DomainViolation on injected entry key")
    except DomainViolation as exc:
        assert "invalid" in str(exc).lower() or "extra" in str(exc).lower()


def test_1_6_hash_bit_flip_and_mutation(tmp_path: Path) -> None:
    """Verify hash corruptions (bit-flip, uppercase, wrong length, non-hex) are caught."""
    manifest = _make_manifest()
    path = tmp_path / "candidate_registry.json"
    write_candidate_registry(path, manifest)
    original_json = json.loads(path.read_text(encoding="utf-8"))
    original_hash = original_json["registry_hash"]

    # 1. Flip single character in hash
    bad_hash = ("0" if original_hash[0] != "0" else "1") + original_hash[1:]
    original_json["registry_hash"] = bad_hash
    path.write_text(json.dumps(original_json), encoding="utf-8")
    try:
        read_candidate_registry(path, verify_hash=True)
        raise AssertionError("Expected DomainViolation on flipped hash bit")
    except DomainViolation as exc:
        assert "hash mismatch" in str(exc)

    # 2. Uppercase hex
    original_json["registry_hash"] = original_hash.upper()
    path.write_text(json.dumps(original_json), encoding="utf-8")
    try:
        read_candidate_registry(path, verify_hash=True)
        raise AssertionError("Expected DomainViolation on uppercase hash")
    except DomainViolation as exc:
        assert "invalid" in str(exc).lower() or "pattern" in str(exc).lower()

    # 3. 63 hex characters (too short)
    original_json["registry_hash"] = original_hash[:63]
    path.write_text(json.dumps(original_json), encoding="utf-8")
    try:
        read_candidate_registry(path, verify_hash=True)
        raise AssertionError("Expected DomainViolation on 63-char hash")
    except DomainViolation as exc:
        assert "invalid" in str(exc).lower() or "pattern" in str(exc).lower()

    # 4. 65 hex characters (too long)
    original_json["registry_hash"] = original_hash + "a"
    path.write_text(json.dumps(original_json), encoding="utf-8")
    try:
        read_candidate_registry(path, verify_hash=True)
        raise AssertionError("Expected DomainViolation on 65-char hash")
    except DomainViolation as exc:
        assert "invalid" in str(exc).lower() or "pattern" in str(exc).lower()

    # 5. Non-hex characters
    original_json["registry_hash"] = "z" * 64
    path.write_text(json.dumps(original_json), encoding="utf-8")
    try:
        read_candidate_registry(path, verify_hash=True)
        raise AssertionError("Expected DomainViolation on non-hex hash")
    except DomainViolation as exc:
        assert "invalid" in str(exc).lower() or "pattern" in str(exc).lower()


def test_1_7_corrupt_updated_at(tmp_path: Path) -> None:
    """Verify invalid updated_at timestamps are rejected fail-closed."""
    manifest = _make_manifest()
    path = tmp_path / "candidate_registry.json"
    write_candidate_registry(path, manifest)
    original_json = json.loads(path.read_text(encoding="utf-8"))

    invalid_timestamps = [
        "not-a-timestamp",
        "2026/09/09 12:00:00",
        "yesterday",
        "",
        "   ",
    ]

    for ts in invalid_timestamps:
        original_json["updated_at"] = ts
        path.write_text(json.dumps(original_json), encoding="utf-8")
        try:
            read_candidate_registry(path, verify_hash=True)
            raise AssertionError(f"Expected DomainViolation on invalid timestamp: {ts}")
        except DomainViolation as exc:
            assert "invalid" in str(exc).lower()


def test_1_8_corrupt_registry_version(tmp_path: Path) -> None:
    """Verify invalid registry_version is rejected fail-closed."""
    manifest = _make_manifest()
    path = tmp_path / "candidate_registry.json"
    write_candidate_registry(path, manifest)
    original_json = json.loads(path.read_text(encoding="utf-8"))

    invalid_versions = [0, -1, -99, "abc", 1.5, "v1", ""]
    for ver in invalid_versions:
        original_json["registry_version"] = ver
        path.write_text(json.dumps(original_json), encoding="utf-8")
        try:
            read_candidate_registry(path, verify_hash=True)
            raise AssertionError(f"Expected DomainViolation on invalid version: {ver}")
        except DomainViolation as exc:
            assert "invalid" in str(exc).lower()


def test_1_9_tampered_payload_hash_mismatch(tmp_path: Path) -> None:
    """Verify modification of payload without updating hash is strictly rejected."""
    manifest = _make_manifest()
    path = tmp_path / "candidate_registry.json"
    write_candidate_registry(path, manifest)

    raw = json.loads(path.read_text(encoding="utf-8"))
    # Alter candidate_id inside valid format
    raw["symbols"]["BTCUSDT"]["candidate_id"] = "cand-tampered-001"
    # Keep old registry_hash
    path.write_text(json.dumps(raw), encoding="utf-8")

    try:
        read_candidate_registry(path, verify_hash=True)
        raise AssertionError("Expected DomainViolation on tampered candidate_id")
    except DomainViolation as exc:
        assert "hash mismatch" in str(exc)


def test_1_10_pre_existing_corrupt_manifest_fail_closed(tmp_path: Path) -> None:
    """Verify publish_candidate_admission fails closed if existing manifest on disk is corrupt."""
    manifest_path = tmp_path / "candidate_registry.json"
    manifest_path.write_text('{"corrupted": "garbage",', encoding="utf-8")

    try:
        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id="cand-btc-001",
            candidate_artifact_hash=HASH_A,
            artifact_path="cand-btc.json",
            qualification_hash=HASH_QUAL,
            admitted_at=NOW_ISO,
        )
        raise AssertionError("Expected DomainViolation when publishing over corrupt manifest")
    except DomainViolation as exc:
        assert "Invalid candidate registry manifest" in str(exc)

    # Ensure corrupt file was NOT clobbered or modified
    assert manifest_path.read_text(encoding="utf-8") == '{"corrupted": "garbage",'


# =========================================================================
# SUITE 2: PATH TRAVERSAL & INJECTION ATTEMPTS
# =========================================================================


def test_2_1_artifact_path_traversal_variants() -> None:
    """Verify various directory traversal attempts are rejected in CandidateManifestEntry."""
    traversal_paths = [
        "../../etc/passwd.json",
        "../secret.json",
        "artifacts/../../cand.json",
        "..\\..\\windows\\system32.json",
        "artifacts/candidates/../candidates/cand.json",
        "./../../cand.json",
        "candidates/sub/../../../cand.json",
    ]

    for bad_path in traversal_paths:
        try:
            _make_entry(artifact_path=bad_path)
            raise AssertionError(f"Expected ValidationError for traversal path: {bad_path}")
        except ValidationError as exc:
            assert "directory traversal" in str(exc)


def test_2_2_artifact_path_non_json_extensions() -> None:
    """Verify non-.json artifact extensions are rejected."""
    bad_extensions = [
        "cand.txt",
        "cand.yaml",
        "cand.py",
        "cand.exe",
        "cand.json.bak",
        "cand",
        "cand.JSON",  # case-sensitive .json requirement
    ]

    for bad in bad_extensions:
        try:
            _make_entry(artifact_path=bad)
            raise AssertionError(f"Expected ValidationError for non-.json path: {bad}")
        except ValidationError as exc:
            assert ".json" in str(exc)


def test_2_3_symbol_injection_attempts(tmp_path: Path) -> None:
    """Verify symbol validation rejects invalid casing, traversal, and injection characters."""
    bad_symbols = [
        "btcusdt",  # lowercase
        "BTC/USDT",
        "BTC-USDT",
        "BTC.USDT",
        "../../BTC",
        "BTC;DROP",
        "BTC\x00USDT",
        "BTC\nUSDT",
        "BTC USDT",
        "",
        "   ",
    ]

    entry = _make_entry()
    for bad_sym in bad_symbols:
        try:
            CandidateRegistryManifest(
                registry_version=1,
                updated_at=NOW_ISO,
                symbols={bad_sym: entry},
                registry_hash=HASH_A,
            )
            raise AssertionError(f"Expected ValidationError for symbol: {bad_sym!r}")
        except ValidationError as exc:
            assert "uppercase alphanumeric" in str(exc) or "string_too_short" in str(exc)


def test_2_4_candidate_id_injection_attempts() -> None:
    """Verify candidate_id rejects traversal, spaces, and shell characters."""
    bad_ids = [
        "",
        "../../evil-id",
        "cand id with spaces",
        "cand;rm -rf",
        "cand$bar",
        "cand/nested",
        "cand\\nested",
        "cand\x00evil",
    ]

    for bad_id in bad_ids:
        try:
            _make_entry(candidate_id=bad_id)
            raise AssertionError(f"Expected ValidationError for candidate_id: {bad_id!r}")
        except ValidationError:
            pass


def test_2_5_hash_regex_injection() -> None:
    """Verify hash fields reject non-64 hex strings, traversal strings, and injection."""
    bad_hashes = [
        "../" + "0" * 61,
        "0" * 63,
        "0" * 65,
        "G" * 64,
        "A" * 64,  # uppercase
        "0" * 32 + ";" + "0" * 31,
        "",
    ]

    for bad_h in bad_hashes:
        try:
            _make_entry(candidate_artifact_hash=bad_h)
            raise AssertionError(f"Expected ValidationError for candidate_artifact_hash: {bad_h!r}")
        except ValidationError:
            pass

        try:
            _make_entry(qualification_hash=bad_h)
            raise AssertionError(f"Expected ValidationError for qualification_hash: {bad_h!r}")
        except ValidationError:
            pass


# =========================================================================
# SUITE 3: RAPID SEQUENTIAL & MULTI-SYMBOL UPDATES, RETENTION & DETERMINISM
# =========================================================================


def test_3_1_multi_symbol_lifecycle_retention(tmp_path: Path) -> None:
    """Verify sequential publishing of 8 distinct symbols retains all symbols."""
    manifest_path = tmp_path / "candidate_registry.json"
    symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "ADAUSDT",
        "XRPUSDT",
        "DOGEUSDT",
        "AVAXUSDT",
    ]

    for idx, sym in enumerate(symbols):
        cand_id = f"cand-{sym.lower()}-{idx + 1:03d}"
        manifest = publish_candidate_admission(
            manifest_path=manifest_path,
            symbol=sym,
            candidate_id=cand_id,
            candidate_artifact_hash=HASH_A,
            artifact_path=f"artifacts/candidates/{cand_id}.json",
            qualification_hash=HASH_QUAL,
            admitted_at=NOW_ISO,
        )
        # Verify all symbols added so far are present
        assert len(manifest.symbols) == idx + 1
        for prior_sym in symbols[: idx + 1]:
            assert prior_sym in manifest.symbols

    # Verify final manifest
    final_manifest = read_candidate_registry(manifest_path, verify_hash=True)
    assert len(final_manifest.symbols) == 8
    for idx, sym in enumerate(symbols):
        expected_id = f"cand-{sym.lower()}-{idx + 1:03d}"
        assert final_manifest.symbols[sym].candidate_id == expected_id
        assert final_manifest.symbols[sym].candidate_artifact_hash == HASH_A


def test_3_2_symbol_update_preserves_other_symbols(tmp_path: Path) -> None:
    """Verify updating one symbol leaves all other symbols untouched."""
    manifest_path = tmp_path / "candidate_registry.json"
    # Seed BTCUSDT and ETHUSDT
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id="cand-btc-001",
        candidate_artifact_hash=HASH_A,
        artifact_path="cand-btc-001.json",
        qualification_hash=HASH_QUAL,
        admitted_at=NOW_ISO,
    )
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="ETHUSDT",
        candidate_id="cand-eth-001",
        candidate_artifact_hash=HASH_B,
        artifact_path="cand-eth-001.json",
        qualification_hash=HASH_A,
        admitted_at=NOW_ISO,
    )

    # Update BTCUSDT to candidate 002 with later timestamp
    later_iso = (NOW + timedelta(hours=3)).isoformat()
    updated_manifest = publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id="cand-btc-002",
        candidate_artifact_hash=HASH_B,
        artifact_path="cand-btc-002.json",
        qualification_hash=HASH_B,
        admitted_at=later_iso,
    )

    # BTCUSDT is updated
    assert updated_manifest.symbols["BTCUSDT"].candidate_id == "cand-btc-002"
    assert updated_manifest.symbols["BTCUSDT"].admitted_at == later_iso

    # ETHUSDT is unchanged
    assert updated_manifest.symbols["ETHUSDT"].candidate_id == "cand-eth-001"
    assert updated_manifest.symbols["ETHUSDT"].candidate_artifact_hash == HASH_B
    assert updated_manifest.symbols["ETHUSDT"].admitted_at == NOW_ISO
    assert verify_candidate_registry_manifest(updated_manifest) is True


def test_3_3_hash_determinism_under_key_permutations() -> None:
    """Verify compute_registry_hash produces identical digests regardless of key order."""
    entries = {f"SYM{i:02d}USDT": _make_entry(candidate_id=f"cand-{i:02d}") for i in range(1, 11)}

    # Canonical reference hash
    ref_manifest = CandidateRegistryManifest(
        registry_version=1,
        updated_at=NOW_ISO,
        symbols=entries,
        registry_hash="0" * 64,
    )
    expected_hash = compute_registry_hash(ref_manifest)

    # Permute dictionary insertion order 30 times
    import random

    keys = list(entries.keys())
    for seed in range(30):
        rnd = random.Random(seed)
        shuffled_keys = list(keys)
        rnd.shuffle(shuffled_keys)
        shuffled_entries = {k: entries[k] for k in shuffled_keys}

        perm_manifest = CandidateRegistryManifest(
            registry_version=1,
            updated_at=NOW_ISO,
            symbols=shuffled_entries,
            registry_hash="0" * 64,
        )
        assert compute_registry_hash(perm_manifest) == expected_hash


def test_3_4_rapid_100_updates_no_tempfile_leak(tmp_path: Path) -> None:
    """Stress test 100 rapid consecutive updates, verifying zero .tmp files remain."""
    manifest_path = tmp_path / "candidate_registry.json"
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]

    for i in range(100):
        sym = symbols[i % len(symbols)]
        cand_id = f"cand-{sym.lower()}-{i:04d}"
        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol=sym,
            candidate_id=cand_id,
            candidate_artifact_hash=HASH_A,
            artifact_path=f"artifacts/{cand_id}.json",
            qualification_hash=HASH_QUAL,
            admitted_at=NOW_ISO,
        )

    # Verify no dangling .tmp files
    all_files = list(tmp_path.iterdir())
    assert len(all_files) == 1
    assert all_files[0].name == "candidate_registry.json"

    # Verify final manifest validity
    final_manifest = read_candidate_registry(manifest_path, verify_hash=True)
    assert len(final_manifest.symbols) == 5
    assert verify_candidate_registry_manifest(final_manifest) is True


def test_3_5_atomic_replace_failure_handling(tmp_path: Path) -> None:
    """Verify that an atomic replace failure leaves original file intact and removes .tmp."""
    manifest_path = tmp_path / "candidate_registry.json"
    original_manifest = _make_manifest()
    write_candidate_registry(manifest_path, original_manifest)

    new_manifest = original_manifest.model_copy(deep=True)
    new_manifest.symbols["ETHUSDT"] = _make_entry(candidate_id="cand-eth-001")

    with patch(
        "pathlib.Path.replace", side_effect=OSError("Simulated rename lock/permission error")
    ):
        try:
            write_candidate_registry(manifest_path, new_manifest)
            raise AssertionError("Expected OSError on replace failure")
        except OSError as exc:
            assert "Simulated rename lock/permission error" in str(exc)

    # Ensure no .tmp files remain
    tmp_files = [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
    assert len(tmp_files) == 0

    # Ensure original manifest is untouched and valid
    loaded = read_candidate_registry(manifest_path, verify_hash=True)
    assert loaded == original_manifest


# =========================================================================
# SUITE 4: FAIL-CLOSED BEHAVIOR ON ARTIFACT TAMPERING & DISK INCONSISTENCIES
# =========================================================================


def test_4_1_artifact_file_missing_on_disk(tmp_path: Path) -> None:
    """Verify FileNotFoundError is raised when candidate artifact does not exist."""
    entry = _make_entry(artifact_path=str(tmp_path / "missing.json"))
    try:
        verify_candidate_manifest_entry(entry)
        raise AssertionError("Expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "not found" in str(exc)

    manifest = build_candidate_registry_manifest(
        symbols={"BTCUSDT": entry},
        updated_at=NOW_ISO,
    )
    try:
        validate_manifest_candidate_artifacts(manifest)
        raise AssertionError("Expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "not found" in str(exc)


def test_4_2_artifact_content_tampered_on_disk(tmp_path: Path) -> None:
    """Verify DomainViolation when candidate artifact content is altered on disk."""
    cand = _make_candidate("cand-btc-001", "BTCUSDT", stop_atr="1.5")
    path = tmp_path / "cand-btc-001.json"
    write_creator_candidate_artifact(path, cand)

    entry = _make_entry(
        candidate_id=cand.candidate_id,
        candidate_artifact_hash=cand.artifact_hash,
        artifact_path=str(path),
    )

    # Initial verification passes
    assert verify_candidate_manifest_entry(entry) is True

    # Tamper risk parameters inside the artifact JSON without changing hash
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["strategy"]["risk"]["stop_atr_multiplier"] = "9.99"
    path.write_text(json.dumps(raw), encoding="utf-8")

    try:
        verify_candidate_manifest_entry(entry)
        raise AssertionError("Expected DomainViolation on tampered risk parameter")
    except DomainViolation as exc:
        assert "creator candidate artifact hash mismatch" in str(
            exc
        ) or "content hash mismatch" in str(exc)


def test_4_3_artifact_candidate_id_mismatch(tmp_path: Path) -> None:
    """Verify DomainViolation when manifest candidate_id differs from artifact content."""
    cand = _make_candidate("cand-btc-001", "BTCUSDT")
    path = tmp_path / "cand-btc-001.json"
    write_creator_candidate_artifact(path, cand)

    entry = _make_entry(
        candidate_id="cand-btc-different",
        candidate_artifact_hash=cand.artifact_hash,
        artifact_path=str(path),
    )

    try:
        verify_candidate_manifest_entry(entry)
        raise AssertionError("Expected DomainViolation on candidate_id mismatch")
    except DomainViolation as exc:
        assert "Candidate ID mismatch" in str(exc)


def test_4_4_artifact_hash_mismatch(tmp_path: Path) -> None:
    """Verify DomainViolation when manifest entry hash differs from artifact hash."""
    cand = _make_candidate("cand-btc-001", "BTCUSDT")
    path = tmp_path / "cand-btc-001.json"
    write_creator_candidate_artifact(path, cand)

    entry = _make_entry(
        candidate_id=cand.candidate_id,
        candidate_artifact_hash="f" * 64,
        artifact_path=str(path),
    )

    try:
        verify_candidate_manifest_entry(entry)
        raise AssertionError("Expected DomainViolation on artifact hash mismatch")
    except DomainViolation as exc:
        assert "Candidate artifact hash mismatch" in str(exc)


def test_4_5_symbol_universe_mismatch(tmp_path: Path) -> None:
    """Verify validate_manifest_candidate_artifacts fails if symbol is not in candidate universe."""
    cand_btc = _make_candidate("cand-btc-001", "BTCUSDT")
    path_btc = tmp_path / "cand-btc-001.json"
    write_creator_candidate_artifact(path_btc, cand_btc)

    # Manifest assigns BTC candidate to ETHUSDT
    entry = _make_entry(
        candidate_id=cand_btc.candidate_id,
        candidate_artifact_hash=cand_btc.artifact_hash,
        artifact_path=str(path_btc),
    )

    manifest = build_candidate_registry_manifest(
        symbols={"ETHUSDT": entry},
        updated_at=NOW_ISO,
    )

    try:
        validate_manifest_candidate_artifacts(manifest)
        raise AssertionError("Expected DomainViolation on symbol universe mismatch")
    except DomainViolation as exc:
        assert "not present in candidate universe symbols" in str(exc)


def test_4_6_tampered_outer_manifest_rejected_in_validate(tmp_path: Path) -> None:
    """Verify validate_manifest_candidate_artifacts rejects manifest with invalid registry_hash."""
    cand = _make_candidate("cand-btc-001", "BTCUSDT")
    path = tmp_path / "cand-btc-001.json"
    write_creator_candidate_artifact(path, cand)

    entry = _make_entry(
        candidate_id=cand.candidate_id,
        candidate_artifact_hash=cand.artifact_hash,
        artifact_path=str(path),
    )

    manifest = build_candidate_registry_manifest(
        symbols={"BTCUSDT": entry},
        updated_at=NOW_ISO,
    )

    # Tamper outer registry_hash
    tampered_manifest = manifest.model_copy(update={"registry_hash": "e" * 64})

    try:
        validate_manifest_candidate_artifacts(tampered_manifest)
        raise AssertionError("Expected DomainViolation on outer registry_hash tampering")
    except DomainViolation as exc:
        assert "Manifest registry_hash mismatch" in str(exc)


# =========================================================================
# SUITE 5: LINEAGE & PUBLISHER BOUNDARY VALIDATION
# =========================================================================


def test_5_1_nested_parent_directory_creation(tmp_path: Path) -> None:
    """Verify write_candidate_registry automatically creates deeply nested directories."""
    deep_path = tmp_path / "level1" / "level2" / "deep_registry.json"
    manifest = _make_manifest()
    write_candidate_registry(deep_path, manifest)

    assert deep_path.is_file()
    loaded = read_candidate_registry(deep_path, verify_hash=True)
    assert loaded == manifest


def test_5_2_timestamp_iso_format_acceptance() -> None:
    """Verify ISO timestamps with Z or explicit UTC offsets are accepted."""
    entry_z = _make_entry(admitted_at="2026-09-09T12:00:00Z")
    assert entry_z.admitted_at == "2026-09-09T12:00:00Z"

    entry_offset = _make_entry(admitted_at="2026-09-09T12:00:00+00:00")
    assert entry_offset.admitted_at == "2026-09-09T12:00:00+00:00"

    entry_micro = _make_entry(admitted_at="2026-09-09T12:00:00.123456+00:00")
    assert entry_micro.admitted_at == "2026-09-09T12:00:00.123456+00:00"


def test_5_3_read_creator_candidate_artifact_corrupted_json(tmp_path: Path) -> None:
    """Verify candidate artifact with invalid JSON fails closed."""
    cand_path = tmp_path / "cand-corrupt.json"
    cand_path.write_text("{corrupt: json,", encoding="utf-8")

    entry = _make_entry(artifact_path=str(cand_path))
    try:
        verify_candidate_manifest_entry(entry)
        raise AssertionError(
            "Expected ValidationError or DomainViolation on corrupted candidate artifact"
        )
    except (DomainViolation, ValidationError) as exc:
        assert (
            "Invalid" in str(exc) or "Failed" in str(exc) or "validation error" in str(exc).lower()
        )


# =========================================================================
# TEST RUNNER HARNESS
# =========================================================================

ALL_TESTS = [
    # Suite 1: Malformed & Tampered Manifest Resistance
    ("1.1 Truncated JSON boundaries", test_1_1_truncated_json_boundaries),
    ("1.2 Corrupt JSON syntax", test_1_2_corrupt_json_syntax),
    ("1.3 Empty & whitespace files", test_1_3_empty_and_whitespace_files),
    ("1.4 Extra root key injection", test_1_4_extra_root_key_injection),
    ("1.5 Extra entry key injection", test_1_5_extra_entry_key_injection),
    ("1.6 Hash bit-flip & mutations", test_1_6_hash_bit_flip_and_mutation),
    ("1.7 Corrupt timestamps", test_1_7_corrupt_updated_at),
    ("1.8 Corrupt registry versions", test_1_8_corrupt_registry_version),
    ("1.9 Tampered payload hash mismatch", test_1_9_tampered_payload_hash_mismatch),
    (
        "1.10 Pre-existing corrupt manifest fail-closed",
        test_1_10_pre_existing_corrupt_manifest_fail_closed,
    ),
    # Suite 2: Path Traversal & Injection Attempts
    ("2.1 Artifact path traversal variants", lambda p: test_2_1_artifact_path_traversal_variants()),
    (
        "2.2 Artifact path non-json extensions",
        lambda p: test_2_2_artifact_path_non_json_extensions(),
    ),
    ("2.3 Symbol injection attempts", test_2_3_symbol_injection_attempts),
    ("2.4 Candidate ID injection attempts", lambda p: test_2_4_candidate_id_injection_attempts()),
    ("2.5 Hash regex injection attempts", lambda p: test_2_5_hash_regex_injection()),
    # Suite 3: Rapid Sequential & Multi-Symbol Updates, Retention & Determinism
    ("3.1 Multi-symbol lifecycle retention", test_3_1_multi_symbol_lifecycle_retention),
    ("3.2 Symbol update preserves others", test_3_2_symbol_update_preserves_other_symbols),
    (
        "3.3 Hash determinism under key permutations",
        lambda p: test_3_3_hash_determinism_under_key_permutations(),
    ),
    ("3.4 Rapid 100 updates no tempfile leak", test_3_4_rapid_100_updates_no_tempfile_leak),
    ("3.5 Atomic replace failure handling", test_3_5_atomic_replace_failure_handling),
    # Suite 4: Fail-Closed Behavior on Artifact Tampering & Disk Inconsistencies
    ("4.1 Missing artifact file on disk", test_4_1_artifact_file_missing_on_disk),
    ("4.2 Artifact content tampered on disk", test_4_2_artifact_content_tampered_on_disk),
    ("4.3 Artifact candidate_id mismatch", test_4_3_artifact_candidate_id_mismatch),
    ("4.4 Artifact hash mismatch", test_4_4_artifact_hash_mismatch),
    ("4.5 Symbol universe mismatch", test_4_5_symbol_universe_mismatch),
    ("4.6 Tampered outer manifest rejected", test_4_6_tampered_outer_manifest_rejected_in_validate),
    # Suite 5: Lineage & Publisher Boundary Validation
    ("5.1 Nested parent directory creation", test_5_1_nested_parent_directory_creation),
    ("5.2 Timestamp ISO format acceptance", lambda p: test_5_2_timestamp_iso_format_acceptance()),
    (
        "5.3 Corrupt candidate artifact JSON",
        test_5_3_read_creator_candidate_artifact_corrupted_json,
    ),
]


def run_all_stress_tests() -> int:
    print("=== Running Adversarial Stress Suite for Candidate Registry Manifest (M1) ===")
    passed = 0
    failed = 0

    for name, test_fn in ALL_TESTS:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            try:
                test_fn(tmp_path)
                print(f"[PASS] {name}")
                passed += 1
            except Exception as exc:
                print(f"[FAIL] {name}: {exc}")
                import traceback

                traceback.print_exc()
                failed += 1

    print(
        f"\nSummary: {passed} passed, {failed} failed "
        f"out of {len(ALL_TESTS)} adversarial stress tests."
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all_stress_tests())
