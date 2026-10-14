"""Real market ingress, measured Hawkes warmup, and age/sequence gates for entries."""

from __future__ import annotations

import asyncio
import math
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from autonomous_futures.feed.measured_hawkes import Arrival, HawkesFit, fit_arrivals
from autonomous_futures.feed.runtime_hawkes_calibration import RuntimeHawkesCalibration

DEFAULT_CALIBRATION_WINDOW_MS = 1_800_000
MINIMUM_CALIBRATION_WINDOW_MS = 90_001
MAXIMUM_CALIBRATION_WINDOW_MS = 3_600_000


@dataclass(frozen=True)
class MicrostructureEvidence:
    symbol: str
    event_timestamp_ms: int
    quote_timestamp_ms: int
    fit_timestamp_ms: int
    spectral_radius: Decimal
    best_bid: Decimal
    best_ask: Decimal
    generation: int
    arrivals_sha256: str
    beta_per_second: Decimal
    calibration_sha256: str

    def validate(self, now_ms: int, uncertainty_ms: int = 0) -> None:
        if not 0 <= uncertainty_ms <= 250:
            raise ValueError("Invalid observed clock uncertainty")
        if not all(
            -uncertainty_ms <= now_ms - timestamp <= 500 - uncertainty_ms
            for timestamp in (self.event_timestamp_ms, self.quote_timestamp_ms)
        ):
            raise ValueError("Trade or depth evidence is stale")
        if not -uncertainty_ms <= now_ms - self.fit_timestamp_ms <= 20_000 - uncertainty_ms:
            raise ValueError("Hawkes fit is stale")
        if not self.spectral_radius.is_finite() or not 0 <= self.spectral_radius < 1:
            raise ValueError("Measured Hawkes process is supercritical or invalid")
        if not self.beta_per_second.is_finite() or self.beta_per_second <= 0:
            raise ValueError("Invalid measured Hawkes decay parameter")
        if len(self.calibration_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.calibration_sha256
        ):
            raise ValueError("Hawkes calibration evidence hash is invalid")
        if not 0 < self.best_bid < self.best_ask:
            raise ValueError("Invalid or crossed depth")


