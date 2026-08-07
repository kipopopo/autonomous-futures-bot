from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.data.registry import (
    DatasetRegistryEntry,
    build_dataset_registry,
    find_dataset_entry,
    read_dataset_registry,
    write_dataset_registry,
)
from autonomous_futures.domain.errors import DomainViolation

OBSERVED_AT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 8, 2, tzinfo=UTC)


def _entry(
    kind: str,
    *,
    symbols: tuple[str, ...] = ("BTCUSDT",),
    interval: str | None = "5m",
    content_hash: str = "a" * 64,
) -> DatasetRegistryEntry:
    return DatasetRegistryEntry(
        kind=kind,
        symbols=symbols,
        interval=interval,
        time_start=START if kind != "exchange_filters" else None,
        time_end=END if kind != "exchange_filters" else None,
        observed_at=OBSERVED_AT,
        schema_version="1",
        content_hash=content_hash,
        artifact_ref=f"artifacts/{kind}.json",
        source="binance_public_rest",
        endpoint_path={
            "kline": "/fapi/v1/klines",
            "funding_rate": "/fapi/v1/fundingRate",
            "mark_price": "/fapi/v1/markPriceKlines",
            "exchange_filters": "/fapi/v1/exchangeInfo",
        }[kind],
        provenance=("binance_public_rest", "unsigned", "closed_bar_policy"),
    )


def test_registry_sorts_entries_hashes_without_created_at_and_supports_exact_lookup() -> None:
    entries = (
        _entry("mark_price", content_hash="b" * 64),
        _entry("exchange_filters", interval=None, content_hash="c" * 64),
        _entry("kline", content_hash="a" * 64),
        _entry("funding_rate", interval=None, content_hash="d" * 64),
    )
    first = build_dataset_registry(entries, created_at=OBSERVED_AT)
    second = build_dataset_registry(
        tuple(reversed(entries)), created_at=OBSERVED_AT + timedelta(hours=1)
    )

    assert [item.kind for item in first.entries] == [
        "exchange_filters",
        "funding_rate",
        "kline",
        "mark_price",
    ]
    assert first.registry_hash == second.registry_hash
    assert (
        find_dataset_entry(
            first,
            kind="kline",
            symbols=("BTCUSDT",),
            interval="5m",
            time_start=START,
            time_end=END,
        )
        == first.entries[2]
    )
    assert (
        find_dataset_entry(first, kind="exchange_filters", symbols=("BTCUSDT",), interval=None)
        == first.entries[0]
    )
    assert find_dataset_entry(first, kind="kline", symbols=("ETHUSDT",), interval="5m") is None


def test_registry_rejects_duplicate_identity_and_invalid_kind_contracts() -> None:
    with pytest.raises(DataQualityError, match="duplicate registry entry"):
        build_dataset_registry(
            (_entry("kline"), _entry("kline", content_hash="b" * 64)),
            created_at=OBSERVED_AT,
        )

    with pytest.raises(ValidationError, match="interval"):
        DatasetRegistryEntry(**_entry("kline", interval=None).model_dump())
    invalid_range = _entry("exchange_filters", interval=None).model_copy(
        update={"time_start": START, "time_end": END}
    )
    with pytest.raises(ValidationError, match="time range"):
        DatasetRegistryEntry(**invalid_range.model_dump())


def test_registry_is_write_once_and_tamper_evident(tmp_path: Path) -> None:
    registry = build_dataset_registry(
        (_entry("kline"), _entry("exchange_filters", interval=None, content_hash="b" * 64)),
        created_at=OBSERVED_AT,
    )
    path = tmp_path / "dataset-registry.json"
    write_dataset_registry(path, registry)

    assert read_dataset_registry(path) == registry
    assert write_dataset_registry(path, registry) == registry

    conflicting = build_dataset_registry(
        (
            _entry("kline", content_hash="c" * 64),
            _entry("exchange_filters", interval=None, content_hash="b" * 64),
        ),
        created_at=OBSERVED_AT,
    )
    with pytest.raises(DomainViolation, match="immutable"):
        write_dataset_registry(path, conflicting)

    path.write_text(
        path.read_text(encoding="utf-8").replace("artifacts/kline.json", "artifacts/xline.json"),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_dataset_registry(path)
