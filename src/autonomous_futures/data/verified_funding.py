from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pandas as pd

from .bundle import DatasetBundle, find_bundle_component, read_dataset_bundle
from .derivatives_artifacts import (
    FUNDING_PRICE_PROVENANCE_COLUMNS,
    FUNDING_PRICE_SOURCE_MARK_OPEN,
    DerivativesArtifactManifest,
    read_derivatives_artifact_manifest,
    read_funding_artifact,
    read_mark_price_artifact,
)
from .parquet import DataQualityError
from .registry import DatasetRegistry, DatasetRegistryEntry, read_dataset_registry

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_COLUMNS = ("symbol", "funding_time", "funding_rate", "funding_mark_price")


@dataclass(frozen=True, slots=True)
class VerifiedFundingSlice:
    """Funding rows read from a manifest and artifact bound to a verified bundle."""

    symbol: str
    time_start: datetime
    time_end: datetime
    bundle_hash: str
    dataset_registry_hash: str
    manifest_hash: str
    artifact_sha256: str
    _events: pd.DataFrame = field(repr=False)

    def __post_init__(self) -> None:
        for value in (self.time_start, self.time_end):
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                raise DataQualityError("verified funding slice timestamps must be UTC")
        if self.time_start >= self.time_end:
            raise DataQualityError("verified funding slice must have a positive time range")
        if any(
            not _SHA256_PATTERN.fullmatch(value)
            for value in (
                self.bundle_hash,
                self.dataset_registry_hash,
                self.manifest_hash,
                self.artifact_sha256,
            )
        ):
            raise DataQualityError("verified funding slice requires exact SHA-256 bindings")
        missing = sorted(set(_REQUIRED_COLUMNS).difference(self._events.columns))
        if missing:
            raise DataQualityError("verified funding slice is missing required columns")
        provenance = set(FUNDING_PRICE_PROVENANCE_COLUMNS).intersection(self._events.columns)
        if provenance and provenance != set(FUNDING_PRICE_PROVENANCE_COLUMNS):
            raise DataQualityError("verified funding slice has incomplete price provenance")
        columns = (
            (*_REQUIRED_COLUMNS, *FUNDING_PRICE_PROVENANCE_COLUMNS)
            if provenance
            else _REQUIRED_COLUMNS
        )
        events = self._events.loc[:, columns].copy(deep=True).reset_index(drop=True)
        timestamps = pd.to_datetime(events["funding_time"], utc=True, errors="raise")
        if not events.empty:
            if not events["symbol"].eq(self.symbol).all():
                raise DataQualityError("verified funding slice symbol mismatch")
            if not (
                (timestamps >= pd.Timestamp(self.time_start))
                & (timestamps < pd.Timestamp(self.time_end))
            ).all():
                raise DataQualityError("verified funding slice event is outside its time range")
            if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
                raise DataQualityError("verified funding slice events must be ordered and unique")
        object.__setattr__(self, "time_start", self.time_start.astimezone(UTC))
        object.__setattr__(self, "time_end", self.time_end.astimezone(UTC))
        object.__setattr__(self, "_events", events)

    def copy_events(self) -> pd.DataFrame:
        return self._events.copy(deep=True)

    @property
    def events(self) -> pd.DataFrame:
        return self.copy_events()


def _resolve_artifact(root: Path, relative_ref: str) -> Path:
    reference = PurePosixPath(relative_ref)
    if reference.is_absolute() or ".." in reference.parts or "\\" in relative_ref:
        raise DataQualityError("funding artifact reference must remain within its root")
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*reference.parts).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise DataQualityError("funding artifact reference escapes its root")
    if not candidate.is_file():
        raise DataQualityError("funding artifact reference is unavailable")
    return candidate


def _verify_registry_binding(
    bundle: DatasetBundle, registry: DatasetRegistry, component: DatasetRegistryEntry
) -> None:
    if bundle.registry_hash != registry.registry_hash:
        raise DataQualityError("funding bundle is not bound to the persisted registry")
    if component not in registry.entries:
        raise DataQualityError("funding bundle component is not bound to the registry")


def _verify_manifest_binding(
    manifest: DerivativesArtifactManifest,
    *,
    component: DatasetRegistryEntry,
    symbol: str,
    time_start: datetime,
    time_end: datetime,
) -> None:
    if (
        component.kind != "funding_rate"
        or component.symbols != (symbol,)
        or component.interval is not None
        or component.content_hash != manifest.manifest_hash
        or component.time_start != manifest.time_start
        or component.time_end != manifest.time_end
        or manifest.kind != "funding_rate"
        or manifest.symbol != symbol
        or manifest.interval is not None
        or manifest.time_start > time_start
        or manifest.time_end < time_end
    ):
        raise DataQualityError("funding manifest does not cover the requested bundle slice")


