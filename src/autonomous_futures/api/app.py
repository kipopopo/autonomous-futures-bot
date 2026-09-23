from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query

from ..data.bundle import DatasetBundle
from ..data.registry import DatasetKind, DatasetRegistry, DatasetRegistryEntry
from ..domain.contracts import DomainModel
from ..research.creator_artifacts import CreatorCandidateRegistry
from ..research.learner_artifacts import LearnerArtifact
from ..research.learner_metric_quality_qualification import (
    LearnerMetricQualityQualificationEvidence,
)
from ..research.learner_qualification import LearnerQualificationEvidence
from ..research.learner_quality_review import LearnerQualityReviewEvidence
from ..research.learner_runs import LearnerRun
from ..research.learner_training_evidence import LearnerTrainingEvidence
from ..research.qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    QualificationDecision,
    QualificationSource,
)
from .artifacts import (
    ArtifactInspection,
    ArtifactIntegrityError,
    inspect_dataset_artifacts,
)
from .canary import (
    CanaryAccountingResponse,
    CanaryAutoEvolutionResponse,
    CanaryAutonomousLifecycleResponse,
    CanaryBracketPositionsResponse,
    CanaryCalibrationResponse,
    CanaryEnsembleResponse,
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    CanaryExecutionGuardResponse,
    CanaryHawkesResponse,
    CanaryLiveMarketResponse,
    CanaryOrchestratorResponse,
    CanaryPaperExecutionResponse,
    CanaryPortfolioRebalancingResponse,
    CanaryRiskResponse,
    CanaryStrategyActivationResponse,
    CanaryStrategyMiningResponse,
    CanaryStressFaultInjectionResponse,
    CanarySummaryResponse,
    CanaryTestnetBridgeResponse,
    CanaryTestnetGatewayResponse,
    CandidatePromotionItem,
    CandidateSignalItem,
    LedgerReconciliationItem,
    VetoInterlockItem,
    load_verified_canary_accounting,
    load_verified_canary_auto_evolution,
    load_verified_canary_autonomous_lifecycle,
    load_verified_canary_bracket_positions,
    load_verified_canary_calibration,
    load_verified_canary_ensemble,
    load_verified_canary_execution_guard,
    load_verified_canary_hawkes,
    load_verified_canary_live_market,
    load_verified_canary_orchestrator,
    load_verified_canary_paper_execution,
    load_verified_canary_portfolio_rebalancing,
    load_verified_canary_risk,
    load_verified_canary_strategy_activation,
    load_verified_canary_strategy_mining,
    load_verified_canary_stress_fault_injection,
    load_verified_canary_summary,
    load_verified_canary_testnet_bridge,
    load_verified_canary_testnet_gateway,
)
from .catalog import (
    DatasetCatalogIntegrityError,
    VerifiedDatasetCatalog,
    load_verified_dataset_catalog,
)
from .creator import (
    CreatorCandidateRegistryIntegrityError,
    CreatorCandidateRegistryNotFoundError,
    load_verified_creator_candidate_registry,
)
from .learner import (
    LearnerArtifactNotFoundError,
    LearnerEvidenceIntegrityError,
    LearnerQualificationEvidenceIntegrityError,
    LearnerQualificationEvidenceNotFoundError,
    LearnerQualityReviewEvidenceIntegrityError,
    LearnerQualityReviewEvidenceNotFoundError,
    LearnerRunNotFoundError,
    LearnerTrainingEvidenceIntegrityError,
    LearnerTrainingEvidenceNotFoundError,
    VerifiedLearnerEvidence,
    load_verified_learner_artifact,
    load_verified_learner_qualification_evidence,
    load_verified_learner_quality_review_evidence,
    load_verified_learner_run,
    load_verified_learner_training_evidence,
)
from .metric_quality_qualification import (
    LearnerMetricQualityQualificationEvidenceIntegrityError,
    LearnerMetricQualityQualificationEvidenceNotFoundError,
    load_verified_metric_quality_qualification_evidence,
)
from .qualification import (
    CreatorQualificationArtifactIntegrityError,
    CreatorQualificationArtifactNotFoundError,
    load_verified_creator_candidate_qualification,
    load_verified_creator_candidate_qualifications,
)
from .query import (
    MAX_QUERY_ROWS,
    JSONScalar,
    QueryDataIntegrityError,
    QueryError,
    query_component_rows,
)
from .telemetry_ws import (
    TelemetryBroadcastManager,
    register_telemetry_websocket,
)


