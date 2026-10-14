"""Stream checksum-verified official 1m candles without interpolation or float conversion."""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import zipfile
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

from autonomous_futures.strategy.ict_mmxm import Candle

HEADER = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)


def archive_minutes(path: Path, expected_sha256: str) -> Iterator[Candle]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("Official archive checksum mismatch")
    with zipfile.ZipFile(path) as archive:
        expected_name = path.name.removesuffix(".zip") + ".csv"
        if archive.namelist() != [expected_name]:
            raise ValueError("Unexpected archive member")
        with (
            archive.open(expected_name) as member,
            io.TextIOWrapper(member, encoding="utf-8", newline="") as text,
        ):
            rows = csv.reader(text)
            first = next(rows, None)
            if first is None:
                raise ValueError("Empty official archive")
            data_rows = rows if tuple(first) == HEADER else itertools.chain((first,), rows)
            previous = None
            for row in data_rows:
                if len(row) != len(HEADER):
                    raise ValueError("Truncated official kline")
                timestamp = int(row[0])
                values = [Decimal(value) for value in row[1:6]]
                bar = Candle(timestamp, *values)
                if (
                    timestamp % 60000
                    or int(row[6]) != timestamp + 59999
                    or (previous is not None and timestamp != previous + 60000)
                    or not all(value.is_finite() for value in values)
                    or min(values[:4]) <= 0
                    or bar.volume < 0
                    or bar.high < max(bar.open, bar.close, bar.low)
                    or bar.low > min(bar.open, bar.close)
                ):
                    raise ValueError("Invalid, duplicated or gapped official candle")
                yield bar
                previous = timestamp
            if previous is None:
                raise ValueError("Empty official archive")


def official_minutes(root: Path, symbol: str) -> Iterator[Candle]:
    manifests = sorted((root / symbol).glob("*.zip.manifest.json"))
    if not manifests:
        raise ValueError("No verified official minute archives")
    previous = None
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["symbol"] != symbol or manifest["timeframe"] != "1m":
            raise ValueError("Archive manifest symbol/timeframe mismatch")
        path = manifest_path.with_name(manifest_path.name.removesuffix(".manifest.json"))
        for bar in archive_minutes(path, manifest["sha256"]):
            if previous is not None and bar.timestamp_ms != previous + 60000:
                raise ValueError("Missing official minute across archive boundaries")
            yield bar
            previous = bar.timestamp_ms


def aggregate_minutes(minutes: Iterator[Candle], duration_ms: int) -> Iterator[Candle]:
    """Derive higher timeframes only from complete contiguous observed minute buckets."""
    if duration_ms < 60000 or duration_ms % 60000:
        raise ValueError("Higher timeframe must be an integral number of minutes")
    bucket: list[Candle] = []
    for bar in minutes:
        start = bar.timestamp_ms // duration_ms * duration_ms
        if bucket and bucket[0].timestamp_ms // duration_ms * duration_ms != start:
            bucket.clear()
        bucket.append(bar)
        if bar.timestamp_ms + 60000 != start + duration_ms:
            continue
        if [item.timestamp_ms for item in bucket] == list(range(start, start + duration_ms, 60000)):
            yield Candle(
                start,
                bucket[0].open,
                max(item.high for item in bucket),
                min(item.low for item in bucket),
                bucket[-1].close,
                sum((item.volume for item in bucket), Decimal("0")),
            )
        bucket.clear()


def official_funding(
    root: Path, symbol: str
) -> tuple[list[tuple[int, Decimal, Decimal | None]], list[dict[str, str]]]:
    """Read real published funding rates; archives do not supply historical mark prices."""
    manifests = sorted((root / symbol).glob("*.zip.manifest.json"))
    if not manifests:
        raise ValueError("Official funding provenance is missing")
    funding: list[tuple[int, Decimal, Decimal | None]] = []
    provenance = []
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["symbol"] != symbol or manifest["timeframe"] != "fundingRate":
            raise ValueError("Funding manifest identity mismatch")
        path = manifest_path.with_name(manifest_path.name.removesuffix(".manifest.json"))
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
            raise ValueError("Published funding archive checksum mismatch")
        with zipfile.ZipFile(path) as archive:
            name = path.name.removesuffix(".zip") + ".csv"
            if archive.namelist() != [name]:
                raise ValueError("Unexpected funding archive member")
            with (
                archive.open(name) as member,
                io.TextIOWrapper(member, encoding="utf-8", newline="") as text,
            ):
                rows = csv.DictReader(text)
                if rows.fieldnames != ["calc_time", "funding_interval_hours", "last_funding_rate"]:
                    raise ValueError("Unknown published funding schema")
                for row in rows:
                    timestamp, hours = int(row["calc_time"]), int(row["funding_interval_hours"])
                    rate = Decimal(row["last_funding_rate"])
                    if timestamp <= 0 or hours <= 0 or not rate.is_finite():
                        raise ValueError("Invalid published funding observation")
                    if funding and timestamp <= funding[-1][0]:
                        raise ValueError("Funding observations are duplicated or out of order")
                    funding.append((timestamp, rate, None))
        provenance.append(manifest)
    return funding, provenance
