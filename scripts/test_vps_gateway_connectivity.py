"""Quick connectivity probe for Binance Futures Gateway."""

import asyncio
import os
import sys
from pathlib import Path

# Ensure src is in sys.path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Load .env using standard library
env_path = Path("/opt/autonomous-futures-bot/.env")
if not env_path.exists():
    env_path = Path(".env")
if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line_clean = line.strip()
            if line_clean and not line_clean.startswith("#") and "=" in line_clean:
                k, v = line_clean.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway  # noqa: E402


async def main() -> None:
    gw = BinanceFuturesGateway()
    print("REST Base URL:", gw.rest_base)
    print("Testnet mode:", gw.testnet)
    print("API Key configured:", bool(gw.api_key and not gw.api_key.startswith("mock-")))

    server_time = await gw.get_server_time()
    print(f"Server time: {server_time}")
    offset = await gw.sync_clock_drift()
    print(f"Clock drift synchronized. Offset: {offset} ms")

    try:
        acc = await gw.get_account_balance()
        wallet_balance = acc.get("totalWalletBalance", "0")
        avail_balance = acc.get("availableBalance", "0")
        print(f"Auth verified! Wallet: {wallet_balance} USDT, Available: {avail_balance} USDT")

        positions = await gw.get_position_risk()
        active_pos = [p for p in positions if float(p.get("positionAmt", 0)) != 0]
        print(f"Active positions count: {len(active_pos)} (Total tracked: {len(positions)})")
    except Exception as e:
        print("API query exception:", type(e).__name__, str(e))


if __name__ == "__main__":
    asyncio.run(main())
