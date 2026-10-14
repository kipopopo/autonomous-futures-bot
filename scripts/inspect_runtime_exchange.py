"""Read-only, credential-free exchange filter snapshot for runtime qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

UNIVERSE = (
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


def public_json(base: str, endpoint: str) -> dict:
    request = urllib.request.Request(
        base + endpoint, headers={"User-Agent": "AFBotQualification/1"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        choices=["https://testnet.binancefuture.com", "https://fapi.binance.com"],
        default="https://testnet.binancefuture.com",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    exchange = public_json(args.base, "/fapi/v1/exchangeInfo")
    observed = public_json(args.base, "/fapi/v1/time")["serverTime"]
    specs = {}
    for item in exchange["symbols"]:
        if item["symbol"] not in UNIVERSE or item["status"] != "TRADING":
            continue
        filters = {f["filterType"]: f for f in item["filters"]}
        price, lot = filters["PRICE_FILTER"], filters["LOT_SIZE"]
        specs[item["symbol"]] = {
            "tick_size": price["tickSize"],
            "step_size": lot["stepSize"],
            "min_qty": lot["minQty"],
            "max_qty": lot["maxQty"],
            "min_notional": filters["MIN_NOTIONAL"]["notional"],
        }
    payload = {
        "source": args.base + "/fapi/v1/exchangeInfo",
        "observed_ms": observed,
        "exchange_response_sha256": hashlib.sha256(
            json.dumps(exchange, sort_keys=True).encode()
        ).hexdigest(),
        "specs": specs,
    }
    content = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    else:
        print(content)


if __name__ == "__main__":
    main()
