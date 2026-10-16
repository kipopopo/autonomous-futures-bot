"""Autonomous Futures Bot - ICT Market Maker Model (MMXM) Core Engine.

Codifies:
- Higher Time Frame (HTF) PD Arrays: +OB, -OB, +BB, -BB, BISI, SIBI, IFVG, BSL, SSL.
- Change in State of Delivery (CISD) vs MSS with strict body close validation.
- The 6-Step Mechanical Twins Reversal State Machine.
- Fibonacci Standard Deviation (STDV) projections with opposite PDA capping.
- 100% immutable Decimal precision arithmetic.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import Any, Literal

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.strategy.pd_array_touch_index import touched_pd_arrays

logger = logging.getLogger("autonomous_futures.strategy.ict_mmxm")

# Universal Decimal Constants
ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")
HALF = Decimal("0.5")

FIB_500 = Decimal("0.500")
FIB_618 = Decimal("0.618")
FIB_705 = Decimal("0.705")
FIB_786 = Decimal("0.786")
FIB_886 = Decimal("0.886")

STDV_1_0 = Decimal("1.0")
STDV_1_5 = Decimal("1.5")
STDV_2_0 = Decimal("2.0")
STDV_2_5 = Decimal("2.5")
STDV_4_0 = Decimal("4.0")


class IctStrategyError(DomainViolation):
    """Base exception for ICT strategy invariant errors."""


class InvalidCandleSequenceError(IctStrategyError):
    """Raised when candle sequences are empty, unordered, or corrupted."""


class PdArrayType:
    """Standard ICT PD Array type constants."""

    ORDER_BLOCK = "ORDER_BLOCK"
    BREAKER_BLOCK = "BREAKER_BLOCK"
    FVG_BISI = "FVG_BISI"
    FVG_SIBI = "FVG_SIBI"
    INVERSION_FVG = "INVERSION_FVG"
    OLD_HIGH = "OLD_HIGH"
    OLD_LOW = "OLD_LOW"


class SetupDirection(enum.StrEnum):
    """Market Maker Model direction."""

    BULLISH = "BULLISH"  # Market Maker Buy Model (MMBM)
    BEARISH = "BEARISH"  # Market Maker Sell Model (MMSM)


class TwinsStep(enum.StrEnum):
    """State progression steps for the Twins Reversal Model."""

    IDLE = "IDLE"
    STEP_1_HTF_HIT = "STEP_1_HTF_HIT"
    STEP_2_M5_CISD = "STEP_2_M5_CISD"
    STEP_3_TWINS_FVG = "STEP_3_TWINS_FVG"
    STEP_4_OTE_RETRACE = "STEP_4_OTE_RETRACE"
    STEP_5_M1_CISD = "STEP_5_M1_CISD"
    STEP_6_READY = "STEP_6_READY"
    DISPATCHED = "DISPATCHED"
    INVALIDATED = "INVALIDATED"


class InvalidationReason(enum.StrEnum):
    """Explicit invalidation and rejection reasons."""

    NONE = "NONE"
    TIMEOUT_HTF_TO_M5_CISD = "TIMEOUT_HTF_TO_M5_CISD"
    PDA_BREACHED = "PDA_BREACHED"
    NO_TWIN_FVGS = "NO_TWIN_FVGS"
    OTE_OVERSHOOT = "OTE_OVERSHOOT"
    TIMEOUT_OTE_RETRACE = "TIMEOUT_OTE_RETRACE"
    M1_CISD_TIMEOUT = "M1_CISD_TIMEOUT"
    WICK_SWEEP_ONLY = "WICK_SWEEP_ONLY"
    DEALING_RANGE_INVALID = "DEALING_RANGE_INVALID"
    RISK_REWARD_INSUFFICIENT = "RISK_REWARD_INSUFFICIENT"


@dataclasses.dataclass(frozen=True)
class Candle:
    """Standard immutable OHLCV market candle."""

    timestamp_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Candle:
        ts = int(data.get("open_time", data.get("timestamp_ms", data.get("timestamp", 0))))
        return cls(
            timestamp_ms=ts,
            open=Decimal(str(data["open"])),
            high=Decimal(str(data["high"])),
            low=Decimal(str(data["low"])),
            close=Decimal(str(data["close"])),
            volume=Decimal(str(data["volume"])),
        )

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclasses.dataclass(frozen=True)
class PdArray:
    """Higher Time Frame Institutional PD Array."""

    array_type: str
    timeframe: str
    top: Decimal
    bottom: Decimal
    mean_threshold: Decimal  # (top + bottom) / 2
    direction: Literal["BULLISH", "BEARISH"] | str
    creation_ts: int
    is_mitigated: bool = False
    known_from_ms: int | None = None


@dataclasses.dataclass(frozen=True)
class StdvProjections:
    """Fibonacci Standard Deviation projections from the manipulation leg."""

    anchor_high: Decimal
    anchor_low: Decimal
    dealing_range: Decimal
    direction: Literal["BULLISH", "BEARISH"] | str
    target_1_0: Decimal
    target_1_5: Decimal
    target_2_0: Decimal  # Partial profit target (50%)
    target_2_5: Decimal
    target_4_0: Decimal  # Terminal exhaustion target
    terminus: Decimal  # 4.0 STDV or capped at opposing HTF PDA boundary


@dataclasses.dataclass(frozen=True)
class TwinsSetupState:
    """State record capturing the 6-step mechanical sequence and structured brackets."""

    symbol: str
    step_1_htf_hit: bool = False
    step_2_m5_cisd: bool = False
    step_3_twins_fvg: bool = False
    step_4_ote_retrace: bool = False
    step_5_m1_cisd: bool = False
    step_6_ready: bool = False
    confirmation_ms: int | None = None
    active_pda: PdArray | None = None
    m5_cisd_price: Decimal | None = None
    m1_cisd_price: Decimal | None = None
    ote_62: Decimal | None = None
    ote_705: Decimal | None = None
    ote_79: Decimal | None = None
    stdv_2_0: Decimal | None = None
    stdv_4_0: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit_partial: Decimal | None = None
    take_profit_final: Decimal | None = None
    side: Literal["BUY", "SELL"] | None = None
    invalidation_reason: InvalidationReason = InvalidationReason.NONE
    projections: StdvProjections | None = None
    step: TwinsStep = TwinsStep.IDLE


class StopLossMode(enum.StrEnum):
    """Stop loss placement mode for the Twins Reversal Model (LumiTraders PDF p. 157)."""

    SWING_EXTREME = "swing_extreme"  # Conservative: beyond 100% manipulation extreme (ITH/ITL)
    OTE_79_ADAPTIVE = "ote_79_adaptive"  # Aggressive: beyond 79% OTE if 1m CISD forms before 79%


class QuarterlyCyclePhase(enum.StrEnum):
    """Daily 6-hour Quarterly Cycle phases (Daye's Theory / LumiTraders PDF pp. 63, 99)."""

    Q1_ACCUMULATION = "Q1_ACCUMULATION"  # 18:00 - 00:00 NY
    Q2_MANIPULATION = "Q2_MANIPULATION"  # 00:00 - 06:00 NY (London)
    Q3_DISTRIBUTION = "Q3_DISTRIBUTION"  # 06:00 - 12:00 NY (NY AM)
    Q4_CONTINUATION_REVERSAL = "Q4_CONTINUATION_REVERSAL"  # 12:00 - 18:00 NY (NY PM)


@dataclasses.dataclass(frozen=True)
class QuarterlyCycleSnapshot:
    """Time-of-day alignment for ICT Killzones & Quarterly Theory (PDF pp. 31, 63, 99, 146)."""

    timestamp_ms: int
    ny_hour: int
    ny_minute: int
    daily_quarter: QuarterlyCyclePhase
    in_manipulation_window: bool
    in_distribution_window: bool
    in_twins_am_window: bool
    in_twins_pm_window: bool
    active_killzone: Literal["ASIA", "LONDON", "NY_AM", "LONDON_CLOSE", "NONE"]

    @property
    def is_high_probability_twins_window(self) -> bool:
        """True during the 08:15-10:30 NY AM or 13:30-15:00 NY PM Twins windows (PDF p. 146)."""
        return self.in_twins_am_window or self.in_twins_pm_window


@dataclasses.dataclass(frozen=True)
class IntradayBiasSnapshot:
    """LumiTraders Intraday Bias & Liquidity Reference levels (PDF pp. 116-139)."""

    ny_midnight_open: Decimal | None = None
    pdh: Decimal | None = None
    pdl: Decimal | None = None
    pdr_equilibrium: Decimal | None = None
    asia_high: Decimal | None = None
    asia_low: Decimal | None = None
    london_high: Decimal | None = None
    london_low: Decimal | None = None
    pdh_swept: bool = False
    pdl_swept: bool = False
    pdr_zone: Literal["PREMIUM", "DISCOUNT", "EQUILIBRIUM", "UNKNOWN"] = "UNKNOWN"
    nymo_zone: Literal["ABOVE_NYMO", "BELOW_NYMO", "AT_NYMO", "UNKNOWN"] = "UNKNOWN"


@dataclasses.dataclass(frozen=True)
class MeasuringGapProjection:
    """Measuring Gap (halfway FVG) projection to 100% terminus target (PDF pp. 34, 72-76)."""

    fvg: PdArray
    anchor_high: Decimal
    anchor_low: Decimal
    direction: Literal["BULLISH", "BEARISH"] | str
    gap_midpoint_ratio: Decimal
    projected_terminus: Decimal


def quantize_price(price: Decimal, tick_size: Decimal | None) -> Decimal:
    """Quantizes a Decimal price to tick size using ROUND_HALF_UP."""
    if tick_size is None or tick_size <= ZERO:
        return price
    return price.quantize(tick_size, rounding=ROUND_HALF_UP)


class IctMmxmEngine:
    """Pure mathematical pattern recognizer and execution state machine for ICT MMXM."""

    def __init__(
        self,
        lookback_htf: int = 100,
        min_fvg_size_ticks: int = 1,
        ote_lower: Decimal = Decimal("0.62"),
        ote_upper: Decimal = Decimal("0.79"),
        ote_sweet_spot: Decimal = FIB_705,
        default_tick_size: Decimal = Decimal("0.01"),
    ) -> None:
        self.lookback_htf = lookback_htf
        self.min_fvg_size_ticks = min_fvg_size_ticks
        self.ote_lower = ote_lower
        self.ote_upper = ote_upper
        self.ote_sweet_spot = ote_sweet_spot
        self.default_tick_size = default_tick_size

    def detect_pd_arrays(self, candles: Sequence[Candle], timeframe: str) -> list[PdArray]:
        """Cache exact immutable HTF inputs; callers receive a fresh result list."""
        bounded = candles[-self.lookback_htf :] if self.lookback_htf > 0 else candles
        configuration = (
            self.lookback_htf,
            self.min_fvg_size_ticks,
            self.ote_lower,
            self.ote_upper,
            self.ote_sweet_spot,
            self.default_tick_size,
        )
        return list(self._detect_pd_arrays_cached(tuple(bounded), timeframe, configuration))

    @staticmethod
    @lru_cache(maxsize=64)
    def _detect_pd_arrays_cached(
        candles: tuple[Candle, ...], timeframe: str, configuration: tuple[Any, ...]
    ) -> tuple[PdArray, ...]:
        """Scans candle series and identifies active Higher Time Frame PD Arrays.

        Detects:
        1. Order Blocks (+OB, -OB) with Mean Threshold and displacement verification.
        2. Breaker Blocks (+BB, -BB) via 4-point structural swings (sweep + break).
        3. Fair Value Gaps (BISI, SIBI) with Consequent Encroachment (CE).
        4. Inversion FVGs (IFVG) where candle bodies close through gap boundaries.
        5. Old Highs / Lows (BSL / SSL liquidity pools).
        """
        if not candles:
            return ()

        # Bound processing horizon to lookback_htf to prevent combinatorial denial-of-service
        if int(configuration[0]) > 0 and len(candles) > int(configuration[0]):
            candles = candles[-int(configuration[0]) :]

        if len(candles) < 2:
            return ()

        results: list[PdArray] = []
        duration_ms = {
            "1m": 60_000,
            "5m": 300_000,
            "15m": 900_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
        }[timeframe]
        n = len(candles)

        # ---------------------------------------------------------------------
        # 1. Fair Value Gaps (BISI / SIBI) & Inversion FVGs (IFVG)
        # ---------------------------------------------------------------------
        for i in range(2, n):
            c_prev2 = candles[i - 2]
            c_curr = candles[i]

            # BISI: Low(c_curr) > High(c_prev2)
            if c_curr.low > c_prev2.high:
                bottom = c_prev2.high
                top = c_curr.low
                mt = (top + bottom) / TWO
                ts = c_curr.timestamp_ms

                is_mitigated = False
                inverted = False
                for k in range(i + 1, n):
                    sub = candles[k]
                    if sub.low <= top and sub.close >= bottom:
                        is_mitigated = True
                    # Inversion: candle body closes below bottom
                    if sub.close < bottom:
                        inverted = True
                        results.append(
                            PdArray(
                                array_type=PdArrayType.INVERSION_FVG,
                                timeframe=timeframe,
                                top=top,
                                bottom=bottom,
                                mean_threshold=mt,
                                direction=SetupDirection.BEARISH.value,
                                creation_ts=sub.timestamp_ms,
                                known_from_ms=sub.timestamp_ms + duration_ms,
                                is_mitigated=False,
                            )
                        )
                        break

                if not inverted:
                    results.append(
                        PdArray(
                            array_type=PdArrayType.FVG_BISI,
                            timeframe=timeframe,
                            top=top,
                            bottom=bottom,
                            mean_threshold=mt,
                            direction=SetupDirection.BULLISH.value,
                            creation_ts=ts,
                            known_from_ms=c_curr.timestamp_ms + duration_ms,
                            is_mitigated=is_mitigated,
                        )
                    )

            # SIBI: High(c_curr) < Low(c_prev2)
            elif c_curr.high < c_prev2.low:
                bottom = c_curr.high
                top = c_prev2.low
                mt = (top + bottom) / TWO
                ts = c_curr.timestamp_ms

                is_mitigated = False
                inverted = False
                for k in range(i + 1, n):
                    sub = candles[k]
                    if sub.high >= bottom and sub.close <= top:
                        is_mitigated = True
                    # Inversion: candle body closes above top
                    if sub.close > top:
                        inverted = True
                        results.append(
                            PdArray(
                                array_type=PdArrayType.INVERSION_FVG,
                                timeframe=timeframe,
                                top=top,
                                bottom=bottom,
                                mean_threshold=mt,
                                direction=SetupDirection.BULLISH.value,
                                creation_ts=sub.timestamp_ms,
                                known_from_ms=sub.timestamp_ms + duration_ms,
                                is_mitigated=False,
                            )
                        )
                        break

                if not inverted:
                    results.append(
                        PdArray(
                            array_type=PdArrayType.FVG_SIBI,
                            timeframe=timeframe,
                            top=top,
                            bottom=bottom,
                            mean_threshold=mt,
                            direction=SetupDirection.BEARISH.value,
                            creation_ts=ts,
                            known_from_ms=c_curr.timestamp_ms + duration_ms,
                            is_mitigated=is_mitigated,
                        )
                    )

        # ---------------------------------------------------------------------
        # 2. Order Blocks (+OB, -OB)
        # ---------------------------------------------------------------------
        for i in range(n - 1):
            c_ob = candles[i]

            # Bullish Order Block (+OB): Lowest down-close candle preceding displacement
            if c_ob.is_bearish:
                # If subsequent candle is also down-close with lower low, skip non-lowest
                if i + 1 < n and candles[i + 1].is_bearish and candles[i + 1].low <= c_ob.low:
                    continue

                # Check displacement within next 1-2 candles
                has_displacement = False
                confirmation_ms = 0
                for d in range(1, min(3, n - i)):
                    disp = candles[i + d]
                    if disp.close > c_ob.high:
                        has_displacement = True
                        confirmation_ms = disp.timestamp_ms + duration_ms
                        break
                    if i + 2 < n and candles[i + 2].low > c_ob.high:
                        has_displacement = True
                        confirmation_ms = candles[i + 2].timestamp_ms + duration_ms
                        break

                if has_displacement:
                    top = c_ob.high
                    bottom = c_ob.low
                    mt = (top + bottom) / TWO

                    is_mitigated = False
                    is_invalidated = False
                    for k in range(i + 2, n):
                        future = candles[k]
                        if future.close < bottom:
                            is_invalidated = True
                            break
                        if future.low <= top and future.close >= bottom:
                            is_mitigated = True

                    if not is_invalidated:
                        results.append(
                            PdArray(
                                array_type=PdArrayType.ORDER_BLOCK,
                                timeframe=timeframe,
                                top=top,
                                bottom=bottom,
                                mean_threshold=mt,
                                direction=SetupDirection.BULLISH.value,
                                creation_ts=c_ob.timestamp_ms,
                                known_from_ms=confirmation_ms,
                                is_mitigated=is_mitigated,
                            )
                        )

            # Bearish Order Block (-OB): Highest up-close candle preceding displacement
            elif c_ob.is_bullish:
                # If subsequent candle is also up-close with higher high, skip non-highest
                if i + 1 < n and candles[i + 1].is_bullish and candles[i + 1].high >= c_ob.high:
                    continue

                has_displacement = False
                confirmation_ms = 0
                for d in range(1, min(3, n - i)):
                    disp = candles[i + d]
                    if disp.close < c_ob.low:
                        has_displacement = True
                        confirmation_ms = disp.timestamp_ms + duration_ms
                        break
                    if i + 2 < n and candles[i + 2].high < c_ob.low:
                        has_displacement = True
                        confirmation_ms = candles[i + 2].timestamp_ms + duration_ms
                        break

                if has_displacement:
                    top = c_ob.high
                    bottom = c_ob.low
                    mt = (top + bottom) / TWO

                    is_mitigated = False
                    is_invalidated = False
                    for k in range(i + 2, n):
                        future = candles[k]
                        if future.close > top:
                            is_invalidated = True
                            break
                        if future.high >= bottom and future.close <= top:
                            is_mitigated = True

                    if not is_invalidated:
                        results.append(
                            PdArray(
                                array_type=PdArrayType.ORDER_BLOCK,
                                timeframe=timeframe,
                                top=top,
                                bottom=bottom,
                                mean_threshold=mt,
                                direction=SetupDirection.BEARISH.value,
                                creation_ts=c_ob.timestamp_ms,
                                known_from_ms=confirmation_ms,
                                is_mitigated=is_mitigated,
                            )
                        )

        # ---------------------------------------------------------------------
        # 3. Breaker Blocks (+BB, -BB) via Confirmed 4-Point Structural Pivots
        # ---------------------------------------------------------------------
        if n >= 4:
            # Pre-filter structural swing pivots to prevent O(n^4) combinatorial explosion.
            # Use radius=1 (3-bar pivot) on micro-sequences (n < 10) and radius=2 (5-bar fractal)
            # on standard HTF horizons. Boundary checks adapt gracefully to edge bars.
            radius = 1 if n < 10 else 2
            swing_highs: list[int] = []
            swing_lows: list[int] = []

            for i in range(n):
                c = candles[i]
                left_h = [candles[j].high for j in range(max(0, i - radius), i)]
                right_h = [candles[j].high for j in range(i + 1, min(n, i + radius + 1))]
                left_l = [candles[j].low for j in range(max(0, i - radius), i)]
                right_l = [candles[j].low for j in range(i + 1, min(n, i + radius + 1))]

                is_sh = (not left_h or all(c.high > h for h in left_h)) and (
                    not right_h or all(c.high > h for h in right_h)
                )
                is_sl = (not left_l or all(c.low < val_l for val_l in left_l)) and (
                    not right_l or all(c.low < val_l for val_l in right_l)
                )

                if is_sh:
                    swing_highs.append(i)
                if is_sl:
                    swing_lows.append(i)

            seen_breaker_zones: set[tuple[str, Decimal, Decimal]] = set()

            # Bullish Breaker (+BB): L1 -> H1 -> L2 -> H2
            # L1 (swing low) -> H1 (swing high) -> L2 (sweep below L1) -> H2 (MSS break above H1)
            # The breaker block is the last up-close candle in the L1 -> H1 leg.
            for i1 in swing_lows:
                l1 = candles[i1].low
                for i2 in swing_highs:
                    if i2 <= i1:
                        continue
                    h1 = candles[i2].high
                    if h1 <= l1:
                        continue

                    # Locate last up-close candle in L1 -> H1 leg
                    bb_candle = None
                    for k in range(i1, i2 + 1):
                        if candles[k].is_bullish:
                            bb_candle = candles[k]

                    if bb_candle is None:
                        continue

                    top = bb_candle.high
                    bottom = bb_candle.low
                    zone_key = (SetupDirection.BULLISH.value, top, bottom)
                    if zone_key in seen_breaker_zones:
                        continue

                    # Confirm liquidity sweep at L2 (< L1) and structure break at H2 (> H1)
                    confirmed = False
                    for i3 in swing_lows:
                        if i3 <= i2:
                            continue
                        if candles[i3].low >= l1:  # Must sweep sellside liquidity below L1
                            continue

                        for i4 in swing_highs:
                            if i4 <= i3:
                                continue
                            if candles[i4].high <= h1:  # Must break market structure above H1
                                continue

                            seen_breaker_zones.add(zone_key)
                            mt = (top + bottom) / TWO
                            results.append(
                                PdArray(
                                    array_type=PdArrayType.BREAKER_BLOCK,
                                    timeframe=timeframe,
                                    top=top,
                                    bottom=bottom,
                                    mean_threshold=mt,
                                    direction=SetupDirection.BULLISH.value,
                                    creation_ts=candles[i4].timestamp_ms,
                                    known_from_ms=candles[min(n - 1, i4 + radius)].timestamp_ms
                                    + duration_ms,
                                    is_mitigated=False,
                                )
                            )
                            confirmed = True
                            break

                        if confirmed:
                            break

            # Bearish Breaker (-BB): H1 -> L1 -> H2 -> L2
            # H1 (swing high) -> L1 (swing low) -> H2 (sweep above H1) -> L2 (MSS break below L1)
            # The breaker block is the last down-close candle in the H1 -> L1 leg.
            for i1 in swing_highs:
                h1 = candles[i1].high
                for i2 in swing_lows:
                    if i2 <= i1:
                        continue
                    l1 = candles[i2].low
                    if l1 >= h1:
                        continue

                    # Locate last down-close candle in H1 -> L1 leg
                    bb_candle = None
                    for k in range(i1, i2 + 1):
                        if candles[k].is_bearish:
                            bb_candle = candles[k]

                    if bb_candle is None:
                        continue

                    top = bb_candle.high
                    bottom = bb_candle.low
                    zone_key = (SetupDirection.BEARISH.value, top, bottom)
                    if zone_key in seen_breaker_zones:
                        continue

                    # Confirm liquidity sweep at H2 (> H1) and structure break at L2 (< L1)
                    confirmed = False
                    for i3 in swing_highs:
                        if i3 <= i2:
                            continue
                        if candles[i3].high <= h1:  # Must sweep buyside liquidity above H1
                            continue

                        for i4 in swing_lows:
                            if i4 <= i3:
                                continue
                            if candles[i4].low >= l1:  # Must break market structure below L1
                                continue

                            seen_breaker_zones.add(zone_key)
                            mt = (top + bottom) / TWO
                            results.append(
                                PdArray(
                                    array_type=PdArrayType.BREAKER_BLOCK,
                                    timeframe=timeframe,
                                    top=top,
                                    bottom=bottom,
                                    mean_threshold=mt,
                                    direction=SetupDirection.BEARISH.value,
                                    creation_ts=candles[i4].timestamp_ms,
                                    known_from_ms=candles[min(n - 1, i4 + radius)].timestamp_ms
                                    + duration_ms,
                                    is_mitigated=False,
                                )
                            )
                            confirmed = True
                            break

                        if confirmed:
                            break

        # ---------------------------------------------------------------------
        # 4. Old Highs / Lows (BSL / SSL Liquidity Pools)
        # ---------------------------------------------------------------------
        if n >= 5:
            for i in range(2, n - 2):
                c = candles[i]
                # 5-bar fractal high
                if (
                    c.high > candles[i - 2].high
                    and c.high > candles[i - 1].high
                    and c.high > candles[i + 1].high
                    and c.high > candles[i + 2].high
                ):
                    results.append(
                        PdArray(
                            array_type=PdArrayType.OLD_HIGH,
                            timeframe=timeframe,
                            top=c.high,
                            bottom=c.high,
                            mean_threshold=c.high,
                            direction=SetupDirection.BEARISH.value,
                            creation_ts=c.timestamp_ms,
                            known_from_ms=candles[i + 2].timestamp_ms + duration_ms,
                            is_mitigated=False,
                        )
                    )
                # 5-bar fractal low
                if (
                    c.low < candles[i - 2].low
                    and c.low < candles[i - 1].low
                    and c.low < candles[i + 1].low
                    and c.low < candles[i + 2].low
                ):
                    results.append(
                        PdArray(
                            array_type=PdArrayType.OLD_LOW,
                            timeframe=timeframe,
                            top=c.low,
                            bottom=c.low,
                            mean_threshold=c.low,
                            direction=SetupDirection.BULLISH.value,
                            creation_ts=c.timestamp_ms,
                            known_from_ms=candles[i + 2].timestamp_ms + duration_ms,
                            is_mitigated=False,
                        )
                    )

        return tuple(results)

    def detect_cisd(
        self,
        candles: Sequence[Candle],
        reference_price: Decimal,
        direction: str,
    ) -> tuple[bool, Decimal | None]:
        """Detects Change in State of Delivery (CISD) with strict body close validation.

        Rules:
        - Bearish: Confirmed iff a candle body closes strictly below reference_price.
          Wick penetrations (low < ref but close >= ref) and equality (close == ref) are rejected.
        - Bullish: Confirmed iff a candle body closes strictly above reference_price.
          Wick penetrations (high > ref but close <= ref) and equality (close == ref) are rejected.
        """
        confirmation = self._first_cisd_confirmation(candles, reference_price, direction)
        if confirmation is not None:
            return True, reference_price
        return False, None

    @staticmethod
    def _first_cisd_confirmation(
        candles: Sequence[Candle], reference_price: Decimal, direction: str
    ) -> Candle | None:
        """Return the first closed candle confirming CISD, preserving its causal timestamp."""
        for candle in candles:
            if direction == SetupDirection.BEARISH.value:
                if candle.close < reference_price:
                    return candle
            elif direction == SetupDirection.BULLISH.value:
                if candle.close > reference_price:
                    return candle
        return None

    @staticmethod
    def _resolve_setup_direction(
        *,
        has_bearish_pda: bool,
        has_bullish_pda: bool,
        bearish_confirmation_ms: int | None,
        bullish_confirmation_ms: int | None,
    ) -> str | None:
        """Resolve opposing 5m candidates by confirmation time and reject unresolved ties."""
        if bearish_confirmation_ms is not None and bullish_confirmation_ms is not None:
            if bearish_confirmation_ms == bullish_confirmation_ms:
                return None
            return (
                SetupDirection.BEARISH.value
                if bearish_confirmation_ms > bullish_confirmation_ms
                else SetupDirection.BULLISH.value
            )
        if bearish_confirmation_ms is not None:
            return SetupDirection.BEARISH.value
        if bullish_confirmation_ms is not None:
            return SetupDirection.BULLISH.value
        if has_bearish_pda and not has_bullish_pda:
            return SetupDirection.BEARISH.value
        if has_bullish_pda and not has_bearish_pda:
            return SetupDirection.BULLISH.value
        return None

    def compute_stdv_targets(
        self,
        high: Decimal,
        low: Decimal,
        direction: str,
    ) -> dict[str, Decimal]:
        """Computes Fibonacci Standard Deviation extensions from manipulation leg.

        Projections: 1.0, 1.5, 2.0 (partial TP), 2.5, 4.0 (terminal exhaustion).
        Zero dealing range (high == low) is trapped without raising ZeroDivisionError.
        """
        d = high - low
        if d <= ZERO:
            return {
                "1.0": high,
                "1.5": high,
                "2.0": high,
                "2.5": high,
                "4.0": high,
            }

        if direction == SetupDirection.BEARISH.value:
            return {
                "1.0": high - STDV_1_0 * d,
                "1.5": high - STDV_1_5 * d,
                "2.0": high - STDV_2_0 * d,
                "2.5": high - STDV_2_5 * d,
                "4.0": high - STDV_4_0 * d,
            }
        else:
            return {
                "1.0": low + STDV_1_0 * d,
                "1.5": low + STDV_1_5 * d,
                "2.0": low + STDV_2_0 * d,
                "2.5": low + STDV_2_5 * d,
                "4.0": low + STDV_4_0 * d,
            }

    def resolve_terminus_target(
        self,
        raw_target: Decimal,
        opposing_pda_boundary: Decimal,
        direction: str,
    ) -> Decimal:
        """Caps the 4.0 STDV terminus target at the opposing HTF PDA boundary."""
        if direction == SetupDirection.BEARISH.value:
            return max(raw_target, opposing_pda_boundary)
        else:
            return min(raw_target, opposing_pda_boundary)

    @staticmethod
    def resolve_twins_stop_loss(
        *,
        direction: str,
        h_leg: Decimal,
        l_leg: Decimal,
        ote_79: Decimal,
        retracement_extreme: Decimal,
        tick_size: Decimal | None = None,
        stop_loss_mode: StopLossMode | str = StopLossMode.SWING_EXTREME,
    ) -> Decimal:
        """Resolves Twins stop loss per LumiTraders PDF p. 157.

        - StopLossMode.SWING_EXTREME (default): places stop loss beyond the 100%
          manipulation extreme (h_leg + buffer for BEARISH, l_leg - buffer for BULLISH).
        - StopLossMode.OTE_79_ADAPTIVE: if the 1m CISD retracement extreme occurs strictly
          before touching the 79% Fibonacci level, places stop loss right beyond 79% OTE;
          if the retracement touches 79% OTE, places stop loss beyond 100% (h_leg / l_leg).
        """
        buffer = tick_size * TWO if tick_size is not None and tick_size > ZERO else Decimal("1.00")
        adaptive = str(stop_loss_mode) == StopLossMode.OTE_79_ADAPTIVE.value

        if direction == SetupDirection.BEARISH.value:
            anchor = ote_79 if (adaptive and retracement_extreme < ote_79) else h_leg
            return anchor + buffer

        anchor = ote_79 if (adaptive and retracement_extreme > ote_79) else l_leg
        stop_loss = anchor - buffer
        if stop_loss <= ZERO:
            fallback_tick = (
                tick_size if (tick_size is not None and tick_size > ZERO) else Decimal("0.0001")
            )
            stop_loss = max(anchor * Decimal("0.99"), fallback_tick)
        return stop_loss

    @staticmethod
    def evaluate_quarterly_time_window(
        timestamp_ms: int,
        *,
        utc_offset_hours: int = -5,
    ) -> QuarterlyCycleSnapshot:
        """Evaluates ICT Killzones, 6-hour Quarters, & Twins Windows (PDF pp. 31, 63, 99, 146)."""
        shifted_ms = timestamp_ms + utc_offset_hours * 3_600_000
        day_ms = shifted_ms % 86_400_000
        total_minutes = int(day_ms // 60_000)
        ny_hour = total_minutes // 60
        ny_minute = total_minutes % 60

        if 18 <= ny_hour < 24:
            quarter = QuarterlyCyclePhase.Q1_ACCUMULATION
        elif 0 <= ny_hour < 6:
            quarter = QuarterlyCyclePhase.Q2_MANIPULATION
        elif 6 <= ny_hour < 12:
            quarter = QuarterlyCyclePhase.Q3_DISTRIBUTION
        else:
            quarter = QuarterlyCyclePhase.Q4_CONTINUATION_REVERSAL

        # Manipulation windows within Q2 (01:30-03:00 NY) & Q3 (07:30-09:00 NY) (PDF p. 99)
        in_manip = (90 <= total_minutes < 180) or (450 <= total_minutes < 540)
        # Distribution windows within Q2 (03:00-04:30 NY) & Q3 (09:00-10:30 NY) (PDF p. 99)
        in_dist = (180 <= total_minutes < 270) or (540 <= total_minutes < 630)
        # Twins high-probability windows: AM (08:15-10:30 NY) & PM (13:30-15:00 NY) (PDF p. 146)
        in_twins_am = 495 <= total_minutes <= 630
        in_twins_pm = 810 <= total_minutes <= 900

        # ICT Killzones (PDF p. 31)
        if 20 <= ny_hour < 24:
            killzone: Literal["ASIA", "LONDON", "NY_AM", "LONDON_CLOSE", "NONE"] = "ASIA"
        elif 2 <= ny_hour < 5:
            killzone = "LONDON"
        elif 7 <= ny_hour < 10:
            killzone = "NY_AM"
        elif 10 <= ny_hour < 12:
            killzone = "LONDON_CLOSE"
        else:
            killzone = "NONE"

        return QuarterlyCycleSnapshot(
            timestamp_ms=timestamp_ms,
            ny_hour=ny_hour,
            ny_minute=ny_minute,
            daily_quarter=quarter,
            in_manipulation_window=in_manip,
            in_distribution_window=in_dist,
            in_twins_am_window=in_twins_am,
            in_twins_pm_window=in_twins_pm,
            active_killzone=killzone,
        )

    @staticmethod
    def compute_intraday_bias(
        candles: Sequence[Candle],
        *,
        utc_offset_hours: int = -5,
    ) -> IntradayBiasSnapshot:
        """Computes LumiTraders Intraday Bias: NYMO, PDH/PDL, EQ of PDR, Asia/London."""
        if not candles:
            return IntradayBiasSnapshot()

        offset_ms = utc_offset_hours * 3_600_000
        latest = candles[-1]
        current_ny_day = (latest.timestamp_ms + offset_ms) // 86_400_000
        prev_ny_day = current_ny_day - 1

        prev_day_candles: list[Candle] = []
        curr_day_candles: list[Candle] = []
        asia_candles: list[Candle] = []
        london_candles: list[Candle] = []

        for c in candles:
            shifted = c.timestamp_ms + offset_ms
            ny_day = shifted // 86_400_000
            ny_hour = int((shifted % 86_400_000) // 3_600_000)
            if ny_day == prev_ny_day:
                prev_day_candles.append(c)
                if 20 <= ny_hour < 24:
                    asia_candles.append(c)
            elif ny_day == current_ny_day:
                curr_day_candles.append(c)
                if 2 <= ny_hour < 5:
                    london_candles.append(c)

        nymo = curr_day_candles[0].open if curr_day_candles else None
        pdh = max((c.high for c in prev_day_candles), default=None)
        pdl = min((c.low for c in prev_day_candles), default=None)
        pdr_eq = (pdh + pdl) / TWO if (pdh is not None and pdl is not None) else None

        asia_high = max((c.high for c in asia_candles), default=None)
        asia_low = min((c.low for c in asia_candles), default=None)
        london_high = max((c.high for c in london_candles), default=None)
        london_low = min((c.low for c in london_candles), default=None)

        pdh_swept = bool(pdh is not None and any(c.high > pdh for c in curr_day_candles))
        pdl_swept = bool(pdl is not None and any(c.low < pdl for c in curr_day_candles))

        pdr_zone: Literal["PREMIUM", "DISCOUNT", "EQUILIBRIUM", "UNKNOWN"] = "UNKNOWN"
        if pdr_eq is not None:
            if latest.close > pdr_eq:
                pdr_zone = "PREMIUM"
            elif latest.close < pdr_eq:
                pdr_zone = "DISCOUNT"
            else:
                pdr_zone = "EQUILIBRIUM"

        nymo_zone: Literal["ABOVE_NYMO", "BELOW_NYMO", "AT_NYMO", "UNKNOWN"] = "UNKNOWN"
        if nymo is not None:
            if latest.close > nymo:
                nymo_zone = "ABOVE_NYMO"
            elif latest.close < nymo:
                nymo_zone = "BELOW_NYMO"
            else:
                nymo_zone = "AT_NYMO"

        return IntradayBiasSnapshot(
            ny_midnight_open=nymo,
            pdh=pdh,
            pdl=pdl,
            pdr_equilibrium=pdr_eq,
            asia_high=asia_high,
            asia_low=asia_low,
            london_high=london_high,
            london_low=london_low,
            pdh_swept=pdh_swept,
            pdl_swept=pdl_swept,
            pdr_zone=pdr_zone,
            nymo_zone=nymo_zone,
        )

    def compute_measuring_gap(
        self,
        candles: Sequence[Candle],
        *,
        anchor_high: Decimal,
        anchor_low: Decimal,
        direction: str,
        timeframe: str = "5m",
    ) -> MeasuringGapProjection | None:
        """Detects a Measuring Gap near the 50% midpoint and projects 100% terminus."""
        delta = anchor_high - anchor_low
        if delta <= ZERO or len(candles) < 3:
            return None

        target_type = (
            PdArrayType.FVG_SIBI
            if direction == SetupDirection.BEARISH.value
            else PdArrayType.FVG_BISI
        )
        pdas = [
            p
            for p in self.detect_pd_arrays(candles, timeframe)
            if p.array_type == target_type and p.direction == direction
        ]
        if not pdas:
            return None

        best_pda: PdArray | None = None
        best_ratio = ZERO
        best_dist = Decimal("999")

        for pda in pdas:
            ratio = (
                (anchor_high - pda.mean_threshold) / delta
                if direction == SetupDirection.BEARISH.value
                else (pda.mean_threshold - anchor_low) / delta
            )
            if Decimal("0.35") <= ratio <= Decimal("0.65"):
                dist = abs(ratio - FIB_500)
                if dist < best_dist:
                    best_dist = dist
                    best_pda = pda
                    best_ratio = ratio

        if best_pda is None:
            return None

        if direction == SetupDirection.BEARISH.value:
            half_leg = anchor_high - best_pda.mean_threshold
            terminus = anchor_high - TWO * half_leg
        else:
            half_leg = best_pda.mean_threshold - anchor_low
            terminus = anchor_low + TWO * half_leg

        return MeasuringGapProjection(
            fvg=best_pda,
            anchor_high=anchor_high,
            anchor_low=anchor_low,
            direction=direction,
            gap_midpoint_ratio=best_ratio,
            projected_terminus=terminus,
        )

    def evaluate_twins_setup(
        self,
        symbol: str,
        candles_4h: Sequence[Candle],
        candles_1h: Sequence[Candle],
        candles_15m: Sequence[Candle],
        candles_5m: Sequence[Candle],
        candles_1m: Sequence[Candle],
        tick_size: Decimal | None = None,
        stop_loss_mode: StopLossMode | str = StopLossMode.SWING_EXTREME,
    ) -> TwinsSetupState:
        """Evaluates multi-timeframe candle streams across the 6-step mechanical sequence.

        Steps:
        1. Step 1: Detect HTF PDA tap (15m/1h/4h) aligned with market displacement direction.
        2. Step 2: Detect 5m CISD; establish anchored manipulation dealing range.
        3. Step 3: Detect >= 2 distinct 1m FVGs during 5m displacement leg.
        4. Step 4: Validate OTE retracement (62%-79%) with Twin FVG confluence.
        5. Step 5: Validate 1m CISD confirmation inside OTE with follow-through retention.
        6. Step 6: Structure SL, TP1 (2.0 STDV), TP2 (Terminus) and verify R:R >= 1.5.
        """
        if not candles_5m or not candles_1m:
            return TwinsSetupState(symbol=symbol, step=TwinsStep.IDLE)

        # ---------------------------------------------------------------------
        # Step 1: Detect HTF Level Hit (Aligned with Market Displacement)
        # ---------------------------------------------------------------------
        htf_pdas: list[PdArray] = []
        if candles_4h:
            htf_pdas.extend(self.detect_pd_arrays(candles_4h, "4h"))
        if candles_1h:
            htf_pdas.extend(self.detect_pd_arrays(candles_1h, "1h"))
        if candles_15m:
            htf_pdas.extend(self.detect_pd_arrays(candles_15m, "15m"))

        # Query every PDA against the ordered closed-candle series in one indexed pass.
        # This preserves the original inclusive overlap and known-from boundaries while
        # avoiding a full candle scan for each of the often hundreds of HTF arrays.
        touched = touched_pd_arrays(htf_pdas, candles_5m)
        bearish_pdas: list[PdArray] = []
        bullish_pdas: list[PdArray] = []
        for pda, is_touched in zip(htf_pdas, touched, strict=True):
            if not is_touched:
                continue
            if pda.direction == SetupDirection.BEARISH.value:
                bearish_pdas.append(pda)
            elif pda.direction == SetupDirection.BULLISH.value:
                bullish_pdas.append(pda)

        def touches(pda: PdArray, candle: Candle) -> bool:
            return (
                (pda.known_from_ms is None or candle.timestamp_ms >= pda.known_from_ms)
                and candle.high >= pda.bottom
                and candle.low <= pda.top
            )

        hit_pda: PdArray | None = None
        direction: str | None = None

        # Check directional displacement on 5m candles
        bearish_confirmation: Candle | None = None
        bullish_confirmation: Candle | None = None

        if bearish_pdas:
            max_h = max(c.high for c in candles_5m)
            ref_b = next((c for c in candles_5m if c.high == max_h), None)
            if ref_b is not None:
                post_ref_b = [c for c in candles_5m if c.timestamp_ms > ref_b.timestamp_ms]
                bearish_confirmation = self._first_cisd_confirmation(
                    post_ref_b, ref_b.low, SetupDirection.BEARISH.value
                )

        if bullish_pdas:
            min_l = min(c.low for c in candles_5m)
            ref_u = next((c for c in candles_5m if c.low == min_l), None)
            if ref_u is not None:
                post_ref_u = [c for c in candles_5m if c.timestamp_ms > ref_u.timestamp_ms]
                bullish_confirmation = self._first_cisd_confirmation(
                    post_ref_u, ref_u.high, SetupDirection.BULLISH.value
                )

        # Confirmed displacement resolves simultaneous PDA directions. A same-candle tie
        # has no causal ordering, so it is rejected instead of receiving a bearish bias.
        direction = self._resolve_setup_direction(
            has_bearish_pda=bool(bearish_pdas),
            has_bullish_pda=bool(bullish_pdas),
            bearish_confirmation_ms=(
                bearish_confirmation.timestamp_ms if bearish_confirmation is not None else None
            ),
            bullish_confirmation_ms=(
                bullish_confirmation.timestamp_ms if bullish_confirmation is not None else None
            ),
        )

        # Select the PDA aligned with the resolved displacement. A single-direction PDA
        # can still enter Step 2, where the full anchored CISD check remains mandatory.
        if direction == SetupDirection.BEARISH.value and bearish_pdas:
            hit_pda = bearish_pdas[0]
        elif direction == SetupDirection.BULLISH.value and bullish_pdas:
            hit_pda = bullish_pdas[0]
        else:
            direction = None

        if hit_pda is None or direction is None:
            return TwinsSetupState(
                symbol=symbol,
                step_1_htf_hit=False,
                step=TwinsStep.IDLE,
            )

        # ---------------------------------------------------------------------
        # Step 2: 5m CISD Formed (Anchored Dealing Range)
        # ---------------------------------------------------------------------
        ref_5m_candle: Candle | None = None
        m5_cisd_price: Decimal | None = None
        m5_cisd_confirmed = False
        h_leg = ZERO
        l_leg = ZERO

        if direction == SetupDirection.BEARISH.value:
            # Anchor peak to the highest candle that interacted with HTF PDA or subsequent run
            pda_touches = [c for c in candles_5m if touches(hit_pda, c)]
            first_touch_ts = (
                pda_touches[0].timestamp_ms if pda_touches else candles_5m[0].timestamp_ms
            )
            relevant_5m = [c for c in candles_5m if c.timestamp_ms >= first_touch_ts]
            ref_5m_candle = max(relevant_5m, key=lambda c: c.high)

            m5_cisd_price = ref_5m_candle.low
            cisd_candles = [c for c in candles_5m if c.timestamp_ms > ref_5m_candle.timestamp_ms]
            m5_cisd_confirmed, _ = self.detect_cisd(cisd_candles, m5_cisd_price, direction)

            h_leg = ref_5m_candle.high
            # Anchor l_leg strictly to the displacement run AFTER the manipulation peak
            if cisd_candles:
                l_leg = min(c.low for c in cisd_candles)
            else:
                l_leg = ref_5m_candle.low
        else:
            pda_touches = [c for c in candles_5m if touches(hit_pda, c)]
            first_touch_ts = (
                pda_touches[0].timestamp_ms if pda_touches else candles_5m[0].timestamp_ms
            )
            relevant_5m = [c for c in candles_5m if c.timestamp_ms >= first_touch_ts]
            ref_5m_candle = min(relevant_5m, key=lambda c: c.low)

            m5_cisd_price = ref_5m_candle.high
            cisd_candles = [c for c in candles_5m if c.timestamp_ms > ref_5m_candle.timestamp_ms]
            m5_cisd_confirmed, _ = self.detect_cisd(cisd_candles, m5_cisd_price, direction)

            l_leg = ref_5m_candle.low
            # Anchor h_leg strictly to the displacement run AFTER the manipulation trough
            if cisd_candles:
                h_leg = max(c.high for c in cisd_candles)
            else:
                h_leg = ref_5m_candle.high

        if not m5_cisd_confirmed or m5_cisd_price is None:
            return TwinsSetupState(
                symbol=symbol,
                step_1_htf_hit=True,
                step_2_m5_cisd=False,
                active_pda=hit_pda,
                step=TwinsStep.STEP_1_HTF_HIT,
            )

        delta = h_leg - l_leg
        if delta <= ZERO:
            return TwinsSetupState(
                symbol=symbol,
                step_1_htf_hit=True,
                step_2_m5_cisd=True,
                active_pda=hit_pda,
                m5_cisd_price=m5_cisd_price,
                invalidation_reason=InvalidationReason.DEALING_RANGE_INVALID,
                step=TwinsStep.STEP_2_M5_CISD,
            )

        # ---------------------------------------------------------------------
        # Step 3: Two 1m FVGs within 5m Displacement Leg ("The Twins")
        # ---------------------------------------------------------------------
        # Filter 1m candles bounded between ref_5m_candle and displacement extreme
        eligible_1m = [c1 for c1 in candles_1m if c1.timestamp_ms >= ref_5m_candle.timestamp_ms]
        if not eligible_1m:
            eligible_1m = list(candles_1m)

        m1_displacement: list[Candle] = []
        post_displacement: list[Candle] = []

        if direction == SetupDirection.BEARISH.value:
            trough_idx = -1
            for idx, c1 in enumerate(eligible_1m):
                if c1.low == l_leg:
                    trough_idx = idx
                    break

            if trough_idx >= 0:
                m1_displacement = list(eligible_1m[: trough_idx + 1])
                post_displacement = list(eligible_1m[trough_idx + 1 :])
            else:
                m1_displacement = list(eligible_1m)
                post_displacement = []
        else:
            peak_idx = -1
            for idx, c1 in enumerate(eligible_1m):
                if c1.high == h_leg:
                    peak_idx = idx
                    break

            if peak_idx >= 0:
                m1_displacement = list(eligible_1m[: peak_idx + 1])
                post_displacement = list(eligible_1m[peak_idx + 1 :])
            else:
                m1_displacement = list(eligible_1m)
                post_displacement = []

        # Count distinct non-overlapping FVGs in displacement leg (PDF pp. 143, 152, 176)
        twins_fvgs: list[PdArray] = []
        last_fvg_idx = -999

        if direction == SetupDirection.BEARISH.value:
            for i in range(2, len(m1_displacement)):
                if i > last_fvg_idx + 1:
                    c_prev2 = m1_displacement[i - 2]
                    c_curr = m1_displacement[i]
                    if c_curr.high < c_prev2.low:
                        bottom = c_curr.high
                        top = c_prev2.low
                        mt = (top + bottom) / TWO
                        twins_fvgs.append(
                            PdArray(
                                array_type=PdArrayType.FVG_SIBI,
                                timeframe="1m",
                                top=top,
                                bottom=bottom,
                                mean_threshold=mt,
                                direction=direction,
                                creation_ts=c_curr.timestamp_ms,
                            )
                        )
                        last_fvg_idx = i
        else:
            for i in range(2, len(m1_displacement)):
                if i > last_fvg_idx + 1:
                    c_prev2 = m1_displacement[i - 2]
                    c_curr = m1_displacement[i]
                    if c_curr.low > c_prev2.high:
                        bottom = c_prev2.high
                        top = c_curr.low
                        mt = (top + bottom) / TWO
                        twins_fvgs.append(
                            PdArray(
                                array_type=PdArrayType.FVG_BISI,
                                timeframe="1m",
                                top=top,
                                bottom=bottom,
                                mean_threshold=mt,
                                direction=direction,
                                creation_ts=c_curr.timestamp_ms,
                            )
                        )
                        last_fvg_idx = i

        has_twin_fvgs = len(twins_fvgs) >= 2
        if not has_twin_fvgs:
            return TwinsSetupState(
                symbol=symbol,
                step_1_htf_hit=True,
                step_2_m5_cisd=True,
                step_3_twins_fvg=False,
                active_pda=hit_pda,
                m5_cisd_price=m5_cisd_price,
                invalidation_reason=InvalidationReason.NO_TWIN_FVGS,
                step=TwinsStep.STEP_2_M5_CISD,
            )

        # ---------------------------------------------------------------------
        # Step 4: OTE Retracement (Equilibrium / OTE Fibonacci Range)
        # ---------------------------------------------------------------------
        lower_ratio = self.ote_lower
        upper_ratio = getattr(self, "ote_upper", FIB_786) or FIB_786

        if direction == SetupDirection.BEARISH.value:
            ote_lower_lvl = l_leg + lower_ratio * delta
            ote_62 = ote_lower_lvl
            ote_705 = l_leg + self.ote_sweet_spot * delta
            ote_79 = l_leg + upper_ratio * delta
            ote_886 = l_leg + FIB_886 * delta

            reached_ote = any(c.high >= ote_lower_lvl for c in post_displacement)
            invalidated_ote = any(
                c.close > ote_79 or c.high > ote_886 or c.high > h_leg for c in post_displacement
            )
        else:
            ote_lower_lvl = h_leg - lower_ratio * delta
            ote_62 = ote_lower_lvl
            ote_705 = h_leg - self.ote_sweet_spot * delta
            ote_79 = h_leg - upper_ratio * delta
            ote_886 = h_leg - FIB_886 * delta

            reached_ote = any(c.low <= ote_lower_lvl for c in post_displacement)
            invalidated_ote = any(
                c.close < ote_79 or c.low < ote_886 or c.low < l_leg for c in post_displacement
            )

        if not reached_ote or invalidated_ote:
            reason = (
                InvalidationReason.OTE_OVERSHOOT
                if invalidated_ote
                else InvalidationReason.TIMEOUT_OTE_RETRACE
            )
            return TwinsSetupState(
                symbol=symbol,
                step_1_htf_hit=True,
                step_2_m5_cisd=True,
                step_3_twins_fvg=True,
                step_4_ote_retrace=False,
                active_pda=hit_pda,
                m5_cisd_price=m5_cisd_price,
                ote_62=ote_62,
                ote_705=ote_705,
                ote_79=ote_79,
                invalidation_reason=reason,
                step=TwinsStep.STEP_3_TWINS_FVG,
            )

        # ---------------------------------------------------------------------
        # Step 5: Formation of 1-minute CISD Confirmation inside OTE
        # ---------------------------------------------------------------------
        m1_cisd_price: Decimal | None = None
        m1_cisd_confirmed = False
        confirmation_ms: int | None = None
        retracement_extreme = h_leg if direction == SetupDirection.BEARISH.value else l_leg

        if direction == SetupDirection.BEARISH.value:
            ote_candidates = [c for c in post_displacement if c.high >= ote_lower_lvl]
            if ote_candidates:
                ote_high_candle = max(ote_candidates, key=lambda c: c.high)
                retracement_extreme = ote_high_candle.high
                m1_cisd_price = ote_high_candle.low
                confirm_candles = [
                    c for c in post_displacement if c.timestamp_ms > ote_high_candle.timestamp_ms
                ]
                if confirm_candles:
                    m1_cisd_confirmed, _ = self.detect_cisd(
                        confirm_candles, m1_cisd_price, direction
                    )
        else:
            ote_candidates = [c for c in post_displacement if c.low <= ote_lower_lvl]
            if ote_candidates:
                ote_low_candle = min(ote_candidates, key=lambda c: c.low)
                retracement_extreme = ote_low_candle.low
                m1_cisd_price = ote_low_candle.high
                confirm_candles = [
                    c for c in post_displacement if c.timestamp_ms > ote_low_candle.timestamp_ms
                ]
                if confirm_candles:
                    m1_cisd_confirmed, _ = self.detect_cisd(
                        confirm_candles, m1_cisd_price, direction
                    )

        if m1_cisd_confirmed and m1_cisd_price is not None:
            confirmations = [
                c
                for c in confirm_candles
                if (
                    c.close < m1_cisd_price
                    if direction == SetupDirection.BEARISH.value
                    else c.close > m1_cisd_price
                )
            ]
            confirmation_ms = confirmations[0].timestamp_ms + 60_000
            latest_close = candles_1m[-1].close
            m1_cisd_confirmed = (
                latest_close < m1_cisd_price
                if direction == SetupDirection.BEARISH.value
                else latest_close > m1_cisd_price
            )

        if not m1_cisd_confirmed or m1_cisd_price is None:
            return TwinsSetupState(
                symbol=symbol,
                step_1_htf_hit=True,
                step_2_m5_cisd=True,
                step_3_twins_fvg=True,
                step_4_ote_retrace=True,
                step_5_m1_cisd=False,
                active_pda=hit_pda,
                m5_cisd_price=m5_cisd_price,
                ote_62=ote_62,
                ote_705=ote_705,
                ote_79=ote_79,
                m1_cisd_price=m1_cisd_price,
                invalidation_reason=InvalidationReason.M1_CISD_TIMEOUT,
                step=TwinsStep.STEP_4_OTE_RETRACE,
            )

        # ---------------------------------------------------------------------
        # Step 6: Bracket Structuring & Low-Price Asset Protection
        # ---------------------------------------------------------------------
        stdv_targets = self.compute_stdv_targets(h_leg, l_leg, direction)
        stdv_2_0 = stdv_targets["2.0"]
        stdv_4_0 = stdv_targets["4.0"]

        opposing_direction = (
            SetupDirection.BULLISH.value
            if direction == SetupDirection.BEARISH.value
            else SetupDirection.BEARISH.value
        )
        opposing_pdas = [p for p in htf_pdas if p.direction == opposing_direction]

        take_profit_final = stdv_4_0
        if opposing_pdas:
            if direction == SetupDirection.BEARISH.value:
                opp_top = max(p.top for p in opposing_pdas)
                take_profit_final = self.resolve_terminus_target(
                    raw_target=stdv_4_0,
                    opposing_pda_boundary=opp_top,
                    direction=direction,
                )
            else:
                opp_bottom = min(p.bottom for p in opposing_pdas)
                take_profit_final = self.resolve_terminus_target(
                    raw_target=stdv_4_0,
                    opposing_pda_boundary=opp_bottom,
                    direction=direction,
                )

        # Low-Price Asset Proportional Buffer & Stop Loss Mode Calculation (PDF p. 157)
        stop_loss = self.resolve_twins_stop_loss(
            direction=direction,
            h_leg=h_leg,
            l_leg=l_leg,
            ote_79=ote_79,
            retracement_extreme=retracement_extreme,
            tick_size=tick_size,
            stop_loss_mode=stop_loss_mode,
        )
        side: Literal["BUY", "SELL"] = (
            "SELL" if direction == SetupDirection.BEARISH.value else "BUY"
        )

        projections = StdvProjections(
            anchor_high=h_leg,
            anchor_low=l_leg,
            dealing_range=delta,
            direction=direction,
            target_1_0=stdv_targets["1.0"],
            target_1_5=stdv_targets["1.5"],
            target_2_0=stdv_2_0,
            target_2_5=stdv_targets["2.5"],
            target_4_0=stdv_4_0,
            terminus=take_profit_final,
        )

        return TwinsSetupState(
            symbol=symbol,
            step_1_htf_hit=True,
            step_2_m5_cisd=True,
            step_3_twins_fvg=True,
            step_4_ote_retrace=True,
            step_5_m1_cisd=True,
            step_6_ready=True,
            confirmation_ms=confirmation_ms,
            active_pda=hit_pda,
            m5_cisd_price=m5_cisd_price,
            m1_cisd_price=m1_cisd_price,
            ote_62=ote_62,
            ote_705=ote_705,
            ote_79=ote_79,
            stdv_2_0=stdv_2_0,
            stdv_4_0=stdv_4_0,
            stop_loss=stop_loss,
            take_profit_partial=stdv_2_0,
            take_profit_final=take_profit_final,
            side=side,
            projections=projections,
            step=TwinsStep.STEP_6_READY,
            invalidation_reason=InvalidationReason.NONE,
        )
