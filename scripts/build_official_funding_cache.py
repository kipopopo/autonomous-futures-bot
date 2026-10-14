"""Normalize published funding archives with immutable checksum provenance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from autonomous_futures.research.official_market_data import official_funding  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=REPO / "research/official-archives/fundingRate"
    )
    parser.add_argument(
        "--extension-source",
        type=Path,
        action="append",
        default=[],
        help="Optional adjacent official fundingRate archive root(s) to append.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "research/immutable-data/runtime-official-20261013/funding",
    )
    parser.add_argument("--symbol", action="append", help="Optional symbol filter(s).")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    symbols = args.symbol or [
        directory.name for directory in sorted(args.source.iterdir()) if directory.is_dir()
    ]
    for symbol in symbols:
        funding, provenance = official_funding(args.source, symbol)
        for ext_source in args.extension_source:
            ext_funding, ext_provenance = official_funding(ext_source, symbol)
            if funding and ext_funding and ext_funding[0][0] <= funding[-1][0]:
                raise ValueError(
                    f"Extension funding observations overlap or are out of order for {symbol}"
                )
            funding.extend(ext_funding)
            provenance.extend(ext_provenance)
        target = args.output / f"{symbol}-funding.csv"
        if target.exists():
            raise ValueError("Immutable funding cache already exists")
        with target.open("x", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["symbol", "fundingTime", "fundingRate", "markPrice"])
            writer.writerows((symbol, timestamp, str(rate), "") for timestamp, rate, _ in funding)
        sha = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest = {
            "symbol": symbol,
            "sha256": sha,
            "rows": len(funding),
            "first_ms": funding[0][0],
            "last_ms": funding[-1][0],
            "official_archives": provenance,
            "historical_marks_available": False,
        }
        target.with_suffix(".manifest.json").write_bytes(
            (json.dumps(manifest, indent=2) + "\n").encode()
        )
        print(
            json.dumps(
                {
                    "event": "FUNDING_CACHE_BUILT",
                    "symbol": symbol,
                    "rows": len(funding),
                    "sha256": sha,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
