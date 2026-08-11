from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import pandas as pd

from .alignment import MARK_PRICE_COLUMNS, canonicalize_mark_price_klines
from .backfill import BackfillResult, BackfillWindow, resumable_backfill_klines
from .builder import INTERVAL_MS, KlineInterval
from .derivatives_artifacts import DerivativesArtifactManifest, write_mark_price_artifact


def collect_mark_price_artifact(
    fetch_page: Callable[[BackfillWindow], Sequence[Sequence[object]]],
    *,
    artifact_path: Path,
    manifest_path: Path,
    artifact_ref: str,
    symbol: str,
    interval: KlineInterval,
    start_ms: int,
    end_ms_exclusive: int,
    now_ms: int,
    created_at: datetime,
    code_version: str,
    dependency_lock_hash: str,
    checkpoint_path: Path | None = None,
) -> DerivativesArtifactManifest:
    """Collect one explicit public mark-price scope into an immutable artifact."""
    interval_ms = INTERVAL_MS[interval]
    checkpoint = checkpoint_path or artifact_path.with_suffix(".checkpoint.json")
    result: BackfillResult = resumable_backfill_klines(
        fetch_page,
        checkpoint,
        job_id=f"mark-price:{symbol}:{interval}:{start_ms}:{end_ms_exclusive}",
        symbol=symbol,
        interval=interval,
        start_ms=start_ms,
        requested_end_exclusive=end_ms_exclusive,
        now_ms=now_ms,
        interval_ms=interval_ms,
    )
    canonical = canonicalize_mark_price_klines(
        result.rows,
        symbol=symbol,
        interval=interval,
        end_exclusive_ms=end_ms_exclusive,
    )
    return write_mark_price_artifact(
        canonical.loc[:, MARK_PRICE_COLUMNS],
        artifact_path,
        manifest_path,
        artifact_ref=artifact_ref,
        symbol=symbol,
        interval=interval,
        time_start=pd.Timestamp(start_ms, unit="ms", tz="UTC").to_pydatetime(),
        time_end=pd.Timestamp(end_ms_exclusive, unit="ms", tz="UTC").to_pydatetime(),
        created_at=created_at,
        code_version=code_version,
        dependency_lock_hash=dependency_lock_hash,
    )


__all__ = ["collect_mark_price_artifact"]
