"""Quick connectivity probe for Binance Futures Gateway."""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway


async def main() -> None:
    gw = BinanceFuturesGateway()
    print("REST Base URL:", gw.rest_base)
    print("Testnet mode:", gw.testnet)
    print("API Key configured:", bool(gw.api_key and not gw.api_key.startswith("mock-")))

    offset = await gw.sync_server_time()
    print(f"Server time synchronized. Offset: {offset} ms")

    try:
        acc = await gw.get_account()
        wallet_balance = acc.get("totalWalletBalance", "0")
        available_balance = acc.get("availableBalance", "0")
        print(f"Authentication verified! Wallet Balance: {wallet_balance} USDT, Available: {available_balance} USDT")
    except Exception as e:
        print("API query exception:", type(e).__name__, str(e))


if __name__ == "__main__":
    asyncio.run(main())
