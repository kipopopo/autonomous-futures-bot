from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.api.artifacts import inspect_dataset_artifacts
from autonomous_futures.api.catalog import load_verified_dataset_catalog
from autonomous_futures.data.derivatives_artifacts import (
    read_derivatives_artifact_manifest,
    read_funding_artifact,
)
from autonomous_futures.data.parquet import DataQualityError
from scripts import collect_approved_public_data as collector_module
from scripts.collect_approved_public_data import (
    APPROVED_START_MS,
    ApprovedPublicGet,
    CollectionScopeViolation,
    RequestBudgetExceeded,
    collect_approved_public_data,
    main,
    plan_collection_calls,
)
from tests.unit.test_exchange_filters import _exchange_info_payload


def test_approved_scope_plans_fixed_pages_and_reserves_funding_budget() -> None:
    plan = plan_collection_calls()

    assert plan == {
        "klines": 1_014,
        "mark_price": 759,
        "exchange_info": 1,
        "fixed_total": 1_774,
        "funding_budget": 26,
        "maximum_total": 1_800,
    }


def test_default_cli_is_preflight_only(capsys) -> None:
    assert main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "preflight_only"
    assert payload["network_requests"] == 0
    assert payload["request_plan"]["maximum_total"] == 1_800


def test_funding_price_fallback_uses_only_an_exact_mark_open() -> None:
    funding_time = APPROVED_START_MS + 300_000
    event = {
        "symbol": "BTCUSDT",
        "fundingTime": str(funding_time),
        "fundingRate": "0.0001",
        "markPrice": "",
    }

    resolved = collector_module._bind_funding_price_provenance(
        [event],
        mark_price_opens={funding_time: Decimal("100.25")},
        mark_manifest_hash="a" * 64,
    )

    assert resolved[0]["markPrice"] == "100.25"
    assert resolved[0]["fundingMarkPriceSource"] == "mark_price_kline.open"
    assert resolved[0]["fundingMarkPriceSourceArtifactHash"] == "a" * 64
    with pytest.raises(DataQualityError, match="exact 5m mark-price candle"):
        collector_module._bind_funding_price_provenance(
            [{**event, "fundingTime": str(funding_time + 1)}],
            mark_price_opens={funding_time: Decimal("100.25")},
            mark_manifest_hash="a" * 64,
        )


def test_script_preflight_runs_directly_from_the_src_layout() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts/collect_approved_public_data.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["network_requests"] == 0


def test_execute_cli_preserves_failed_scope_in_a_fresh_attempt_root(monkeypatch, capsys) -> None:
    output_roots: list[Path] = []

    def stop_before_collection(output_root: Path, **_kwargs: object) -> dict[str, object]:
        output_roots.append(output_root)
        raise RuntimeError("test-only preflight stop")

    monkeypatch.setattr(collector_module, "collect_approved_public_data", stop_before_collection)

    assert main(["--execute-approved-scope"]) == 1
    capsys.readouterr()
    assert len(output_roots) == 1
    assert output_roots[0].name == "approved-public-20261006-attempt3"
    assert not output_roots[0].exists()


def test_failure_audit_records_bounded_data_quality_detail_without_retry(tmp_path) -> None:
    symbol = "BTCUSDT"
    start_ms = APPROVED_START_MS
    end_ms = start_ms + 900_000
    calls: list[str] = []

    def get_json(path: str, _params: dict[str, object]) -> object:
        calls.append(path)
        if path == "/fapi/v1/exchangeInfo":
            payload = _exchange_info_payload()
            payload["symbols"] = [item for item in payload["symbols"] if item["symbol"] == symbol]
            return payload
        raise DataQualityError("mark-price data rejected\n" + "x" * 500)

    output_root = tmp_path / "data-quality-failure"
    with pytest.raises(DataQualityError):
        collect_approved_public_data(
            output_root,
            symbols=(symbol,),
            start_ms=start_ms,
            end_ms_exclusive=end_ms,
            now_ms=end_ms,
            max_requests=5,
            get_json=get_json,
            sleep=lambda _seconds: None,
        )

    audit = json.loads((output_root / "collection-audit.json").read_text(encoding="utf-8"))
    assert calls == ["/fapi/v1/exchangeInfo", "/fapi/v1/markPriceKlines"]
    assert (
        audit["failure_detail"]
        == " ".join(str(DataQualityError("mark-price data rejected\n" + "x" * 500)).split())[:240]
    )


