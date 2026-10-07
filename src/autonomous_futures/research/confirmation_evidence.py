"""Separate cross-scope ledger observations, never untouched/acceptance authority."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from ..domain.errors import DomainViolation
from .cached_evaluation import CachedEvaluationWindowSpec
from .creator_artifacts import CreatorCandidateArtifact, _artifact_content_hash
from .qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    _qualification_content_hash,
)
from .trade_simulation import TradeSimulationConfig, TradeSimulationResult
from .window_evidence import (
    WindowSimulationEvidence,
    _content_hash,
    _write_window_evidence_once,
)


class ConfirmationWindowEvidence(WindowSimulationEvidence):
    evidence_scope: Literal["confirmation_observation_only"] = "confirmation_observation_only"
    training_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    research_qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_config: TradeSimulationConfig
    untouched_isolation_verified: Literal[False] = False
    epoch_acceptance_verified: Literal[False] = False
    preregistration_verified: Literal[False] = False

    @model_validator(mode="after")
    def validate_declared_scope(self) -> ConfirmationWindowEvidence:
        if (
            self.window.bundle_hash == self.training_bundle_hash
            or self.window.dataset_registry_hash == self.training_dataset_registry_hash
        ):
            raise ValueError("confirmation requires a separate evaluation scope")
        if self.simulation.starting_equity != self.declared_config.starting_equity:
            raise ValueError("confirmation declared starting equity mismatch")
        return self


def _verified_sources(
    candidate: CreatorCandidateArtifact, qualification: CreatorCandidateQualificationArtifact
) -> tuple[CreatorCandidateArtifact, CreatorCandidateQualificationArtifact]:
    try:
        candidate = CreatorCandidateArtifact.model_validate_json(candidate.model_dump_json())
        qualification = CreatorCandidateQualificationArtifact.model_validate_json(
            qualification.model_dump_json()
        )
    except ValidationError as error:
        raise DomainViolation("invalid confirmation source") from error
    if _artifact_content_hash(candidate) != candidate.artifact_hash:
        raise DomainViolation("confirmation candidate hash mismatch")
    if _qualification_content_hash(qualification) != qualification.qualification_hash:
        raise DomainViolation("confirmation research qualification hash mismatch")
    if qualification.decision != "qualified" or qualification.source != "walk_forward_oos":
        raise DomainViolation("confirmation requires qualified research evidence")
    if (
        qualification.candidate_id != candidate.candidate_id
        or qualification.candidate_artifact_hash != candidate.artifact_hash
        or qualification.bundle_hash != candidate.bundle_hash
        or qualification.dataset_registry_hash != candidate.dataset_registry_hash
    ):
        raise DomainViolation("confirmation research source binding mismatch")
    return candidate, qualification


def _verify_binding(
    evidence: ConfirmationWindowEvidence,
    candidate: CreatorCandidateArtifact,
    qualification: CreatorCandidateQualificationArtifact,
) -> None:
    if (
        evidence.candidate_id != candidate.candidate_id
        or evidence.candidate_artifact_hash != candidate.artifact_hash
        or evidence.training_bundle_hash != candidate.bundle_hash
        or evidence.training_dataset_registry_hash != candidate.dataset_registry_hash
        or evidence.research_qualification_hash != qualification.qualification_hash
    ):
        raise DomainViolation("confirmation provenance mismatch")
    if (
        evidence.window.symbol not in candidate.strategy.universe.symbols
        or evidence.window.timeframe != candidate.strategy.universe.timeframe
    ):
        raise DomainViolation("confirmation evaluation universe mismatch")
    risk = candidate.strategy.risk
    if risk is not None and any(
        getattr(evidence.declared_config, name) != getattr(risk, name)
        for name in (
            "position_fraction",
            "stop_atr_multiplier",
            "take_profit_atr_multiplier",
            "trailing_atr_multiplier",
        )
    ):
        raise DomainViolation("confirmation declared risk mismatch")


def read_confirmation_window_evidence(
    path: Path,
    candidate: CreatorCandidateArtifact,
    qualification: CreatorCandidateQualificationArtifact,
) -> ConfirmationWindowEvidence:
    candidate, qualification = _verified_sources(candidate, qualification)
    try:
        evidence = ConfirmationWindowEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise DomainViolation("invalid confirmation window evidence") from error
    if _content_hash(evidence) != evidence.evidence_hash:
        raise DomainViolation("confirmation window evidence hash mismatch")
    _verify_binding(evidence, candidate, qualification)
    return evidence


def write_confirmation_window_evidence(
    path: Path,
    candidate: CreatorCandidateArtifact,
    qualification: CreatorCandidateQualificationArtifact,
    window: CachedEvaluationWindowSpec,
    simulation: TradeSimulationResult,
    declared_config: TradeSimulationConfig,
) -> ConfirmationWindowEvidence:
    candidate, qualification = _verified_sources(candidate, qualification)
    if (
        simulation.simulation_version != 4
        or window.funding_artifact_hash is None
        or simulation.funding_artifact_hash != window.funding_artifact_hash
    ):
        raise DomainViolation("confirmation requires hash-bound funding simulation")
    try:
        provisional = ConfirmationWindowEvidence.model_validate_json(
            json.dumps(
                {
                    "candidate_id": candidate.candidate_id,
                    "candidate_artifact_hash": candidate.artifact_hash,
                    "training_bundle_hash": candidate.bundle_hash,
                    "training_dataset_registry_hash": candidate.dataset_registry_hash,
                    "research_qualification_hash": qualification.qualification_hash,
                    "window": window.model_dump(mode="json"),
                    "simulation": simulation.model_dump(mode="json"),
                    "declared_config": declared_config.model_dump(mode="json"),
                    "evidence_hash": "0" * 64,
                }
            )
        )
    except ValidationError as error:
        raise DomainViolation("invalid confirmation window evidence") from error
    _verify_binding(provisional, candidate, qualification)
    evidence = provisional.model_copy(update={"evidence_hash": _content_hash(provisional)})
    return _write_window_evidence_once(
        path,
        evidence,
        lambda saved: read_confirmation_window_evidence(saved, candidate, qualification),
    )
