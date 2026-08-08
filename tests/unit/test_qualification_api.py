from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import FastAPI

from autonomous_futures.api import create_app
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import (
    build_creator_candidate_artifact,
    build_creator_candidate_registry,
    write_creator_candidate_artifact,
    write_creator_candidate_registry,
)
from autonomous_futures.research.performance_metrics import TradePerformanceMetrics
from autonomous_futures.research.qualification_artifacts import (
    WalkForwardQualificationPolicy,
    build_walk_forward_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)
from autonomous_futures.research.walk_forward import (
    WalkForwardWindowMetrics,
    aggregate_walk_forward_metrics,
)

START = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _candidate(candidate_id: str, offset: int):
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id=candidate_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=20, shift=1),),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="creator-api-qualification",
        research_seed=offset,
        created_at=START + timedelta(minutes=offset),
    )


def _window(window_id: str, offset: int, pnl_text: str) -> WalkForwardWindowMetrics:
    pnl = Decimal(pnl_text)
    gross_profit = max(pnl, Decimal("0"))
    gross_loss = max(-pnl, Decimal("0"))
    metrics = TradePerformanceMetrics(
        symbol="BTCUSDT",
        starting_equity=Decimal("100"),
        final_equity=Decimal("100") + pnl,
        trade_count=1,
        winning_trades=int(pnl > 0),
        losing_trades=int(pnl < 0),
        breakeven_trades=int(pnl == 0),
        win_rate=Decimal("1") if pnl > 0 else Decimal("0"),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=pnl,
        average_trade_pnl=pnl,
        return_pct=pnl,
        profit_factor=(gross_profit / gross_loss if gross_loss else None),
        max_drawdown=Decimal("1"),
        max_drawdown_pct=Decimal("1"),
        peak_equity=Decimal("100"),
    )
    start = START + timedelta(minutes=offset)
    return WalkForwardWindowMetrics(
        window_id=window_id,
        symbol="BTCUSDT",
        split="oos",
        window_start=start,
        window_end=start + timedelta(minutes=10),
        metrics=metrics,
    )


def _aggregation():
    return aggregate_walk_forward_metrics(
        (_window("fold-1", 0, "5"), _window("fold-2", 20, "-1")),
        required_symbols=("BTCUSDT",),
        minimum_windows=2,
    )


def _policy() -> WalkForwardQualificationPolicy:
    return WalkForwardQualificationPolicy(
        policy_id="strict-oos-v1",
        minimum_windows=2,
        minimum_trades=2,
        minimum_profit_factor=Decimal("1"),
        maximum_drawdown_pct=Decimal("5"),
        minimum_average_return_pct=Decimal("0"),
    )


def _request(app: FastAPI, method: str, path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path)

    return asyncio.run(send())


def _fixture(tmp_path: Path) -> tuple[FastAPI, Path, Path, Path, Path]:
    candidates = (_candidate("cand-api-qual-a", 0), _candidate("cand-api-qual-b", 1))
    candidate_root = tmp_path / "creator-artifacts"
    registry_path = tmp_path / "creator-candidate-registry.json"
    qualification_root = tmp_path / "qualifications"
    refs: list[str] = []
    for candidate in candidates:
        ref = f"candidates/{candidate.candidate_id}.json"
        refs.append(ref)
        write_creator_candidate_artifact(candidate_root / Path(*ref.split("/")), candidate)
    registry = build_creator_candidate_registry(
        tuple(zip(candidates, refs, strict=True)),
        created_at=START,
    )
    write_creator_candidate_registry(registry_path, registry)
    qualification = build_walk_forward_qualification_artifact(
        candidate=candidates[0],
        aggregation=_aggregation(),
        policy=_policy(),
        evaluator_run_id="api-qualification-run",
        evaluator_version="api-qualification-v1",
        evaluated_at=START,
    )
    qualification_path = qualification_root / f"{candidates[0].candidate_id}.json"
    write_creator_candidate_qualification_artifact(qualification_path, qualification)
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-dataset-registry.json",
        artifact_root=tmp_path / "missing-artifacts",
        creator_candidate_registry_path=registry_path,
        creator_candidate_artifact_root=candidate_root,
        qualification_artifact_root=qualification_root,
    )
    return app, registry_path, candidate_root, qualification_root, qualification_path


def test_qualification_list_and_detail_return_verified_read_only_evidence(tmp_path: Path) -> None:
    app, registry_path, candidate_root, qualification_root, qualification_path = _fixture(tmp_path)
    registry_bytes = registry_path.read_bytes()
    candidate_bytes = {
        str(path.relative_to(candidate_root)): path.read_bytes()
        for path in candidate_root.rglob("*.json")
    }

    listing = _request(app, "GET", "/api/v1/creator/qualifications")
    detail = _request(app, "GET", "/api/v1/creator/qualifications/cand-api-qual-a")

    assert listing.status_code == 200
    listing_payload = listing.json()
    assert listing_payload["verified"] is True
    assert listing_payload["candidate_count"] == 2
    assert listing_payload["qualification_count"] == 1
    assert listing_payload["missing_candidate_ids"] == ["cand-api-qual-b"]
    assert listing_payload["qualifications"][0]["candidate_id"] == "cand-api-qual-a"
    assert listing_payload["qualifications"][0]["decision"] == "qualified"
    assert listing_payload["qualifications"][0]["promotion_state"] == "unpromoted"
    assert listing_payload["qualifications"][0]["execution_authority"] is False

    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["verified"] is True
    assert detail_payload["artifact"]["candidate_id"] == "cand-api-qual-a"
    assert detail_payload["artifact"]["source"] == "walk_forward_oos"
    assert detail_payload["artifact"]["decision"] == "qualified"
    assert detail_payload["artifact"]["execution_authority"] is False
    assert "order" not in detail_payload
    assert registry_path.read_bytes() == registry_bytes
    assert {
        str(path.relative_to(candidate_root)): path.read_bytes()
        for path in candidate_root.rglob("*.json")
    } == candidate_bytes
    assert qualification_path.exists()
    assert qualification_root.exists()


def test_qualification_detail_is_get_only_and_missing_is_unavailable(tmp_path: Path) -> None:
    app, _, _, _, _ = _fixture(tmp_path)

    missing = _request(app, "GET", "/api/v1/creator/qualifications/cand-api-qual-b")
    post = _request(app, "POST", "/api/v1/creator/qualifications")
    unknown = _request(app, "GET", "/api/v1/creator/qualifications/cand-api-qual-unknown")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "creator qualification artifact unavailable"}
    assert post.status_code == 405
    assert unknown.status_code == 404


def test_qualification_api_fails_closed_on_tampered_artifact(tmp_path: Path) -> None:
    app, _, _, _, qualification_path = _fixture(tmp_path)
    payload = qualification_path.read_text(encoding="utf-8").replace(
        "api-qualification-v1", "api-qualification-tampered"
    )
    qualification_path.write_text(payload, encoding="utf-8")

    detail = _request(app, "GET", "/api/v1/creator/qualifications/cand-api-qual-a")
    listing = _request(app, "GET", "/api/v1/creator/qualifications")

    assert detail.status_code == 503
    assert detail.json() == {
        "detail": "creator qualification artifact integrity verification failed"
    }
    assert listing.status_code == 503
    assert listing.json() == {
        "detail": "creator qualification artifact integrity verification failed"
    }