def test_public_get_budget_never_dispatches_beyond_ceiling() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def get_json(path: str, params: dict[str, object]) -> object:
        calls.append((path, params))
        return {"symbols": []}

    budgeted_get = ApprovedPublicGet(
        get_json,
        symbols=("BTCUSDT",),
        start_ms=APPROVED_START_MS,
        end_ms_exclusive=APPROVED_START_MS + 900_000,
        max_requests=1,
        sleep=lambda _seconds: None,
    )

    params = {
        "symbol": "BTCUSDT",
        "interval": "5m",
        "startTime": APPROVED_START_MS,
        "endTime": APPROVED_START_MS + 299_999,
        "limit": 1,
    }
    assert budgeted_get("/fapi/v1/klines", params) == {"symbols": []}
    with pytest.raises(RequestBudgetExceeded):
        budgeted_get("/fapi/v1/klines", params)

    assert calls == [("/fapi/v1/klines", params)]


def test_public_get_rejects_the_unapproved_server_time_endpoint() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def get_json(path: str, params: dict[str, object]) -> object:
        calls.append((path, params))
        return {}

    budgeted_get = ApprovedPublicGet(
        get_json,
        symbols=("BTCUSDT",),
        start_ms=APPROVED_START_MS,
        end_ms_exclusive=APPROVED_START_MS + 900_000,
        max_requests=1,
        sleep=lambda _seconds: None,
    )
    with pytest.raises(CollectionScopeViolation):
        budgeted_get("/fapi/v1/time", {})

    assert calls == []


