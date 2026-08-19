"""Read-only completion summary for persisted bounded testnet evidence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from .domain.contracts import DomainModel
from .testnet_audit import TestnetLifecycleEvidence
from .testnet_freeze import TestnetEvidenceReview
from .testnet_observation import TestnetObservation


class TestnetCompletionSummary(DomainModel):
    status: Literal["unavailable", "incomplete", "blocked", "complete"]
    audit_count: int = Field(ge=0, strict=True)
    reconciled_audit_count: int = Field(ge=0, strict=True)
    observation_count: int = Field(ge=0, strict=True)
    stable_observation_count: int = Field(ge=0, strict=True)
    accepted_review_count: int = Field(ge=0, strict=True)
    nonzero_position_observation_count: int = Field(ge=0, strict=True)
    new_actions_allowed: Literal[False] = False
    live_enabled: Literal[False] = False
    reason_codes: tuple[str, ...] = Field(min_length=1)


def _summary(
    status: Literal["unavailable", "incomplete", "blocked", "complete"],
    audits: Sequence[TestnetLifecycleEvidence],
    observations: Sequence[TestnetObservation],
    reviews: Sequence[TestnetEvidenceReview],
    reason_codes: tuple[str, ...],
) -> TestnetCompletionSummary:
    return TestnetCompletionSummary(
        status=status,
        audit_count=len(audits),
        reconciled_audit_count=sum(audit.audit.status == "reconciled" for audit in audits),
        observation_count=len(observations),
        stable_observation_count=sum(
            observation.status == "stable" for observation in observations
        ),
        accepted_review_count=sum(
            review.decision == "accept_testnet_observation" for review in reviews
        ),
        nonzero_position_observation_count=sum(
            observation.nonzero_position_count > 0 for observation in observations
        ),
        reason_codes=reason_codes,
    )


def summarize_testnet_completion(
    audits: Sequence[TestnetLifecycleEvidence],
    observations: Sequence[TestnetObservation],
    reviews: Sequence[TestnetEvidenceReview],
) -> TestnetCompletionSummary:
    """Summarize evidence state without network, mutation, or activation."""
    if not audits:
        return _summary(
            "unavailable", audits, observations, reviews, ("testnet_evidence_unavailable",)
        )
    audit_map = {audit.audit_id: audit for audit in audits}
    if len(audit_map) != len(audits):
        return _summary(
            "blocked", audits, observations, reviews, ("testnet_evidence_duplicate_audit",)
        )
    observation_ids = {observation.observation_id for observation in observations}
    review_ids = {review.review_id for review in reviews}
    if len(observation_ids) != len(observations) or len(review_ids) != len(reviews):
        return _summary(
            "blocked", audits, observations, reviews, ("testnet_evidence_duplicate_record",)
        )
    for observation in observations:
        audit = audit_map.get(observation.audit_id)
        if audit is None or observation.audit_hash != audit.evidence_hash:
            return _summary(
                "blocked", audits, observations, reviews, ("testnet_evidence_binding_drift",)
            )
    for review in reviews:
        audit = audit_map.get(review.audit_id)
        matched_observation = next(
            (item for item in observations if item.observation_id == review.observation_id), None
        )
        if (
            audit is None
            or review.audit_hash != audit.evidence_hash
            or matched_observation is None
            or review.observation_hash != matched_observation.observation_hash
        ):
            return _summary(
                "blocked", audits, observations, reviews, ("testnet_evidence_binding_drift",)
            )
    if any(audit.audit.status != "reconciled" for audit in audits):
        return _summary(
            "incomplete", audits, observations, reviews, ("testnet_evidence_not_reconciled",)
        )
    if any(
        observation.status != "stable" or observation.nonzero_position_count != 0
        for observation in observations
    ):
        return _summary(
            "incomplete", audits, observations, reviews, ("testnet_evidence_not_stable",)
        )
    if len(observations) != len(audits) or len(reviews) != len(audits):
        return _summary(
            "incomplete", audits, observations, reviews, ("testnet_evidence_chain_incomplete",)
        )
    if any(review.decision != "accept_testnet_observation" for review in reviews):
        return _summary(
            "incomplete", audits, observations, reviews, ("testnet_evidence_review_not_accepted",)
        )
    return _summary(
        "complete",
        audits,
        observations,
        reviews,
        ("testnet_evidence_complete_and_frozen",),
    )
