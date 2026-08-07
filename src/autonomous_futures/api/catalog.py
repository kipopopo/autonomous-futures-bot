from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..data.bundle import DatasetBundle, read_dataset_bundle
from ..data.registry import DatasetRegistry, DatasetRegistryEntry, read_dataset_registry


class DatasetCatalogIntegrityError(ValueError):
    """Persisted registry/bundle state cannot be trusted by the API."""


@dataclass(frozen=True, slots=True)
class VerifiedDatasetCatalog:
    bundle: DatasetBundle
    registry: DatasetRegistry


def _entry_identity(entry: DatasetRegistryEntry) -> tuple[object, ...]:
    return (
        entry.kind,
        entry.symbols,
        entry.interval,
        entry.time_start,
        entry.time_end,
    )


def load_verified_dataset_catalog(
    *, bundle_path: Path, registry_path: Path
) -> VerifiedDatasetCatalog:
    try:
        registry = read_dataset_registry(registry_path)
        bundle = read_dataset_bundle(bundle_path)
    except (OSError, ValueError) as exc:
        raise DatasetCatalogIntegrityError from exc

    if bundle.registry_hash != registry.registry_hash:
        raise DatasetCatalogIntegrityError("bundle is not bound to the persisted registry")

    registry_entries = {_entry_identity(entry): entry for entry in registry.entries}
    for component in bundle.components:
        persisted = registry_entries.get(_entry_identity(component))
        if persisted is None or persisted != component:
            raise DatasetCatalogIntegrityError(
                "bundle component is not bound to the persisted registry"
            )

    return VerifiedDatasetCatalog(bundle=bundle, registry=registry)