def _verify_mark_price_fallback(
    events: pd.DataFrame,
    *,
    artifact_root: Path,
    bundle: DatasetBundle,
    registry: DatasetRegistry,
    symbol: str,
) -> None:
    if "funding_mark_price_source" not in events.columns:
        return
    fallback = events["funding_mark_price_source"].eq(FUNDING_PRICE_SOURCE_MARK_OPEN)
    if not fallback.any():
        return
    component = find_bundle_component(bundle, kind="mark_price", symbol=symbol, interval="5m")
    if component is None or any(
        value != component.content_hash
        for value in events.loc[fallback, "funding_mark_price_source_artifact_hash"]
    ):
        raise DataQualityError("funding fallback provenance is not bound to the mark-price bundle")
    _verify_registry_binding(bundle, registry, component)

    manifest_path = _resolve_artifact(artifact_root, component.artifact_ref)
    mark_manifest = read_derivatives_artifact_manifest(manifest_path)
    if (
        component.symbols != (symbol,)
        or component.content_hash != mark_manifest.manifest_hash
        or component.time_start != mark_manifest.time_start
        or component.time_end != mark_manifest.time_end
        or mark_manifest.kind != "mark_price"
        or mark_manifest.symbol != symbol
        or mark_manifest.interval != "5m"
    ):
        raise DataQualityError("mark-price manifest is not bound to the funding fallback source")
    mark_artifact_path = _resolve_artifact(artifact_root, mark_manifest.artifact_ref)
    read_derivatives_artifact_manifest(manifest_path, artifact_path=mark_artifact_path)
    mark_frame = read_mark_price_artifact(
        mark_artifact_path,
        symbol=symbol,
        interval="5m",
        time_start=mark_manifest.time_start,
        time_end=mark_manifest.time_end,
    )
    opens_by_time = {
        int(timestamp.value // 1_000_000): open_price
        for timestamp, open_price in mark_frame.loc[:, ["timestamp", "open"]].itertuples(
            index=False, name=None
        )
    }
    for funding_time, funding_mark_price in events.loc[
        fallback, ["funding_time", "funding_mark_price"]
    ].itertuples(index=False, name=None):
        timestamp_ms = int(pd.Timestamp(funding_time).value // 1_000_000)
        if opens_by_time.get(timestamp_ms) != funding_mark_price:
            raise DataQualityError(
                "funding fallback price does not match the exact mark-price candle open"
            )


def load_verified_funding_slice(
    *,
    artifact_root: Path,
    bundle_path: Path,
    registry_path: Path,
    symbol: str,
    time_start: datetime,
    time_end: datetime,
    bar_timestamps: tuple[datetime, ...],
    expected_bundle_hash: str | None = None,
    expected_registry_hash: str | None = None,
) -> VerifiedFundingSlice:
    """Load funding after verifying bundle, registry, manifest, bytes and window alignment."""
    if not symbol or symbol != symbol.upper():
        raise DataQualityError("funding symbol must be uppercase")
    for value in (time_start, time_end):
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise DataQualityError("funding slice range must be timezone-aware UTC")
    start = time_start.astimezone(UTC)
    end = time_end.astimezone(UTC)
    if start >= end:
        raise DataQualityError("funding slice range must be positive")
    if not bar_timestamps:
        raise DataQualityError("funding slice requires exact evaluation bar timestamps")
    if any(
        value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        for value in bar_timestamps
    ):
        raise DataQualityError("funding slice bar timestamps must be timezone-aware UTC")
    bars = tuple(value.astimezone(UTC) for value in bar_timestamps)
    if bars != tuple(sorted(set(bars))) or any(not start <= value < end for value in bars):
        raise DataQualityError("funding slice bars must be ordered within its range")

    try:
        registry = read_dataset_registry(registry_path)
        bundle = read_dataset_bundle(bundle_path)
        if expected_bundle_hash is not None and bundle.bundle_hash != expected_bundle_hash:
            raise DataQualityError("bundle hash does not match requested provenance")
        if expected_registry_hash is not None and registry.registry_hash != expected_registry_hash:
            raise DataQualityError("registry hash does not match requested provenance")
        component = find_bundle_component(bundle, kind="funding_rate", symbol=symbol)
        if component is None:
            raise DataQualityError("funding bundle component is unavailable")
        _verify_registry_binding(bundle, registry, component)
        if (
            component.time_start is None
            or component.time_end is None
            or component.time_start > start
            or component.time_end < end
        ):
            raise DataQualityError("funding registry component does not cover the requested range")
        manifest_path = _resolve_artifact(artifact_root, component.artifact_ref)
        manifest = read_derivatives_artifact_manifest(manifest_path)
        _verify_manifest_binding(
            manifest,
            component=component,
            symbol=symbol,
            time_start=start,
            time_end=end,
        )
        artifact_path = _resolve_artifact(artifact_root, manifest.artifact_ref)
        manifest = read_derivatives_artifact_manifest(manifest_path, artifact_path=artifact_path)
        source_events = read_funding_artifact(
            artifact_path,
            symbol=symbol,
            time_start=manifest.time_start,
            time_end=manifest.time_end,
        )
    except DataQualityError:
        raise
    except Exception as exc:
        raise DataQualityError("funding artifact integrity verification failed") from exc

    event_times = pd.to_datetime(source_events["funding_time"], utc=True)
    selected = source_events.loc[
        (event_times >= pd.Timestamp(start)) & (event_times < pd.Timestamp(end))
    ].reset_index(drop=True)
    _verify_mark_price_fallback(
        selected,
        artifact_root=artifact_root,
        bundle=bundle,
        registry=registry,
        symbol=symbol,
    )
    bar_set = set(bars)
    selected_times = tuple(
        pd.Timestamp(value).to_pydatetime() for value in selected["funding_time"]
    )
    if any(timestamp not in bar_set for timestamp in selected_times):
        raise DataQualityError("funding event does not align with an evaluation bar")
    return VerifiedFundingSlice(
        symbol=symbol,
        time_start=start,
        time_end=end,
        bundle_hash=bundle.bundle_hash,
        dataset_registry_hash=registry.registry_hash,
        manifest_hash=manifest.manifest_hash,
        artifact_sha256=manifest.artifact_sha256,
        _events=selected,
    )


__all__ = ["VerifiedFundingSlice", "load_verified_funding_slice"]
