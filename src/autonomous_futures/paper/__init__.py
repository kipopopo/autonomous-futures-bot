"""Autonomous Futures Paper Trading Subsystem."""

from .candidate_registry import (
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    CandidateManifestEntry,
    CandidateRegistryHotReloader,
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
from .circuit_breakers import (
    CircuitBreakerConfig,
    CircuitBreakerEvaluationResult,
    HardenedSharedMarginAccount,
    calculate_adverse_gap_fill,
)
from .feedback_extractor import (
    PaperFeedbackExtractor,
    PaperQualificationPolicy,
    ResolvedCandidateMetadata,
    compute_feedback_qualification_hash,
    extract_paper_feedback,
    paper_qualification_policy_content_hash,
)
from .fills import PaperRoundTripResult, simulate_paper_round_trip
from .ledger import PaperLedger, PaperLedgerEntry, PaperLedgerError
from .lifecycle import PaperLifecycleTelemetry, mark_paper_position
from .live_engine import ActivePaperTrade, LivePaperEngine
from .observation import PaperObservation, observe_paper_ledger
from .runtime import PaperRuntime, PaperRuntimeResult
from .safety import (
    PaperActionApproval,
    PaperActionPermission,
    PaperSafetyDecision,
    PaperSafetyEvidence,
    evaluate_paper_action_permission,
    evaluate_paper_safety,
)
from .sqlite_ledger import SqlitePaperLedger
from .sqlite_lifecycle import SqlitePaperLifecycle
from .sqlite_observation import SqlitePaperObservations

__all__ = [
    "ActivePaperTrade",
    "CandidateManifestEntry",
    "CandidateRegistryHotReloader",
    "CandidateRegistryManifest",
    "CircuitBreakerConfig",
    "CircuitBreakerEvaluationResult",
    "DEFAULT_CANDIDATE_REGISTRY_PATH",
    "HardenedSharedMarginAccount",
    "LivePaperEngine",
    "PaperActionApproval",
    "PaperActionPermission",
    "PaperFeedbackExtractor",
    "PaperLedger",
    "PaperLedgerEntry",
    "PaperLedgerError",
    "PaperLifecycleTelemetry",
    "PaperObservation",
    "PaperQualificationPolicy",
    "PaperRoundTripResult",
    "PaperRuntime",
    "PaperRuntimeResult",
    "PaperSafetyDecision",
    "PaperSafetyEvidence",
    "ResolvedCandidateMetadata",
    "SqlitePaperLedger",
    "SqlitePaperLifecycle",
    "SqlitePaperObservations",
    "build_candidate_registry_manifest",
    "calculate_adverse_gap_fill",
    "compute_feedback_qualification_hash",
    "compute_registry_hash",
    "evaluate_paper_action_permission",
    "evaluate_paper_safety",
    "extract_paper_feedback",
    "mark_paper_position",
    "observe_paper_ledger",
    "paper_qualification_policy_content_hash",
    "publish_admitted_candidate",
    "publish_candidate_admission",
    "read_candidate_registry",
    "simulate_paper_round_trip",
    "validate_manifest_candidate_artifacts",
    "verify_candidate_manifest_entry",
    "verify_candidate_registry_manifest",
    "write_candidate_registry",
]
