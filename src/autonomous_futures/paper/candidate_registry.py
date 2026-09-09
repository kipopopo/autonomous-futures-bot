"""Versioned, atomic candidate registry manifest for autonomous strategy hot-reloading."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from ..research.creator_artifacts import (
    CreatorCandidateArtifact,
    _artifact_content_hash,
    read_creator_candidate_artifact,
)

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATE_REGISTRY_PATH = Path("artifacts/paper_live/candidate_registry.json")

_SYMBOL_REGEX = re.compile(r"^[A-Z0-9]+$")
_CANDIDATE_ID_REGEX = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256_REGEX = re.compile(r"^[0-9a-f]{64}$")


class CandidateManifestEntry(DomainModel):
    """Entry describing an active admitted candidate in the paper registry."""

    candidate_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_path: str = Field(min_length=1)
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    admitted_at: str = Field(min_length=1)

    @field_validator("admitted_at")
    @classmethod
    def validate_admitted_at_format(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"admitted_at must be a valid ISO-8601 timestamp string: {value}"
            ) from exc
        return value

    @field_validator("artifact_path")
    @classmethod
    def validate_artifact_path(cls, value: str) -> str:
        clean = value.strip()
        if not clean.endswith(".json"):
            raise ValueError(f"artifact_path must reference a .json artifact file: {value}")
        norm_parts = Path(clean).parts
        if ".." in norm_parts or ".." in clean:
            raise ValueError(f"artifact_path must not contain directory traversal ('..'): {value}")
        return clean


class CandidateRegistryManifest(DomainModel):
    """Immutable, versioned registry manifest binding symbols to qualified candidates."""

    registry_version: int = Field(default=1, ge=1)
    updated_at: str = Field(min_length=1)
    symbols: dict[str, CandidateManifestEntry] = Field(default_factory=dict)
    registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at_format(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"updated_at must be a valid ISO-8601 timestamp string: {value}"
            ) from exc
        return value

    @field_validator("symbols")
    @classmethod
    def validate_symbol_keys(
        cls, symbols: dict[str, CandidateManifestEntry]
    ) -> dict[str, CandidateManifestEntry]:
        for sym in symbols.keys():
            if not _SYMBOL_REGEX.match(sym):
                raise ValueError(f"Symbol key must be uppercase alphanumeric: '{sym}'")
        return symbols


def compute_registry_hash(manifest: CandidateRegistryManifest) -> str:
    """Compute deterministic SHA-256 hex digest of the canonical manifest payload.

    Excludes the top-level 'registry_hash' field.
    Serializes using canonical JSON (sorted keys, compact separators, UTF-8 encoded).
    Note: updated_at is included in the hash so release snapshots are strictly unique.
    """
    payload = manifest.model_dump(mode="json", exclude={"registry_hash"})
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(canonical_bytes).hexdigest()


def build_candidate_registry_manifest(
    *,
    symbols: Mapping[str, CandidateManifestEntry] | None = None,
    updated_at: str | datetime | None = None,
    registry_version: int = 1,
) -> CandidateRegistryManifest:
    """Construct a CandidateRegistryManifest with deterministically computed registry_hash."""
    if updated_at is None:
        updated_at_str = datetime.now(UTC).isoformat()
    elif isinstance(updated_at, datetime):
        updated_at_str = updated_at.astimezone(UTC).isoformat()
    else:
        updated_at_str = str(updated_at)

    entries = dict(sorted(symbols.items())) if symbols else {}
    provisional = CandidateRegistryManifest(
        registry_version=registry_version,
        updated_at=updated_at_str,
        symbols=entries,
        registry_hash="0" * 64,
    )
    computed_hash = compute_registry_hash(provisional)
    return provisional.model_copy(update={"registry_hash": computed_hash})


def read_candidate_registry(
    path: Path | str,
    *,
    verify_hash: bool = True,
) -> CandidateRegistryManifest:
    """Read and validate a candidate registry manifest from disk.

    Raises:
        FileNotFoundError: If the manifest file does not exist.
        DomainViolation: If JSON is corrupt, empty, schema invalid, or hash mismatches.
    """
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Candidate registry manifest not found: {manifest_path}")

    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
        if not raw_text.strip():
            raise DomainViolation(f"Candidate registry manifest at {manifest_path} is empty")
        manifest = CandidateRegistryManifest.model_validate_json(raw_text)
    except DomainViolation:
        raise
    except Exception as exc:
        raise DomainViolation(
            f"Invalid candidate registry manifest schema at {manifest_path}: {exc}"
        ) from exc

    if verify_hash:
        computed = compute_registry_hash(manifest)
        if computed != manifest.registry_hash:
            raise DomainViolation(
                f"Candidate registry manifest hash mismatch at {manifest_path}: "
                f"expected {manifest.registry_hash}, computed {computed}"
            )

    return manifest


def write_candidate_registry(
    path: Path | str,
    manifest: CandidateRegistryManifest,
    *,
    indent: int = 2,
) -> CandidateRegistryManifest:
    """Atomically write candidate registry manifest to disk using temp file, fsync, and replace.

    Guarantees:
    1. Re-computes registry_hash to ensure published file is cryptographically consistent.
    2. Writes to a temporary file in the same directory (.{filename}.{pid}_{time_ns}.tmp).
    3. Flushes and fsyncs to physical disk.
    4. Replaces destination atomically via Path.replace (atomic on POSIX and Windows).
    5. Cleanly unlinks temporary file on failure.
    """
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    expected_hash = compute_registry_hash(manifest)
    if manifest.registry_hash != expected_hash:
        manifest = manifest.model_copy(update={"registry_hash": expected_hash})

    payload = json.dumps(manifest.model_dump(mode="json"), indent=indent, sort_keys=True) + "\n"

    temp_path = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}_{time.time_ns()}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        # Retry loop for Windows NTFS file contention during replace
        for attempt in range(5):
            try:
                temp_path.replace(manifest_path)
                break
            except PermissionError, OSError:
                if attempt < 4:
                    time.sleep(0.015)
                else:
                    raise
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    return manifest


def publish_candidate_admission(
    manifest_path: Path | str,
    symbol: str,
    candidate_id: str,
    candidate_artifact_hash: str,
    artifact_path: str | Path,
    qualification_hash: str,
    admitted_at: str | datetime | None = None,
) -> CandidateRegistryManifest:
    """Publish an admitted candidate into the candidate registry manifest atomically.

    Loads existing manifest if present (preserving all other symbols), updates the entry
    for the specified symbol, recomputes canonical registry_hash, and atomically replaces.
    """
    target_path = Path(manifest_path)

    if target_path.is_file():
        prior_manifest = read_candidate_registry(target_path, verify_hash=True)
        updated_symbols = dict(prior_manifest.symbols)
        version = prior_manifest.registry_version
    else:
        updated_symbols = {}
        version = 1

    if admitted_at is None:
        admitted_str = datetime.now(UTC).isoformat()
    elif isinstance(admitted_at, datetime):
        admitted_str = admitted_at.astimezone(UTC).isoformat()
    else:
        admitted_str = str(admitted_at)

    clean_symbol = symbol.strip().upper()
    entry = CandidateManifestEntry(
        candidate_id=candidate_id,
        candidate_artifact_hash=candidate_artifact_hash,
        artifact_path=str(artifact_path),
        qualification_hash=qualification_hash,
        admitted_at=admitted_str,
    )
    updated_symbols[clean_symbol] = entry

    new_manifest = build_candidate_registry_manifest(
        symbols=updated_symbols,
        updated_at=admitted_str,
        registry_version=version,
    )

    write_candidate_registry(target_path, new_manifest)
    return new_manifest


publish_admitted_candidate = publish_candidate_admission


def verify_candidate_registry_manifest(manifest: CandidateRegistryManifest) -> bool:
    """Verify that the manifest's registry_hash strictly matches its content."""
    return compute_registry_hash(manifest) == manifest.registry_hash


