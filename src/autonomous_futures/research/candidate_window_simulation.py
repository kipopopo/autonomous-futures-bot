from __future__ import annotations

from datetime import timedelta

import pandas as pd

from ..data.parquet import DataQualityError
from ..data.verified_funding import VerifiedFundingSlice
from .creator_artifacts import CreatorCandidateArtifact
from .feature_signals import CausalFeatureSignalEvaluator
from .trade_simulation import TradeSimulationConfig, TradeSimulationResult, simulate_cached_signals


def _timeframe_to_timedelta(timeframe: str) -> timedelta:
    if timeframe == "5m":
        return timedelta(minutes=5)
    if timeframe == "15m":
        return timedelta(minutes=15)
    if timeframe == "1h":
        return timedelta(hours=1)
    return timedelta(minutes=5)


def simulate_candidate_window(
    candidate: CreatorCandidateArtifact,
    frame: pd.DataFrame,
    *,
    symbol: str,
    config: TradeSimulationConfig,
    funding_events: pd.DataFrame | None = None,
    funding_artifact_hash: str | None = None,
    funding_slice: VerifiedFundingSlice | None = None,
) -> TradeSimulationResult:
    """Simulate one candidate against an explicit cached window."""
    if symbol not in candidate.strategy.universe.symbols:
        raise DataQualityError("simulation symbol is not present in candidate universe")
    uses_funding_signal = any(
        feature.name == "funding_rate" for feature in candidate.strategy.features
    )
    if funding_slice is not None and not isinstance(funding_slice, VerifiedFundingSlice):
        raise DataQualityError("simulation funding input must be a verified funding slice")
    if uses_funding_signal and funding_slice is None:
        raise DataQualityError("funding_rate candidate requires a verified funding slice")
    if funding_slice is not None:
        if (
            funding_slice.symbol != symbol
            or funding_slice.bundle_hash != candidate.bundle_hash
            or funding_slice.dataset_registry_hash != candidate.dataset_registry_hash
            or funding_artifact_hash != funding_slice.manifest_hash
        ):
            raise DataQualityError("verified funding slice does not match candidate simulation")
        verified_events = funding_slice.copy_events()
        if funding_events is not None:
            try:
                pd.testing.assert_frame_equal(
                    funding_events.reset_index(drop=True),
                    verified_events,
                    check_dtype=False,
                    check_exact=True,
                )
            except AssertionError as error:
                raise DataQualityError(
                    "simulation funding events differ from verified slice"
                ) from error
        funding_events = verified_events
    if config.funding_mode == "settled" and (
        funding_events is None or funding_artifact_hash is None
    ):
        raise DataQualityError(
            "candidate qualification requires cached funding events and their "
            "derivative manifest hash"
        )
    signals = CausalFeatureSignalEvaluator().evaluate(
        candidate,
        frame,
        funding_slice=funding_slice,
        symbol=symbol,
    )
    risk = candidate.strategy.risk
    if risk is not None:
        config = config.model_copy(
            update={
                "position_fraction": risk.position_fraction,
                "stop_atr_multiplier": risk.stop_atr_multiplier,
                "take_profit_atr_multiplier": risk.take_profit_atr_multiplier,
                "trailing_atr_multiplier": risk.trailing_atr_multiplier,
            }
        )
    interval = _timeframe_to_timedelta(candidate.strategy.universe.timeframe)
    if interval == timedelta(minutes=5):
        return simulate_cached_signals(
            signals,
            symbol=symbol,
            config=config,
            funding_events=funding_events,
            funding_artifact_hash=funding_artifact_hash,
        )
    return simulate_cached_signals(
        signals,
        symbol=symbol,
        config=config,
        interval=interval,
        funding_events=funding_events,
        funding_artifact_hash=funding_artifact_hash,
    )


__all__ = ["simulate_candidate_window"]
