"""Write-once cached window ledgers; provenance is not trading authority."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .cached_evaluation import CachedEvaluationWindowSpec
from .creator_artifacts import CreatorCandidateArtifact, _artifact_content_hash
from .trade_simulation import TradeSimulationResult


class WindowSimulationEvidence(DomainModel):
    evidence_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    window: CachedEvaluationWindowSpec
    simulation: TradeSimulationResult
    promotion_state: Literal["unpromoted"] = "unpromoted"
    execution_authority: Literal[False] = False
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_window_binding(self) -> WindowSimulationEvidence:
        if self.simulation.symbol != self.window.symbol:
            raise ValueError("window simulation symbol mismatch")
        if any(
            not self.window.time_start <= point.timestamp < self.window.time_end
            for point in self.simulation.equity_curve
        ):
            raise ValueError("simulation equity timestamp outside window")
        if any(
            trade.symbol != self.window.symbol
            or not self.window.time_start <= trade.entry_timestamp < self.window.time_end
            or not self.window.time_start <= trade.exit_timestamp < self.window.time_end
            for trade in self.simulation.trades
        ):
            raise ValueError("simulation trade outside window scope")
        return self


def _content_hash(evidence: WindowSimulationEvidence) -> str:
    payload = evidence.model_dump(mode="json", exclude={"evidence_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_window_simulation_evidence(path: Path) -> WindowSimulationEvidence:
    try:
        evidence = WindowSimulationEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise DomainViolation("invalid window simulation evidence") from error
    if _content_hash(evidence) != evidence.evidence_hash:
        raise DomainViolation("window simulation evidence hash mismatch")
    return evidence


def write_window_simulation_evidence(
    path: Path,
    candidate: CreatorCandidateArtifact,
    window: CachedEvaluationWindowSpec,
    simulation: TradeSimulationResult,
) -> WindowSimulationEvidence:
    if _artifact_content_hash(candidate) != candidate.artifact_hash:
        raise DomainViolation("window simulation candidate hash mismatch")
    if (
        window.bundle_hash != candidate.bundle_hash
        or window.dataset_registry_hash != candidate.dataset_registry_hash
        or window.symbol not in candidate.strategy.universe.symbols
        or window.timeframe != candidate.strategy.universe.timeframe
    ):
        raise DomainViolation("window simulation candidate scope mismatch")
    provisional = WindowSimulationEvidence.model_validate_json(
        json.dumps(
            {
                "candidate_id": candidate.candidate_id,
                "candidate_artifact_hash": candidate.artifact_hash,
                "window": window.model_dump(mode="json"),
                "simulation": simulation.model_dump(mode="json"),
                "evidence_hash": "0" * 64,
            }
        )
    )
    evidence = provisional.model_copy(update={"evidence_hash": _content_hash(provisional)})
    return _write_window_evidence_once(path, evidence, read_window_simulation_evidence)


def _write_window_evidence_once[T: DomainModel](
    path: Path, evidence: T, reader: Callable[[Path], T]
) -> T:
    if path.exists():
        existing = reader(path)
        if existing != evidence:
            raise DomainViolation("window simulation evidence path is immutable")
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".window-", suffix=".tmp", dir=path.parent)
    temporary_path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as temporary:
            temporary.write(json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2))
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.link(temporary_path, path)
    except FileExistsError:
        existing = reader(path)
        if existing != evidence:
            raise DomainViolation("window simulation evidence path is immutable") from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return reader(path)
