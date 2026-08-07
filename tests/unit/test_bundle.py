from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autonomous_futures.data.bundle import (
    DatasetBundle,
    build_dataset_bundle,
    context_bar_is_usable,
    find_bundle_component,
    read_dataset_bundle,
    write_dataset_bundle,
)
from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.data.registry import DatasetRegistryEntry, build_dataset_registry
from autonomous_futures.domain.errors import DomainViolation

START = datetime(2026, 8, 7, tzinfo=UTC)
END = START + timedelta(hours=1)
OBSERVED = datetime(2026, 8, 7, 12, tzinfo=UTC)
SYMBOLS = ("BTCUSDT", "ETHUSDT")


def test_context_bar_is_unusable_until_its_close_boundary() -> None:
    context_open = START
    assert not context_bar_is_usable(
        context_open, primary_timestamp=START + timedelta(minutes=14, seconds=59)
    )
    assert context_bar_is_usable(context_open, primary_timestamp=START + timedelta(minutes=15))


def _entry(
    kind: str,
    symbol_set: tuple[str, ...],
    *,
    symbol: str | None = None,
    interval: str | None = "5m",
    time_start: datetime | None = START,
    time_end: datetime | None = END,
    content_hash: str = "a" * 64,
) -> DatasetRegistryEntry:
    endpoint = {
        "kline": "/fapi/v1/klines",
        "funding_rate": "/fapi/v1/fundingRate",
        "mark_price": "/fapi/v1/markPriceKlines",
        "exchange_filters": "/fapi/v1/exchangeInfo",
    }[kind]
    if kind == "funding_rate":
        interval = None
    if kind == "exchange_filters":
        interval = None
        time_start = None
        time_end = None
    return DatasetRegistryEntry(
        kind=kind,
        symbols=symbol_set,
        interval=interval,
        time_start=time_start,
        time_end=time_end,
        observed_at=OBSERVED,
        schema_version=f"{kind}-v1",
        content_hash=content_hash,
        artifact_ref=f"artifacts/{kind}-{symbol or 'universe'}.json",
        endpoint_path=endpoint,
        provenance=("binance_public_rest", "unsigned", "bundle_fixture"),
    )


def _complete_registry() -> object:
    entries: list[DatasetRegistryEntry] = []
    for index, symbol in enumerate(SYMBOLS):
        content_hash = f"{index + 1:x}" * 64
        entries.extend(
            (
                _entry(
                    "kline",
                    (symbol,),
                    symbol=symbol,
                    time_end=END - timedelta(minutes=5),
                    content_hash=content_hash,
                ),
                _entry(
                    "kline",
                    (symbol,),
                    symbol=symbol,
                    interval="15m",
                    time_start=START - timedelta(minutes=15),
                    time_end=END - timedelta(minutes=15),
                    content_hash=f"{index + 7:x}" * 64,
                ),
                _entry("mark_price", (symbol,), symbol=symbol, content_hash=f"{index + 3:x}" * 64),
                _entry(
                    "funding_rate",
                    (symbol,),
                    symbol=symbol,
                    time_start=START - timedelta(hours=8),
                    time_end=END + timedelta(hours=8),
                    content_hash=f"{index + 5:x}" * 64,
                ),
            )
        )
    entries.append(
        _entry(
            "exchange_filters",
            SYMBOLS,
            content_hash="f" * 64,
        )
    )
    return build_dataset_registry(entries, created_at=OBSERVED)


def test_bundle_requires_complete_universe_and_binds_registry_hash() -> None:
    registry = _complete_registry()
    bundle = build_dataset_bundle(
        registry,
        symbols=SYMBOLS,
        time_start=START,
        time_end=END,
        created_at=OBSERVED,
    )

    assert isinstance(bundle, DatasetBundle)
    assert bundle.registry_hash == registry.registry_hash
    assert bundle.symbols == SYMBOLS
    assert len(bundle.components) == 9
    assert {component.kind for component in bundle.components} == {
        "kline",
        "mark_price",
        "funding_rate",
        "exchange_filters",
    }
    assert find_bundle_component(bundle, kind="mark_price", symbol="ETHUSDT") is not None
    context = find_bundle_component(bundle, kind="kline", symbol="ETHUSDT", interval="15m")
    assert context is not None
    assert context.interval == "15m"
    assert bundle.bundle_hash != "0" * 64


