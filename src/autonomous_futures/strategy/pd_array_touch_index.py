"""Exact indexed overlap queries for ICT PD arrays and closed candles."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ict_mmxm import Candle, PdArray


def touched_pd_arrays(pdas: Sequence[PdArray], candles: Sequence[Candle]) -> tuple[bool, ...]:
    """Return whether each PD array overlaps any candle after its known-from time.

    This is equivalent to ``any`` over every array/candle pair and processes all
    queries together in O((n + q) log n). Candles must be timestamp ordered.
    """
    if not pdas:
        return ()
    if not candles:
        return (False,) * len(pdas)
    if any(
        left.timestamp_ms > right.timestamp_ms
        for left, right in zip(candles, candles[1:], strict=False)
    ):
        raise ValueError("PD-array touch candles must be timestamp ordered")

    lows = sorted({candle.low for candle in candles})
    size = 1 << (len(lows) - 1).bit_length()
    tree: list[Decimal | None] = [None] * (2 * size)

    def add_candle(candle: Candle) -> None:
        node = size + bisect_right(lows, candle.low) - 1
        current = tree[node]
        if current is None or candle.high > current:
            tree[node] = candle.high
            node //= 2
            while node:
                left, right = tree[2 * node], tree[2 * node + 1]
                best = right if left is None else left if right is None else max(left, right)
                if tree[node] == best:
                    break
                tree[node] = best
                node //= 2

    def max_high_at_or_below(price: Decimal) -> Decimal | None:
        stop = bisect_right(lows, price)
        left, right = size, size + stop
        best: Decimal | None = None
        while left < right:
            if left & 1:
                value = tree[left]
                if value is not None and (best is None or value > best):
                    best = value
                left += 1
            if right & 1:
                right -= 1
                value = tree[right]
                if value is not None and (best is None or value > best):
                    best = value
            left //= 2
            right //= 2
        return best

    candle_order = sorted(
        range(len(candles)), key=lambda index: candles[index].timestamp_ms, reverse=True
    )
    queries = sorted(
        enumerate(pdas),
        key=lambda item: (
            item[1].known_from_ms if item[1].known_from_ms is not None else candles[0].timestamp_ms
        ),
        reverse=True,
    )
    result = [False] * len(pdas)
    cursor = 0
    for index, pda in queries:
        first_known = (
            pda.known_from_ms if pda.known_from_ms is not None else candles[0].timestamp_ms
        )
        while (
            cursor < len(candle_order) and candles[candle_order[cursor]].timestamp_ms >= first_known
        ):
            add_candle(candles[candle_order[cursor]])
            cursor += 1
        max_high = max_high_at_or_below(pda.top)
        result[index] = max_high is not None and max_high >= pda.bottom
    return tuple(result)


__all__ = ["touched_pd_arrays"]
