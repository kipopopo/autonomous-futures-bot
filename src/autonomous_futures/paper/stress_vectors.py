"""Phase 255: Deterministic Multi-Vector Synthetic Market Shock Injector.

Injects calibrated adverse market shocks onto canonical 5m Parquet market data:
- Vector 1: Flash Crash Wicks & Adverse Opening Gaps (-10% to -25% intra-bar adverse drops).
- Vector 2: Severe Liquidity Dry-Ups & Slippage Surges (10x to 50x baseline, up to 200 bps).
- Vector 3: Bid-Ask Spread Blowouts (5x to 20x baseline, 10 to 40 bps total friction).
- Vector 4: High-Frequency Volatility Spikes & Rapid Whipsaws (alternating intra-bar spikes).
- Vector 5: Composite Combined Crisis (flash crash + 50x slippage + 20x spread + whipsaws).

All injected DataFrames strictly pass canonicalize_bars(interval=timedelta(minutes=5)).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from autonomous_futures.data.parquet import canonicalize_bars


class ShockType(StrEnum):
    """Calibrated adverse market shock types for stress testing."""

    FLASH_CRASH = "flash_crash"
    SLIPPAGE_SURGE = "slippage_surge"
    SPREAD_BLOWOUT = "spread_blowout"
    VOLATILITY_WHIPSAW = "volatility_whipsaw"
    COMPOSITE_CRISIS = "composite_crisis"


StrictPositiveDecimal = Annotated[Decimal, Field(strict=True, gt=Decimal("0"))]
StrictNonNegativeDecimal = Annotated[Decimal, Field(strict=True, ge=Decimal("0"))]


class MarketShockSpec(BaseModel):
    """Specification defining parameters for synthetic market shock injection."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    shock_type: ShockType
    drop_fraction: Decimal = Field(default=Decimal("-0.15"))
    slippage_multiplier: Decimal = Field(default=Decimal("25"), ge=Decimal("1"), le=Decimal("100"))
    spread_multiplier: Decimal = Field(default=Decimal("10"), ge=Decimal("1"), le=Decimal("50"))
    target_symbols: tuple[str, ...] = Field(default=("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"))
    start_bar_index: int = Field(default=500, ge=0)
    duration_bars: int = Field(default=12, ge=1)

    @field_validator("drop_fraction")
    @classmethod
    def validate_drop_fraction(cls, v: Decimal) -> Decimal:
        abs_v = abs(v)
        if not (Decimal("0.05") <= abs_v <= Decimal("0.50")):
            raise ValueError(
                f"drop_fraction magnitude must be between 0.05 (5%) and 0.50 (50%), got {v}"
            )
        return v