def verify_candidate_manifest_entry(
    entry: CandidateManifestEntry,
    base_dir: Path | None = None,
) -> bool:
    """Validate that candidate artifact exists on disk and content hash matches entry."""
    art_path = Path(entry.artifact_path)
    if not art_path.is_file() and base_dir is not None:
        candidate_path = Path(base_dir) / art_path
        if candidate_path.is_file():
            art_path = candidate_path

    if not art_path.is_file():
        raise FileNotFoundError(f"Candidate artifact file not found: {entry.artifact_path}")

    candidate = read_creator_candidate_artifact(art_path)
    if candidate.candidate_id != entry.candidate_id:
        raise DomainViolation(
            f"Candidate ID mismatch in {art_path}: expected {entry.candidate_id}, "
            f"found {candidate.candidate_id}"
        )
    if candidate.artifact_hash != entry.candidate_artifact_hash:
        raise DomainViolation(
            f"Candidate artifact hash mismatch in {art_path}: "
            f"expected {entry.candidate_artifact_hash}, "
            f"found {candidate.artifact_hash}"
        )
    computed_hash = _artifact_content_hash(candidate)
    if computed_hash != entry.candidate_artifact_hash:
        raise DomainViolation(
            f"Candidate content hash mismatch in {art_path}: "
            f"expected {entry.candidate_artifact_hash}, "
            f"computed {computed_hash}"
        )
    return True


