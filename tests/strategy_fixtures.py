"""Fresh test-only strategies; never replacements for pinned historical evidence."""

from datetime import UTC, datetime

from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)
from autonomous_futures.research.creator_proposals import canonical_creator_candidate_id


def synthetic_rsi_candidate(
    *,
    symbol: str,
    bundle_hash: str,
    dataset_registry_hash: str,
    timeframe: str = "5m",
    vetoes: tuple[str, ...] = ("rsi > 0 and rsi < 0",),
) -> CreatorCandidateArtifact:
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id="cand-synthetic-rsi-accounting",
        family="range_mean_reversion",
        universe=StrategyUniverse(
            symbols=(symbol,),
            timeframe=timeframe,
            regime_context_timeframe={"5m": "15m", "15m": "1h", "1h": "4h"}[timeframe],
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=vetoes,
        risk=None,
    )
    candidate_id = canonical_creator_candidate_id(strategy)
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy.model_copy(update={"strategy_id": candidate_id}),
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        creator_run_id="creator-synthetic-veto-accounting",
        research_seed=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