class SyntheticMarketShockInjector:
    """Deterministic injector applying calibrated distress vectors to 5m market data."""

    @staticmethod
    def inject_flash_crash(
        df: pd.DataFrame,
        start_idx: int,
        drop_pct: Decimal | float,
        wick_only: bool = False,
    ) -> pd.DataFrame:
        """Inject an adverse intra-bar flash crash (-10% to -25% price drop).

        If wick_only is True, only the intra-bar low plunges, modeling an adverse wick that
        recovers within the same candle.
        If wick_only is False, the entire candle drops (open, low, close), modeling an adverse gap
        or crash that remains depressed.
        """
        if not (0 <= start_idx < len(df)):
            raise ValueError(
                f"start_idx {start_idx} out of range for DataFrame of length {len(df)}"
            )

        abs_drop = abs(Decimal(str(drop_pct)))
        if not (Decimal("0.05") <= abs_drop <= Decimal("0.50")):
            raise ValueError(f"drop_pct magnitude must be between 0.05 and 0.50, got {drop_pct}")

        df_mod = df.copy()

        # Retrieve current prices at start_idx as Decimals
        open_val = Decimal(str(df_mod.at[start_idx, "open"]))
        high_val = Decimal(str(df_mod.at[start_idx, "high"]))
        low_val = Decimal(str(df_mod.at[start_idx, "low"]))
        close_val = Decimal(str(df_mod.at[start_idx, "close"]))

        if wick_only:
            # Wick plunges, but open/close remain in place
            new_low = low_val * (Decimal("1.0") - abs_drop)
            new_open = open_val
            new_close = close_val
            new_high = max(high_val, new_open, new_close)
        else:
            # Full adverse drop: open, close, and low drop
            multiplier = Decimal("1.0") - abs_drop
            new_open = open_val * multiplier
            new_close = close_val * multiplier
            new_low = min(low_val * multiplier, new_open, new_close)
            new_high = max(new_open, new_close, high_val * multiplier)

        # Enforce valid OHLC invariant: low <= min(open, close), high >= max(open, close)
        new_low = min(new_low, new_open, new_close)
        new_high = max(new_high, new_open, new_close)

        df_mod.at[start_idx, "open"] = new_open
        df_mod.at[start_idx, "high"] = new_high
        df_mod.at[start_idx, "low"] = new_low
        df_mod.at[start_idx, "close"] = new_close

        return canonicalize_bars(df_mod, interval=timedelta(minutes=5))

    @staticmethod
    def inject_slippage_surge(
        df: pd.DataFrame,
        multiplier: Decimal | int | float,
    ) -> pd.DataFrame:
        """Inject severe execution slippage surge (10x to 50x baseline, up to 200 bps).

        Annotates DataFrame columns and attributes while preserving canonical 5m bar structure.
        """
        mult_dec = Decimal(str(multiplier))
        if mult_dec < Decimal("1.0"):
            raise ValueError(f"multiplier must be >= 1.0, got {multiplier}")

        df_mod = df.copy()
        df_mod["slippage_multiplier"] = mult_dec
        # Baseline slippage is 2.0 bps
        df_mod["slippage_bps"] = Decimal("2.0") * mult_dec
        df_mod.attrs["slippage_multiplier"] = mult_dec
        df_mod.attrs["slippage_bps"] = Decimal("2.0") * mult_dec

        return canonicalize_bars(df_mod, interval=timedelta(minutes=5))

    @staticmethod
    def inject_spread_blowout(
        df: pd.DataFrame,
        multiplier: Decimal | int | float,
    ) -> pd.DataFrame:
        """Inject severe bid-ask spread blowout (5x to 20x baseline, 10 to 40 bps).

        Annotates DataFrame columns and attributes while preserving canonical 5m bar structure.
        """
        mult_dec = Decimal(str(multiplier))
        if mult_dec < Decimal("1.0"):
            raise ValueError(f"multiplier must be >= 1.0, got {multiplier}")

        df_mod = df.copy()
        df_mod["spread_multiplier"] = mult_dec
        # Baseline spread is 2.0 bps
        df_mod["spread_bps"] = Decimal("2.0") * mult_dec
        df_mod.attrs["spread_multiplier"] = mult_dec
        df_mod.attrs["spread_bps"] = Decimal("2.0") * mult_dec

        return canonicalize_bars(df_mod, interval=timedelta(minutes=5))

    @staticmethod
    def inject_whipsaws(
        df: pd.DataFrame,
        start_idx: int,
        num_bars: int,
        oscillation_pct: Decimal | float,
    ) -> pd.DataFrame:
        """Inject high-frequency volatility spikes and rapid whipsaws over consecutive bars.

        Alternates between large upward surges and sharp downward plunges, surging ATR
        while strictly preserving continuous canonical 5m bar formatting.
        """
        if not (0 <= start_idx < len(df)):
            raise ValueError(
                f"start_idx {start_idx} out of range for DataFrame of length {len(df)}"
            )
        if num_bars < 1:
            raise ValueError(f"num_bars must be >= 1, got {num_bars}")
        if start_idx + num_bars > len(df):
            raise ValueError(
                f"start_idx {start_idx} + num_bars {num_bars} exceeds length {len(df)}"
            )

        osc = abs(Decimal(str(oscillation_pct)))
        if not (Decimal("0.01") <= osc <= Decimal("0.30")):
            raise ValueError(
                f"oscillation_pct magnitude must be in [0.01, 0.30], got {oscillation_pct}"
            )

        df_mod = df.copy()

        for k in range(num_bars):
            idx = start_idx + k
            prior_close = (
                Decimal(str(df_mod.at[idx - 1, "close"]))
                if idx > 0
                else Decimal(str(df_mod.at[idx, "open"]))
            )

            if k % 2 == 0:
                # Upward whipsaw spike
                new_open = prior_close
                new_high = new_open * (Decimal("1.0") + osc)
                new_low = new_open * (Decimal("1.0") - osc * Decimal("0.2"))
                new_close = new_open * (Decimal("1.0") + osc * Decimal("0.8"))
            else:
                # Downward whipsaw plunge
                new_open = prior_close
                new_high = new_open * (Decimal("1.0") + osc * Decimal("0.2"))
                new_low = new_open * (Decimal("1.0") - osc)
                new_close = new_open * (Decimal("1.0") - osc * Decimal("0.8"))

            new_low = min(new_low, new_open, new_close)
            new_high = max(new_high, new_open, new_close)

            df_mod.at[idx, "open"] = new_open
            df_mod.at[idx, "high"] = new_high
            df_mod.at[idx, "low"] = new_low
            df_mod.at[idx, "close"] = new_close

        return canonicalize_bars(df_mod, interval=timedelta(minutes=5))

    # Support alias inject_whipsaw (singular)
    inject_whipsaw = inject_whipsaws

    @classmethod
    def inject_composite_crisis(
        cls,
        df: pd.DataFrame,
        start_idx: int,
    ) -> pd.DataFrame:
        """Inject combined multi-vector crisis shock onto historical 5m market data.

        Simultaneously injects:
        - 1. Flash crash wick & gap drop (-20%) at start_idx
        - 2. High-frequency whipsaws for 8 bars immediately following start_idx
        - 3. 50x slippage surge (100 bps)
        - 4. 20x spread blowout (40 bps)
        """
        # Step 1: Flash crash
        df_shocked = cls.inject_flash_crash(
            df, start_idx=start_idx, drop_pct=Decimal("0.20"), wick_only=False
        )

        # Step 2: Whipsaws
        whipsaw_bars = min(8, len(df) - (start_idx + 1))
        if whipsaw_bars > 0:
            df_shocked = cls.inject_whipsaws(
                df_shocked,
                start_idx=start_idx + 1,
                num_bars=whipsaw_bars,
                oscillation_pct=Decimal("0.06"),
            )

        # Step 3: Slippage surge (50x)
        df_shocked = cls.inject_slippage_surge(df_shocked, multiplier=Decimal("50"))

        # Step 4: Spread blowout (20x)
        df_shocked = cls.inject_spread_blowout(df_shocked, multiplier=Decimal("20"))

        return df_shocked