class HealthResponse(DomainModel):
    status: Literal["ok"] = "ok"
    service: Literal["autonomous-futures-data-api"] = "autonomous-futures-data-api"
    paper_safe: Literal[True] = True
    execution_authority: Literal[False] = False


class BundleResponse(DomainModel):
    verified: Literal[True] = True
    registry_hash: str
    bundle_hash: str
    component_count: int
    bundle: DatasetBundle


class RegistryResponse(DomainModel):
    verified: Literal[True] = True
    registry: DatasetRegistry


class CreatorRegistryResponse(DomainModel):
    verified: Literal[True] = True
    registry_hash: str
    candidate_count: int
    registry: CreatorCandidateRegistry


class CreatorQualificationSummary(DomainModel):
    candidate_id: str
    decision: QualificationDecision
    source: QualificationSource
    qualification_hash: str
    evaluator_run_id: str
    evaluator_version: str
    windows_evaluated: int
    qualification_policy_id: str | None
    evaluated_at: datetime
    promotion_state: Literal["unpromoted"]
    execution_authority: Literal[False]


class CreatorQualificationsResponse(DomainModel):
    verified: Literal[True] = True
    candidate_count: int
    qualification_count: int
    missing_candidate_ids: tuple[str, ...]
    qualifications: tuple[CreatorQualificationSummary, ...]


class CreatorQualificationResponse(DomainModel):
    verified: Literal[True] = True
    artifact: CreatorCandidateQualificationArtifact


class LearnerArtifactResponse(DomainModel):
    verified: Literal[True] = True
    artifact: LearnerArtifact


class LearnerRunResponse(DomainModel):
    verified: Literal[True] = True
    run: LearnerRun


class LearnerTrainingEvidenceResponse(DomainModel):
    verified: Literal[True] = True
    evidence: LearnerTrainingEvidence


class LearnerQualityReviewEvidenceResponse(DomainModel):
    verified: Literal[True] = True
    evidence: LearnerQualityReviewEvidence


class LearnerQualificationEvidenceResponse(DomainModel):
    verified: Literal[True] = True
    evidence: LearnerQualificationEvidence


class LearnerMetricQualityQualificationEvidenceResponse(DomainModel):
    verified: Literal[True] = True
    evidence: LearnerMetricQualityQualificationEvidence


class ComponentsResponse(DomainModel):
    verified: Literal[True] = True
    component_count: int
    components: tuple[ArtifactInspection, ...]


class RowsResponse(DomainModel):
    verified: Literal[True] = True
    kind: DatasetKind
    symbol: str
    interval: str | None
    start: datetime
    end: datetime
    row_count: int
    limit: int
    rows: tuple[dict[str, JSONScalar], ...]


def _configured_path(environment_name: str, default: str) -> Path:
    return Path(os.environ.get(environment_name, default))


