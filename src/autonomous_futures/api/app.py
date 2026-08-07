from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException

from ..data.bundle import DatasetBundle
from ..data.registry import DatasetRegistry
from ..domain.contracts import DomainModel
from .catalog import (
    DatasetCatalogIntegrityError,
    VerifiedDatasetCatalog,
    load_verified_dataset_catalog,
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


def _configured_path(environment_name: str, default: str) -> Path:
    return Path(os.environ.get(environment_name, default))


def create_app(*, bundle_path: Path | None = None, registry_path: Path | None = None) -> FastAPI:
    configured_bundle_path = bundle_path or _configured_path(
        "AFBOT_DATASET_BUNDLE_PATH", "data/dataset-bundle.json"
    )
    configured_registry_path = registry_path or _configured_path(
        "AFBOT_DATASET_REGISTRY_PATH", "data/dataset-registry.json"
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

    return app


app = create_app()


__all__ = [
    "BundleResponse",
    "HealthResponse",
    "RegistryResponse",
    "app",
    "create_app",
]