def test_collection_underbudget_is_rejected_before_writing_or_network(tmp_path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    with pytest.raises(ValueError, match="funding page"):
        collect_approved_public_data(
            tmp_path / "underfunded",
            symbols=("BTCUSDT",),
            start_ms=APPROVED_START_MS,
            end_ms_exclusive=APPROVED_START_MS + 900_000,
            now_ms=APPROVED_START_MS + 900_000,
            max_requests=4,
            get_json=lambda path, params: calls.append((path, params)),
            sleep=lambda _seconds: None,
        )

    assert calls == []
    assert not (tmp_path / "underfunded").exists()


def test_explicit_zero_clock_is_not_replaced_by_the_local_clock(tmp_path) -> None:
    output_root = tmp_path / "invalid-clock"
    with pytest.raises(ValueError, match="has not fully closed"):
        collect_approved_public_data(
            output_root,
            symbols=("BTCUSDT",),
            start_ms=APPROVED_START_MS,
            end_ms_exclusive=APPROVED_START_MS + 900_000,
            now_ms=0,
            max_requests=5,
            get_json=lambda _path, _params: pytest.fail("must not issue a request"),
            sleep=lambda _seconds: None,
        )

    assert not output_root.exists()


def test_funding_pagination_cannot_spend_the_reserved_fixed_page_budget(tmp_path) -> None:
    start_ms = APPROVED_START_MS
    end_ms = start_ms + 900_000
    symbol = "BTCUSDT"
    calls: list[str] = []
    funding_page = [
        {
            "symbol": symbol,
            "fundingTime": str(start_ms + index + 1),
            "fundingRate": "0.0001",
            "markPrice": "100",
        }
        for index in range(1_000)
    ]

    def get_json(path: str, params: dict[str, object]) -> object:
        calls.append(path)
        if path == "/fapi/v1/exchangeInfo":
            payload = _exchange_info_payload()
            payload["symbols"] = [item for item in payload["symbols"] if item["symbol"] == symbol]
            return payload
        if path == "/fapi/v1/markPriceKlines":
            return [
                (
                    start_ms + offset * 300_000,
                    "100",
                    "101",
                    "99",
                    "100.5",
                    "0",
                    start_ms + (offset + 1) * 300_000 - 1,
                    "0",
                    0,
                    "0",
                    "0",
                    "0",
                )
                for offset in range(3)
            ]
        if path == "/fapi/v1/fundingRate":
            return funding_page
        pytest.fail(f"unexpected request after funding budget was exhausted: {path}")

    output_root = tmp_path / "funding-cap"
    with pytest.raises(RequestBudgetExceeded, match="reserved request budget"):
        collect_approved_public_data(
            output_root,
            symbols=(symbol,),
            start_ms=start_ms,
            end_ms_exclusive=end_ms,
            now_ms=end_ms,
            max_requests=5,
            get_json=get_json,
            sleep=lambda _seconds: None,
        )

    audit = json.loads((output_root / "collection-audit.json").read_text(encoding="utf-8"))
    assert calls == [
        "/fapi/v1/exchangeInfo",
        "/fapi/v1/markPriceKlines",
        "/fapi/v1/fundingRate",
    ]
    assert audit["status"] == "failed"
    assert audit["request_count"] == 3
    assert not (output_root / "bundle.json").exists()


def test_collection_writes_a_verified_synthetic_bundle_without_network(
    tmp_path,
) -> None:
    start_ms = APPROVED_START_MS
    end_ms = start_ms + 1_800_000
    symbol = "BTCUSDT"

    def row(timestamp: int, interval_ms: int) -> tuple[object, ...]:
        return (
            timestamp,
            "100",
            "101",
            "99",
            "100.5",
            "1",
            timestamp + interval_ms - 1,
            "100.5",
            1,
            "0.5",
            "50.25",
            "0",
        )

    kline_rows = {
        "5m": [row(start_ms + offset * 300_000, 300_000) for offset in range(6)],
        "15m": [row(start_ms + offset * 900_000, 900_000) for offset in range(2)],
    }
    calls: list[tuple[str, dict[str, object]]] = []

    def get_json(path: str, params: dict[str, object]) -> object:
        calls.append((path, params))
        if path == "/fapi/v1/exchangeInfo":
            payload = _exchange_info_payload()
            payload["symbols"] = [item for item in payload["symbols"] if item["symbol"] == symbol]
            return payload
        if path == "/fapi/v1/fundingRate":
            return [
                {
                    "symbol": symbol,
                    "fundingTime": str(start_ms + 300_000),
                    "fundingRate": "0.0001",
                    "markPrice": "",
                }
            ]
        if path in {"/fapi/v1/klines", "/fapi/v1/markPriceKlines"}:
            interval = str(params["interval"])
            rows = kline_rows[interval]
            return [
                item
                for item in rows
                if int(str(params["startTime"])) <= item[0] <= int(str(params["endTime"]))
            ]
        raise AssertionError(f"unexpected public endpoint: {path}")

    result = collect_approved_public_data(
        tmp_path / "catalog",
        symbols=(symbol,),
        start_ms=start_ms,
        end_ms_exclusive=end_ms,
        now_ms=end_ms,
        max_requests=5,
        get_json=get_json,
        sleep=lambda _seconds: None,
    )

    catalog = load_verified_dataset_catalog(
        bundle_path=tmp_path / "catalog/bundle.json",
        registry_path=tmp_path / "catalog/registry.json",
    )
    inspections = inspect_dataset_artifacts(tmp_path / "catalog", catalog)
    mark_manifest = read_derivatives_artifact_manifest(
        tmp_path / "catalog/mark_price/BTCUSDT/manifests/BTCUSDT-mark-5m.manifest.json"
    )
    funding_frame = read_funding_artifact(
        tmp_path / "catalog/funding_rate/BTCUSDT/canonical/BTCUSDT-funding.parquet",
        symbol=symbol,
        time_start=datetime.fromtimestamp(start_ms / 1000, tz=UTC),
        time_end=datetime.fromtimestamp(end_ms / 1000, tz=UTC),
    )
    assert result["request_count"] == 5
    assert len(calls) == 5
    assert len(catalog.bundle.components) == 5
    assert len(inspections) == 5
    assert all(item.verified for item in inspections)
    assert funding_frame["funding_mark_price"].tolist() == [Decimal("100")]
    assert funding_frame["funding_mark_price_source"].tolist() == ["mark_price_kline.open"]
    assert funding_frame["funding_mark_price_source_artifact_hash"].tolist() == [
        mark_manifest.manifest_hash
    ]
