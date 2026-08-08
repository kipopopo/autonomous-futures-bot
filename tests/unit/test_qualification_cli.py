from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
from autonomous_futures.research.qualification_artifacts import WalkForwardQualificationPolicy
from autonomous_futures.research.qualification_cli import main
from autonomous_futures.research.walk_forward import (
    WalkForwardWindowMetrics,
    aggregate_walk_forward_metrics,
    write_walk_forward_aggregation,
)

START = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _candidate():
    candidate_id = "cand-cli-a"
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
        creator_run_id="creator-cli-run",
        research_seed=7,
        created_at=START,
    )


def _window(window_id: str, offset: int, pnl: str) -> WalkForwardWindowMetrics:
    net_pnl = Decimal(pnl)
    gross_profit = max(net_pnl, Decimal("0"))
    gross_loss = max(-net_pnl, Decimal("0"))
    start = START + timedelta(minutes=offset)
    metrics = TradePerformanceMetrics(
        symbol="BTCUSDT",
        starting_equity=Decimal("100"),
        final_equity=Decimal("100") + net_pnl,
        trade_count=1,
        winning_trades=int(net_pnl > 0),
        losing_trades=int(net_pnl < 0),
        breakeven_trades=int(net_pnl == 0),
        win_rate=Decimal("1") if net_pnl > 0 else Decimal("0"),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net_pnl,
        average_trade_pnl=net_pnl,
        return_pct=net_pnl,
        profit_factor=(gross_profit / gross_loss if gross_loss else None),
        max_drawdown=Decimal("1"),
        max_drawdown_pct=Decimal("1"),
        peak_equity=Decimal("100"),
    )
    return WalkForwardWindowMetrics(
        window_id=window_id,
        symbol="BTCUSDT",
        split="oos",
        window_start=start,
        window_end=start + timedelta(minutes=10),
        metrics=metrics,
    )


def _write_fixture(tmp_path):
    candidate = _candidate()
    candidate_root = tmp_path / "candidates"
    aggregation_root = tmp_path / "aggregations"
    qualification_root = tmp_path / "qualifications"
    candidate_ref = "cand-cli-a.json"
    write_creator_candidate_artifact(candidate_root / candidate_ref, candidate)
    aggregation = aggregate_walk_forward_metrics(
        (_window("fold-1", 0, "5"), _window("fold-2", 20, "-1")),
        required_symbols=("BTCUSDT",),
        minimum_windows=2,
    )
    aggregation_ref = "cand-cli-a.json"
    write_walk_forward_aggregation(aggregation_root / aggregation_ref, aggregation)
    registry = build_creator_candidate_registry(
        ((candidate, candidate_ref),),
        created_at=START,
    )
    registry_path = tmp_path / "registry.json"
    write_creator_candidate_registry(registry_path, registry)
    policy_path = tmp_path / "policy.json"
    policy = WalkForwardQualificationPolicy(
        policy_id="strict-oos-v1",
        minimum_windows=2,
        minimum_trades=2,
        minimum_profit_factor=Decimal("1"),
        maximum_drawdown_pct=Decimal("5"),
        minimum_average_return_pct=Decimal("0"),
    )
    policy_path.write_text(
        json.dumps(policy.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "registry_path": registry_path,
        "candidate_root": candidate_root,
        "aggregation_root": aggregation_root,
        "qualification_root": qualification_root,
        "policy_path": policy_path,
        "aggregation_ref": aggregation_ref,
    }


def _args(paths: dict[str, object], *, aggregation_ref: str | None = None) -> list[str]:
    return [
        "--registry-path",
        str(paths["registry_path"]),
        "--candidate-artifact-root",
        str(paths["candidate_root"]),
        "--aggregation-root",
        str(paths["aggregation_root"]),
        "--qualification-root",
        str(paths["qualification_root"]),
        "--policy-path",
        str(paths["policy_path"]),
        "--evaluator-run-id",
        "cli-batch-run-001",
        "--evaluator-version",
        "cli-batch-v1",
        "--evaluated-at",
        "2026-08-08T12:00:00Z",
        "--aggregation-ref",
        f"cand-cli-a={aggregation_ref or paths['aggregation_ref']}",
    ]


def test_cli_emits_stable_json_and_persists_qualification(tmp_path, capsys) -> None:
    paths = _write_fixture(tmp_path)

    exit_code = main(_args(paths))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["selected_count"] == 1
    assert payload["evaluated_count"] == 1
    assert payload["qualified_count"] == 1
    assert payload["rejected_count"] == 0
    assert payload["blocked_count"] == 0
    assert payload["qualified_candidate_ids"] == ["cand-cli-a"]
    assert payload["promotion_state"] == "unpromoted"
    assert payload["execution_authority"] is False
    assert (paths["qualification_root"] / "cand-cli-a.json").exists()


def test_cli_returns_stable_error_json_for_invalid_policy(tmp_path, capsys) -> None:
    paths = _write_fixture(tmp_path)
    paths["policy_path"].write_text('{"policy_id": "bad"}\n', encoding="utf-8")

    exit_code = main(_args(paths))

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "error_code": "invalid_policy_config",
        "status": "error",
    }


def test_cli_reports_path_traversal_as_blocked_evidence(tmp_path, capsys) -> None:
    paths = _write_fixture(tmp_path)

    exit_code = main(_args(paths, aggregation_ref="../outside.json"))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["blocked_count"] == 1
    assert payload["blocked_candidate_ids"] == ["cand-cli-a"]
    assert payload["failures"][0]["reason_code"] == "invalid_persisted_aggregation"
    assert not (paths["qualification_root"] / "cand-cli-a.json").exists()
