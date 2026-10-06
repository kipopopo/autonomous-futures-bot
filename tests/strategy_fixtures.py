"""Fresh test-only strategies; never replacements for pinned historical evidence."""

from datetime import UTC, datetime
from hashlib import sha256

import pandas as pd

from autonomous_futures.data.verified_funding import VerifiedFundingSlice
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.cached_evaluation import CachedEvaluationWindow
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


def with_synthetic_verified_funding(
    window: CachedEvaluationWindow,
) -> CachedEvaluationWindow:
    """Attach an explicit test-only funding slice for deterministic pipeline fixtures."""
    identity = (
        f"test-only:{window.spec.window_id}:{window.spec.symbol}:"
        f"{window.spec.time_start.isoformat()}:{window.spec.time_end.isoformat()}"
    )
    manifest_hash = sha256(f"manifest:{identity}".encode()).hexdigest()
    artifact_sha256 = sha256(f"artifact:{identity}".encode()).hexdigest()
    spec = window.spec.model_copy(update={"funding_artifact_hash": manifest_hash})
    funding_slice = VerifiedFundingSlice(
        symbol=spec.symbol,
        time_start=spec.time_start,
        time_end=spec.time_end,
        bundle_hash=spec.bundle_hash,
        dataset_registry_hash=spec.dataset_registry_hash,
        manifest_hash=manifest_hash,
        artifact_sha256=artifact_sha256,
        _events=pd.DataFrame(
            columns=("symbol", "funding_time", "funding_rate", "funding_mark_price")
        ),
    )
    return CachedEvaluationWindow(
        spec=spec,
        frame=window.copy_frame(),
        funding_slice=funding_slice,
    )
