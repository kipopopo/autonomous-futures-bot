"""Read authenticated Testnet account evidence into isolated probe storage; no orders."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from autonomous_futures.execution.account_evidence import (  # noqa: E402
    finite_decimal,
    observe_account,
    read_account,
)
from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway  # noqa: E402


async def probe(directory: Path) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=False)
    gateway = BinanceFuturesGateway(testnet=True, offline_mode=False)
    await gateway.sync_clock_drift()
    path = directory / "exchange-account.json"
    await observe_account(gateway, path)
    observed = read_account(path)
    sources = (
        REPO / "src/autonomous_futures/execution/account_evidence.py",
        REPO / "src/autonomous_futures/execution/binance_gateway.py",
        Path(__file__),
    )
    result = {
        "source": observed["source"],
        "timestamp_ms": observed["timestamp_ms"],
        "testnet": observed["testnet"],
        "account_observation_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "reconciliation": observed["reconciliation"],
        "daily_risk": observed["daily_risk"],
        "position_records": len(observed["positions"]),
        "open_position_count": sum(
            bool(finite_decimal(row["positionAmt"])) for row in observed["positions"]
        ),
        "ordinary_orders": len(observed["open_orders"]),
        "conditional_orders": len(observed["open_algo_orders"]),
        "implementation": {
            str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
        },
        "execution_authority": False,
    }
    (directory / "probe-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(probe(args.output))
    except Exception as exc:
        # Never print signed request URLs or credential-bearing transport errors.
        print(json.dumps({"probe_failed": True, "error_type": type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
