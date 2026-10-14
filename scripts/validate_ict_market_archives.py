"""Verify the acquired minute corpus, record observed coverage, and report gaps honestly."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from autonomous_futures.research.official_market_data import official_minutes  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO / "research/official-archives/1m")
    parser.add_argument("--symbol", action="append")
    parser.add_argument(
        "--output", type=Path, default=REPO / "artifacts/qualification/runtime-inputs"
    )
    args = parser.parse_args()
    symbols = args.symbol or sorted(path.name for path in args.root.iterdir() if path.is_dir())
    failed = False
    for symbol in symbols:
        count = 0
        first_ms = last_ms = None
        status, reason = "VERIFIED", None
        try:
            for bar in official_minutes(args.root, symbol):
                count += 1
                if first_ms is None:
                    first_ms = bar.timestamp_ms
                last_ms = bar.timestamp_ms
        except ValueError as exc:
            status, reason, failed = "REJECTED_DATA", str(exc), True
        manifests = [
            {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted((args.root / symbol).glob("*.manifest.json"))
        ]
        result = {
            "symbol": symbol,
            "status": status,
            "reason": reason,
            "rows": count,
            "first_ms": first_ms,
            "last_close_ms": None if last_ms is None else last_ms + 60000,
            "manifests": manifests,
            "execution_authority": False,
        }
        encoded = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
        sha = hashlib.sha256(encoded).hexdigest()
        args.output.mkdir(parents=True, exist_ok=True)
        target = args.output / f"official-minute-coverage-{symbol}-{sha[:16]}.json"
        if target.exists() and target.read_bytes() != encoded:
            raise ValueError("Immutable coverage evidence collision")
        target.write_bytes(encoded)
        print(
            json.dumps(
                {
                    "symbol": symbol,
                    "status": status,
                    "reason": reason,
                    "rows": count,
                    "path": str(target),
                }
            ),
            flush=True,
        )
    if failed:
        raise SystemExit("At least one corpus has invalid or missing observations")


if __name__ == "__main__":
    main()
