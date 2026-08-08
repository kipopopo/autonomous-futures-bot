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

    return app


app = create_app()


__all__ = [
    "BundleResponse",
    "ComponentsResponse",
    "CreatorRegistryResponse",
    "CreatorQualificationResponse",
    "CreatorQualificationSummary",
    "CreatorQualificationsResponse",
    "HealthResponse",
    "RegistryResponse",
    "RowsResponse",
    "app",
    "create_app",
]
