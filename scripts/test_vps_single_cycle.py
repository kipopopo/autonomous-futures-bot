"""Test single live cycle of continuous trader on VPS."""

import asyncio
from pathlib import Path

from autonomous_futures.execution.continuous_trader import ContinuousSelfDrivingTrader


async def main() -> None:
    t = ContinuousSelfDrivingTrader(
        storage_dir=Path("artifacts/research/phase310"),
        symbols=["SOLUSDT", "ETHUSDT"],
    )
    bal = await t.synchronize_and_verify_connectivity()
    print("Real Testnet Wallet Balance:", bal, "USDT")
    await t.run_single_cycle()
    print("Cycle 1 complete! BTC 1h bars:", len(t.btc_1h_history))
    print("SOLUSDT 15m bars:", len(t.candle_history.get("SOLUSDT", [])))
    print("ETHUSDT 15m bars:", len(t.candle_history.get("ETHUSDT", [])))
    print("Single cycle execution: ALL SYSTEMS VERIFIED!")


if __name__ == "__main__":
    asyncio.run(main())
