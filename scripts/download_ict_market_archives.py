"""Acquire official monthly 1m USD-M archives and verify their published SHA256 checksums.

No candle synthesis, exchange credentials, or execution authority is involved.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
    "NEARUSDT",
    "LINKUSDT",
    "APTUSDT",
    "ADAUSDT",
)
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"


def months(start: str, end: str) -> list[str]:
    year, month = map(int, start.split("-"))
    stop_year, stop_month = map(int, end.split("-"))
    if not 1 <= month <= 12 or not 1 <= stop_month <= 12 or (year, month) > (stop_year, stop_month):
        raise ValueError("Invalid archive interval")
    result = []
    while (year, month) <= (stop_year, stop_month):
        result.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def acquire(root: Path, symbol: str, month: str, kind: str = "1m") -> dict[str, str]:
    if kind not in {"1m", "fundingRate"}:
        raise ValueError("Unsupported official archive kind")
    name = f"{symbol}-{kind}-{month}.zip"
    url = (
        f"{BASE}/{symbol}/1m/{name}"
        if kind == "1m"
        else f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{symbol}/{name}"
    )
    target = root / symbol / name
    checksum_path = target.with_suffix(".zip.CHECKSUM")
    manifest_path = target.with_suffix(".zip.manifest.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not checksum_path.exists():
        with urllib.request.urlopen(url + ".CHECKSUM", timeout=45) as response:
            checksum_bytes = response.read(1024)
        checksum_path.write_bytes(checksum_bytes)
    checksum = checksum_path.read_text(encoding="utf-8").split()
    if len(checksum) != 2 or checksum[1].lstrip("*") != name or len(checksum[0]) != 64:
        raise ValueError("Invalid published checksum")
    if not target.exists():
        temporary = target.with_suffix(".zip.part")
        with urllib.request.urlopen(url, timeout=90) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != checksum[0]:
            raise ValueError(f"Downloaded archive checksum mismatch: {name}")
        temporary.replace(target)
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != checksum[0]:
        raise ValueError(f"Cached archive checksum mismatch: {name}")
    with zipfile.ZipFile(target) as archive:
        if (
            archive.namelist() != [name.removesuffix(".zip") + ".csv"]
            or archive.testzip() is not None
        ):
            raise ValueError("Unexpected or corrupt archive contents")
    evidence = {
        "source": url,
        "checksum_source": url + ".CHECKSUM",
        "sha256": actual,
        "symbol": symbol,
        "timeframe": kind,
        "month": month,
    }
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != evidence:
            raise ValueError("Immutable archive manifest differs")
    else:
        manifest_path.write_bytes((json.dumps(evidence, indent=2) + "\n").encode())
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["1m", "fundingRate"], default="1m")
    parser.add_argument("--symbol", action="append", choices=SYMBOLS)
    parser.add_argument("--start", default="2023-01")
    parser.add_argument("--end", default="2026-07")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.output = args.output or REPO / "research/official-archives" / args.kind
    jobs = [
        (symbol, month)
        for symbol in (args.symbol or SYMBOLS)
        for month in months(args.start, args.end)
    ]
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(acquire, args.output, symbol, month, args.kind): (symbol, month)
            for symbol, month in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            symbol, month = futures[future]
            try:
                result = future.result()
                print(json.dumps({"event": "ARCHIVE_VERIFIED", **result}), flush=True)
            except Exception as exc:
                failures.append((symbol, month, type(exc).__name__, str(exc)))
                print(
                    json.dumps(
                        {
                            "event": "ARCHIVE_FAILED",
                            "symbol": symbol,
                            "month": month,
                            "reason": str(exc),
                        }
                    ),
                    flush=True,
                )
    if failures:
        raise SystemExit(f"Incomplete immutable dataset: {len(failures)} archives failed")
    print(json.dumps({"event": "DATASET_ACQUIRED", "archives": len(jobs)}), flush=True)


if __name__ == "__main__":
    main()
