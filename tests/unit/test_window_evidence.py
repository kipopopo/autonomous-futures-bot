"""Synthetic window evidence, never market or qualification proof."""

import json
import os
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.cached_evaluation import CachedEvaluationWindowSpec
from autonomous_futures.research.trade_simulation import (
    EquityPoint,
    SimulatedTrade,
    TradeSimulationConfig,
    simulate_cached_signals,
)
from autonomous_futures.research.window_evidence import (
    read_window_simulation_evidence,
    write_window_simulation_evidence,
)
from tests.unit.test_autonomous_cycle import _build_test_candidate, _make_cached_window
from tests.unit.test_cached_oos_walk_forward import _flat_result


def test_window_ledger_round_trip_is_bound_immutable_and_hash_verified(tmp_path: Path) -> None:
    candidate = _build_test_candidate("cand-window-evidence")
    window = _make_cached_window()
    result = _flat_result(candidate, window.copy_frame(), window)
    path = tmp_path / "window.json"
    saved = write_window_simulation_evidence(path, candidate, window.spec, result)
    assert read_window_simulation_evidence(path) == saved
    assert saved.candidate_artifact_hash == candidate.artifact_hash
    assert saved.window == window.spec
    assert saved.simulation == result
    assert write_window_simulation_evidence(path, candidate, window.spec, result) == saved
    before = path.read_bytes()
    other_candidate = _build_test_candidate("cand-window-evidence-other")
    with pytest.raises(DomainViolation, match="immutable"):
        write_window_simulation_evidence(path, other_candidate, window.spec, result)
    assert path.read_bytes() == before
    assert tuple(tmp_path.iterdir()) == (path,)

    payload = json.loads(before)
    payload["candidate_artifact_hash"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_window_simulation_evidence(path)


def test_v1_window_ledger_without_funding_fields_remains_readable(tmp_path: Path) -> None:
    candidate = _build_test_candidate("cand-window-evidence")
    window = _make_cached_window()
    simulation = _flat_result(candidate, window.copy_frame(), window, legacy=True)
    window_payload = window.spec.model_dump(mode="json")
    window_payload.pop("funding_artifact_hash", None)
    simulation_payload = simulation.model_dump(mode="json")
    simulation_payload.pop("total_funding_payment", None)
    simulation_payload.pop("funding_artifact_hash", None)
    for trade in simulation_payload["trades"]:
        trade.pop("funding_payment", None)
    payload = {
        "evidence_version": 1,
        "candidate_id": candidate.candidate_id,
        "candidate_artifact_hash": candidate.artifact_hash,
        "window": window_payload,
        "simulation": simulation_payload,
        "promotion_state": "unpromoted",
        "execution_authority": False,
    }
    payload["evidence_hash"] = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = tmp_path / "legacy-window.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = read_window_simulation_evidence(path)

    assert loaded.simulation.simulation_version == 2
    assert loaded.simulation.total_funding_payment == 0
    assert loaded.window.funding_artifact_hash is None


def test_new_window_ledger_writer_rejects_legacy_simulation(tmp_path: Path) -> None:
    candidate = _build_test_candidate("cand-window-evidence")
    window = _make_cached_window()
    legacy_spec = window.spec.model_copy(update={"funding_artifact_hash": None})
    simulation = _flat_result(candidate, window.copy_frame(), window, legacy=True)
    path = tmp_path / "absent" / "window.json"

    with pytest.raises(DomainViolation, match="funding"):
        write_window_simulation_evidence(path, candidate, legacy_spec, simulation)

    assert not path.parent.exists()


@pytest.mark.parametrize("fault", ["candidate_hash", "bundle", "registry", "timeframe", "symbol"])
def test_window_evidence_rejects_foreign_inputs_before_filesystem_work(
    tmp_path: Path, fault: str
) -> None:
    candidate = _build_test_candidate("cand-window-evidence")
    window = _make_cached_window()
    spec = window.spec
    if fault == "candidate_hash":
        candidate = candidate.model_copy(update={"artifact_hash": "0" * 64})
    else:
        updates = {
            "bundle": {"bundle_hash": "0" * 64},
            "registry": {"dataset_registry_hash": "0" * 64},
            "timeframe": {"timeframe": "15m"},
            "symbol": {"symbol": "ETHUSDT"},
        }
        spec = spec.model_copy(update=updates[fault])
    path = tmp_path / "absent" / "window.json"
    with pytest.raises(DomainViolation, match="mismatch"):
        write_window_simulation_evidence(
            path, candidate, spec, _flat_result(candidate, window.copy_frame(), window)
        )
    assert not path.parent.exists()


def test_window_evidence_cleans_temporary_file_on_failed_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _build_test_candidate("cand-window-evidence")
    window = _make_cached_window()

    def fail_link(*args, **kwargs):
        raise OSError("synthetic publication failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="synthetic"):
        write_window_simulation_evidence(
            tmp_path / "window.json",
            candidate,
            window.spec,
            _flat_result(candidate, window.copy_frame(), window),
        )
    assert not tuple(tmp_path.iterdir())


def test_window_evidence_rejects_equity_outside_its_half_open_range(tmp_path: Path) -> None:
    candidate = _build_test_candidate("cand-window-evidence")
    window = _make_cached_window()
    result = _flat_result(candidate, window.copy_frame(), window)
    result = result.model_copy(
        update={
            "equity_curve": (
                EquityPoint(timestamp=window.spec.time_end, equity=result.final_equity),
            )
        }
    )
    path = tmp_path / "absent" / "window.json"
    with pytest.raises(ValidationError, match="outside window"):
        write_window_simulation_evidence(path, candidate, window.spec, result)
    assert not path.parent.exists()


def test_funding_ledger_is_bound_to_the_exact_window_derivative_manifest(tmp_path: Path) -> None:
    candidate = _build_test_candidate("cand-window-evidence")
    window = _make_cached_window()
    frame = window.copy_frame()
    frame["signal"] = 0
    funding = pd.DataFrame(columns=("symbol", "funding_time", "funding_rate", "funding_mark_price"))
    simulation = simulate_cached_signals(
        frame,
        symbol=window.spec.symbol,
        config=TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.5"),
            taker_fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
        ),
        funding_events=funding,
        funding_artifact_hash="b" * 64,
    )

    absent_path = tmp_path / "absent" / "window.json"
    with pytest.raises(DomainViolation, match="funding"):
        write_window_simulation_evidence(absent_path, candidate, window.spec, simulation)
    assert not absent_path.parent.exists()

    bound_spec = CachedEvaluationWindowSpec.model_validate(
        window.spec.model_dump() | {"funding_artifact_hash": "b" * 64}
    )
    saved = write_window_simulation_evidence(
        tmp_path / "window.json", candidate, bound_spec, simulation
    )
    assert saved.window.funding_artifact_hash == simulation.funding_artifact_hash


@pytest.mark.parametrize("fault", ["symbol", "entry", "exit"])
def test_window_evidence_rejects_trade_outside_its_scope(tmp_path: Path, fault: str) -> None:
    candidate = _build_test_candidate("cand-window-evidence")
    window = _make_cached_window()
    zero = Decimal("0")
    trade = SimulatedTrade(
        trade_id="synthetic-flat-trade",
        symbol="ETHUSDT" if fault == "symbol" else window.spec.symbol,
        side="LONG",
        entry_timestamp=window.spec.time_start - timedelta(minutes=5)
        if fault == "entry"
        else window.spec.time_start,
        exit_timestamp=window.spec.time_end
        if fault == "exit"
        else window.spec.time_end - timedelta(minutes=5),
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100"),
        entry_notional=Decimal("100"),
        exit_notional=Decimal("100"),
        entry_fee=zero,
        exit_fee=zero,
        fees=zero,
        slippage_cost=zero,
        gross_pnl=zero,
        net_pnl=zero,
        exit_reason="forced_end_of_window",
    )
    result = _flat_result(candidate, window.copy_frame(), window).model_copy(
        update={"trades": (trade,)}
    )
    path = tmp_path / "absent" / "window.json"
    with pytest.raises(ValidationError, match="trade.*window"):
        write_window_simulation_evidence(path, candidate, window.spec, result)
    assert not path.parent.exists()
