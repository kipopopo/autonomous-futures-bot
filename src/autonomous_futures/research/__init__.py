"""Paper-safe research-plane contracts."""

from .cached_evaluation import (
    CachedEvaluationRun,
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
    CachedEvaluator,
    CachedOnlyEvaluatorAdapter,
    CachedWindowEvaluation,
)
from .causal_evaluation import CausalCachedEvaluatorAdapter, materialize_causal_context
from .creator_artifacts import (
    CandidateState,
    CreatorCandidateArtifact,
    CreatorCandidateRegistry,
    CreatorCandidateRegistryEntry,
    build_creator_candidate_artifact,
    build_creator_candidate_registry,
    find_creator_candidate,
    read_creator_candidate_artifact,
    read_creator_candidate_registry,
    write_creator_candidate_artifact,
    write_creator_candidate_registry,
)
from .feature_signals import CausalFeatureSignalEvaluator
from .qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    QualificationComparator,
    QualificationDecision,
    QualificationGateResult,
    QualificationMetric,
    build_creator_candidate_qualification_artifact,
    read_creator_candidate_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)

__all__ = [
    "CandidateState",
    "CreatorCandidateArtifact",
    "CreatorCandidateRegistry",
    "CreatorCandidateRegistryEntry",
    "build_creator_candidate_artifact",
    "build_creator_candidate_registry",
    "find_creator_candidate",
    "read_creator_candidate_artifact",
    "read_creator_candidate_registry",
    "write_creator_candidate_artifact",
    "write_creator_candidate_registry",
    "CachedEvaluationRun",
    "CachedEvaluationWindow",
    "CachedEvaluationWindowSpec",
    "CachedEvaluator",
    "CachedOnlyEvaluatorAdapter",
    "CachedWindowEvaluation",
    "CausalCachedEvaluatorAdapter",
    "materialize_causal_context",
    "CausalFeatureSignalEvaluator",
    "CreatorCandidateQualificationArtifact",
    "QualificationComparator",
    "QualificationDecision",
    "QualificationGateResult",
    "QualificationMetric",
    "build_creator_candidate_qualification_artifact",
    "read_creator_candidate_qualification_artifact",
    "write_creator_candidate_qualification_artifact",
]
