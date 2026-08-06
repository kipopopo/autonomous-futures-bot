from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError

from .backfill import MAX_BINANCE_KLINE_LIMIT
from .builder import KlineInterval
from .public_collector import public_get

if TYPE_CHECKING:
    from .backfill import BackfillWindow


class PublicTransportError(RuntimeError):
    """Classified failure from a public market-data transport."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def _parse_retry_after(headers: object) -> float | None:
    if headers is None or not hasattr(headers, "get"):
        return None
    raw_value = headers.get("Retry-After")
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except TypeError:
        return None
    except ValueError:
        return None
    return value if value >= 0 else None


def classify_public_transport_error(error: BaseException) -> PublicTransportError:
    if isinstance(error, PublicTransportError):
        return error
    if isinstance(error, HTTPError):
        status_code = error.code
        retryable = status_code in {418, 429} or 500 <= status_code <= 599
        return PublicTransportError(
            f"Binance public HTTP error {status_code}",
            status_code=status_code,
            retryable=retryable,
            retry_after_seconds=_parse_retry_after(error.headers),
        )
    if isinstance(error, (ConnectionError, TimeoutError, URLError)):
        return PublicTransportError(
            f"Binance public transport failure: {error}",
            retryable=True,
        )
    return PublicTransportError(
        f"Binance public transport failure: {error}",
        retryable=False,
    )


class BinancePublicKlineFetcher:
    """Unsigned adapter from a backfill window to Binance public klines."""

    def __init__(
        self,
        *,
        symbol: str,
        interval: KlineInterval,
        limit: int = MAX_BINANCE_KLINE_LIMIT,
        get_json: Callable[[str, dict[str, object]], object] = public_get,
    ) -> None:
        if not symbol:
            raise ValueError("symbol must not be empty")
        if not 1 <= limit <= MAX_BINANCE_KLINE_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_BINANCE_KLINE_LIMIT}")
        self.symbol = symbol
        self.interval = interval
        self.limit = limit
        self._get_json = get_json

    def __call__(self, window: BackfillWindow) -> tuple[tuple[object, ...], ...]:
        try:
            payload = self._get_json(
                "/fapi/v1/klines",
                window.api_params(
                    symbol=self.symbol,
                    interval=self.interval,
                    limit=self.limit,
                ),
            )
        except (ConnectionError, HTTPError, TimeoutError, URLError) as exc:
            raise classify_public_transport_error(exc) from exc

        if not isinstance(payload, list):
            raise PublicTransportError(
                "Binance kline response must be a list",
                retryable=False,
            )
        rows: list[tuple[object, ...]] = []
        for row in payload:
            if not isinstance(row, (list, tuple)):
                raise PublicTransportError(
                    "Binance kline response rows must be lists",
                    retryable=False,
                )
            rows.append(tuple(row))
        return tuple(rows)


__all__ = [
    "BinancePublicKlineFetcher",
    "PublicTransportError",
    "classify_public_transport_error",
]
