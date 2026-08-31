from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd

from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.candidate_window_simulation import simulate_candidate_window
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.trade_simulation import TradeSimulationConfig

START = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64


def test_v2_candidate_risk_profile_controls_cached_position_size() -> None:
    candidate = build_creator_candidate_artifact(
        candidate_id="cand-risk-profile-001",
        strategy=StrategySpec(
            dsl_version=2,
            strategy_id="cand-risk-profile-001",
            family="experimental",
            universe=StrategyUniverse(
                symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
            ),
            features=(FeatureRef(name="returns", lookback=1, shift=1),),
            entry=EntryExit(long="returns > 0", short="returns < 0"),
            exit=EntryExit(long="returns < 0", short="returns > 0"),
            vetoes=("testing_only_no_promotion",),
            risk={
                "position_fraction": Decimal("0.25"),
                "stop_atr_multiplier": Decimal("1"),
                "take_profit_atr_multiplier": Decimal("0"),
                "trailing_atr_multiplier": Decimal("0"),
            },
        ),
        bundle_hash=HASH,
        dataset_registry_hash=HASH,
        creator_run_id="creator-risk-profile-001",
        research_seed=1,
        created_at=START,
    )
    prices = ("100", "100", "101", "102", "103")
    frame = pd.DataFrame(
        {
            "timestamp": [START + timedelta(minutes=5 * index) for index in range(len(prices))],
            "open": [Decimal(price) for price in prices],
            "high": [Decimal(price) + Decimal("1") for price in prices],
            "low": [Decimal(price) - Decimal("1") for price in prices],
            "close": [Decimal(price) for price in prices],
        }
    )

    result = simulate_candidate_window(
        candidate,
        frame,
        symbol="BTCUSDT",
        config=TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1"),
            taker_fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            atr_lookback=1,
        ),
    )

    assert result.trades[0].entry_notional == Decimal("25")
    assert result.exchange_access is False