def validate_manifest_candidate_artifacts(
    manifest: CandidateRegistryManifest,
    base_dir: Path | None = None,
) -> dict[str, CreatorCandidateArtifact]:
    """Validate all candidate artifacts in manifest against disk and return dictionary.

    Enforces:
    1. Outer manifest hash integrity.
    2. Candidate artifact presence on disk.
    3. Candidate ID equality.
    4. Candidate artifact hash equality.
    5. Content hash verification (_artifact_content_hash).
    6. Universe membership for symbol.
    """
    if not verify_candidate_registry_manifest(manifest):
        raise DomainViolation(
            f"Manifest registry_hash mismatch: expected {manifest.registry_hash}, "
            f"computed {compute_registry_hash(manifest)}"
        )

    loaded: dict[str, CreatorCandidateArtifact] = {}
    for symbol, entry in manifest.symbols.items():
        art_path = Path(entry.artifact_path)
        if not art_path.is_file() and base_dir is not None:
            candidate_path = Path(base_dir) / art_path
            if candidate_path.is_file():
                art_path = candidate_path

        if not art_path.is_file():
            raise FileNotFoundError(
                f"Candidate artifact file for {symbol} not found: {entry.artifact_path}"
            )

        candidate = read_creator_candidate_artifact(art_path)
        if candidate.candidate_id != entry.candidate_id:
            raise DomainViolation(
                f"Candidate ID mismatch for {symbol}: expected {entry.candidate_id}, "
                f"found {candidate.candidate_id}"
            )
        if candidate.artifact_hash != entry.candidate_artifact_hash:
            raise DomainViolation(
                f"Candidate artifact hash mismatch for {symbol}: "
                f"expected {entry.candidate_artifact_hash}, "
                f"found {candidate.artifact_hash}"
            )
        computed_hash = _artifact_content_hash(candidate)
        if computed_hash != entry.candidate_artifact_hash:
            raise DomainViolation(
                f"Candidate content hash mismatch for {symbol}: "
                f"expected {entry.candidate_artifact_hash}, "
                f"computed {computed_hash}"
            )
        if symbol not in candidate.strategy.universe.symbols:
            raise DomainViolation(
                f"Symbol {symbol} not present in candidate universe symbols: "
                f"{candidate.strategy.universe.symbols}"
            )
        loaded[symbol] = candidate
    return loaded


