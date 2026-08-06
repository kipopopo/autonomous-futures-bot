"""Collect public Binance USD-M research data only.

This program cannot authenticate and has no order endpoints. It writes immutable
5m-primary / 15m-context snapshots consumed later by the offline strategy screener.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

BASE = "https://fapi.binance.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
PRIMARY_INTERVAL = "5m"
CONTEXT_INTERVAL = "15m"
INTERVALS = {"5m": 300_000, "15m": 900_000}
START_MS = int(datetime(2023, 1, 1, tzinfo=UTC).timestamp() * 1000)
OUT = Path(__file__).resolve().parent / "data"


def public_get(path: str, params: dict[str, object]) -> object:
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "HermesResearch/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def server_time() -> int:
    payload = public_get("/fapi/v1/time", {})
    assert isinstance(payload, dict)
    return int(payload["serverTime"])


def fully_closed_end_ms(now_ms: int, interval_ms: int) -> int:
    """Return the inclusive end timestamp of the last fully closed candle."""
    return (now_ms // interval_ms) * interval_ms - 1


def snapshot_path(intervals: tuple[str, ...]) -> Path:
    return OUT / f"snapshot-{'-'.join(intervals)}.json"


def fetch_klines(symbol: str, interval: str, interval_ms: int, end_ms: int) -> list[list[object]]:
    rows: list[list[object]] = []
    cursor = START_MS
    while cursor < end_ms:
        page = public_get(
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1500,
            },
        )
        assert isinstance(page, list)
        if not page:
            break
        rows.extend(page)
        next_cursor = int(page[-1][0]) + interval_ms
        if next_cursor <= cursor:
            raise RuntimeError(f"Non-advancing kline cursor for {symbol} {interval}")
        cursor = next_cursor
        time.sleep(0.04)
    dedup = {int(row[0]): row for row in rows}
    return [dedup[key] for key in sorted(dedup)]


def fetch_funding(symbol: str, end_ms: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    cursor = START_MS
    while cursor < end_ms:
        page = public_get(
            "/fapi/v1/fundingRate",
            {"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000},
        )
        assert isinstance(page, list)
        if not page:
            break
        rows.extend(page)
        next_cursor = int(page[-1]["fundingTime"]) + 1
        if next_cursor <= cursor:
            raise RuntimeError(f"Non-advancing funding cursor for {symbol}")
        cursor = next_cursor
        time.sleep(0.04)
    dedup = {int(row["fundingTime"]): row for row in rows}
    return [dedup[key] for key in sorted(dedup)]


def write_klines(path: Path, rows: list[list[object]]) -> None:
    header = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def write_funding(path: Path, rows: list[dict[str, object]]) -> None:
    header = ["symbol", "fundingTime", "fundingRate", "markPrice"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    now_ms = server_time()
    intervals = (PRIMARY_INTERVAL, CONTEXT_INTERVAL)
    end_by_interval = {
        interval: fully_closed_end_ms(now_ms, INTERVALS[interval]) for interval in intervals
    }
    summary: dict[str, object] = {
        "source": BASE,
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "timeframe_contract": {"primary": PRIMARY_INTERVAL, "context": CONTEXT_INTERVAL},
        "start_ms": START_MS,
        "intervals": {},
    }
    for interval in intervals:
        interval_ms = INTERVALS[interval]
        end_ms = end_by_interval[interval]
        interval_summary: dict[str, object] = {
            "interval_ms": interval_ms,
            "end_ms": end_ms,
            "symbols": {},
        }
        for symbol in SYMBOLS:
            klines = fetch_klines(symbol, interval, interval_ms, end_ms)
            if not klines:
                raise RuntimeError(f"No klines for {symbol} {interval}")
            expected = (int(klines[-1][0]) - int(klines[0][0])) // interval_ms + 1
            if expected != len(klines):
                raise RuntimeError(
                    f"Kline gap for {symbol} {interval}: expected {expected}, got {len(klines)}"
                )
            write_klines(OUT / f"{symbol}-{interval}.csv", klines)
            interval_summary["symbols"][symbol] = {
                "klines": len(klines),
                "first_open_time": int(klines[0][0]),
                "last_open_time": int(klines[-1][0]),
            }
            print(interval, symbol, interval_summary["symbols"][symbol])
        summary["intervals"][interval] = interval_summary

    funding_end_ms = end_by_interval[PRIMARY_INTERVAL]
    funding_summary: dict[str, object] = {}
    for symbol in SYMBOLS:
        funding = fetch_funding(symbol, funding_end_ms)
        write_funding(OUT / f"{symbol}-funding.csv", funding)
        funding_summary[symbol] = {"funding_rows": len(funding)}
        print("funding", symbol, funding_summary[symbol])
    summary["funding"] = funding_summary
    output = snapshot_path(intervals)
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("WROTE", output)


if __name__ == "__main__":
    main()
