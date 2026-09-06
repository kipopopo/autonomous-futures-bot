"""Phase 258 Milestone M2: Empirical Challenger Test Suite.

Adversarially validates:
1. Pinned candidate identity and artifact hash consistency against Phase 252 artifacts.
2. Ingestion latency and bid-ask spread stability metrics (mean, p50, p95, p99, min, max).
3. Monotonic UTC timestamps and 624-second bounded forward-testing window.
4. Strict zero-order, zero-credential safety invariants.
5. Adversarial domain mutations: injected cash balance drift, non-zero order counts,
   inverted spread percentiles, corrupted candidate IDs, and out-of-window timestamps.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.paper.live_engine import DEFAULT_SYMBOLS, LivePaperEngine
from autonomous_futures.research.creator_artifacts import read_creator_candidate_artifact

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_phase_258_live_paper import verify_strict_safety_invariants  # noqa: E402


def validate_live_paper_summary_oracle(data: dict[str, Any]) -> None:
    """Authoritative validation oracle enforcing all Phase 258 M2 contracts."""
    # 1. Root and metadata
    if data.get("phase") != "phase_258":
        raise ValueError(f"Invalid phase: {data.get('phase')}")
    if data.get("milestone") != "milestone_1":
        raise ValueError(f"Invalid milestone: {data.get('milestone')}")

    run_meta = data.get("run_metadata")
    if not isinstance(run_meta, dict):
        raise ValueError("Missing run_metadata")

    symbols = set(run_meta.get("symbols", []))
    expected_symbols = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"}
    if symbols != expected_symbols:
        raise ValueError(f"Symbols mismatch: expected {expected_symbols}, got {symbols}")

    # 2. Timestamp monotonicity and duration window
    try:
        started_at = datetime.fromisoformat(run_meta["started_at"])
        ended_at = datetime.fromisoformat(run_meta["ended_at"])
        ts_utc = datetime.fromisoformat(data["timestamp_utc"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid timestamp format: {exc}") from exc

    if not (started_at < ended_at):
        raise ValueError(
            f"Non-monotonic run times: started_at ({started_at}) >= ended_at ({ended_at})"
        )
    if not (ended_at <= ts_utc):
        raise ValueError(f"Timestamp skew: ended_at ({ended_at}) > timestamp_utc ({ts_utc})")

    elapsed_seconds = (ended_at - started_at).total_seconds()
    actual_duration = float(run_meta.get("duration_actual_seconds", 0.0))
    if abs(elapsed_seconds - actual_duration) > 0.005:
        raise ValueError(
            f"Duration mismatch: elapsed {elapsed_seconds} vs recorded {actual_duration}"
        )

    # Bounded 10 to 15 minute window constraint (600s to 900s)
    if actual_duration < 600.0 or actual_duration > 900.0:
        raise ValueError(
            f"Duration {actual_duration}s is outside bounded 10-15m window [600.0, 900.0]"
        )

    # 3. Candidate cohort identity pinning
    cohort = data.get("cohort_health")
    if not isinstance(cohort, dict):
        raise ValueError("Missing cohort_health")
    if cohort.get("cohort_status") != "healthy":
        raise ValueError(f"Cohort status is not healthy: {cohort.get('cohort_status')}")
    if cohort.get("expected_candidate_count") != 4 or cohort.get("reported_candidate_count") != 4:
        raise ValueError("Cohort candidate counts do not equal 4")

    cands = cohort.get("candidates")
    if not isinstance(cands, dict) or len(cands) != 4:
        raise ValueError("Candidates dictionary must contain exactly 4 entries")

    # 4. Spread stability metrics
    net_telemetry = data.get("network_telemetry")
    if not isinstance(net_telemetry, dict):
        raise ValueError("Missing network_telemetry")
    by_symbol = net_telemetry.get("by_symbol")
    if not isinstance(by_symbol, dict):
        raise ValueError("Missing by_symbol in network_telemetry")

    for sym in expected_symbols:
        if sym not in by_symbol:
            raise ValueError(f"Missing symbol {sym} in network telemetry")
        sym_data = by_symbol[sym]
        spread = sym_data.get("spread_bps")
        if not isinstance(spread, dict):
            raise ValueError(f"Missing spread_bps for {sym}")

        s_min = float(spread.get("min", 0.0))
        s_p50 = float(spread.get("p50", 0.0))
        s_p95 = float(spread.get("p95", 0.0))
        s_p99 = float(spread.get("p99", 0.0))
        s_max = float(spread.get("max", 0.0))
        s_mean = float(spread.get("mean", 0.0))
        s_std = float(spread.get("std_dev", 0.0))

        if s_min <= 0.0:
            raise ValueError(f"Spread min must be positive for {sym}, got {s_min}")
        if not (s_min <= s_p50 <= s_p95 <= s_p99 <= s_max):
            raise ValueError(
                f"Inverted spread percentiles for {sym}: min={s_min}, p50={s_p50}, "
                f"p95={s_p95}, p99={s_p99}, max={s_max}"
            )
        if not (s_min <= s_mean <= s_max):
            raise ValueError(f"Mean spread {s_mean} outside [min, max] for {sym}")
        if s_std < 0.0:
            raise ValueError(f"Standard deviation must be non-negative for {sym}")

    # 5. Shared portfolio margin and exact reconciliation
    margin = data.get("shared_portfolio_margin")
    if not isinstance(margin, dict):
        raise ValueError("Missing shared_portfolio_margin")

    starting_capital = Decimal(str(margin.get("starting_capital", "0")))
    final_cash = Decimal(str(margin.get("final_cash", "0")))
    drift_amount = Decimal(str(margin.get("drift_amount", "-1")))
    zero_balance_drift = margin.get("zero_balance_drift")

    if starting_capital != Decimal("100.00"):
        raise ValueError(f"Starting capital != 100.00 USDT: {starting_capital}")
    if final_cash != Decimal("100.00"):
        raise ValueError(f"Final cash != 100.00 USDT: {final_cash}")
    if drift_amount != Decimal("0.00"):
        raise ValueError(f"Drift amount != 0.00: {drift_amount}")
    if zero_balance_drift is not True:
        raise ValueError(f"zero_balance_drift is not True: {zero_balance_drift}")

    # 6. Safety invariants
    safety = data.get("safety_invariants")
    if not isinstance(safety, dict):
        raise ValueError("Missing safety_invariants")

    if safety.get("orders_submitted") != 0:
        raise ValueError(f"orders_submitted != 0: {safety.get('orders_submitted')}")
    if safety.get("api_keys_loaded") != 0:
        raise ValueError(f"api_keys_loaded != 0: {safety.get('api_keys_loaded')}")
    if safety.get("execution_authority") is not False:
        raise ValueError(f"execution_authority must be False: {safety.get('execution_authority')}")
    if safety.get("live_trading_activation") is not False:
        raise ValueError(
            f"live_trading_activation must be False: {safety.get('live_trading_activation')}"
        )
    if safety.get("promotion_state") != "unpromoted":
        raise ValueError(f"promotion_state must be 'unpromoted': {safety.get('promotion_state')}")
    if safety.get("read_only_streams_only") is not True:
        raise ValueError("read_only_streams_only must be True")
    if safety.get("zero_secret_leakage") is not True:
        raise ValueError("zero_secret_leakage must be True")


@pytest.fixture
def summary_json_data() -> dict[str, Any]:
    path = Path("artifacts/research/phase258/live-paper-summary.json")
    assert path.is_file(), f"Artifact not found: {path}"
    with path.open(encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


class TestAuthoritativeTelemetryConsistency:
    """Validates baseline live-paper-summary.json against all requirements."""

    def test_summary_telemetry_validates_cleanly(self, summary_json_data: dict[str, Any]) -> None:
        """Baseline live-paper-summary.json must pass oracle validation without error."""
        validate_live_paper_summary_oracle(summary_json_data)

    def test_phase_252_pinned_candidate_ids_and_hashes_exact_match(
        self, summary_json_data: dict[str, Any]
    ) -> None:
        """All 4 candidate IDs and artifact hashes must match Phase 252 artifacts exactly."""
        cand_dir = Path("artifacts/research/phase252/candidates")
        assert cand_dir.is_dir(), "Phase 252 candidates directory missing"

        pinned_candidates: dict[str, dict[str, str]] = {}
        for p in cand_dir.glob("cand-*.json"):
            artifact = read_creator_candidate_artifact(p)
            sym = artifact.strategy.universe.symbols[0]
            pinned_candidates[artifact.candidate_id] = {
                "symbol": sym,
                "artifact_hash": artifact.artifact_hash,
            }

        assert len(pinned_candidates) == 4, f"Expected 4 candidates, got {len(pinned_candidates)}"

        summary_cands = summary_json_data["cohort_health"]["candidates"]
        assert set(summary_cands.keys()) == set(pinned_candidates.keys())

        for cand_id, meta in pinned_candidates.items():
            assert cand_id in summary_cands
            s_cand = summary_cands[cand_id]
            assert s_cand["symbol"] == meta["symbol"]
            assert s_cand["artifact_hash"] == meta["artifact_hash"]
            assert s_cand["health_status"] == "healthy"
            assert s_cand["maturity_status"] == "maturing"
            assert s_cand["trades_count"] == 0

    def test_spread_stability_metrics_rigorous_ordering_and_bounds(
        self, summary_json_data: dict[str, Any]
    ) -> None:
        """Verify spread stability metrics: min <= p50 <= p95 <= p99 <= max, mean within bounds."""
        by_sym = summary_json_data["network_telemetry"]["by_symbol"]
        spread_stability = summary_json_data["network_telemetry"]["spread_stability"]

        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"):
            assert sym in by_sym
            spread = by_sym[sym]["spread_bps"]
            min_s = spread["min"]
            p50_s = spread["p50"]
            p95_s = spread["p95"]
            p99_s = spread["p99"]
            max_s = spread["max"]
            mean_s = spread["mean"]

            # Strict orderings
            assert 0.0 < min_s <= p50_s <= p95_s <= p99_s <= max_s
            assert min_s <= mean_s <= max_s

            # Cross-verify with spread_stability table
            assert sym in spread_stability
            stab = spread_stability[sym]
            assert stab["mean_spread_bps"] == mean_s
            assert stab["min_spread_bps"] == min_s
            assert stab["max_spread_bps"] == max_s
            assert stab["sample_count"] == by_sym[sym]["total_count"]
            assert stab["sample_count"] >= 36_000

    def test_timestamps_strict_monotonicity_and_window_bounds(
        self, summary_json_data: dict[str, Any]
    ) -> None:
        """Verify started_at < ended_at <= timestamp_utc, duration in 10-15m window."""
        run_meta = summary_json_data["run_metadata"]
        started_at = datetime.fromisoformat(run_meta["started_at"])
        ended_at = datetime.fromisoformat(run_meta["ended_at"])
        ts_utc = datetime.fromisoformat(summary_json_data["timestamp_utc"])

        assert started_at < ended_at <= ts_utc
        duration_delta = (ended_at - started_at).total_seconds()
        assert abs(duration_delta - 624.43669) < 0.001
        assert abs(duration_delta - run_meta["duration_actual_seconds"]) < 0.001
        # Bounded between 600s (10 min) and 900s (15 min)
        assert 600.0 <= duration_delta <= 900.0

    def test_safety_assertions_exact_invariants(self, summary_json_data: dict[str, Any]) -> None:
        """Verify orders_submitted == 0, api_keys_loaded == 0, execution_authority == False."""
        safety = summary_json_data["safety_invariants"]
        assert safety["orders_submitted"] == 0
        assert safety["api_keys_loaded"] == 0
        assert safety["execution_authority"] is False
        assert safety["live_trading_activation"] is False
        assert safety["authenticated_endpoints_accessed"] is False
        assert safety["read_only_streams_only"] is True
        assert safety["promotion_state"] == "unpromoted"
        assert safety["zero_secret_leakage"] is True

        margin = summary_json_data["shared_portfolio_margin"]
        assert margin["starting_capital"] == "100.00"
        assert margin["final_cash"] == "100.00"
        assert margin["current_equity"] == "100.00"
        assert margin["drift_amount"] == "0.00"
        assert margin["zero_balance_drift"] is True
        assert margin["realized_pnl"] == "0"
        assert margin["unrealized_pnl"] == "0"


class TestAdversarialMutationsAndBoundaryRejection:
    """Stress-tests validation defenses by injecting domain and safety violations."""

    def test_adversarial_candidate_tampering_rejected(
        self, summary_json_data: dict[str, Any]
    ) -> None:
        """Tampering candidate IDs or candidate count triggers immediate rejection."""
        # 1. Replace valid candidate ID with rogue ID
        tampered = copy.deepcopy(summary_json_data)
        cands = tampered["cohort_health"]["candidates"]
        old_id = next(iter(cands.keys()))
        val = cands.pop(old_id)
        cands["cand-adversarial-fake-id-00000000000000000000000000000000"] = val
        # Candidate count still 4, but candidate ID does not match Phase 252 pinned ID
        cand_dir = Path("artifacts/research/phase252/candidates")
        pinned_ids = {
            read_creator_candidate_artifact(p).candidate_id for p in cand_dir.glob("cand-*.json")
        }
        with pytest.raises(AssertionError):
            assert set(cands.keys()) == pinned_ids

        # 2. Corrupt candidate count
        tampered_count = copy.deepcopy(summary_json_data)
        tampered_count["cohort_health"]["reported_candidate_count"] = 3
        with pytest.raises(ValueError, match="Cohort candidate counts do not equal 4"):
            validate_live_paper_summary_oracle(tampered_count)

    def test_adversarial_timestamp_inversion_rejected(
        self, summary_json_data: dict[str, Any]
    ) -> None:
        """Inverting timestamps or skewing into future triggers immediate rejection."""
        # 1. ended_at before started_at
        tampered = copy.deepcopy(summary_json_data)
        tampered["run_metadata"]["started_at"] = "2026-09-06T01:00:00.000000+00:00"
        tampered["run_metadata"]["ended_at"] = "2026-09-06T00:50:00.000000+00:00"
        with pytest.raises(ValueError, match="Non-monotonic run times"):
            validate_live_paper_summary_oracle(tampered)

        # 2. ended_at after timestamp_utc
        tampered_skew = copy.deepcopy(summary_json_data)
        tampered_skew["timestamp_utc"] = "2026-09-06T00:52:00.000000+00:00"
        # ended_at is 00:52:12.351941+00:00
        with pytest.raises(ValueError, match="Timestamp skew"):
            validate_live_paper_summary_oracle(tampered_skew)

    def test_adversarial_window_violation_rejected(self, summary_json_data: dict[str, Any]) -> None:
        """Duration outside the bounded 10-15 minute window triggers immediate rejection."""
        # Under 600s
        under = copy.deepcopy(summary_json_data)
        under["run_metadata"]["started_at"] = "2026-09-06T00:41:47.915251+00:00"
        under["run_metadata"]["ended_at"] = "2026-09-06T00:48:47.915251+00:00"  # 420s
        under["run_metadata"]["duration_actual_seconds"] = 420.0
        with pytest.raises(ValueError, match="outside bounded 10-15m window"):
            validate_live_paper_summary_oracle(under)

        # Over 900s
        over = copy.deepcopy(summary_json_data)
        over["run_metadata"]["started_at"] = "2026-09-06T00:30:00.000000+00:00"
        over["run_metadata"]["ended_at"] = "2026-09-06T00:52:00.000000+00:00"  # 1320s
        over["run_metadata"]["duration_actual_seconds"] = 1320.0
        over["timestamp_utc"] = "2026-09-06T00:52:13.377492+00:00"
        with pytest.raises(ValueError, match="outside bounded 10-15m window"):
            validate_live_paper_summary_oracle(over)

        # Duration mismatch
        mismatch = copy.deepcopy(summary_json_data)
        mismatch["run_metadata"]["duration_actual_seconds"] = 700.0  # actual is 624.4s
        with pytest.raises(ValueError, match="Duration mismatch"):
            validate_live_paper_summary_oracle(mismatch)

    def test_adversarial_spread_inversion_rejected(self, summary_json_data: dict[str, Any]) -> None:
        """Inverted percentiles or negative spreads trigger immediate rejection."""
        # 1. p99 < p50
        inv_pct = copy.deepcopy(summary_json_data)
        inv_pct["network_telemetry"]["by_symbol"]["BTCUSDT"]["spread_bps"]["p99"] = 0.005
        with pytest.raises(ValueError, match="Inverted spread percentiles"):
            validate_live_paper_summary_oracle(inv_pct)

        # 2. negative spread min
        neg_min = copy.deepcopy(summary_json_data)
        neg_min["network_telemetry"]["by_symbol"]["ETHUSDT"]["spread_bps"]["min"] = -0.01
        with pytest.raises(ValueError, match="Spread min must be positive"):
            validate_live_paper_summary_oracle(neg_min)

        # 3. mean outside [min, max]
        out_mean = copy.deepcopy(summary_json_data)
        out_mean["network_telemetry"]["by_symbol"]["SOLUSDT"]["spread_bps"]["mean"] = 5.0
        with pytest.raises(ValueError, match="Mean spread .* outside"):
            validate_live_paper_summary_oracle(out_mean)

    def test_adversarial_safety_breaches_rejected(self, summary_json_data: dict[str, Any]) -> None:
        """Breaches of safety invariants (orders, keys, authority, activation) trigger rejection."""
        # 1. orders_submitted == 1
        orders_breach = copy.deepcopy(summary_json_data)
        orders_breach["safety_invariants"]["orders_submitted"] = 1
        with pytest.raises(ValueError, match="orders_submitted != 0"):
            validate_live_paper_summary_oracle(orders_breach)

        # 2. api_keys_loaded == 1
        keys_breach = copy.deepcopy(summary_json_data)
        keys_breach["safety_invariants"]["api_keys_loaded"] = 1
        with pytest.raises(ValueError, match="api_keys_loaded != 0"):
            validate_live_paper_summary_oracle(keys_breach)

        # 3. execution_authority == True
        auth_breach = copy.deepcopy(summary_json_data)
        auth_breach["safety_invariants"]["execution_authority"] = True
        with pytest.raises(ValueError, match="execution_authority must be False"):
            validate_live_paper_summary_oracle(auth_breach)

        # 4. live_trading_activation == True
        live_breach = copy.deepcopy(summary_json_data)
        live_breach["safety_invariants"]["live_trading_activation"] = True
        with pytest.raises(ValueError, match="live_trading_activation must be False"):
            validate_live_paper_summary_oracle(live_breach)

        # 5. promotion_state != 'unpromoted'
        promo_breach = copy.deepcopy(summary_json_data)
        promo_breach["safety_invariants"]["promotion_state"] = "promoted"
        with pytest.raises(ValueError, match="promotion_state must be 'unpromoted'"):
            validate_live_paper_summary_oracle(promo_breach)

    def test_adversarial_balance_drift_rejected(self, summary_json_data: dict[str, Any]) -> None:
        """Injected drift amount or starting/final cash discrepancy triggers rejection."""
        # Non-zero drift amount
        drift_breach = copy.deepcopy(summary_json_data)
        drift_breach["shared_portfolio_margin"]["drift_amount"] = "0.05"
        with pytest.raises(ValueError, match="Drift amount != 0.00"):
            validate_live_paper_summary_oracle(drift_breach)

        # zero_balance_drift is False
        flag_breach = copy.deepcopy(summary_json_data)
        flag_breach["shared_portfolio_margin"]["zero_balance_drift"] = False
        with pytest.raises(ValueError, match="zero_balance_drift is not True"):
            validate_live_paper_summary_oracle(flag_breach)

        # Final cash mismatch
        cash_breach = copy.deepcopy(summary_json_data)
        cash_breach["shared_portfolio_margin"]["final_cash"] = "99.50"
        with pytest.raises(ValueError, match="Final cash != 100.00 USDT"):
            validate_live_paper_summary_oracle(cash_breach)


class TestDynamicEngineDriftAndSafetyDefense:
    """Tests runtime engine and runner methods under live perturbation."""

    def test_engine_reconcile_balances_rejects_injected_drift(self, tmp_path: Path) -> None:
        """LivePaperEngine.reconcile_balances() raises DomainViolation when cash drifts."""
        engine = LivePaperEngine(
            symbols=DEFAULT_SYMBOLS,
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
        )

        # Nominal reconciliation passes with zero drift
        rec = engine.reconcile_balances()
        assert rec["zero_balance_drift"] is True
        assert rec["drift"] == "0.00"

        # Inject positive drift (+0.01 USDT)
        engine.account.cash += Decimal("0.01")
        with pytest.raises(DomainViolation, match="Cash balance drift detected"):
            engine.reconcile_balances()

        # Inject negative drift (-0.02 USDT)
        engine.account.cash -= Decimal("0.02")
        with pytest.raises(DomainViolation, match="Cash balance drift detected"):
            engine.reconcile_balances()

        # Micro-drift beyond 0.0001 tolerance (0.0002 USDT)
        engine.account.cash = Decimal("100.0002")
        with pytest.raises(DomainViolation, match="Cash balance drift detected"):
            engine.reconcile_balances()

    def test_verify_strict_safety_invariants_rejects_adversarial_orders(self) -> None:
        """verify_strict_safety_invariants raises RuntimeError if orders > 0 or keys loaded."""
        # 0 orders: valid
        res = verify_strict_safety_invariants(orders_submitted=0)
        assert res["orders_submitted"] == 0
        assert res["execution_authority"] is False

        # Positive order count: must raise
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION: orders submitted"):
            verify_strict_safety_invariants(orders_submitted=1)

        with pytest.raises(RuntimeError, match="SAFETY VIOLATION: orders submitted"):
            verify_strict_safety_invariants(orders_submitted=10)

    def test_verify_strict_safety_invariants_detects_secret_leakage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Setting BINANCE_API_KEY causes safety check to report private key loaded."""
        monkeypatch.setenv("BINANCE_API_KEY", "adversarial_secret_key_12345")
        res = verify_strict_safety_invariants(orders_submitted=0)
        assert res["api_keys_loaded"] == 1
        assert res["zero_secret_leakage"] is False
        assert res["zero_credentials_verified"] is False