class CandidateRegistryHotReloader:
    """Zero-downtime hot-reloader monitoring candidate_registry.json for live paper engine."""

    def __init__(
        self,
        manifest_path: Path | str,
        engine: Any,
        base_dir: Path | None = None,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.engine = engine
        self.base_dir = Path(base_dir) if base_dir is not None else None
        self.last_mtime_ns: int | None = None
        self.last_size: int | None = None
        self.last_registry_hash: str | None = None
        self.last_reloaded_at: str | None = None
        self.last_reload_status: str = "NONE"
        self.reload_count: int = 0

    def check_and_reload(self) -> bool:
        """Poll candidate registry manifest using stat-first check and reload candidates."""
        try:
            stat_res = self.manifest_path.stat()
        except FileNotFoundError, OSError:
            return False

        if (
            self.last_mtime_ns is not None
            and self.last_size is not None
            and stat_res.st_mtime_ns == self.last_mtime_ns
            and stat_res.st_size == self.last_size
        ):
            return False

        manifest: CandidateRegistryManifest | None = None
        for attempt in range(3):
            try:
                manifest = read_candidate_registry(self.manifest_path, verify_hash=True)
                break
            except (PermissionError, FileNotFoundError, OSError) as exc:
                if attempt < 2:
                    time.sleep(0.015)
                else:
                    logger.warning(
                        "Contention error reading candidate registry at %s: %s",
                        self.manifest_path,
                        exc,
                    )
                    self.last_reload_status = "FAILED_FILE_CONTENTION"
                    return False
            except DomainViolation as exc:
                err_msg = str(exc)
                logger.warning(
                    "Validation failed for candidate registry at %s: %s",
                    self.manifest_path,
                    err_msg,
                )
                if "hash mismatch" in err_msg.lower():
                    self.last_reload_status = "FAILED_HASH_MISMATCH"
                else:
                    self.last_reload_status = "FAILED_CORRUPT"
                self.last_mtime_ns = stat_res.st_mtime_ns
                self.last_size = stat_res.st_size
                return False
            except Exception as exc:
                logger.warning(
                    "Unexpected error reading candidate registry at %s: %s",
                    self.manifest_path,
                    exc,
                )
                self.last_reload_status = "FAILED_CORRUPT"
                self.last_mtime_ns = stat_res.st_mtime_ns
                self.last_size = stat_res.st_size
                return False

        if manifest is None:
            return False

        if manifest.registry_hash == self.last_registry_hash:
            self.last_mtime_ns = stat_res.st_mtime_ns
            self.last_size = stat_res.st_size
            return False

        candidates_to_admit: list[tuple[CreatorCandidateArtifact, str]] = []
        for symbol, entry in manifest.symbols.items():
            current = getattr(self.engine, "candidates", {}).get(symbol)
            if (
                current is not None
                and getattr(current, "candidate_id", None) == entry.candidate_id
                and getattr(current, "artifact_hash", None) == entry.candidate_artifact_hash
            ):
                continue

            try:
                verify_candidate_manifest_entry(entry, base_dir=self.base_dir)
            except FileNotFoundError as exc:
                logger.warning(
                    "Candidate artifact file missing for %s at %s: %s",
                    symbol,
                    entry.artifact_path,
                    exc,
                )
                self.last_reload_status = "FAILED_ARTIFACT_MISSING"
                self.last_mtime_ns = stat_res.st_mtime_ns
                self.last_size = stat_res.st_size
                return False
            except DomainViolation as exc:
                err_msg = str(exc)
                logger.warning(
                    "Candidate artifact verification failed for %s at %s: %s",
                    symbol,
                    entry.artifact_path,
                    err_msg,
                )
                if "hash mismatch" in err_msg.lower():
                    self.last_reload_status = "FAILED_ARTIFACT_HASH_MISMATCH"
                else:
                    self.last_reload_status = "FAILED_CORRUPT"
                self.last_mtime_ns = stat_res.st_mtime_ns
                self.last_size = stat_res.st_size
                return False
            except Exception as exc:
                logger.warning("Error verifying candidate artifact for %s: %s", symbol, exc)
                self.last_reload_status = "FAILED_CORRUPT"
                self.last_mtime_ns = stat_res.st_mtime_ns
                self.last_size = stat_res.st_size
                return False

            art_path = Path(entry.artifact_path)
            if not art_path.is_file() and self.base_dir is not None:
                candidate_path = Path(self.base_dir) / art_path
                if candidate_path.is_file():
                    art_path = candidate_path

            cand = read_creator_candidate_artifact(art_path)
            if symbol not in cand.strategy.universe.symbols:
                logger.warning(
                    "Symbol %s not present in candidate universe symbols %s for candidate %s",
                    symbol,
                    cand.strategy.universe.symbols,
                    cand.candidate_id,
                )
                self.last_reload_status = "FAILED_UNIVERSE_MISMATCH"
                self.last_mtime_ns = stat_res.st_mtime_ns
                self.last_size = stat_res.st_size
                return False

            candidates_to_admit.append((cand, entry.qualification_hash))

        for cand, q_hash in candidates_to_admit:
            self.engine.admit_candidate(
                candidate=cand,
                qualification_hash=q_hash,
                require_flat=False,
            )

        self.last_reloaded_at = datetime.now(UTC).isoformat()
        self.last_registry_hash = manifest.registry_hash
        self.last_reload_status = "RELOADED"
        self.last_mtime_ns = stat_res.st_mtime_ns
        self.last_size = stat_res.st_size
        self.reload_count += 1
        logger.info(
            "Successfully reloaded candidate registry from %s: "
            "registry_hash=%s, reloaded=%d, total_reloads=%d",
            self.manifest_path,
            manifest.registry_hash,
            len(candidates_to_admit),
            self.reload_count,
        )
        return True

    def get_telemetry(self) -> tuple[dict[str, str], dict[str, Any]]:
        """Return active candidate mappings and latest reload health telemetry."""
        candidates = getattr(self.engine, "candidates", {})
        active_candidates = {
            s: getattr(c, "candidate_id", str(c)) for s, c in sorted(candidates.items())
        }
        last_registry_reload = {
            "reloaded_at": self.last_reloaded_at,
            "registry_hash": self.last_registry_hash,
            "reload_status": self.last_reload_status,
            "reload_count": self.reload_count,
        }
        return active_candidates, last_registry_reload
