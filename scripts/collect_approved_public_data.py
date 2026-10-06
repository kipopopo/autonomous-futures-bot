"""One-shot, unsigned collector for the user's explicitly approved Binance scope."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import sleep as sleep_seconds

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for import_root in (REPO_ROOT, SRC_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from autonomous_futures.api.artifacts import inspect_dataset_artifacts  # noqa: E402
from autonomous_futures.api.catalog import load_verified_dataset_catalog  # noqa: E402
from autonomous_futures.data.alignment import canonicalize_funding_rows  # noqa: E402
from autonomous_futures.data.artifacts import finalize_resumable_backfill  # noqa: E402
from autonomous_futures.data.backfill import (  # noqa: E402
    MAX_BINANCE_KLINE_LIMIT,
    BackfillWindow,
    RetryPolicy,
    plan_kline_windows,
    resumable_backfill_klines,
)
from autonomous_futures.data.builder import INTERVAL_MS  # noqa: E402
from autonomous_futures.data.bundle import build_dataset_bundle, write_dataset_bundle  # noqa: E402
from autonomous_futures.data.derivative_collection import collect_mark_price_artifact  # noqa: E402
from autonomous_futures.data.derivatives_artifacts import write_funding_artifact  # noqa: E402
from autonomous_futures.data.exchange_filters import (  # noqa: E402
    build_exchange_filter_snapshot,
    write_exchange_filter_snapshot,
)
from autonomous_futures.data.manifest import sha256_file  # noqa: E402
from autonomous_futures.data.parquet import DataQualityError  # noqa: E402
from autonomous_futures.data.public_collector import public_get  # noqa: E402
from autonomous_futures.data.registry import (  # noqa: E402
    DatasetKind,
    DatasetRegistryEntry,
    build_dataset_registry,
    write_dataset_registry,
)
from autonomous_futures.data.transport import (  # noqa: E402
    MAX_BINANCE_FUNDING_LIMIT,
    BinancePublicExchangeInfoFetcher,
    BinancePublicFundingFetcher,
    BinancePublicKlineFetcher,
    BinancePublicMarkPriceKlineFetcher,
    TransportTelemetry,
)

APPROVED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
APPROVED_START_MS = int(datetime(2023, 1, 1, tzinfo=UTC).timestamp() * 1000)
APPROVED_END_MS_EXCLUSIVE = int(datetime(2026, 8, 6, 5, 30, tzinfo=UTC).timestamp() * 1000)
MAX_PUBLIC_GETS = 1_800
RATE_DELAY_SECONDS = 0.3
CODE_VERSION = "approved-public-data-collector-v1"

_ENDPOINTS = {
    "/fapi/v1/klines",
    "/fapi/v1/markPriceKlines",
    "/fapi/v1/fundingRate",
    "/fapi/v1/exchangeInfo",
}


class RequestBudgetExceeded(RuntimeError):
    """Raised before a public GET would exceed the explicitly approved cap."""


class CollectionScopeViolation(ValueError):
    """Raised when a request falls outside the approved public endpoint/range."""


class ApprovedPublicGet:
    """Enforce the approved endpoints, symbol/range scope, and total GET ceiling."""

    def __init__(
        self,
        get_json: Callable[[str, dict[str, object]], object],
        *,
        symbols: tuple[str, ...],
        start_ms: int,
        end_ms_exclusive: int,
        max_requests: int,
        sleep: Callable[[float], None] = sleep_seconds,
        on_request: Callable[[int, dict[str, int]], None] | None = None,
    ) -> None:
        if not symbols or len(set(symbols)) != len(symbols):
            raise CollectionScopeViolation("symbols must be non-empty and unique")
        if not set(symbols).issubset(APPROVED_SYMBOLS):
            raise CollectionScopeViolation("symbols are outside the approved scope")
        if not APPROVED_START_MS <= start_ms < end_ms_exclusive <= APPROVED_END_MS_EXCLUSIVE:
            raise CollectionScopeViolation("time range is outside the approved scope")
        if not 1 <= max_requests <= MAX_PUBLIC_GETS:
            raise CollectionScopeViolation("request budget is outside the approved ceiling")
        self._get_json = get_json
        self._symbols = frozenset(symbols)
        self._start_ms = start_ms
        self._end_ms_exclusive = end_ms_exclusive
        self._max_requests = max_requests
        self._sleep = sleep
        self._on_request = on_request
        self.request_count = 0
        self.request_counts: dict[str, int] = {}
        self._exchange_info_requested = False
        self.last_path: str | None = None

    def __call__(self, path: str, params: dict[str, object]) -> object:
        self._validate(path, params)
        if self.request_count >= self._max_requests:
            raise RequestBudgetExceeded("approved public GET ceiling reached")
        self.request_count += 1
        self.request_counts[path] = self.request_counts.get(path, 0) + 1
        self.last_path = path
        if self._on_request is not None:
            self._on_request(self.request_count, dict(self.request_counts))
        payload = self._get_json(path, params)
        self._sleep(RATE_DELAY_SECONDS)
        return payload

    def _validate(self, path: str, params: dict[str, object]) -> None:
        if path not in _ENDPOINTS:
            raise CollectionScopeViolation("endpoint is outside the approved public scope")
        if path == "/fapi/v1/exchangeInfo":
            if params or self._exchange_info_requested:
                raise CollectionScopeViolation("exchangeInfo is limited to one parameterless GET")
            self._exchange_info_requested = True
            return

        required = {"symbol", "startTime", "endTime", "limit"}
        interval = path in {"/fapi/v1/klines", "/fapi/v1/markPriceKlines"}
        if interval:
            required.add("interval")
        if set(params) != required:
            raise CollectionScopeViolation(
                "public GET parameters do not match the approved contract"
            )
        if params["symbol"] not in self._symbols:
            raise CollectionScopeViolation("symbol is outside the approved scope")
        start_ms = int(str(params["startTime"]))
        end_ms = int(str(params["endTime"]))
        if not self._start_ms <= start_ms <= end_ms < self._end_ms_exclusive:
            raise CollectionScopeViolation("public GET time range is outside the approved scope")
        limit = int(str(params["limit"]))
        max_limit = MAX_BINANCE_KLINE_LIMIT if interval else MAX_BINANCE_FUNDING_LIMIT
        if not 1 <= limit <= max_limit:
            raise CollectionScopeViolation("public GET limit exceeds the endpoint contract")
        if interval:
            allowed_intervals = {"5m", "15m"} if path == "/fapi/v1/klines" else {"5m"}
            if params["interval"] not in allowed_intervals:
                raise CollectionScopeViolation("interval is outside the approved scope")


def plan_collection_calls(
    *,
    symbols: tuple[str, ...] = APPROVED_SYMBOLS,
    start_ms: int = APPROVED_START_MS,
    end_ms_exclusive: int = APPROVED_END_MS_EXCLUSIVE,
    max_requests: int = MAX_PUBLIC_GETS,
) -> dict[str, int]:
    """Preflight page geometry and reserve the remaining cap for funding pagination."""
    if not symbols or len(set(symbols)) != len(symbols):
        raise CollectionScopeViolation("symbols must be non-empty and unique")
    if not set(symbols).issubset(APPROVED_SYMBOLS):
        raise CollectionScopeViolation("symbols are outside the approved scope")
    if not APPROVED_START_MS <= start_ms < end_ms_exclusive <= APPROVED_END_MS_EXCLUSIVE:
        raise CollectionScopeViolation("time range is outside the approved scope")
    if not 1 <= max_requests <= MAX_PUBLIC_GETS:
        raise CollectionScopeViolation("request budget is outside the approved ceiling")
    kline_pages_per_symbol = sum(
        len(
            plan_kline_windows(
                start_ms,
                end_ms_exclusive,
                interval_ms=INTERVAL_MS[interval],
                page_limit=MAX_BINANCE_KLINE_LIMIT,
            )
        )
        for interval in ("5m", "15m")
    )
    kline_pages = len(symbols) * kline_pages_per_symbol
    mark_pages = len(symbols) * len(
        plan_kline_windows(
            start_ms,
            end_ms_exclusive,
            interval_ms=INTERVAL_MS["5m"],
            page_limit=MAX_BINANCE_KLINE_LIMIT,
        )
    )
    fixed_total = kline_pages + mark_pages + 1
    funding_budget = max_requests - fixed_total
    if funding_budget < len(symbols):
        raise ValueError("approved GET ceiling cannot cover even one funding page per symbol")
    return {
        "klines": kline_pages,
        "mark_price": mark_pages,
        "exchange_info": 1,
        "fixed_total": fixed_total,
        "funding_budget": funding_budget,
        "maximum_total": max_requests,
    }


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _utc_datetime(value_ms: int) -> datetime:
    return datetime.fromtimestamp(value_ms / 1000, tz=UTC)


def _entry(
    *,
    kind: DatasetKind,
    symbols: tuple[str, ...],
    interval: str | None,
    time_start: datetime | None,
    time_end: datetime | None,
    observed_at: datetime,
    schema_version: str,
    content_hash: str,
    artifact_ref: str,
    endpoint_path: str,
) -> DatasetRegistryEntry:
    return DatasetRegistryEntry(
        kind=kind,
        symbols=symbols,
        interval=interval,
        time_start=time_start,
        time_end=time_end,
        observed_at=observed_at,
        schema_version=schema_version,
        content_hash=content_hash,
        artifact_ref=artifact_ref,
        endpoint_path=endpoint_path,
        provenance=("binance_public_rest", "unsigned", "approved_public_scope"),
    )


def collect_approved_public_data(
    output_root: Path,
    *,
    symbols: tuple[str, ...] = APPROVED_SYMBOLS,
    start_ms: int = APPROVED_START_MS,
    end_ms_exclusive: int = APPROVED_END_MS_EXCLUSIVE,
    now_ms: int | None = None,
    max_requests: int = MAX_PUBLIC_GETS,
    get_json: Callable[[str, dict[str, object]], object] = public_get,
    sleep: Callable[[float], None] = sleep_seconds,
) -> dict[str, object]:
    """Collect, persist, and verify one bounded unsigned dataset bundle."""
    symbols = tuple(symbols)
    plan = plan_collection_calls(
        symbols=symbols,
        start_ms=start_ms,
        end_ms_exclusive=end_ms_exclusive,
        max_requests=max_requests,
    )
    observed_now_ms = now_ms if now_ms is not None else int(datetime.now(UTC).timestamp() * 1000)
    if observed_now_ms < end_ms_exclusive:
        raise ValueError("approved range has not fully closed on the local clock")
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite existing collection root: {output_root}")
    output_root.mkdir(parents=True)

    dependency_lock_hash = f"sha256:{sha256_file(REPO_ROOT / 'uv.lock')}"
    audit_path = output_root / "collection-audit.json"
    scope = {
        "symbols": symbols,
        "time_start_utc": _utc_datetime(start_ms).isoformat(),
        "time_end_exclusive_utc": _utc_datetime(end_ms_exclusive).isoformat(),
        "endpoint_paths": tuple(sorted(_ENDPOINTS)),
        "authenticated": False,
        "orders_sent": False,
        "vps_accessed": False,
    }

    def persist_progress(request_count: int, request_counts: dict[str, int]) -> None:
        _write_json_atomic(
            audit_path,
            {
                **scope,
                "status": "running",
                "request_count": request_count,
                "request_limit": max_requests,
                "request_counts": request_counts,
                "retries_allowed": False,
            },
        )
        if request_count % 100 == 0:
            print(
                f"public data collection progress: {request_count}/{max_requests} GET attempts",
                flush=True,
            )

    budgeted_get = ApprovedPublicGet(
        get_json,
        symbols=symbols,
        start_ms=start_ms,
        end_ms_exclusive=end_ms_exclusive,
        max_requests=max_requests,
        sleep=sleep,
        on_request=persist_progress,
    )
    telemetry = TransportTelemetry()
    entries: list[DatasetRegistryEntry] = []
    row_counts: dict[tuple[str, str, str | None], int] = {}

    try:
        _write_json_atomic(
            audit_path,
            {
                **scope,
                "status": "preflight_complete",
                "request_count": 0,
                "request_limit": max_requests,
                "planned_fixed_requests": plan["fixed_total"],
                "reserved_funding_requests": plan["funding_budget"],
                "request_counts": {},
                "retries_allowed": False,
            },
        )

        exchange_payload = BinancePublicExchangeInfoFetcher(
            get_json=budgeted_get,
            telemetry=telemetry,
        )()
        filters_observed_at = datetime.now(UTC)
        filter_snapshot = build_exchange_filter_snapshot(
            exchange_payload,
            symbols=symbols,
            observed_at=filters_observed_at,
        )
        filter_ref = "exchange_filters/metadata/exchange-filters.json"
        write_exchange_filter_snapshot(output_root / filter_ref, filter_snapshot)
        entries.append(
            _entry(
                kind="exchange_filters",
                symbols=symbols,
                interval=None,
                time_start=None,
                time_end=None,
                observed_at=filters_observed_at,
                schema_version=f"exchange-filter-snapshot-v{filter_snapshot.snapshot_version}",
                content_hash=filter_snapshot.snapshot_hash,
                artifact_ref=filter_ref,
                endpoint_path="/fapi/v1/exchangeInfo",
            )
        )
        row_counts[("exchange_filters", "", None)] = len(filter_snapshot.symbols)

        for symbol in symbols:
            funding_fetcher = BinancePublicFundingFetcher(
                symbol=symbol,
                limit=MAX_BINANCE_FUNDING_LIMIT,
                get_json=budgeted_get,
                telemetry=telemetry,
            )
            cursor = start_ms
            raw_events: list[dict[str, object]] = []
            while cursor < end_ms_exclusive:
                if (
                    budgeted_get.request_counts.get("/fapi/v1/fundingRate", 0)
                    >= plan["funding_budget"]
                ):
                    raise RequestBudgetExceeded(
                        "funding history exhausted its reserved request budget"
                    )
                page = funding_fetcher(BackfillWindow(cursor, end_ms_exclusive))
                if not page:
                    break
                if len(page) > MAX_BINANCE_FUNDING_LIMIT:
                    raise DataQualityError("funding page exceeded the public endpoint limit")
                page_frame = canonicalize_funding_rows(
                    page,
                    symbol=symbol,
                    start_ms=cursor,
                    end_exclusive_ms=end_ms_exclusive,
                )
                raw_events.extend(page)
                last_event_ms = int(page_frame["funding_time"].iloc[-1].value // 1_000_000)
                next_cursor = last_event_ms + 1
                if next_cursor <= cursor:
                    raise DataQualityError("funding pagination cursor did not advance")
                cursor = next_cursor
                if len(page) < MAX_BINANCE_FUNDING_LIMIT:
                    break
            funding_frame = canonicalize_funding_rows(
                raw_events,
                symbol=symbol,
                start_ms=start_ms,
                end_exclusive_ms=end_ms_exclusive,
            )
            artifact_ref = f"funding_rate/{symbol}/canonical/{symbol}-funding.parquet"
            manifest_ref = f"funding_rate/{symbol}/manifests/{symbol}-funding.manifest.json"
            funding_manifest = write_funding_artifact(
                funding_frame,
                output_root / artifact_ref,
                output_root / manifest_ref,
                artifact_ref=artifact_ref,
                symbol=symbol,
                time_start=_utc_datetime(start_ms),
                time_end=_utc_datetime(end_ms_exclusive),
                created_at=datetime.now(UTC),
                code_version=CODE_VERSION,
                dependency_lock_hash=dependency_lock_hash,
            )
            entries.append(
                _entry(
                    kind="funding_rate",
                    symbols=(symbol,),
                    interval=None,
                    time_start=funding_manifest.time_start,
                    time_end=funding_manifest.time_end,
                    observed_at=funding_manifest.created_at,
                    schema_version=funding_manifest.schema_version,
                    content_hash=funding_manifest.manifest_hash,
                    artifact_ref=manifest_ref,
                    endpoint_path="/fapi/v1/fundingRate",
                )
            )
            row_counts[("funding_rate", symbol, None)] = funding_manifest.rows

        fixed_remaining = plan["klines"] + plan["mark_price"]
        if budgeted_get.request_count + fixed_remaining > max_requests:
            raise RequestBudgetExceeded("funding history used the reserved fixed-page budget")

        for interval in ("5m", "15m"):
            for symbol in symbols:
                dataset_root = output_root / "klines" / interval / symbol
                checkpoint_path = dataset_root / "state" / f"{symbol}-{interval}.checkpoint.json"
                fetcher = BinancePublicKlineFetcher(
                    symbol=symbol,
                    interval=interval,
                    get_json=budgeted_get,
                    telemetry=telemetry,
                )
                resumable_backfill_klines(
                    fetcher,
                    checkpoint_path,
                    job_id=f"approved-public:{symbol}:{interval}:{start_ms}:{end_ms_exclusive}",
                    symbol=symbol,
                    interval=interval,
                    start_ms=start_ms,
                    requested_end_exclusive=end_ms_exclusive,
                    now_ms=observed_now_ms,
                    interval_ms=INTERVAL_MS[interval],
                    retry_policy=RetryPolicy(max_attempts=1),
                    sleep=lambda _seconds: None,
                    checkpoint_clock=lambda: datetime.now(UTC),
                )
                completed_at = datetime.now(UTC)
                manifest = finalize_resumable_backfill(
                    checkpoint_path,
                    dataset_root,
                    code_version=CODE_VERSION,
                    dependency_lock_hash=dependency_lock_hash,
                    created_at=completed_at,
                    completed_at=completed_at,
                )
                manifest_ref = (
                    (dataset_root / "manifests" / f"{symbol}-{interval}.manifest.json")
                    .resolve()
                    .relative_to(output_root)
                    .as_posix()
                )
                entries.append(
                    _entry(
                        kind="kline",
                        symbols=(symbol,),
                        interval=interval,
                        time_start=manifest.time_start,
                        time_end=manifest.time_end,
                        observed_at=manifest.created_at,
                        schema_version=f"dataset-manifest-v{manifest.manifest_version}",
                        content_hash=manifest.manifest_hash,
                        artifact_ref=manifest_ref,
                        endpoint_path="/fapi/v1/klines",
                    )
                )
                canonical_file = next(
                    item
                    for item in manifest.source_files
                    if item.relative_path.endswith(".parquet")
                )
                row_counts[("kline", symbol, interval)] = canonical_file.rows

        for symbol in symbols:
            artifact_ref = f"mark_price/{symbol}/canonical/{symbol}-mark-5m.parquet"
            manifest_ref = f"mark_price/{symbol}/manifests/{symbol}-mark-5m.manifest.json"
            dataset_root = output_root / "mark_price" / symbol
            mark_manifest = collect_mark_price_artifact(
                BinancePublicMarkPriceKlineFetcher(
                    symbol=symbol,
                    interval="5m",
                    get_json=budgeted_get,
                    telemetry=telemetry,
                ),
                artifact_path=output_root / artifact_ref,
                manifest_path=output_root / manifest_ref,
                artifact_ref=artifact_ref,
                symbol=symbol,
                interval="5m",
                start_ms=start_ms,
                end_ms_exclusive=end_ms_exclusive,
                now_ms=observed_now_ms,
                created_at=datetime.now(UTC),
                code_version=CODE_VERSION,
                dependency_lock_hash=dependency_lock_hash,
                checkpoint_path=dataset_root / "state" / f"{symbol}-mark-5m.checkpoint.json",
                retry_policy=RetryPolicy(max_attempts=1),
            )
            entries.append(
                _entry(
                    kind="mark_price",
                    symbols=(symbol,),
                    interval="5m",
                    time_start=mark_manifest.time_start,
                    time_end=mark_manifest.time_end,
                    observed_at=mark_manifest.created_at,
                    schema_version=mark_manifest.schema_version,
                    content_hash=mark_manifest.manifest_hash,
                    artifact_ref=manifest_ref,
                    endpoint_path="/fapi/v1/markPriceKlines",
                )
            )
            row_counts[("mark_price", symbol, "5m")] = mark_manifest.rows

        registry_created_at = datetime.now(UTC)
        registry = build_dataset_registry(entries, created_at=registry_created_at)
        registry_path = output_root / "registry.json"
        write_dataset_registry(registry_path, registry)
        bundle = build_dataset_bundle(
            registry,
            symbols=symbols,
            time_start=_utc_datetime(start_ms),
            time_end=_utc_datetime(end_ms_exclusive),
            created_at=registry_created_at,
        )
        bundle_path = output_root / "bundle.json"
        write_dataset_bundle(bundle_path, bundle)
        catalog = load_verified_dataset_catalog(
            bundle_path=bundle_path,
            registry_path=registry_path,
        )
        inspections = inspect_dataset_artifacts(output_root, catalog)
        if len(inspections) != len(bundle.components):
            raise DataQualityError("verified catalog readback omitted a bundle component")

        components = [
            {
                "kind": entry.kind,
                "symbols": entry.symbols,
                "interval": entry.interval,
                "artifact_ref": entry.artifact_ref,
                "content_hash": entry.content_hash,
                "rows": row_counts.get(
                    (entry.kind, entry.symbols[0], entry.interval),
                    len(filter_snapshot.symbols) if entry.kind == "exchange_filters" else None,
                ),
            }
            for entry in bundle.components
        ]
        snapshot = telemetry.snapshot()
        audit = {
            **scope,
            "status": "complete",
            "collection_code_version": CODE_VERSION,
            "dependency_lock_hash": dependency_lock_hash,
            "request_count": budgeted_get.request_count,
            "request_limit": max_requests,
            "request_counts": dict(sorted(budgeted_get.request_counts.items())),
            "retries_allowed": False,
            "transport_failures": snapshot.failure_count,
            "artifact_readback_verified": True,
            "registry_hash": registry.registry_hash,
            "bundle_hash": bundle.bundle_hash,
            "components": components,
        }
        _write_json_atomic(audit_path, audit)
        return audit
    except Exception as exc:
        failure = {
            **scope,
            "status": "failed",
            "request_count": budgeted_get.request_count,
            "request_limit": max_requests,
            "request_counts": dict(sorted(budgeted_get.request_counts.items())),
            "retries_allowed": False,
            "failure_endpoint": budgeted_get.last_path,
            "failure_type": type(exc).__name__,
        }
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            failure["http_status"] = status_code
        if isinstance(exc, DataQualityError):
            failure["failure_detail"] = " ".join(str(exc).split())[:240]
        _write_json_atomic(audit_path, failure)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Collect the approved unsigned Binance public-data scope")
    parser.add_argument(
        "--execute-approved-scope",
        action="store_true",
        help="perform the bounded GETs; without this flag only print the request plan",
    )
    args = parser.parse_args(argv)
    if not args.execute_approved_scope:
        print(
            json.dumps(
                {
                    "status": "preflight_only",
                    "symbols": APPROVED_SYMBOLS,
                    "start_ms": APPROVED_START_MS,
                    "end_ms_exclusive": APPROVED_END_MS_EXCLUSIVE,
                    "request_plan": plan_collection_calls(),
                    "network_requests": 0,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0

    output_root = REPO_ROOT / "research" / "immutable-data" / "approved-public-20261006-attempt2"
    try:
        result = collect_approved_public_data(
            output_root,
            now_ms=int(datetime.now(UTC).timestamp() * 1000),
        )
    except Exception as exc:
        failure: dict[str, object] = {
            "status": "failed",
            "failure_type": type(exc).__name__,
        }
        audit_path = output_root / "collection-audit.json"
        if audit_path.is_file():
            try:
                saved = json.loads(audit_path.read_text(encoding="utf-8"))
            except OSError, ValueError:
                saved = None
            if isinstance(saved, dict):
                for name in (
                    "request_count",
                    "request_limit",
                    "request_counts",
                    "failure_endpoint",
                ):
                    if name in saved:
                        failure[name] = saved[name]
        print(json.dumps(failure, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
