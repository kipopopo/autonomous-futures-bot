"""Phase 317 Milestone 2: Chronological Candle Synchronizer & Gap Handler.

Deduplicates, chronologically sorts, and repairs candle sequences across horizons.
Implements 2-tier gap handling:
- Small gaps (<= 2 bars): padded with zero-volume flat hold bars to preserve time continuity.
- Large gaps (> 2 bars): flagged as unrepaired gaps and isolated without artificial flat padding.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from autonomous_futures.strategy.ict_mmxm import Candle

logger = logging.getLogger("autonomous_futures.feed.kline_synchronizer")

INTERVAL_MILLISECONDS: Final[dict[str, int]] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}


@dataclasses.dataclass(frozen=True)
class SynchronizedCandleSequence:
    """Immutable result of chronological synchronization."""

    symbol: str
    interval: str
    interval_ms: int
    candles: tuple[Candle, ...]
    gaps_detected: int
    bars_interpolated: int
    has_unrepaired_gap: bool


class ChronologicalCandleSynchronizer:
    """Aligns, sorts, deduplicates, and repairs candle sequences."""

    def __init__(self, max_interpolate_bars: int = 2) -> None:
        self.max_interpolate_bars = max_interpolate_bars

    def get_interval_ms(self, interval: str) -> int:
        """Returns duration of standard interval in milliseconds."""
        if interval not in INTERVAL_MILLISECONDS:
            raise ValueError(f"Unsupported interval: {interval!r}")
        return INTERVAL_MILLISECONDS[interval]

    def synchronize(
        self,
        symbol: str,
        interval: str,
        candles: Sequence[Candle],
    ) -> SynchronizedCandleSequence:
        """Deduplicates, sorts, and aligns candle sequence with 2-tier gap handling."""
        interval_ms = self.get_interval_ms(interval)
        if not candles:
            return SynchronizedCandleSequence(
                symbol=symbol,
                interval=interval,
                interval_ms=interval_ms,
                candles=(),
                gaps_detected=0,
                bars_interpolated=0,
                has_unrepaired_gap=False,
            )

        # 1. Deduplicate by timestamp_ms (keep latest occurrence) and sort
        deduped_by_ts: dict[int, Candle] = {}
        for c in candles:
            deduped_by_ts[c.timestamp_ms] = c

        sorted_candles = [deduped_by_ts[ts] for ts in sorted(deduped_by_ts.keys())]

        # 2. Sequential gap inspection & repair
        aligned_candles: list[Candle] = [sorted_candles[0]]
        gaps_detected = 0
        bars_interpolated = 0
        has_unrepaired_gap = False

        for i in range(1, len(sorted_candles)):
            prev_candle = aligned_candles[-1]
            curr_candle = sorted_candles[i]

            diff_ms = curr_candle.timestamp_ms - prev_candle.timestamp_ms

            if diff_ms == interval_ms:
                # Perfect consecutive continuity
                aligned_candles.append(curr_candle)
            elif diff_ms > interval_ms:
                # Gap detected
                gaps_detected += 1
                missing_bars = (diff_ms // interval_ms) - 1

                if 1 <= missing_bars <= self.max_interpolate_bars:
                    # Small liquidity gap: pad with zero-volume flat hold bars
                    logger.debug(
                        "Interpolating %d flat bar(s) for %s %s between %d and %d",
                        missing_bars,
                        symbol,
                        interval,
                        prev_candle.timestamp_ms,
                        curr_candle.timestamp_ms,
                    )
                    flat_price = prev_candle.close
                    for step in range(1, missing_bars + 1):
                        synth_ts = prev_candle.timestamp_ms + step * interval_ms
                        synth_bar = Candle(
                            timestamp_ms=synth_ts,
                            open=flat_price,
                            high=flat_price,
                            low=flat_price,
                            close=flat_price,
                            volume=Decimal("0"),
                        )
                        aligned_candles.append(synth_bar)
                        bars_interpolated += 1

                    aligned_candles.append(curr_candle)
                else:
                    # Large gap (maintenance / outage): do NOT pad flat bars
                    logger.warning(
                        "Sequence gap of %d bars for %s %s exceeds max "
                        "interpolation (%d); flagging gap",
                        missing_bars,
                        symbol,
                        interval,
                        self.max_interpolate_bars,
                    )
                    has_unrepaired_gap = True
                    aligned_candles.append(curr_candle)
            else:
                # Sub-interval timestamp (unexpected out-of-sequence tick): retain without gap
                aligned_candles.append(curr_candle)

        return SynchronizedCandleSequence(
            symbol=symbol,
            interval=interval,
            interval_ms=interval_ms,
            candles=tuple(aligned_candles),
            gaps_detected=gaps_detected,
            bars_interpolated=bars_interpolated,
            has_unrepaired_gap=has_unrepaired_gap,
        )