def create_app(
    *,
    bundle_path: Path | None = None,
    registry_path: Path | None = None,
    artifact_root: Path | None = None,
    creator_candidate_registry_path: Path | None = None,
    creator_candidate_artifact_root: Path | None = None,
    qualification_artifact_root: Path | None = None,
    learner_artifact_path: Path | None = None,
    learner_model_root: Path | None = None,
    learner_run_path: Path | None = None,
    learner_training_evidence_path: Path | None = None,
    learner_training_artifact_root: Path | None = None,
    learner_quality_review_evidence_path: Path | None = None,
    learner_qualification_evidence_path: Path | None = None,
    learner_qualification_policy_path: Path | None = None,
    learner_metric_evaluation_path: Path | None = None,
    learner_metric_quality_review_evidence_path: Path | None = None,
    learner_metric_quality_decision_path: Path | None = None,
    learner_metric_quality_policy_path: Path | None = None,
    learner_metric_quality_qualification_evidence_path: Path | None = None,
    learner_metric_quality_qualification_policy_path: Path | None = None,
    canary_phase_dir: Path | None = None,
    telemetry_broadcaster: TelemetryBroadcastManager | None = None,
    frontend_dist_path: Path | None = None,
) -> FastAPI:
    configured_bundle_path = bundle_path or _configured_path(
        "AFBOT_DATASET_BUNDLE_PATH", "data/dataset-bundle.json"
    )
    configured_registry_path = registry_path or _configured_path(
        "AFBOT_DATASET_REGISTRY_PATH", "data/dataset-registry.json"
    )
    configured_artifact_root = artifact_root or _configured_path(
        "AFBOT_DATASET_ARTIFACT_ROOT", "data"
    )
    configured_creator_registry_path = creator_candidate_registry_path or _configured_path(
        "AFBOT_CREATOR_CANDIDATE_REGISTRY_PATH", "data/creator-candidate-registry.json"
    )
    configured_creator_artifact_root = creator_candidate_artifact_root or _configured_path(
        "AFBOT_CREATOR_CANDIDATE_ARTIFACT_ROOT", "data"
    )
    configured_qualification_artifact_root = qualification_artifact_root or _configured_path(
        "AFBOT_QUALIFICATION_ARTIFACT_ROOT", "data/qualifications"
    )
    configured_learner_artifact_path = learner_artifact_path or _configured_path(
        "AFBOT_LEARNER_ARTIFACT_PATH", "data/learner-artifact.json"
    )
    configured_learner_model_root = learner_model_root or _configured_path(
        "AFBOT_LEARNER_MODEL_ROOT", "data/models"
    )
    configured_learner_run_path = learner_run_path or _configured_path(
        "AFBOT_LEARNER_RUN_PATH", "data/learner-run.json"
    )
    configured_learner_training_evidence_path = learner_training_evidence_path or _configured_path(
        "AFBOT_LEARNER_TRAINING_EVIDENCE_PATH", "data/learner-training-evidence.json"
    )
    configured_learner_training_artifact_root = learner_training_artifact_root or _configured_path(
        "AFBOT_LEARNER_TRAINING_ARTIFACT_ROOT", "data"
    )
    configured_learner_quality_review_evidence_path = (
        learner_quality_review_evidence_path
        or _configured_path(
            "AFBOT_LEARNER_QUALITY_REVIEW_EVIDENCE_PATH",
            "data/learner-quality-review-evidence.json",
        )
    )
    configured_learner_qualification_evidence_path = (
        learner_qualification_evidence_path
        or _configured_path(
            "AFBOT_LEARNER_QUALIFICATION_EVIDENCE_PATH",
            "data/learner-qualification-evidence.json",
        )
    )
    configured_learner_qualification_policy_path = (
        learner_qualification_policy_path
        or _configured_path(
            "AFBOT_LEARNER_QUALIFICATION_POLICY_PATH",
            "data/learner-qualification-policy.json",
        )
    )
    configured_learner_metric_evaluation_path = learner_metric_evaluation_path or _configured_path(
        "AFBOT_LEARNER_METRIC_EVALUATION_PATH", "data/learner-metric-evaluation.json"
    )
    configured_learner_metric_quality_review_evidence_path = (
        learner_metric_quality_review_evidence_path
        or _configured_path(
            "AFBOT_LEARNER_METRIC_QUALITY_REVIEW_EVIDENCE_PATH",
            "data/learner-metric-quality-review-evidence.json",
        )
    )
    configured_learner_metric_quality_decision_path = (
        learner_metric_quality_decision_path
        or _configured_path(
            "AFBOT_LEARNER_METRIC_QUALITY_DECISION_PATH",
            "data/learner-metric-quality-decision.json",
        )
    )
    configured_learner_metric_quality_policy_path = (
        learner_metric_quality_policy_path
        or _configured_path(
            "AFBOT_LEARNER_METRIC_QUALITY_POLICY_PATH",
            "data/learner-metric-quality-policy.json",
        )
    )
    configured_learner_metric_quality_qualification_evidence_path = (
        learner_metric_quality_qualification_evidence_path
        or _configured_path(
            "AFBOT_LEARNER_METRIC_QUALITY_QUALIFICATION_EVIDENCE_PATH",
            "data/learner-metric-quality-qualification-evidence.json",
        )
    )
    configured_learner_metric_quality_qualification_policy_path = (
        learner_metric_quality_qualification_policy_path
        or _configured_path(
            "AFBOT_LEARNER_METRIC_QUALITY_QUALIFICATION_POLICY_PATH",
            "data/learner-metric-quality-qualification-policy.json",
        )
    )
    configured_canary_phase_dir = canary_phase_dir or _configured_path(
        "AFBOT_CANARY_PHASE_DIR", "artifacts/research/phase291"
    )

    app = FastAPI(
        title="Autonomous Futures Data API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    def verified_catalog() -> VerifiedDatasetCatalog:
        try:
            return load_verified_dataset_catalog(
                bundle_path=configured_bundle_path,
                registry_path=configured_registry_path,
            )
        except DatasetCatalogIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="dataset catalog integrity verification failed",
            ) from exc

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    def verified_learner_artifact() -> VerifiedLearnerEvidence:
        try:
            return load_verified_learner_artifact(
                artifact_path=configured_learner_artifact_path,
                model_root=configured_learner_model_root,
                bundle_path=configured_bundle_path,
                registry_path=configured_registry_path,
                candidate_registry_path=configured_creator_registry_path,
                candidate_artifact_root=configured_creator_artifact_root,
            )
        except LearnerArtifactNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="learner artifact unavailable",
            ) from exc
        except LearnerEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="learner artifact integrity verification failed",
            ) from exc

    @app.get("/api/v1/learner/artifact", response_model=LearnerArtifactResponse)
    def learner_artifact() -> LearnerArtifactResponse:
        verified = verified_learner_artifact()
        return LearnerArtifactResponse(artifact=verified.artifact)

    @app.get("/api/v1/learner/run", response_model=LearnerRunResponse)
    def learner_run() -> LearnerRunResponse:
        if not configured_learner_run_path.exists():
            raise HTTPException(status_code=404, detail="learner run unavailable")
        verified_artifact = verified_learner_artifact()
        try:
            run = load_verified_learner_run(
                run_path=configured_learner_run_path,
                learner_evidence=verified_artifact,
            )
        except LearnerRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="learner run unavailable") from exc
        except LearnerEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="learner run integrity verification failed",
            ) from exc
        return LearnerRunResponse(run=run)

    @app.get(
        "/api/v1/learner/training-evidence",
        response_model=LearnerTrainingEvidenceResponse,
    )
    def learner_training_evidence() -> LearnerTrainingEvidenceResponse:
        if not configured_learner_training_evidence_path.exists():
            raise HTTPException(
                status_code=404,
                detail="learner training evidence unavailable",
            )
        try:
            verified_artifact = verified_learner_artifact()
            evidence = load_verified_learner_training_evidence(
                evidence_path=configured_learner_training_evidence_path,
                run_root=configured_learner_run_path.parent,
                artifact_root=configured_learner_training_artifact_root,
                model_root=configured_learner_model_root,
                candidate=verified_artifact.candidate,
            )
        except LearnerTrainingEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="learner training evidence unavailable",
            ) from exc
        except LearnerTrainingEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="learner training evidence integrity verification failed",
            ) from exc
        except HTTPException as exc:
            raise HTTPException(
                status_code=404 if exc.status_code == 404 else 503,
                detail=(
                    "learner training evidence unavailable"
                    if exc.status_code == 404
                    else "learner training evidence integrity verification failed"
                ),
            ) from exc
        return LearnerTrainingEvidenceResponse(evidence=evidence)

    @app.get(
        "/api/v1/learner/quality-review",
        response_model=LearnerQualityReviewEvidenceResponse,
    )
    def learner_quality_review() -> LearnerQualityReviewEvidenceResponse:
        if not configured_learner_quality_review_evidence_path.exists():
            raise HTTPException(
                status_code=404,
                detail="learner quality review unavailable",
            )
        try:
            verified_artifact = verified_learner_artifact()
            evidence = load_verified_learner_quality_review_evidence(
                evidence_path=configured_learner_quality_review_evidence_path,
                training_evidence_path=configured_learner_training_evidence_path,
                run_root=configured_learner_run_path.parent,
                artifact_root=configured_learner_training_artifact_root,
                model_root=configured_learner_model_root,
                candidate=verified_artifact.candidate,
            )
        except LearnerQualityReviewEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="learner quality review unavailable",
            ) from exc
        except LearnerQualityReviewEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="learner quality review integrity verification failed",
            ) from exc
        except HTTPException as exc:
            raise HTTPException(
                status_code=404 if exc.status_code == 404 else 503,
                detail=(
                    "learner quality review unavailable"
                    if exc.status_code == 404
                    else "learner quality review integrity verification failed"
                ),
            ) from exc
        return LearnerQualityReviewEvidenceResponse(evidence=evidence)

    @app.get(
        "/api/v1/learner/qualification",
        response_model=LearnerQualificationEvidenceResponse,
    )
    def learner_qualification() -> LearnerQualificationEvidenceResponse:
        if not configured_learner_qualification_evidence_path.exists():
            raise HTTPException(
                status_code=404,
                detail="learner qualification unavailable",
            )
        try:
            verified_artifact = verified_learner_artifact()
            evidence = load_verified_learner_qualification_evidence(
                evidence_path=configured_learner_qualification_evidence_path,
                policy_path=configured_learner_qualification_policy_path,
                quality_review_path=configured_learner_quality_review_evidence_path,
                training_evidence_path=configured_learner_training_evidence_path,
                run_root=configured_learner_run_path.parent,
                artifact_root=configured_learner_training_artifact_root,
                model_root=configured_learner_model_root,
                candidate=verified_artifact.candidate,
            )
        except LearnerQualificationEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="learner qualification unavailable",
            ) from exc
        except LearnerQualificationEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="learner qualification integrity verification failed",
            ) from exc
        except HTTPException as exc:
            raise HTTPException(
                status_code=404 if exc.status_code == 404 else 503,
                detail=(
                    "learner qualification unavailable"
                    if exc.status_code == 404
                    else "learner qualification integrity verification failed"
                ),
            ) from exc
        return LearnerQualificationEvidenceResponse(evidence=evidence)

    @app.get(
        "/api/v1/learner/metric-quality-qualification",
        response_model=LearnerMetricQualityQualificationEvidenceResponse,
    )
    def learner_metric_quality_qualification() -> LearnerMetricQualityQualificationEvidenceResponse:
        if not configured_learner_metric_quality_qualification_evidence_path.exists():
            raise HTTPException(
                status_code=404,
                detail="learner metric-quality qualification evidence unavailable",
            )
        try:
            verified_artifact = verified_learner_artifact()
            evidence = load_verified_metric_quality_qualification_evidence(
                qualification_evidence_path=(
                    configured_learner_metric_quality_qualification_evidence_path
                ),
                decision_path=configured_learner_metric_quality_decision_path,
                review_path=configured_learner_metric_quality_review_evidence_path,
                metric_evaluation_path=configured_learner_metric_evaluation_path,
                source_policy_path=configured_learner_metric_quality_policy_path,
                qualification_policy_path=(
                    configured_learner_metric_quality_qualification_policy_path
                ),
                learner=verified_artifact.artifact,
                candidate=verified_artifact.candidate,
            )
        except LearnerMetricQualityQualificationEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="learner metric-quality qualification evidence unavailable",
            ) from exc
        except LearnerMetricQualityQualificationEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "learner metric-quality qualification evidence integrity verification failed"
                ),
            ) from exc
        except HTTPException as exc:
            raise HTTPException(
                status_code=404 if exc.status_code == 404 else 503,
                detail=(
                    "learner metric-quality qualification evidence unavailable"
                    if exc.status_code == 404
                    else (
                        "learner metric-quality qualification evidence integrity "
                        "verification failed"
                    )
                ),
            ) from exc
        return LearnerMetricQualityQualificationEvidenceResponse(evidence=evidence)

    @app.get("/api/v1/dataset/bundle", response_model=BundleResponse)
    def dataset_bundle() -> BundleResponse:
        catalog = verified_catalog()
        return BundleResponse(
            registry_hash=catalog.registry.registry_hash,
            bundle_hash=catalog.bundle.bundle_hash,
            component_count=len(catalog.bundle.components),
            bundle=catalog.bundle,
        )

    @app.get("/api/v1/dataset/registry", response_model=RegistryResponse)
    def dataset_registry() -> RegistryResponse:
        catalog = verified_catalog()
        return RegistryResponse(registry=catalog.registry)

    @app.get("/api/v1/creator/registry", response_model=CreatorRegistryResponse)
    def creator_registry() -> CreatorRegistryResponse:
        try:
            verified = load_verified_creator_candidate_registry(
                registry_path=configured_creator_registry_path,
                artifact_root=configured_creator_artifact_root,
            )
        except CreatorCandidateRegistryNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="creator candidate registry unavailable",
            ) from exc
        except CreatorCandidateRegistryIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="creator candidate registry integrity verification failed",
            ) from exc
        return CreatorRegistryResponse(
            registry_hash=verified.registry.registry_hash,
            candidate_count=len(verified.registry.entries),
            registry=verified.registry,
        )

    @app.get(
        "/api/v1/creator/qualifications",
        response_model=CreatorQualificationsResponse,
    )
    def creator_qualifications() -> CreatorQualificationsResponse:
        try:
            verified = load_verified_creator_candidate_qualifications(
                registry_path=configured_creator_registry_path,
                candidate_artifact_root=configured_creator_artifact_root,
                qualification_root=configured_qualification_artifact_root,
            )
        except CreatorCandidateRegistryNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="creator candidate registry unavailable",
            ) from exc
        except CreatorCandidateRegistryIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="creator candidate registry integrity verification failed",
            ) from exc
        except CreatorQualificationArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="creator qualification artifact integrity verification failed",
            ) from exc
        summaries = tuple(
            CreatorQualificationSummary(
                candidate_id=item.qualification.candidate_id,
                decision=item.qualification.decision,
                source=item.qualification.source,
                qualification_hash=item.qualification.qualification_hash,
                evaluator_run_id=item.qualification.evaluator_run_id,
                evaluator_version=item.qualification.evaluator_version,
                windows_evaluated=item.qualification.windows_evaluated,
                qualification_policy_id=item.qualification.qualification_policy_id,
                evaluated_at=item.qualification.evaluated_at,
                promotion_state=item.qualification.promotion_state,
                execution_authority=item.qualification.execution_authority,
            )
            for item in verified.qualifications
        )
        return CreatorQualificationsResponse(
            candidate_count=len(verified.registry.entries),
            qualification_count=len(summaries),
            missing_candidate_ids=verified.missing_candidate_ids,
            qualifications=summaries,
        )

    @app.get(
        "/api/v1/creator/qualifications/{candidate_id}",
        response_model=CreatorQualificationResponse,
    )
    def creator_qualification(candidate_id: str) -> CreatorQualificationResponse:
        try:
            verified = load_verified_creator_candidate_qualification(
                registry_path=configured_creator_registry_path,
                candidate_artifact_root=configured_creator_artifact_root,
                qualification_root=configured_qualification_artifact_root,
                candidate_id=candidate_id,
            )
        except CreatorCandidateRegistryNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="creator candidate registry unavailable",
            ) from exc
        except CreatorCandidateRegistryIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="creator candidate registry integrity verification failed",
            ) from exc
        except CreatorQualificationArtifactNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="creator qualification artifact unavailable",
            ) from exc
        except CreatorQualificationArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="creator qualification artifact integrity verification failed",
            ) from exc
        return CreatorQualificationResponse(artifact=verified.qualification)

    @app.get("/api/v1/dataset/components", response_model=ComponentsResponse)
    def dataset_components() -> ComponentsResponse:
        catalog = verified_catalog()
        try:
            components = inspect_dataset_artifacts(configured_artifact_root, catalog)
        except ArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="dataset artifact integrity verification failed",
            ) from exc
        return ComponentsResponse(component_count=len(components), components=components)

    @app.get("/api/v1/dataset/rows", response_model=RowsResponse)
    def dataset_rows(
        *,
        kind: Literal["kline", "funding_rate", "mark_price"],
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_QUERY_ROWS)] = 100,
    ) -> RowsResponse:
        if not symbol or symbol != symbol.upper():
            raise HTTPException(status_code=422, detail="symbol must be uppercase")
        if kind == "funding_rate" and interval is not None:
            raise HTTPException(status_code=422, detail="funding_rate interval must be null")
        if kind != "funding_rate" and interval not in {"5m", "15m"}:
            raise HTTPException(status_code=422, detail="kline and mark_price require interval")

        catalog = verified_catalog()
        try:
            components = inspect_dataset_artifacts(configured_artifact_root, catalog)
        except ArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="dataset artifact integrity verification failed",
            ) from exc

        selected: tuple[DatasetRegistryEntry, ArtifactInspection] | None = None
        for entry, inspection in zip(catalog.bundle.components, components, strict=True):
            if entry.kind == kind and entry.symbols == (symbol,) and entry.interval == interval:
                selected = (entry, inspection)
                break
        if selected is None:
            raise HTTPException(status_code=404, detail="dataset component not found")

        entry, inspection = selected
        try:
            rows = query_component_rows(
                configured_artifact_root,
                entry,
                inspection,
                start=start,
                end=end,
                limit=limit,
            )
        except QueryDataIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="dataset query integrity verification failed",
            ) from exc
        except QueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return RowsResponse(
            kind=entry.kind,
            symbol=symbol,
            interval=entry.interval,
            start=start,
            end=end,
            row_count=len(rows),
            limit=limit,
            rows=rows,
        )

    @app.get("/api/v1/canary/summary", response_model=CanarySummaryResponse)
    def canary_summary() -> CanarySummaryResponse:
        try:
            return load_verified_canary_summary(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="canary evidence unavailable") from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evidence integrity verification failed",
            ) from exc

    @app.get("/api/v1/canary/hawkes", response_model=CanaryHawkesResponse)
    def canary_hawkes() -> CanaryHawkesResponse:
        try:
            return load_verified_canary_hawkes(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="canary evidence unavailable") from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evidence integrity verification failed",
            ) from exc

    @app.get("/api/v1/canary/risk", response_model=CanaryRiskResponse)
    def canary_risk() -> CanaryRiskResponse:
        try:
            return load_verified_canary_risk(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="canary evidence unavailable") from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evidence integrity verification failed",
            ) from exc

    @app.get("/api/v1/canary/accounting", response_model=CanaryAccountingResponse)
    def canary_accounting() -> CanaryAccountingResponse:
        try:
            return load_verified_canary_accounting(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="canary evidence unavailable") from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evidence integrity verification failed",
            ) from exc

    @app.get("/api/v1/canary/live-market", response_model=CanaryLiveMarketResponse)
    def canary_live_market() -> CanaryLiveMarketResponse:
        try:
            return load_verified_canary_live_market(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="canary evidence unavailable") from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evidence integrity verification failed",
            ) from exc

    # Phase 294: Live Paper-Safe Execution Engine & Zero-Drift Matching Simulator
    @app.get("/api/v1/canary/paper-execution", response_model=CanaryPaperExecutionResponse)
    def canary_paper_execution() -> CanaryPaperExecutionResponse:
        try:
            return load_verified_canary_paper_execution(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="canary paper execution evidence unavailable"
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary paper execution integrity verification failed",
            ) from exc

    # Phase 295: Live Strategy Activation & Walk-Forward OOS Promotion Gates
    @app.get(
        "/api/v1/canary/strategy-activation",
        response_model=CanaryStrategyActivationResponse,
    )
    def canary_strategy_activation() -> CanaryStrategyActivationResponse:
        try:
            return load_verified_canary_strategy_activation(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary strategy activation evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary strategy activation integrity verification failed",
            ) from exc

    # Phase 296: Full Autonomous Lifecycle Orchestration & Multi-Session Longevity
    @app.get(
        "/api/v1/canary/autonomous-lifecycle",
        response_model=CanaryAutonomousLifecycleResponse,
    )
    def canary_autonomous_lifecycle() -> CanaryAutonomousLifecycleResponse:
        try:
            return load_verified_canary_autonomous_lifecycle(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary autonomous lifecycle evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary autonomous lifecycle integrity verification failed",
            ) from exc

    # Phase 297: Extreme Market Stress, Flash Crash Simulation & Fault Injection Resilience
    @app.get(
        "/api/v1/canary/stress-fault-injection",
        response_model=CanaryStressFaultInjectionResponse,
    )
    def canary_stress_fault_injection() -> CanaryStressFaultInjectionResponse:
        try:
            return load_verified_canary_stress_fault_injection(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary stress fault injection evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary stress fault injection integrity verification failed",
            ) from exc

    # Phase 298: Dynamic Strategy Mining, Auto-Evolution & Microstructure Mutation Engine
    @app.get(
        "/api/v1/canary/strategy-mining",
        response_model=CanaryStrategyMiningResponse,
    )
    def canary_strategy_mining() -> CanaryStrategyMiningResponse:
        try:
            return load_verified_canary_strategy_mining(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary strategy mining evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary strategy mining integrity verification failed",
            ) from exc

    # Phase 299: Dynamic Multi-Asset Risk Orchestration & Portfolio Rebalancing Engine
    @app.get(
        "/api/v1/canary/portfolio-rebalancing",
        response_model=CanaryPortfolioRebalancingResponse,
    )
    def canary_portfolio_rebalancing() -> CanaryPortfolioRebalancingResponse:
        try:
            return load_verified_canary_portfolio_rebalancing(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary portfolio rebalancing evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary portfolio rebalancing integrity verification failed",
            ) from exc

    # Phase 300: Testnet Exchange Connectivity & Multi-Sig Order Gateway
    @app.get(
        "/api/v1/canary/testnet-gateway",
        response_model=CanaryTestnetGatewayResponse,
    )
    def canary_testnet_gateway() -> CanaryTestnetGatewayResponse:
        try:
            return load_verified_canary_testnet_gateway(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary testnet gateway evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary testnet gateway integrity verification failed",
            ) from exc

    # Phase 301: Live User Data Stream Ingress, Dynamic Position & Bracket Order Management
    @app.get(
        "/api/v1/canary/bracket-positions",
        response_model=CanaryBracketPositionsResponse,
    )
    def canary_bracket_positions() -> CanaryBracketPositionsResponse:
        try:
            return load_verified_canary_bracket_positions(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary bracket positions evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary bracket positions integrity verification failed",
            ) from exc

    # Phase 302: Real-Time Toxic Flow Defense, Adverse Selection Guard
    # & Dynamic Microstructure Slippage Attribution
    @app.get(
        "/api/v1/canary/execution-guard",
        response_model=CanaryExecutionGuardResponse,
    )
    def canary_execution_guard() -> CanaryExecutionGuardResponse:
        try:
            return load_verified_canary_execution_guard(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary execution guard evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary execution guard integrity verification failed",
            ) from exc

    # Phase 303: Autonomous End-to-End Closed-Loop Paper Trading Orchestrator
    # & Shadow Execution Engine
    @app.get(
        "/api/v1/canary/orchestrator",
        response_model=CanaryOrchestratorResponse,
    )
    def canary_orchestrator() -> CanaryOrchestratorResponse:
        try:
            return load_verified_canary_orchestrator(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary orchestrator evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary orchestrator integrity verification failed",
            ) from exc

    # Phase 304: Autonomous Self-Calibrating Parameter Adaptation
    # & Online Regime Learning Engine
    @app.get(
        "/api/v1/canary/calibration",
        response_model=CanaryCalibrationResponse,
    )
    def canary_calibration() -> CanaryCalibrationResponse:
        try:
            return load_verified_canary_calibration(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary calibration evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary calibration integrity verification failed",
            ) from exc

    # Phase 305: Autonomous Multi-Horizon Alpha Ensemble & Meta-Policy Blending Engine
    @app.get(
        "/api/v1/canary/ensemble",
        response_model=CanaryEnsembleResponse,
    )
    def canary_ensemble() -> CanaryEnsembleResponse:
        try:
            return load_verified_canary_ensemble(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary ensemble evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary ensemble integrity verification failed",
            ) from exc

    # Phase 306: Continuous Self-Learning Loop, Strategy Autopsy & Auto-Evolution Daemon
    @app.get(
        "/api/v1/canary/evolution",
        response_model=CanaryAutoEvolutionResponse,
    )
    def canary_evolution() -> CanaryAutoEvolutionResponse:
        try:
            return load_verified_canary_auto_evolution(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary evolution evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evolution integrity verification failed",
            ) from exc

    # Phase 307: Binance Futures Testnet Live API Integration & Order Dispatch Bridge
    @app.get(
        "/api/v1/canary/testnet-bridge",
        response_model=CanaryTestnetBridgeResponse,
    )
    def canary_testnet_bridge() -> CanaryTestnetBridgeResponse:
        try:
            return load_verified_canary_testnet_bridge(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary testnet bridge evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary testnet bridge integrity verification failed",
            ) from exc

    # Phase 293: Real-Time Telemetry Streaming & WebSocket Push
    register_telemetry_websocket(app, broadcaster=telemetry_broadcaster)

    # Serve production frontend single-page application if dist exists
    default_frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    configured_frontend_dist = frontend_dist_path or Path(
        os.environ.get("AFBOT_FRONTEND_DIST_PATH", str(default_frontend_dist))
    )
    if configured_frontend_dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount(
            "/",
            StaticFiles(directory=str(configured_frontend_dist), html=True),
            name="frontend",
        )

    return app


