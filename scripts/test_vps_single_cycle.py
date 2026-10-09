"""Test single live cycle of continuous trader on VPS."""

import asyncio
from pathlib import Path

from autonomous_futures.execution.continuous_trader import ContinuousSelfDrivingTrader


async def main() -> None:
    import httpx

    async with httpx.AsyncClient() as client:
        r1 = await client.get(
            "https://testnet.binancefuture.com/fapi/v1/klines",
            params={"symbol": "SOLUSDT", "interval": "15m", "limit": 5},
        )
        print("Testnet SOLUSDT status:", r1.status_code, "text:", r1.text[:100])
        r2 = await client.get(
            "https://fapi.binance.com/fapi/v1/klines",
            params={"symbol": "SOLUSDT", "interval": "15m", "limit": 5},
        )
        print("Live SOLUSDT status:", r2.status_code, "count:", len(r2.json()))


if __name__ == "__main__":
    asyncio.run(main())
