"""Phase 251 Empirical Adversarial Challenge Test Suite.

Adversarially stress-tests Phase 251 offline paper trading simulation harness:
1. Data Quality Controls: canonicalize_bars rejecting timestamp gaps, duplicate bars,
   non-monotonic/irregular timestamps, naive timestamps, and missing columns.
2. Causal Indicator Evaluation: CausalFeatureSignalEvaluator under degenerate price series
   (flat prices, parabolic jump, plummeting crash, extreme volatility square wave, invalid prices).
3. Maturity Slot Evaluation: evaluate_paper_maturity rejecting missing observation slots,
   future/forward timestamps, duplicate slots, binding mismatches, and incomplete accounting.
4. Terminal Boundary Liquidation: Forced closure of active positions at the terminal bar,
   entry suppression on the boundary bar, and cash balance reconciliation across capital scales.
5. Safety Invariants & Zero Secret Leakage: Asserting type-pinned literals and canary detection.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from autonomous_futures.creator_staging_probe import assert_offline_safety_invariants
from autonomous_futures.data.parquet import canonicalize_bars
from autonomous_futures.data.quality import DataQualityError
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.paper.maturity import evaluate_paper_maturity
from autonomous_futures.paper.observation import PaperObservation
from autonomous_futures.paper.reconciliation import reconcile_paper_positions
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger
from autonomous_futures.research.creator_artifacts import read_creator_candidate_artifact
from autonomous_futures.research.feature_signals import CausalFeatureSignalEvaluator

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_phase_251_paper_simulation import (  # noqa: E402
    _assert_zero_secrets,
    run_paper_simulation,
)

CANDIDATE_PATH = Path("artifacts/research/phase250/candidate-artifact.json")
QUALIFICATION_PATH = Path("artifacts/research/phase250/qualification-artifact.json")
START_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar_df(
    timestamps: list[datetime],
    prices: list[float] | None = None,
) -> pd.DataFrame:
    """Create a minimal valid OHLC DataFrame."""
    if prices is None:
        prices = [0.150] * len(timestamps)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal(str(round(p, 5))) for p in prices],
            "high": [Decimal(str(round(p + 0.0005, 5))) for p in prices],
            "low": [Decimal(str(round(p - 0.0005, 5))) for p in prices],
            "close": [Decimal(str(round(p, 5))) for p in prices],
        }
    )


# ===========================================================================
# 1. Data Quality Controls: canonicalize_bars
# ===========================================================================


class TestDataQualityControls:
    """Stress-test bar canonicalization under corrupted, gapped, or duplicate streams."""

    def test_canonicalize_bars_rejects_timestamp_gaps(self) -> None:
        """Verify that any gap > interval triggers DataQualityError with detailed message."""
        # 10m gap between bar 1 and bar 2 (nominal is 5m)
        ts = [
            START_TIME,
            START_TIME + timedelta(minutes=5),
            START_TIME + timedelta(minutes=15),  # gap: expected 00:10, got 00:15
            START_TIME + timedelta(minutes=20),
        ]
        df = _make_bar_df(ts)
        with pytest.raises(DataQualityError, match="timestamp gap"):
            canonicalize_bars(df, interval=timedelta(minutes=5))

    def test_canonicalize_bars_rejects_large_gaps(self) -> None:
        """Verify multi-hour or multi-day gaps are immediately rejected."""
        ts = [
            START_TIME,
            START_TIME + timedelta(hours=6),
        ]
        df = _make_bar_df(ts)
        with pytest.raises(DataQualityError, match="timestamp gap"):
            canonicalize_bars(df, interval=timedelta(minutes=5))

    def test_canonicalize_bars_rejects_sub_interval_irregular_steps(self) -> None:
        """Verify non-grid irregular timestamp steps are rejected."""
        ts = [
            START_TIME,
            START_TIME + timedelta(minutes=7),  # 7m step instead of 5m
            START_TIME + timedelta(minutes=12),
        ]
        df = _make_bar_df(ts)
        with pytest.raises(DataQualityError, match="timestamp gap"):
            canonicalize_bars(df, interval=timedelta(minutes=5))

    def test_canonicalize_bars_rejects_duplicate_timestamps(self) -> None:
        """Verify that duplicate timestamps in the bar stream are rejected."""
        ts = [
            START_TIME,
            START_TIME + timedelta(minutes=5),
            START_TIME + timedelta(minutes=5),  # duplicate
            START_TIME + timedelta(minutes=10),
        ]
        df = _make_bar_df(ts)
        with pytest.raises(DataQualityError, match="duplicate timestamps are not allowed"):
            canonicalize_bars(df, interval=timedelta(minutes=5))

    def test_canonicalize_bars_rejects_all_duplicate_timestamps(self) -> None:
        """Verify duplicate bars with identical OHLC values are rejected."""
        ts = [START_TIME, START_TIME]
        df = _make_bar_df(ts)
        with pytest.raises(DataQualityError, match="duplicate timestamps are not allowed"):
            canonicalize_bars(df, interval=timedelta(minutes=5))

    def test_canonicalize_bars_rejects_timezone_naive_timestamps(self) -> None:
        """Verify timezone-naive timestamps trigger UTC requirement error."""
        naive_ts = [datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 1, 0, 5)]
        df = pd.DataFrame(
            {
                "timestamp": naive_ts,
                "open": [Decimal("0.15"), Decimal("0.15")],
                "high": [Decimal("0.151"), Decimal("0.151")],
                "low": [Decimal("0.149"), Decimal("0.149")],
                "close": [Decimal("0.15"), Decimal("0.15")],
            }
        )
        with pytest.raises(DataQualityError, match="timestamps must be UTC-aware"):
            canonicalize_bars(df, interval=timedelta(minutes=5))

    def test_canonicalize_bars_rejects_empty_frame(self) -> None:
        """Verify empty DataFrame triggers DataQualityError."""
        empty_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
        with pytest.raises(DataQualityError, match="dataset must contain at least one row"):
            canonicalize_bars(empty_df, interval=timedelta(minutes=5))

    def test_canonicalize_bars_rejects_missing_timestamp_column(self) -> None:
        """Verify missing timestamp column is rejected."""
        df = pd.DataFrame({"open": [Decimal("0.15")], "close": [Decimal("0.15")]})
        with pytest.raises(DataQualityError, match="missing timestamp column"):
            canonicalize_bars(df, interval=timedelta(minutes=5))


# ===========================================================================
# 2. Causal Indicator Evaluation: Degenerate Price Series
# ===========================================================================


class TestCausalIndicatorDegenerateSeries:
    """Stress-test CausalFeatureSignalEvaluator under pathological price dynamics."""

    @pytest.fixture
    def candidate(self):
        return read_creator_candidate_artifact(CANDIDATE_PATH)

    @pytest.fixture
    def evaluator(self):
        return CausalFeatureSignalEvaluator()

    def test_causal_rsi_flat_price_series(self, candidate, evaluator) -> None:
        """Verify flat prices produce RSI=50.0 without divide-by-zero or NaNs."""
        n_bars = 60
        ts = [START_TIME + timedelta(minutes=5 * i) for i in range(n_bars)]
        df = _make_bar_df(ts, [0.150] * n_bars)

        evaluated = evaluator.evaluate(candidate, df)

        # After RSI warm-up (lookback=14 + shift=1 = 15 bars), RSI should be exactly 50.0
        active_rsi = evaluated["rsi"].iloc[15:]
        assert (active_rsi == 50.0).all(), f"Expected flat RSI=50.0, got {active_rsi.unique()}"

        # Neither long condition (rsi <= 30) nor short condition (rsi >= 70) should be True
        assert not evaluated["long_condition"].iloc[15:].any()
        assert not evaluated["short_condition"].iloc[15:].any()
        assert (evaluated["signal"].iloc[15:] == 0).all()

    def test_causal_rsi_monotonic_rally_series(self, candidate, evaluator) -> None:
        """Verify monotonic upward price explosion drives RSI to 100.0 with Short entry."""
        n_bars = 40
        ts = [START_TIME + timedelta(minutes=5 * i) for i in range(n_bars)]
        # Exponential growth: 0.10, 0.11, 0.12, ...
        prices = [0.10 + 0.01 * i for i in range(n_bars)]
        df = _make_bar_df(ts, prices)

        evaluated = evaluator.evaluate(candidate, df)

        # Once warm-up completes, gain > 0 and loss == 0, so raw RSI reaches 100.0
        mature_rsi = evaluated["rsi"].iloc[16:]
        assert (mature_rsi == 100.0).all()

        # Short condition (rsi >= 70) must be True; Long condition (rsi <= 30) must be False
        assert evaluated["short_condition"].iloc[16:].all()
        assert not evaluated["long_condition"].iloc[16:].any()

        # Signal must have triggered Short entry (-1) exactly once when entering condition
        assert (evaluated["signal"] == -1).sum() >= 1
        assert (evaluated["signal"] == 1).sum() == 0

    def test_causal_rsi_monotonic_crash_series(self, candidate, evaluator) -> None:
        """Verify monotonic downward crash drives RSI to 0.0 with Long entry."""
        n_bars = 40
        ts = [START_TIME + timedelta(minutes=5 * i) for i in range(n_bars)]
        # Price plummets from 10.0 downwards
        prices = [10.0 - 0.15 * i for i in range(n_bars)]
        df = _make_bar_df(ts, prices)

        evaluated = evaluator.evaluate(candidate, df)

        mature_rsi = evaluated["rsi"].iloc[16:]
        assert (mature_rsi == 0.0).all()

        # Long condition (rsi <= 30) must be True; Short condition (rsi >= 70) must be False
        assert evaluated["long_condition"].iloc[16:].all()
        assert not evaluated["short_condition"].iloc[16:].any()

        # Signal must have triggered Long entry (1)
        assert (evaluated["signal"] == 1).sum() >= 1
        assert (evaluated["signal"] == -1).sum() == 0

    def test_causal_rsi_extreme_volatility_square_wave(self, candidate, evaluator) -> None:
        """Verify alternating extreme swings stay bounded in [0, 100] without
        simultaneous signals.
        """
        n_bars = 80
        ts = [START_TIME + timedelta(minutes=5 * i) for i in range(n_bars)]
        # Rapid square-wave oscillation
        prices = [0.05 if i % 2 == 0 else 5.0 for i in range(n_bars)]
        df = _make_bar_df(ts, prices)

        evaluated = evaluator.evaluate(candidate, df)

        # All finite RSI values must stay within [0, 100]
        finite_rsi = evaluated["rsi"].dropna()
        assert (finite_rsi >= 0.0).all() and (finite_rsi <= 100.0).all()

        # Long and short condition must NEVER both be True simultaneously
        simultaneous = evaluated["long_condition"] & evaluated["short_condition"]
        assert not simultaneous.any(), "Simultaneous long and short condition triggered!"

    def test_causal_evaluator_rejects_non_positive_prices(self, candidate, evaluator) -> None:
        """Verify zero or negative price triggers DataQualityError."""
        ts = [START_TIME, START_TIME + timedelta(minutes=5)]
        df = _make_bar_df(ts, [0.15, -0.01])
        with pytest.raises(DataQualityError, match="OHLC column must be positive"):
            evaluator.evaluate(candidate, df)

    def test_causal_evaluator_rejects_non_finite_prices(self, candidate, evaluator) -> None:
        """Verify NaN or infinite price triggers DataQualityError."""
        ts = [START_TIME, START_TIME + timedelta(minutes=5)]
        df = pd.DataFrame(
            {
                "timestamp": ts,
                "open": [0.15, float("nan")],
                "high": [0.16, 0.16],
                "low": [0.14, 0.14],
                "close": [0.15, 0.15],
            }
        )
        with pytest.raises(DataQualityError, match="OHLC column is not finite"):
            evaluator.evaluate(candidate, df)

    def test_causal_evaluator_rejects_missing_ohlc_columns(self, candidate, evaluator) -> None:
        """Verify missing high/low/open/close columns trigger DataQualityError."""
        ts = [START_TIME, START_TIME + timedelta(minutes=5)]
        df = pd.DataFrame({"timestamp": ts, "close": [Decimal("0.15"), Decimal("0.15")]})
        with pytest.raises(DataQualityError, match="missing OHLC columns"):
            evaluator.evaluate(candidate, df)


# ===========================================================================
# 3. Maturity Evaluation Stress-Testing: evaluate_paper_maturity
# ===========================================================================


class TestMaturityEvaluation:
    """Stress-test evaluate_paper_maturity with gapped slots, forward timestamps, and duplicates."""

    @pytest.fixture
    def candidate(self):
        return read_creator_candidate_artifact(CANDIDATE_PATH)

    def _generate_valid_observations(
        self, candidate, total_slots: int = 28
    ) -> list[PaperObservation]:
        """Generate contiguous sequence of 6-hour paper observations."""
        observations: list[PaperObservation] = []
        for i in range(total_slots):
            obs_time = START_TIME + timedelta(hours=6 * i)
            obs = PaperObservation(
                candidate_id=candidate.candidate_id,
                candidate_artifact_hash=candidate.artifact_hash,
                observed_at=obs_time,
                equity=Decimal("10050.00"),
                realized_pnl=Decimal("50.00"),
                unrealized_pnl=Decimal("0.00"),
                peak_equity=Decimal("10050.00"),
                drawdown_pct=Decimal("0.00"),
                open_position_count=0,
                quote_exposure=Decimal("0.00"),
                cumulative_fees=Decimal("2.00"),
                cumulative_slippage=Decimal("1.00"),
                accounting_complete=True,
                reason_codes=("paper_observed",),
            )
            observations.append(obs)
        return observations

    def test_maturity_blocks_on_missing_observation_slot(self, candidate) -> None:
        """Verify that skipping an observation slot sets status='blocked' with slot_missing."""
        obs = self._generate_valid_observations(candidate, total_slots=28)
        # Drop slot 4 (at 24h)
        missing_slot = obs[4].observed_at
        del obs[4]

        report = evaluate_paper_maturity(
            obs,
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            as_of=START_TIME + timedelta(days=7),
            required_days=7,
        )
        assert report.status == "blocked"
        assert "paper_observation_slot_missing" in report.reason_codes
        assert report.next_slot == missing_slot

    def test_maturity_blocks_on_future_timestamp(self, candidate) -> None:
        """Verify that an observation with timestamp > as_of blocks maturity."""
        obs = self._generate_valid_observations(candidate, total_slots=10)
        # as_of is set prior to the last observation
        as_of_time = obs[-2].observed_at

        report = evaluate_paper_maturity(
            obs,
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            as_of=as_of_time,
            required_days=7,
        )
        assert report.status == "blocked"
        assert "paper_observation_future_timestamp" in report.reason_codes

    def test_maturity_blocks_on_duplicate_slot(self, candidate) -> None:
        """Verify that two observations falling into the same 6-hour window blocks maturity."""
        obs = self._generate_valid_observations(candidate, total_slots=10)
        # Insert duplicate observation in slot 2
        dup = obs[2].model_copy(update={"observed_at": obs[2].observed_at + timedelta(minutes=30)})
        obs.insert(3, dup)

        report = evaluate_paper_maturity(
            obs,
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            as_of=START_TIME + timedelta(days=7),
            required_days=7,
        )
        assert report.status == "blocked"
        assert "paper_observation_duplicate_slot" in report.reason_codes

    def test_maturity_blocks_on_binding_mismatch(self, candidate) -> None:
        """Verify observation with mismatched candidate_id or artifact_hash blocks maturity."""
        obs = self._generate_valid_observations(candidate, total_slots=10)
        tampered = obs[3].model_copy(update={"candidate_id": "cand-mismatched-001"})
        obs[3] = tampered

        report = evaluate_paper_maturity(
            obs,
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            as_of=START_TIME + timedelta(days=7),
            required_days=7,
        )
        assert report.status == "blocked"
        assert "paper_observation_binding_mismatch" in report.reason_codes

    def test_maturity_blocks_on_incomplete_accounting(self, candidate) -> None:
        """Verify an observation with accounting_complete=False blocks maturity."""
        obs = self._generate_valid_observations(candidate, total_slots=10)
        broken = obs[2].model_copy(update={"accounting_complete": False})
        obs[2] = broken

        report = evaluate_paper_maturity(
            obs,
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            as_of=START_TIME + timedelta(days=7),
            required_days=7,
        )
        assert report.status == "blocked"
        assert "paper_observation_accounting_incomplete" in report.reason_codes

    def test_maturity_status_lifecycle_progression(self, candidate) -> None:
        """Verify transition unavailable -> maturing -> mature as slots accumulate."""
        # 1. Unavailable when empty
        rep_unavail = evaluate_paper_maturity(
            (),
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            as_of=START_TIME,
            required_days=7,
        )
        assert rep_unavail.status == "unavailable"
        assert "paper_observation_evidence_unavailable" in rep_unavail.reason_codes

        # 2. Maturing when in-progress (14 of 28 slots observed, as_of at 14 slots)
        obs_14 = self._generate_valid_observations(candidate, total_slots=14)
        rep_maturing = evaluate_paper_maturity(
            obs_14,
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            as_of=START_TIME + timedelta(hours=6 * 14),
            required_days=7,
        )
        assert rep_maturing.status == "maturing"
        assert "paper_observation_maturity_in_progress" in rep_maturing.reason_codes

        # 3. Mature when all 28 slots observed and as_of >= maturity_end
        obs_28 = self._generate_valid_observations(candidate, total_slots=28)
        rep_mature = evaluate_paper_maturity(
            obs_28,
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            as_of=START_TIME + timedelta(days=7),
            required_days=7,
        )
        assert rep_mature.status == "mature"
        assert "paper_observation_maturity_complete" in rep_mature.reason_codes


# ===========================================================================
# 4. Terminal Boundary Position Liquidation & Cash Balance Reconciliation
# ===========================================================================


class TestTerminalBoundaryLiquidationAndCashReconciliation:
    """Stress-test boundary liquidation, entry suppression, and cash reconciliation."""

    def test_terminal_boundary_forces_position_closure(self, tmp_path: Path) -> None:
        """Verify open position is forcibly closed at simulation end with zero drift."""
        output_dir = tmp_path / "terminal_forced_liquidation"

        # Construct a 2-day bar series where the last cycle opens a trade right at the end
        # and has no strategy exit trigger before the terminal bar.
        cycle_bars = 72
        days = 2
        total_cycles = days * 4
        all_prices: list[float] = []

        for c in range(total_cycles):
            flat = [0.150] * 15
            if c == total_cycles - 1:
                # Terminal cycle: plunge right at the end (bars 65-71) to trigger Long entry
                # without time to hit exit condition (rsi >= 50)
                calm = [0.150] * 50
                dip = [0.140 - 0.001 * i for i in range(7)]  # plunge
                all_prices.extend(calm + dip)
            else:
                dip = [0.140, 0.140]
                bounce = [0.140 + 0.001 * i for i in range(1, 10)]
                rally = [0.150 + 0.001 * i for i in range(1, 10)]
                retrace = [0.159 - 0.001 * i for i in range(1, 10)]
                rest = [0.150] * (
                    cycle_bars - len(flat) - len(dip) - len(bounce) - len(rally) - len(retrace)
                )
                all_prices.extend(flat + dip + bounce + rally + retrace + rest)

        all_prices.append(all_prices[-1])  # terminal bar
        ts = [START_TIME + timedelta(minutes=5 * i) for i in range(len(all_prices))]
        df = _make_bar_df(ts, all_prices)

        data_file = tmp_path / "boundary_test_bars.parquet"
        canonicalize_bars(df, interval=timedelta(minutes=5)).to_parquet(data_file)

        result = run_paper_simulation(
            output_dir=output_dir,
            data_path=data_file,
            days=days,
            starting_equity=Decimal("10000.00"),
            quantity=Decimal("1000.0"),
        )

        ledger = SqlitePaperLedger(output_dir / "paper-ledger.sqlite3").load()

        # Zero dangling open positions
        open_positions = ledger.open_positions()
        assert len(open_positions) == 0, f"Found open positions at boundary: {open_positions}"

        # Position reconciliation passes
        recon = reconcile_paper_positions(ledger, ())
        assert recon.reconciled is True
        assert recon.runtime_only_trade_ids == ()
        assert recon.ledger_only_trade_ids == ()

        # Cash reconciliation holds exact
        assert result.final_cash == result.starting_equity + result.realized_pnl

    def test_terminal_bar_entry_is_prevented(self, tmp_path: Path) -> None:
        """Verify that an entry signal on the exact terminal bar is suppressed."""
        output_dir = tmp_path / "terminal_entry_prevention"

        # Generate standard 2 days
        result = run_paper_simulation(
            output_dir=output_dir,
            days=2,
            starting_equity=Decimal("5000.00"),
        )

        ledger = SqlitePaperLedger(output_dir / "paper-ledger.sqlite3").load()
        open_positions = ledger.open_positions()
        assert len(open_positions) == 0
        assert result.positions_reconciled is True
        assert result.final_cash == Decimal("5000.00") + result.realized_pnl

    def test_cash_balance_reconciliation_multi_capital_scales(self, tmp_path: Path) -> None:
        """Verify cash balance equation holds exact across multiple capital scales."""
        scales = [Decimal("1000.00"), Decimal("50000.00")]
        for idx, cap in enumerate(scales):
            out = tmp_path / f"scale_{idx}"
            res = run_paper_simulation(
                output_dir=out,
                days=2,
                starting_equity=cap,
                quantity=Decimal("1000.0"),
            )

            ledger = SqlitePaperLedger(out / "paper-ledger.sqlite3").load()
            closed = [e for e in ledger.entries if e.event == "close"]

            total_net = sum((e.net_pnl for e in closed if e.net_pnl is not None), Decimal("0"))
            assert res.realized_pnl == total_net
            assert res.final_cash == cap + total_net

            # Every trade net PnL is exact
            for e in closed:
                assert e.gross_pnl is not None
                assert e.entry_fee is not None
                assert e.exit_fee is not None
                assert e.net_pnl is not None
                assert e.net_pnl == e.gross_pnl - e.entry_fee - e.exit_fee


# ===========================================================================
# 5. Offline Safety Invariants & Canary Secret Detection
# ===========================================================================


class TestSafetyInvariantsAndCanarySecrets:
    """Stress-test offline safety invariants and secret leakage detection."""

    def test_offline_safety_invariants_pass_in_offline_env(self) -> None:
        """Verify assert_offline_safety_invariants succeeds in offline environment."""
        assert_offline_safety_invariants()

    def test_assert_zero_secrets_catches_canary_tokens(self) -> None:
        """Verify _assert_zero_secrets raises DomainViolation on Canary tokens."""
        canary_keys = [
            "AIzaSyDTESTINGSECRETKEY012345678901234",
            "ya29.a0AfH6SMADVERSARIAL_BEARER_TOKEN_VALUE",
            "bearer abcdefghijklmnopqrstuvwxyz1234567890==",
        ]
        for key in canary_keys:
            with pytest.raises(DomainViolation, match="Secret pattern matched"):
                _assert_zero_secrets(f"Payload containing secret: {key}", "test_canary")

    def test_assert_zero_secrets_passes_benign_text(self) -> None:
        """Verify benign JSON and text pass _assert_zero_secrets without false positives."""
        benign_texts = [
            (
                '{"candidate_id": '
                '"cand-a5454657c3fc480b03246904e7674eeabe9f35890ee863c24ce2788e3f5c4c15"}'
            ),
            "status: healthy, total_trades: 56, win_rate: 0.9821",
            "bundle_hash: 19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816",
        ]
        for text in benign_texts:
            _assert_zero_secrets(text, "test_benign")