class RuntimeMicrostructure:
    """An empty, disconnected, gapped or uncalibrated feed cannot grant entry evidence."""

    def __init__(
        self,
        symbols: tuple[str, ...],
        *,
        calibration: RuntimeHawkesCalibration,
        calibration_window_ms: int = DEFAULT_CALIBRATION_WINDOW_MS,
    ) -> None:
        if not symbols or len(set(symbols)) != len(symbols):
            raise ValueError("Unique runtime symbols are required")
        if calibration.symbols != symbols:
            raise ValueError("Runtime symbols do not match the calibrated symbol universe")
        if (
            type(calibration_window_ms) is not int
            or not MINIMUM_CALIBRATION_WINDOW_MS
            <= calibration_window_ms
            <= MAXIMUM_CALIBRATION_WINDOW_MS
        ):
            raise ValueError("Calibration window must cover the Hawkes burn-in and fit period")
        self.symbols = symbols
        if (
            not math.isfinite(calibration.beta_per_second)
            or calibration.beta_per_second <= 0
            or len(calibration.artifact_sha256) != 64
            or any(character not in "0123456789abcdef" for character in calibration.artifact_sha256)
            or not calibration.trace_sha256s
            or any(
                len(trace_hash) != 64
                or any(character not in "0123456789abcdef" for character in trace_hash)
                for trace_hash in calibration.trace_sha256s
            )
        ):
            raise ValueError("A verified runtime Hawkes calibration is required")
        self.calibration = calibration
        self.calibration_window_ms = calibration_window_ms
        self.arrivals: deque[Arrival] = deque()
        self.last_ids: dict[str, int] = {}
        self.last_depth_ids: dict[str, int] = {}
        self.trade_times: dict[str, int] = {}
        self.quotes: dict[str, tuple[int, Decimal, Decimal]] = {}
        self.fit: HawkesFit | None = None
        self.generation = 0
        self.fitting = False
        self.gaps = self.duplicates = self.stale = 0
        self.last_fit_error: str | None = None

    def disconnect(self) -> None:
        self.generation += 1
        self.arrivals.clear()
        self.fit = None
        self.trade_times.clear()
        self.quotes.clear()
        self.last_ids.clear()
        self.last_depth_ids.clear()

    def ingest(self, payload: dict[str, Any], received_ms: int, *, uncertainty_ms: int = 0) -> None:
        try:
            if not 0 <= uncertainty_ms <= 250:
                raise ValueError("Invalid observed clock uncertainty")
            self._ingest(payload, received_ms, uncertainty_ms)
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            self.disconnect()
            raise ValueError(f"Malformed market ingress: {exc}") from exc

    def _ingest(self, payload: dict[str, Any], received_ms: int, uncertainty_ms: int) -> None:
        data = payload.get("data", payload)
        symbol = data.get("s")
        if symbol not in self.symbols:
            return
        event_ms = int(data["E"])
        if not -uncertainty_ms <= received_ms - event_ms <= 500 - uncertainty_ms:
            self.stale += 1
            # Old genuine frames still inform likelihood and sequence continuity.
            # Their timestamps remain old, so evidence.validate continues to veto entries.
            if event_ms > received_ms + uncertainty_ms or received_ms - event_ms > 180_000:
                return
        if data.get("e") == "aggTrade":
            identity, when = int(data["a"]), int(data["T"])
            if when <= 0 or when > event_ms:
                raise ValueError("Invalid aggregate trade timestamp")
            previous = self.last_ids.get(symbol)
            if previous is not None and identity <= previous:
                self.duplicates += 1
                return
            if previous is not None and identity != previous + 1:
                self.gaps += 1
                self.disconnect()
            self.last_ids[symbol] = identity
            self.trade_times[symbol] = when
            self.arrivals.append(Arrival(symbol, when, identity))
            cutoff = received_ms - self.calibration_window_ms
            while self.arrivals and self.arrivals[0].timestamp_ms < cutoff:
                self.arrivals.popleft()
            if len(self.arrivals) > 200_000:
                self.disconnect()
                raise ValueError(
                    "Ingress overflow; warmup restarted instead of truncating evidence"
                )
        elif data.get("e") == "depthUpdate":
            update = int(data["u"])
            previous = self.last_depth_ids.get(symbol)
            if previous is not None and update <= previous:
                self.duplicates += 1
                return
            if previous is not None and data.get("pu") is not None and int(data["pu"]) != previous:
                self.gaps += 1
                self.disconnect()
            bids, asks = data["b"], data["a"]
            if not bids or not asks:
                self.disconnect()
                raise ValueError("Empty depth cannot grant execution evidence")
            bid, ask = Decimal(str(bids[0][0])), Decimal(str(asks[0][0]))
            if not bid.is_finite() or not ask.is_finite() or not 0 < bid < ask:
                self.disconnect()
                raise ValueError("Crossed or invalid depth")
            bid_quantity, ask_quantity = Decimal(str(bids[0][1])), Decimal(str(asks[0][1]))
            if (
                not bid_quantity.is_finite()
                or not ask_quantity.is_finite()
                or bid_quantity <= 0
                or ask_quantity <= 0
            ):
                self.disconnect()
                raise ValueError("Empty top-of-book quantity")
            self.last_depth_ids[symbol] = update
            self.quotes[symbol] = (event_ms, bid, ask)

    async def calibrate(self) -> None:
        if self.fitting:
            return
        self.fitting = True
        generation = self.generation
        sample = list(self.arrivals)
        try:
            fitted = await asyncio.to_thread(
                fit_arrivals,
                sample,
                self.symbols,
                beta=self.calibration.beta_per_second,
            )
            if generation == self.generation:
                self.fit = fitted
                if fitted.baseline_boundary_symbols:
                    symbols = ",".join(fitted.baseline_boundary_symbols)
                    self.last_fit_error = (
                        f"Hawkes baseline is pinned to the optimizer lower bound: {symbols}"
                    )
                else:
                    self.last_fit_error = None
        except ValueError as exc:
            self.fit = None
            self.last_fit_error = str(exc)
        finally:
            self.fitting = False

    def evidence(
        self, symbol: str, now_ms: int, *, uncertainty_ms: int = 0
    ) -> MicrostructureEvidence:
        if self.fit is None or symbol not in self.trade_times or symbol not in self.quotes:
            raise ValueError("Measured microstructure has not completed genuine warmup")
        if self.fit.symbols != self.symbols or self.fit.beta != self.calibration.beta_per_second:
            raise ValueError("Measured Hawkes fit does not match its runtime calibration")
        if self.fit.baseline_boundary_symbols:
            raise ValueError("Hawkes baseline estimate is pinned to the optimizer lower bound")
        quote_ms, bid, ask = self.quotes[symbol]
        evidence = MicrostructureEvidence(
            symbol,
            self.trade_times[symbol],
            quote_ms,
            self.fit.last_ms,
            Decimal(str(self.fit.spectral_radius)),
            bid,
            ask,
            self.generation,
            self.fit.arrivals_sha256,
            Decimal(str(self.fit.beta)),
            self.calibration.artifact_sha256,
        )
        evidence.validate(now_ms, uncertainty_ms)
        return evidence