app = create_app()


__all__ = [
    "BundleResponse",
    "CanaryAccountingResponse",
    "CanaryAutonomousLifecycleResponse",
    "CanaryBracketPositionsResponse",
    "CanaryCalibrationResponse",
    "CanaryExecutionGuardResponse",
    "CanaryHawkesResponse",
    "CanaryLiveMarketResponse",
    "CanaryOrchestratorResponse",
    "CanaryPaperExecutionResponse",
    "CanaryRiskResponse",
    "CanaryStrategyActivationResponse",
    "CanaryStrategyMiningResponse",
    "CanaryStressFaultInjectionResponse",
    "CanarySummaryResponse",
    "CanaryTestnetGatewayResponse",
    "CandidatePromotionItem",
    "CandidateSignalItem",
    "ComponentsResponse",
    "CreatorRegistryResponse",
    "CreatorQualificationResponse",
    "CreatorQualificationSummary",
    "CreatorQualificationsResponse",
    "HealthResponse",
    "LearnerArtifactResponse",
    "LearnerMetricQualityQualificationEvidenceResponse",
    "LearnerRunResponse",
    "LearnerQualificationEvidenceResponse",
    "LearnerTrainingEvidenceResponse",
    "LedgerReconciliationItem",
    "RegistryResponse",
    "RowsResponse",
    "TelemetryBroadcastManager",
    "VetoInterlockItem",
    "app",
    "create_app",
    "register_telemetry_websocket",
]
