"""Public exchange clock evidence for timestamp-age checks, with bounded uncertainty."""

from __future__ import annotations

from dataclasses import dataclass

MAX_CORRECTABLE_OFFSET_MS = 2_000


@dataclass(frozen=True)
class ExchangeClock:
    sent_ms: int
    received_ms: int
    server_ms: int

    def __post_init__(self) -> None:
        if not 0 <= self.received_ms - self.sent_ms <= 500 or self.server_ms <= 0:
            raise ValueError("Clock observation exceeds the latency uncertainty budget")
        if abs(self.offset_ms) > MAX_CORRECTABLE_OFFSET_MS:
            raise ValueError("Exchange clock offset exceeds the correction interlock")

    @property
    def offset_ms(self) -> int:
        return self.server_ms - (self.sent_ms + self.received_ms) // 2

    @property
    def uncertainty_ms(self) -> int:
        return (self.received_ms - self.sent_ms + 1) // 2

    def aligned_ms(self, local_ms: int) -> int:
        if not 0 <= local_ms - self.received_ms <= 180000:
            raise ValueError("Exchange clock calibration is stale or local time moved backwards")
        return local_ms + self.offset_ms

    def event_fresh(self, event_ms: int, local_ms: int) -> bool:
        age = self.aligned_ms(local_ms) - event_ms
        return age >= -self.uncertainty_ms and age + self.uncertainty_ms <= 500

    def completed_boundary(self, local_ms: int, interval_ms: int) -> int:
        """Only the earliest possible exchange time can prove a candle has closed."""
        if interval_ms <= 0:
            raise ValueError("Candle interval must be positive")
        earliest = self.aligned_ms(local_ms) - self.uncertainty_ms
        return earliest // interval_ms * interval_ms
