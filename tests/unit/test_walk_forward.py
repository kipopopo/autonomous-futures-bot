from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.performance_metrics import TradePerformanceMetrics
from autonomous_futures.research.walk_forward import (
    WalkForwardWindowMetrics,
    aggregate_walk_forward_metrics,
    read_walk_forward_aggregation,
    write_walk_forward_aggregation,
)

START = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _metrics(symbol: str, net_pnl: str, *, max_drawdown: str = "1") -> TradePerformanceMetrics:
    pnl = Decimal(net_pnl)
    drawdown = Decimal(max_drawdown)
    gross_profit = max(pnl, Decimal("0"))
    gross_loss = max(-pnl, Decimal("0"))
    trade_count = 1 if pnl else 0
    return TradePerformanceMetrics(
        symbol=symbol,
        starting_equity=Decimal("100"),
        final_equity=Decimal("100") + pnl,
        trade_count=trade_count,
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
        max_drawdown=drawdown,
        max_drawdown_pct=drawdown,
        peak_equity=Decimal("100"),
    )


def _window(
    window_id: str,
    symbol: str,
    start_offset: int,
    net_pnl: str,
    *,
    split: str = "oos",
    max_drawdown: str = "1",
) -> WalkForwardWindowMetrics:
    window_start = START + timedelta(minutes=5 * start_offset)
    return WalkForwardWindowMetrics(
        window_id=window_id,
        symbol=symbol,
        split=split,
        window_start=window_start,
        window_end=window_start + timedelta(minutes=5 * 2),
        metrics=_metrics(symbol, net_pnl, max_drawdown=max_drawdown),
    )


def test_aggregation_is_deterministic_and_pools_net_window_evidence() -> None:
    windows = (
        _window("fold-2", "ETHUSDT", 4, "-3", max_drawdown="4"),
        _window("fold-2", "BTCUSDT", 4, "-2", max_drawdown="3"),
        _window("fold-1", "BTCUSDT", 0, "5", max_drawdown="1"),
        _window("fold-1", "ETHUSDT", 0, "4", max_drawdown="2"),
    )

    first = aggregate_walk_forward_metrics(
        windows,
        required_symbols=("BTCUSDT", "ETHUSDT"),
        minimum_windows=2,
    )
    second = aggregate_walk_forward_metrics(
        tuple(reversed(windows)),
        required_symbols=("BTCUSDT", "ETHUSDT"),
        minimum_windows=2,
    )

    assert first == second
    assert [window.symbol for window in first.windows] == [
        "BTCUSDT",
        "BTCUSDT",
        "ETHUSDT",
        "ETHUSDT",
    ]
    assert [window.window_id for window in first.windows] == [
        "fold-1",
        "fold-2",
        "fold-1",
        "fold-2",
    ]
    assert first.window_count == 4
    assert first.total_trade_count == 4
    assert first.pooled_net_pnl == Decimal("4")
    assert first.pooled_gross_profit == Decimal("9")
    assert first.pooled_gross_loss == Decimal("5")
    assert first.pooled_profit_factor == Decimal("1.8")
    assert first.worst_max_drawdown == Decimal("4")
    assert first.worst_max_drawdown_pct == Decimal("4")
    assert [(summary.symbol, summary.net_pnl) for summary in first.per_symbol] == [
        ("BTCUSDT", Decimal("3")),
        ("ETHUSDT", Decimal("1")),
    ]


def test_train_or_validation_windows_are_rejected_from_oos_aggregation() -> None:
    with pytest.raises(ValueError, match="OOS"):
        aggregate_walk_forward_metrics(
            (_window("fold-1", "BTCUSDT", 0, "1", split="train"),),
            required_symbols=("BTCUSDT",),
        )


def test_duplicate_symbol_window_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        aggregate_walk_forward_metrics(
            (
                _window("fold-1", "BTCUSDT", 0, "1"),
                _window("fold-1", "BTCUSDT", 4, "2"),
            ),
            required_symbols=("BTCUSDT",),
        )


def test_overlapping_windows_for_one_symbol_are_rejected() -> None:
    with pytest.raises(ValueError, match="overlap"):
        aggregate_walk_forward_metrics(
            (
                _window("fold-1", "BTCUSDT", 0, "1"),
                _window("fold-2", "BTCUSDT", 1, "2"),
            ),
            required_symbols=("BTCUSDT",),
        )


def test_required_symbol_and_minimum_window_coverage_is_enforced() -> None:
    with pytest.raises(ValueError, match="required symbol"):
        aggregate_walk_forward_metrics(
            (_window("fold-1", "BTCUSDT", 0, "1"),),
            required_symbols=("BTCUSDT", "ETHUSDT"),
        )

    with pytest.raises(ValueError, match="minimum"):
        aggregate_walk_forward_metrics(
            (_window("fold-1", "BTCUSDT", 0, "1"),),
            required_symbols=("BTCUSDT",),
            minimum_windows=2,
        )


def test_invalid_window_contract_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WalkForwardWindowMetrics(
            window_id="fold-1",
            symbol="BTCUSDT",
            split="oos",
            window_start=START,
            window_end=START,
            metrics=_metrics("ETHUSDT", "1"),
        )


@pytest.mark.parametrize("second_pnl", ["1", "2"])
def test_concurrent_aggregation_writers_cannot_replace_each_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, second_pnl: str
) -> None:
    path = tmp_path / "aggregation.json"
    inputs = tuple(
        aggregate_walk_forward_metrics(
            (_window("fold-1", "BTCUSDT", 0, pnl),), required_symbols=("BTCUSDT",)
        )
        for pnl in ("1", second_pnl)
    )
    barrier = Barrier(2)
    original_exists = Path.exists

    def synchronized_exists(p: Path) -> bool:
        exists = original_exists(p)
        if p == path:
            barrier.wait(timeout=10)
        return exists

    monkeypatch.setattr(Path, "exists", synchronized_exists)

    def write(aggregation):
        try:
            return write_walk_forward_aggregation(path, aggregation)
        except DomainViolation as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(write, inputs))
    winners = tuple(r for r in results if not isinstance(r, DomainViolation))
    assert len(winners) == (2 if second_pnl == "1" else 1)
    assert all(winner == winners[0] for winner in winners)
    assert read_walk_forward_aggregation(path) == winners[0]
    assert tuple(tmp_path.iterdir()) == (path,)


def test_aggregation_writer_cleans_temporary_file_when_publication_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregation = aggregate_walk_forward_metrics(
        (_window("fold-1", "BTCUSDT", 0, "1"),), required_symbols=("BTCUSDT",)
    )

    def fail_link(*args, **kwargs):
        raise OSError("synthetic publication failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="synthetic"):
        write_walk_forward_aggregation(tmp_path / "aggregation.json", aggregation)
    assert not tuple(tmp_path.iterdir())


def test_legacy_aggregation_without_funding_fields_remains_readable(tmp_path: Path) -> None:
    aggregation = aggregate_walk_forward_metrics(
        (_window("fold-1", "BTCUSDT", 0, "1"),), required_symbols=("BTCUSDT",)
    )
    path = tmp_path / "legacy-aggregation.json"
    write_walk_forward_aggregation(path, aggregation)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["aggregation"]["windows"][0].pop("funding_artifact_hash", None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = read_walk_forward_aggregation(path)

    assert loaded.aggregation.aggregation_version == 1
    assert loaded.aggregation.windows[0].funding_artifact_hash is None
