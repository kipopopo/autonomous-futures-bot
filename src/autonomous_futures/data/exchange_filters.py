from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .parquet import DataQualityError


class ExchangeFilterViolation(ValueError):
    """Raised when a proposed price or quantity violates a venue filter snapshot."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class ExchangeSymbolFilters(DomainModel):
    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    status: str = Field(min_length=1)
    contract_type: str = Field(min_length=1)
    base_asset: str = Field(min_length=1)
    quote_asset: str = Field(min_length=1)
    settle_asset: str = Field(min_length=1)
    price_min: Decimal
    price_max: Decimal
    price_tick_size: Decimal
    quantity_min: Decimal
    quantity_max: Decimal
    quantity_step_size: Decimal
    market_quantity_min: Decimal
    market_quantity_max: Decimal
    market_quantity_step_size: Decimal
    min_notional: Decimal
    max_notional: Decimal | None = None
    min_notional_apply_to_market: bool = True
    max_notional_apply_to_market: bool = False

    @model_validator(mode="after")
    def validate_filter_values(self) -> ExchangeSymbolFilters:
        positive = (
            ("price_tick_size", self.price_tick_size),
            ("quantity_min", self.quantity_min),
            ("quantity_max", self.quantity_max),
            ("quantity_step_size", self.quantity_step_size),
            ("market_quantity_min", self.market_quantity_min),
            ("market_quantity_max", self.market_quantity_max),
            ("market_quantity_step_size", self.market_quantity_step_size),
            ("min_notional", self.min_notional),
        )
        for name, value in positive:
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        non_negative = (("price_min", self.price_min), ("price_max", self.price_max))
        for name, value in non_negative:
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.price_max and self.price_max < self.price_min:
            raise ValueError("price_max must not be below price_min")
        if self.quantity_max < self.quantity_min:
            raise ValueError("quantity_max must not be below quantity_min")
        if self.market_quantity_max < self.market_quantity_min:
            raise ValueError("market_quantity_max must not be below market_quantity_min")
        if self.max_notional is not None and (
            not self.max_notional.is_finite() or self.max_notional <= 0
        ):
            raise ValueError("max_notional must be finite and positive")
        return self


class ExchangeFilterSnapshot(DomainModel):
    snapshot_version: Literal[1] = 1
    venue: Literal["BINANCE_USDS_M_FUTURES"] = "BINANCE_USDS_M_FUTURES"
    observed_at: datetime
    symbols: tuple[ExchangeSymbolFilters, ...] = Field(min_length=1)
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_symbols(self) -> ExchangeFilterSnapshot:
        names = tuple(item.symbol for item in self.symbols)
        if names != tuple(sorted(names)):
            raise ValueError("snapshot symbols must be sorted")
        if len(set(names)) != len(names):
            raise ValueError("snapshot symbols must be unique")
        return self


def _as_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DataQualityError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataQualityError(f"{field} must be a non-empty string")
    return value


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise DataQualityError(f"{field} must be a decimal") from None
    except ValueError:
        raise DataQualityError(f"{field} must be a decimal") from None
    if not result.is_finite():
        raise DataQualityError(f"{field} must be finite")
    return result


def _filter_map(raw_filters: object, *, symbol: str) -> dict[str, Mapping[str, object]]:
    if not isinstance(raw_filters, list):
        raise DataQualityError(f"{symbol} filters must be a list")
    result: dict[str, Mapping[str, object]] = {}
    for raw_filter in raw_filters:
        current = _as_mapping(raw_filter, field=f"{symbol} filter")
        filter_type = _required_text(current.get("filterType"), field="filterType")
        if filter_type in result:
            raise DataQualityError(f"duplicate {filter_type} for {symbol}")
        result[filter_type] = current
    return result


def _required_filter(
    filters: Mapping[str, Mapping[str, object]], *, symbol: str, filter_type: str
) -> Mapping[str, object]:
    current = filters.get(filter_type)
    if current is None:
        raise DataQualityError(f"{symbol} is missing {filter_type}")
    return current


def _bool_field(raw_filter: Mapping[str, object], *names: str, default: bool) -> bool:
    for name in names:
        value = raw_filter.get(name)
        if value is not None:
            if not isinstance(value, bool):
                raise DataQualityError(f"{name} must be boolean")
            return value
    return default


def _parse_symbol(raw_symbol: object) -> ExchangeSymbolFilters:
    symbol_record = _as_mapping(raw_symbol, field="exchange symbol")
    symbol = _required_text(symbol_record.get("symbol"), field="symbol")
    filters = _filter_map(symbol_record.get("filters"), symbol=symbol)
    price_filter = _required_filter(filters, symbol=symbol, filter_type="PRICE_FILTER")
    lot_filter = _required_filter(filters, symbol=symbol, filter_type="LOT_SIZE")
    market_lot_filter = filters.get("MARKET_LOT_SIZE", lot_filter)
    notional_filter = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
    if notional_filter is None:
        raise DataQualityError(f"{symbol} is missing NOTIONAL or MIN_NOTIONAL")

    min_notional_value = notional_filter.get("minNotional", notional_filter.get("notional"))
    if min_notional_value is None:
        raise DataQualityError(f"{symbol} notional filter is missing minNotional")
    max_notional_value = notional_filter.get("maxNotional")

    return ExchangeSymbolFilters(
        symbol=symbol,
        status=_required_text(symbol_record.get("status"), field=f"{symbol}.status"),
        contract_type=_required_text(
            symbol_record.get("contractType"), field=f"{symbol}.contractType"
        ),
        base_asset=_required_text(symbol_record.get("baseAsset"), field=f"{symbol}.baseAsset"),
        quote_asset=_required_text(symbol_record.get("quoteAsset"), field=f"{symbol}.quoteAsset"),
        settle_asset=_required_text(
            symbol_record.get("settleAsset", symbol_record.get("marginAsset")),
            field=f"{symbol}.settleAsset/marginAsset",
        ),
        price_min=_decimal(price_filter.get("minPrice"), field=f"{symbol}.minPrice"),
        price_max=_decimal(price_filter.get("maxPrice"), field=f"{symbol}.maxPrice"),
        price_tick_size=_decimal(price_filter.get("tickSize"), field=f"{symbol}.tickSize"),
        quantity_min=_decimal(lot_filter.get("minQty"), field=f"{symbol}.minQty"),
        quantity_max=_decimal(lot_filter.get("maxQty"), field=f"{symbol}.maxQty"),
        quantity_step_size=_decimal(lot_filter.get("stepSize"), field=f"{symbol}.stepSize"),
        market_quantity_min=_decimal(
            market_lot_filter.get("minQty"), field=f"{symbol}.marketMinQty"
        ),
        market_quantity_max=_decimal(
            market_lot_filter.get("maxQty"), field=f"{symbol}.marketMaxQty"
        ),
        market_quantity_step_size=_decimal(
            market_lot_filter.get("stepSize"), field=f"{symbol}.marketStepSize"
        ),
        min_notional=_decimal(min_notional_value, field=f"{symbol}.minNotional"),
        max_notional=(
            _decimal(max_notional_value, field=f"{symbol}.maxNotional")
            if max_notional_value is not None
            else None
        ),
        min_notional_apply_to_market=_bool_field(
            notional_filter, "applyMinToMarket", "applyToMarket", default=True
        ),
        max_notional_apply_to_market=_bool_field(
            notional_filter, "applyMaxToMarket", default=False
        ),
    )


def _snapshot_content_hash(snapshot: ExchangeFilterSnapshot) -> str:
    payload = snapshot.model_dump(mode="json", exclude={"observed_at", "snapshot_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_exchange_filter_snapshot(
    payload: Mapping[str, object], *, symbols: Sequence[str] | None, observed_at: datetime
) -> ExchangeFilterSnapshot:
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list):
        raise DataQualityError("exchangeInfo symbols must be a list")
    requested = tuple(
        sorted(
            symbols
            if symbols is not None
            else (
                _required_text(
                    _as_mapping(item, field="exchange symbol").get("symbol"), field="symbol"
                )
                for item in raw_symbols
            )
        )
    )
    if not requested or len(set(requested)) != len(requested):
        raise DataQualityError("requested symbols must be non-empty and unique")
    by_symbol: dict[str, object] = {}
    for raw_symbol in raw_symbols:
        record = _as_mapping(raw_symbol, field="exchange symbol")
        raw_name = _required_text(record.get("symbol"), field="symbol")
        by_symbol[raw_name] = raw_symbol
    missing = sorted(set(requested).difference(by_symbol))
    if missing:
        raise DataQualityError(f"symbol not found in exchangeInfo: {', '.join(missing)}")
    parsed = tuple(
        sorted((_parse_symbol(by_symbol[name]) for name in requested), key=lambda x: x.symbol)
    )
    provisional = ExchangeFilterSnapshot(
        observed_at=observed_at.astimezone(UTC),
        symbols=parsed,
        snapshot_hash="0" * 64,
    )
    return provisional.model_copy(update={"snapshot_hash": _snapshot_content_hash(provisional)})


def read_exchange_filter_snapshot(path: Path) -> ExchangeFilterSnapshot:
    snapshot = ExchangeFilterSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    if _snapshot_content_hash(snapshot) != snapshot.snapshot_hash:
        raise DomainViolation(f"exchange filter snapshot hash mismatch: {path}")
    return snapshot


def write_exchange_filter_snapshot(
    path: Path, snapshot: ExchangeFilterSnapshot
) -> ExchangeFilterSnapshot:
    if path.exists():
        existing = read_exchange_filter_snapshot(path)
        if existing != snapshot:
            raise DomainViolation(f"exchange filter snapshot path is immutable: {path}")
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(path)
    return snapshot


def _symbol_filters(snapshot: ExchangeFilterSnapshot, symbol: str) -> ExchangeSymbolFilters:
    for item in snapshot.symbols:
        if item.symbol == symbol:
            return item
    raise ExchangeFilterViolation("symbol", f"{symbol} is absent from the filter snapshot")


def _aligned(value: Decimal, step: Decimal) -> bool:
    return (value % step) == 0


def validate_order_filters(
    snapshot: ExchangeFilterSnapshot,
    *,
    symbol: str,
    order_type: Literal["LIMIT", "MARKET"],
    reference_price: Decimal,
    quantity: Decimal,
) -> None:
    filters = _symbol_filters(snapshot, symbol)
    if filters.status != "TRADING":
        raise ExchangeFilterViolation("status", f"{symbol} status is {filters.status}")
    if reference_price <= 0 or not reference_price.is_finite():
        raise ExchangeFilterViolation("price", "reference price must be finite and positive")
    if quantity <= 0 or not quantity.is_finite():
        raise ExchangeFilterViolation("quantity", "quantity must be finite and positive")

    if order_type == "LIMIT":
        if filters.price_min > 0 and reference_price < filters.price_min:
            raise ExchangeFilterViolation("price", "price is below minPrice")
        if filters.price_max > 0 and reference_price > filters.price_max:
            raise ExchangeFilterViolation("price", "price is above maxPrice")
        if not _aligned(reference_price, filters.price_tick_size):
            raise ExchangeFilterViolation("tick", "price is not aligned to tickSize")

    if order_type == "MARKET":
        quantity_min = filters.market_quantity_min
        quantity_max = filters.market_quantity_max
        quantity_step = filters.market_quantity_step_size
    else:
        quantity_min = filters.quantity_min
        quantity_max = filters.quantity_max
        quantity_step = filters.quantity_step_size
    if quantity < quantity_min:
        raise ExchangeFilterViolation("quantity", "quantity is below minQty")
    if quantity_max > 0 and quantity > quantity_max:
        raise ExchangeFilterViolation("quantity", "quantity is above maxQty")
    if not _aligned(quantity, quantity_step):
        raise ExchangeFilterViolation("step", "quantity is not aligned to stepSize")

    notional = reference_price * quantity
    if (
        order_type == "LIMIT" or filters.min_notional_apply_to_market
    ) and notional < filters.min_notional:
        raise ExchangeFilterViolation("notional", "order notional is below the minimum")
    if (
        filters.max_notional is not None
        and (order_type == "LIMIT" or filters.max_notional_apply_to_market)
        and notional > filters.max_notional
    ):
        raise ExchangeFilterViolation("notional", "order notional is above the maximum")


__all__ = [
    "ExchangeFilterSnapshot",
    "ExchangeFilterViolation",
    "ExchangeSymbolFilters",
    "build_exchange_filter_snapshot",
    "read_exchange_filter_snapshot",
    "validate_order_filters",
    "write_exchange_filter_snapshot",
]