def test_bundle_rejects_missing_component_and_insufficient_funding_coverage() -> None:
    complete = _complete_registry()
    without_mark = tuple(
        entry
        for entry in complete.entries
        if not (entry.kind == "mark_price" and entry.symbols == ("ETHUSDT",))
    )
    incomplete_registry = build_dataset_registry(without_mark, created_at=OBSERVED)
    with pytest.raises(DataQualityError, match="mark_price.*ETHUSDT"):
        build_dataset_bundle(
            incomplete_registry,
            symbols=SYMBOLS,
            time_start=START,
            time_end=END,
            created_at=OBSERVED,
        )

    insufficient = tuple(
        entry.model_copy(update={"time_start": START, "time_end": END - timedelta(minutes=1)})
        if entry.kind == "funding_rate" and entry.symbols == ("BTCUSDT",)
        else entry
        for entry in complete.entries
    )
    with pytest.raises(DataQualityError, match="funding_rate coverage.*BTCUSDT"):
        build_dataset_bundle(
            build_dataset_registry(insufficient, created_at=OBSERVED),
            symbols=SYMBOLS,
            time_start=START,
            time_end=END,
            created_at=OBSERVED,
        )


def test_bundle_rejects_missing_context_component() -> None:
    entries = tuple(
        entry
        for entry in _complete_registry().entries
        if not (entry.kind == "kline" and entry.interval == "15m" and entry.symbols == ("ETHUSDT",))
    )
    with pytest.raises(DataQualityError, match="15m.*ETHUSDT"):
        build_dataset_bundle(
            build_dataset_registry(entries, created_at=OBSERVED),
            symbols=SYMBOLS,
            time_start=START,
            time_end=END,
            created_at=OBSERVED,
        )


def test_bundle_rejects_context_without_primary_range_coverage() -> None:
    entries = tuple(
        entry.model_copy(update={"time_end": END - timedelta(minutes=30)})
        if entry.kind == "kline" and entry.interval == "15m" and entry.symbols == ("BTCUSDT",)
        else entry
        for entry in _complete_registry().entries
    )
    with pytest.raises(DataQualityError, match="15m context coverage.*BTCUSDT"):
        build_dataset_bundle(
            build_dataset_registry(entries, created_at=OBSERVED),
            symbols=SYMBOLS,
            time_start=START,
            time_end=END,
            created_at=OBSERVED,
        )


def test_bundle_rejects_filter_snapshot_with_incomplete_symbol_universe() -> None:
    entries = tuple(
        entry for entry in _complete_registry().entries if not (entry.kind == "exchange_filters")
    ) + (_entry("exchange_filters", ("BTCUSDT",), content_hash="f" * 64),)
    with pytest.raises(DataQualityError, match="exchange_filters.*symbol universe"):
        build_dataset_bundle(
            build_dataset_registry(entries, created_at=OBSERVED),
            symbols=SYMBOLS,
            time_start=START,
            time_end=END,
            created_at=OBSERVED,
        )


def test_bundle_is_write_once_and_tamper_evident(tmp_path: Path) -> None:
    bundle = build_dataset_bundle(
        _complete_registry(),
        symbols=SYMBOLS,
        time_start=START,
        time_end=END,
        created_at=OBSERVED,
    )
    path = tmp_path / "bundle.json"
    write_dataset_bundle(path, bundle)

    assert read_dataset_bundle(path) == bundle
    assert write_dataset_bundle(path, bundle) == bundle

    conflicting = bundle.model_copy(update={"registry_hash": "0" * 64})
    with pytest.raises(DomainViolation, match="immutable"):
        write_dataset_bundle(path, conflicting)

    path.write_text(
        path.read_text(encoding="utf-8").replace(bundle.registry_hash, "1" * 64),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="bundle hash mismatch"):
        read_dataset_bundle(path)
