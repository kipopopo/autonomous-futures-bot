from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest


def _load_selector():
    path = Path(__file__).resolve().parents[2] / "scripts/select_scalper_development_candidates.py"
    spec = importlib.util.spec_from_file_location("select_scalper_development_candidates", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_window_net_pnl_counts_each_window_and_empty_windows_as_zero() -> None:
    selector = _load_selector()
    report = {
        "windows": [
            {"trades": [{"net_pnl": "0.75"}, {"net_pnl": "-0.25"}]},
            {"trades": []},
            {"trades": [{"net_pnl": "-1.25"}]},
        ]
    }

    assert selector.window_net_pnl(report) == [
        Decimal("0.50"),
        Decimal("0"),
        Decimal("-1.25"),
    ]


def test_window_net_pnl_requires_a_nonempty_window_list() -> None:
    selector = _load_selector()

    with pytest.raises(ValueError, match="no windows"):
        selector.window_net_pnl({"windows": []})


def test_candidate_priority_requires_every_frozen_development_gate() -> None:
    selector = _load_selector()
    gates = {
        "sufficient_oos_samples": True,
        "positive_net_edge": True,
        "profit_factor": True,
        "drawdown": True,
        "window_consistency": True,
        "stress_positive": True,
    }
    report = {
        "candidate_decision_on_development_sample": "QUALIFIED",
        "gates": gates,
        "metrics": {
            "stress_net_pnl": "0.05",
            "drawdown_usdt": "1.0",
            "trade_count": 30,
        },
        "research_variant": {
            "parameters": {"distance_threshold": "-3.5", "target_atr_multiplier": "2.2"}
        },
        "windows": [
            {"trades": [{"net_pnl": "0.2"}]},
            {"trades": [{"net_pnl": "0.1"}]},
            {"trades": [{"net_pnl": "0.3"}]},
        ],
    }

    priority = selector.candidate_priority(report, set(gates))

    assert priority == (
        Decimal("-0.1"),
        Decimal("-0.05"),
        Decimal("1.0"),
        -30,
        Decimal("-3.5"),
        Decimal("2.2"),
    )
    report["gates"]["stress_positive"] = False
    assert selector.candidate_priority(report, set(gates)) is None
