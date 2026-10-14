"""Load diagnostic-only, hash-bound Hawkes calibration for the live estimator."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from pathlib import Path
from typing import Any


@dataclasses.dataclass(frozen=True)
class RuntimeHawkesCalibration:
    beta_per_second: float
    artifact_sha256: str
    trace_sha256s: tuple[str, ...]
    symbols: tuple[str, ...]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_file(repo: Path, relative: str) -> Path:
    root = repo.resolve(strict=True)
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Hawkes evidence paths must resolve to files inside the repository")
    return path


def _validate_profile(
    profile: dict[str, Any], record: dict[str, Any], beta: float, repo: Path
) -> None:
    if (
        profile.get("schema") != "hawkes-decay-profile-diagnostic-v1"
        or profile.get("execution_authority") is not False
        or profile.get("qualification") is not False
        or profile.get("selected_beta_per_second") != beta
    ):
        raise ValueError("Hawkes calibration requires matching diagnostic-only profile evidence")

    implementation = profile.get("implementation_sha256")
    if not isinstance(implementation, dict):
        raise ValueError("Hawkes profile has no implementation hashes")
    source_hash = None
    for relative, digest in implementation.items():
        normalized = str(relative).replace("\\", "/")
        if normalized.endswith("src/autonomous_futures/feed/measured_hawkes.py"):
            source = _repository_file(repo, normalized)
            source_hash = _sha256(source)
            if source_hash != digest:
                raise ValueError("Hawkes fitting implementation differs from its evidence")
            break
    if source_hash is None:
        raise ValueError("Hawkes profile does not attest the measured estimator")

    trace_hash = record.get("trace_sha256")
    trace = next(
        (item for item in profile.get("traces", []) if item.get("trace_sha256") == trace_hash),
        None,
    )
    if trace is None:
        raise ValueError("Hawkes calibration trace is absent from its profile")
    if trace.get("generation") != record.get("generation") or trace.get(
        "trade_arrivals_in_current_generation"
    ) != record.get("trade_arrivals"):
        raise ValueError("Hawkes calibration trace metadata does not match its profile")
    fits = [fit for fit in trace.get("fits", []) if fit.get("beta") == beta]
    if (
        len(fits) != 1
        or fits[0].get("accepted_for_diagnostic") is not True
        or fits[0].get("baseline_boundary_symbols") != []
    ):
        raise ValueError("Hawkes calibration fit is not supported by its trace")
    if fits[0].get("spectral_radius") != record.get("spectral_radius"):
        raise ValueError("Hawkes calibration spectral radius does not match its profile")


def load_runtime_hawkes_calibration(path: Path, repo: Path) -> RuntimeHawkesCalibration:
    """Verify immutable profile evidence and return its model parameter only.

    Diagnostic artifacts cannot authorize strategy execution or qualify a strategy.
    Those controls remain in the separate qualification-receipt path.
    """
    root = repo.resolve(strict=True)
    artifact = path.resolve(strict=False)
    if not artifact.is_relative_to(root):
        raise ValueError("Hawkes calibration artifact must be inside the repository")
    artifact = artifact.resolve(strict=True)
    if not artifact.is_relative_to(root):
        raise ValueError("Hawkes calibration artifact must be inside the repository")
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Hawkes calibration artifact is unreadable") from exc
    beta = payload.get("beta_per_second")
    if (
        payload.get("schema") != "runtime-hawkes-calibration-v1"
        or payload.get("purpose") != "runtime_model_parameter_only"
        or payload.get("execution_authority") is not False
        or payload.get("qualification") is not False
        or isinstance(beta, bool)
        or not isinstance(beta, (int, float))
        or not math.isfinite(beta)
        or beta <= 0
    ):
        raise ValueError("Hawkes calibration artifact is not a valid diagnostic parameter record")

    records = payload.get("evidence")
    if not isinstance(records, list) or len(records) < 2:
        raise ValueError("Independent Hawkes selection and validation evidence are required")
    roles = [record.get("role") for record in records if isinstance(record, dict)]
    if roles.count("selection") != 1 or roles.count("independent_validation") < 1:
        raise ValueError("Hawkes calibration must bind selection and independent validation")

    trace_hashes: list[str] = []
    profile_hashes: set[str] = set()
    profile_symbols: tuple[str, ...] | None = None
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Malformed Hawkes calibration evidence record")
        profile_path = _repository_file(root, str(record.get("profile_path", "")))
        profile_hash = _sha256(profile_path)
        if profile_hash != record.get("profile_sha256") or profile_hash in profile_hashes:
            raise ValueError("Hawkes profile evidence is modified or duplicated")
        profile_hashes.add(profile_hash)
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Hawkes profile evidence is malformed") from exc
        symbols = tuple(profile.get("symbols", ()))
        if not symbols or len(set(symbols)) != len(symbols):
            raise ValueError("Hawkes profile does not cover a unique symbol universe")
        if profile_symbols is None:
            profile_symbols = symbols
        elif symbols != profile_symbols:
            raise ValueError("Hawkes selection and validation symbol universes differ")
        _validate_profile(profile, record, float(beta), root)
        trace_hash = record.get("trace_sha256")
        if (
            not isinstance(trace_hash, str)
            or len(trace_hash) != 64
            or any(character not in "0123456789abcdef" for character in trace_hash)
        ):
            raise ValueError("Hawkes calibration trace hash is malformed")
        trace_hashes.append(trace_hash)

    if len(set(trace_hashes)) != len(trace_hashes):
        raise ValueError("Independent Hawkes profiles must use distinct traces")
    if profile_symbols is None:
        raise ValueError("Hawkes calibration has no symbol universe")
    return RuntimeHawkesCalibration(
        beta_per_second=float(beta),
        artifact_sha256=_sha256(artifact),
        trace_sha256s=tuple(trace_hashes),
        symbols=profile_symbols,
    )
