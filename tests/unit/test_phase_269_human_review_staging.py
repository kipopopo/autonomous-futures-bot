"""Unit tests for Phase 269: Operator Human Review Governance & Canary Staging Packaging."""

from __future__ import annotations

import io
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    read_candidate_registry,
)
from autonomous_futures.paper.review_cli import main as review_cli_main  # noqa: E402
from autonomous_futures.paper.sqlite_review import SqlitePaperReviews  # noqa: E402
from autonomous_futures.paper.staging import (  # noqa: E402
    DEFAULT_PHASE268_COHORT_DIR,
    DEFAULT_PHASE269_OUTPUT_DIR,
    DOUBLE_ENTRY_MAX_DRIFT,
    EXPECTED_MANIFEST_V2_CANDIDATES,
    CandidatePerformanceBreakdown,
    assert_zero_secrets,
    check_fail_closed_safety_invariants,
    compute_decision_hash,
    compute_file_sha256,
    compute_manifest_hash,
    compute_staging_signature,
    format_performance_table,
    inspect_cohort,
    safe_decimal,
    save_staging_artifacts,
    stage_canary_candidates,
    verify_prerequisite_gates,
)
from scripts.run_phase_269_human_review_staging import (  # noqa: E402
    build_arg_parser,
    run_phase_269_human_review_staging,
)


class TestPhase269CandidateRegistryAndProvenance:
    """Test candidate registry v2 compatibility, expected candidates, and provenance hashes."""

    def test_manifest_v2_active_candidates_match_phase269_spec(self) -> None:
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH)
        assert manifest.registry_version >= 2
        assert set(manifest.symbols.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        for sym, exp_id in EXPECTED_MANIFEST_V2_CANDIDATES.items():
            entry = manifest.symbols[sym]
            assert entry.candidate_id == exp_id
            assert len(entry.candidate_artifact_hash) == 64
            assert len(entry.qualification_hash) == 64
            assert Path(entry.artifact_path).is_file()

    def test_safe_decimal_coercion(self) -> None:
        assert safe_decimal(None) == Decimal("0")
        assert safe_decimal("123.456") == Decimal("123.456")
        assert safe_decimal(100) == Decimal("100")
        assert safe_decimal("invalid", default=Decimal("5.0")) == Decimal("5.0")
        assert safe_decimal("") == Decimal("0")


class TestPhase269CohortInspectionAndMetrics:
    """Test inspection of Phase 268 mature paper trading cohort and metrics extraction."""

    def test_inspect_phase268_mature_cohort(self) -> None:
        result = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        assert result.cohort_status == "ready_for_human_review"
        assert len(result.upstream_hashes) >= 8
        assert len(result.upstream_digest) == 64
        assert result.starting_equity == Decimal("100.00")
        assert result.final_cash > Decimal("90.00")
        assert result.zero_drift is True
        assert result.drift < DOUBLE_ENTRY_MAX_DRIFT
        assert result.max_margin_utilization <= Decimal("0.80")
        assert result.min_reserve_buffer >= Decimal("0.20")

        # Verify candidate breakdowns
        assert set(result.candidate_breakdowns.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        btc = result.candidate_breakdowns["BTCUSDT"]
        assert btc.candidate_id == "cand-btcusdt-dcb-002"
        assert btc.total_trades == 26
        assert btc.health_status == "healthy"
        assert btc.maturity_status == "mature"
        assert btc.accounting_complete is True
        assert btc.observed_slots == 57

        eth = result.candidate_breakdowns["ETHUSDT"]
        assert eth.candidate_id == "cand-ethusdt-dcb-003"
        assert eth.total_trades == 30
        assert eth.health_status == "healthy"
        assert eth.maturity_status == "mature"

        sol = result.candidate_breakdowns["SOLUSDT"]
        assert sol.candidate_id == "cand-solusdt-rgb-001"
        assert sol.total_trades == 13
        assert sol.health_status == "healthy"
        assert sol.maturity_status == "mature"

        # Check prerequisite checklist passes
        chk = result.prerequisite_checklist
        assert chk.all_gates_passed is True
        assert chk.cohort_status_ready is True
        assert chk.expected_candidates_present is True
        assert chk.all_candidates_mature is True
        assert chk.all_candidates_healthy is True
        assert chk.zero_candidates_blocked is True
        assert chk.accounting_complete is True
        assert chk.zero_balance_drift is True
        assert chk.margin_guardrails_compliant is True
        assert chk.positive_terminal_equity is True
        assert chk.zero_circuit_breaker_flags is True
        assert len(chk.failure_reasons) == 0

    def test_format_performance_table(self) -> None:
        result = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        table_text = format_performance_table(result)
        assert "PHASE 269: CANDIDATE PERFORMANCE & COHORT INSPECTION BREAKDOWN" in table_text
        assert "BTCUSDT" in table_text
        assert "ETHUSDT" in table_text
        assert "SOLUSDT" in table_text
        assert "cand-btcusdt-dcb-002" in table_text
        assert "ALL PASSED" in table_text


class TestPhase269PrerequisiteGatesFailClosed:
    """Test strict fail-closed enforcement when prerequisite gates are violated."""

    def _sample_breakdowns(self) -> dict[str, CandidatePerformanceBreakdown]:
        return {
            "BTCUSDT": CandidatePerformanceBreakdown(
                symbol="BTCUSDT",
                candidate_id="cand-btcusdt-dcb-002",
                family="donchian_channel_breakout",
                timeframe="15m",
                total_trades=26,
                winning_trades=1,
                losing_trades=25,
                win_rate_pct=3.85,
                realized_pnl_usdt=Decimal("-1.0963"),
                observed_slots=57,
                margin_utilization=Decimal("0.20"),
                cumulative_fees_usdt=Decimal("0.4161"),
                cumulative_slippage_usdt=Decimal("0.2081"),
                health_status="healthy",
                maturity_status="mature",
                accounting_complete=True,
            ),
            "ETHUSDT": CandidatePerformanceBreakdown(
                symbol="ETHUSDT",
                candidate_id="cand-ethusdt-dcb-003",
                family="donchian_channel_breakout",
                timeframe="15m",
                total_trades=30,
                winning_trades=5,
                losing_trades=25,
                win_rate_pct=16.67,
                realized_pnl_usdt=Decimal("-1.1488"),
                observed_slots=57,
                margin_utilization=Decimal("0.20"),
                cumulative_fees_usdt=Decimal("0.4800"),
                cumulative_slippage_usdt=Decimal("0.2400"),
                health_status="healthy",
                maturity_status="mature",
                accounting_complete=True,
            ),
            "SOLUSDT": CandidatePerformanceBreakdown(
                symbol="SOLUSDT",
                candidate_id="cand-solusdt-rgb-001",
                family="regime_gated_breakout",
                timeframe="1h",
                total_trades=13,
                winning_trades=5,
                losing_trades=8,
                win_rate_pct=38.46,
                realized_pnl_usdt=Decimal("-0.9937"),
                observed_slots=57,
                margin_utilization=Decimal("0.20"),
                cumulative_fees_usdt=Decimal("0.3760"),
                cumulative_slippage_usdt=Decimal("0.1880"),
                health_status="healthy",
                maturity_status="mature",
                accounting_complete=True,
            ),
        }

    def test_fails_when_cohort_status_not_ready(self) -> None:
        chk = verify_prerequisite_gates(
            cohort_status="not_ready",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=self._sample_breakdowns(),
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
        )
        assert chk.all_gates_passed is False
        assert chk.cohort_status_ready is False
        assert any("cohort_status_not_ready" in r for r in chk.failure_reasons)

    def test_fails_when_candidate_missing_or_mismatched(self) -> None:
        b = self._sample_breakdowns()
        del b["SOLUSDT"]
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=b,
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
        )
        assert chk.all_gates_passed is False
        assert chk.expected_candidates_present is False
        assert any("missing_candidate_symbol:SOLUSDT" in r for r in chk.failure_reasons)

    def test_fails_when_candidate_immature(self) -> None:
        b = self._sample_breakdowns()
        b["BTCUSDT"] = b["BTCUSDT"].model_copy(update={"maturity_status": "evaluating"})
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=b,
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
        )
        assert chk.all_gates_passed is False
        assert chk.all_candidates_mature is False
        assert any("immature_candidate:BTCUSDT" in r for r in chk.failure_reasons)

    def test_fails_when_candidate_unhealthy_or_blocked(self) -> None:
        b = self._sample_breakdowns()
        b["ETHUSDT"] = b["ETHUSDT"].model_copy(update={"health_status": "blocked"})
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=b,
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 1},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
        )
        assert chk.all_gates_passed is False
        assert chk.all_candidates_healthy is False
        assert chk.zero_candidates_blocked is False

    def test_fails_when_accounting_incomplete(self) -> None:
        b = self._sample_breakdowns()
        b["SOLUSDT"] = b["SOLUSDT"].model_copy(update={"accounting_complete": False})
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=b,
            raw_readiness={"all_accounting_complete": False, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
        )
        assert chk.all_gates_passed is False
        assert chk.accounting_complete is False

    def test_fails_when_balance_drift_exceeds_threshold(self) -> None:
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=self._sample_breakdowns(),
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0001"),  # > 1e-15
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
        )
        assert chk.all_gates_passed is False
        assert chk.zero_balance_drift is False
        assert any("balance_drift_exceeded" in r for r in chk.failure_reasons)

    def test_fails_when_margin_guardrails_exceeded(self) -> None:
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=self._sample_breakdowns(),
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.85"),  # > 0.80
            min_reserve_buffer=Decimal("0.15"),  # < 0.20
        )
        assert chk.all_gates_passed is False
        assert chk.margin_guardrails_compliant is False
        assert any("margin_guardrails_violated" in r for r in chk.failure_reasons)

    def test_fails_when_terminal_equity_negative(self) -> None:
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=self._sample_breakdowns(),
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("-1.50"),  # negative terminal equity
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
        )
        assert chk.all_gates_passed is False
        assert chk.positive_terminal_equity is False
        assert any("negative_terminal_equity" in r for r in chk.failure_reasons)

    def test_fails_when_circuit_breaker_active(self) -> None:
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=self._sample_breakdowns(),
            raw_readiness={
                "all_accounting_complete": True,
                "blocked_candidate_count": 0,
                "reason_codes": ["circuit_breaker_gap_risk_tripped"],
            },
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
        )
        assert chk.all_gates_passed is False
        assert chk.zero_circuit_breaker_flags is False
        assert any("unresolved_circuit_breaker" in r for r in chk.failure_reasons)


class TestPhase269StagingPackagingAndSigning:
    """Test candidate staging, cryptographic hashes, HMAC signatures, and summary packaging."""

    def test_stage_canary_candidates_approved(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        dec, man, summary = stage_canary_candidates(
            decision="approved_for_canary",
            operator_id="operator-lead-001",
            rationale="Approved all candidates based on 14-day mature paper evidence",
            inspection=inspection,
        )

        # Decision
        assert dec.decision == "approved_for_canary"
        assert dec.operator_id == "operator-lead-001"
        assert dec.prerequisite_checklist.all_gates_passed is True
        assert len(dec.decision_hash) == 64
        assert compute_decision_hash(dec) == dec.decision_hash

        # Manifest
        assert man.staging_promotion_state == "canary_staged"
        assert man.manifest_version == 2
        assert man.registry_version == 2
        assert len(man.candidates) == 3
        for cand in man.candidates.values():
            assert cand.staging_promotion_state == "canary_staged"
            assert cand.allocated_risk_limits.max_position_fraction == Decimal("0.20")
            assert cand.allocated_risk_limits.max_margin_utilization == Decimal("0.80")
            assert cand.allocated_risk_limits.min_reserve_buffer == Decimal("0.20")
            assert cand.allocated_risk_limits.allocated_margin_usdt == Decimal("20.00")
            assert len(cand.candidate_artifact_hash) == 64
            assert len(cand.qualification_hash) == 64

        assert len(man.manifest_hash) == 64
        assert compute_manifest_hash(man) == man.manifest_hash
        assert len(man.cryptographic_signature) == 64
        assert (
            compute_staging_signature(man.operator_id, man.decision_id, man.manifest_hash)
            == man.cryptographic_signature
        )

        # Summary
        assert summary["phase"] == "phase_269"
        assert summary["decision"] == "approved_for_canary"
        assert summary["staging_promotion_state"] == "canary_staged"
        assert summary["staged_manifest_hash"] == man.manifest_hash
        assert summary["human_review_decision_hash"] == dec.decision_hash

    def test_stage_canary_candidates_fails_if_gates_not_passed(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        # Artificially alter prerequisite checklist to simulate failure
        failing_chk = inspection.prerequisite_checklist.model_copy(
            update={"all_gates_passed": False, "failure_reasons": ["simulated_failure"]}
        )
        failing_inspection = inspection.model_copy(update={"prerequisite_checklist": failing_chk})

        with pytest.raises(DomainViolation, match="prerequisite gates failed"):
            stage_canary_candidates(
                decision="approved_for_canary",
                operator_id="operator-lead-001",
                rationale="Should fail",
                inspection=failing_inspection,
            )

    def test_stage_canary_candidates_rejected_and_held(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)

        # Rejected decision
        dec_rej, man_rej, sum_rej = stage_canary_candidates(
            decision="rejected",
            operator_id="operator-risk-002",
            rationale="Rejected due to conservative risk profile",
            inspection=inspection,
        )
        assert dec_rej.decision == "rejected"
        assert man_rej.staging_promotion_state == "rejected"
        for cand in man_rej.candidates.values():
            assert cand.staging_promotion_state == "rejected"
        assert sum_rej["staging_promotion_state"] == "staging_rejected"

        # Held decision
        dec_held, man_held, sum_held = stage_canary_candidates(
            decision="held",
            operator_id="operator-risk-003",
            rationale="Holding for additional market volatility cycles",
            inspection=inspection,
        )
        assert dec_held.decision == "held"
        assert man_held.staging_promotion_state == "unpromoted"
        for cand in man_held.candidates.values():
            assert cand.staging_promotion_state == "unpromoted"
        assert sum_held["staging_promotion_state"] == "staging_held"

    def test_save_staging_artifacts_atomicity(self, tmp_path: Path) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        dec, man, summary = stage_canary_candidates(
            decision="approved_for_canary",
            operator_id="operator-ops-001",
            rationale="Save artifacts test",
            inspection=inspection,
        )
        hashes = save_staging_artifacts(tmp_path, dec, man, summary)
        assert "canary-staging-manifest.json" in hashes
        assert "human-review-decision.json" in hashes
        assert "operator-summary.json" in hashes
        assert "paper-summary.json" in hashes

        assert (tmp_path / "canary-staging-manifest.json").is_file()
        assert (tmp_path / "human-review-decision.json").is_file()
        assert (tmp_path / "operator-summary.json").is_file()
        assert (tmp_path / "paper-summary.json").is_file()

        # Re-verify hashes on disk
        assert (
            compute_file_sha256(tmp_path / "canary-staging-manifest.json")
            == hashes["canary-staging-manifest.json"]
        )
        assert (
            compute_file_sha256(tmp_path / "human-review-decision.json")
            == hashes["human-review-decision.json"]
        )


class TestPhase269CLIExecutionAndInteractivity:
    """Test CLI commands in batch, interactive, and legacy modes."""

    def test_cli_batch_approved_for_canary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_dir = tmp_path / "phase269_out"
        ret = review_cli_main(
            [
                "--cohort-dir",
                str(DEFAULT_PHASE268_COHORT_DIR),
                "--output-dir",
                str(out_dir),
                "--decision",
                "approved_for_canary",
                "--operator",
                "operator-test-001",
                "--rationale",
                "Batch execution unit test",
                "--json",
            ]
        )
        assert ret == 0
        captured = json.loads(capsys.readouterr().out)
        assert captured["status"] == "success"
        assert captured["decision"] == "approved_for_canary"
        assert captured["operator_id"] == "operator-test-001"
        assert (out_dir / "canary-staging-manifest.json").is_file()

    def test_cli_batch_missing_decision_in_non_interactive_mode(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_dir = tmp_path / "phase269_out"
        ret = review_cli_main(
            [
                "--cohort-dir",
                str(DEFAULT_PHASE268_COHORT_DIR),
                "--output-dir",
                str(out_dir),
                "--json",
            ]
        )
        assert ret == 2
        captured = json.loads(capsys.readouterr().out)
        assert captured["status"] == "error"
        assert captured["error_code"] == "decision_required_in_non_interactive_mode"

    def test_cli_interactive_prompt_simulation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_dir = tmp_path / "phase269_out"
        user_inputs = io.StringIO("operator-interactive-lead\n1\nApproved via interactive prompt\n")
        monkeypatch.setattr(sys, "stdin", user_inputs)

        ret = review_cli_main(
            [
                "--cohort-dir",
                str(DEFAULT_PHASE268_COHORT_DIR),
                "--output-dir",
                str(out_dir),
                "--interactive",
            ]
        )
        assert ret == 0
        captured = capsys.readouterr().out
        assert "PHASE 269: CANDIDATE PERFORMANCE & COHORT INSPECTION BREAKDOWN" in captured
        assert "=== PHASE 269 OPERATOR REVIEW & CANARY STAGING COMPLETED ===" in captured
        assert (out_dir / "canary-staging-manifest.json").is_file()

    def test_cli_optional_sqlite_recording(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase269_out"
        sqlite_file = tmp_path / "paper-reviews.sqlite3"
        ret = review_cli_main(
            [
                "--cohort-dir",
                str(DEFAULT_PHASE268_COHORT_DIR),
                "--output-dir",
                str(out_dir),
                "--decision",
                "approved_for_canary",
                "--operator",
                "operator-sql-001",
                "--rationale",
                "Recording to SQLite as well",
                "--review-path",
                str(sqlite_file),
                "--json",
            ]
        )
        assert ret == 0
        assert sqlite_file.is_file()
        reviews = SqlitePaperReviews(sqlite_file).read()
        assert len(reviews) == 1
        assert reviews[0].reviewer_id == "operator-sql-001"

    def test_runner_script_main_function(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "runner_out"
        ret = run_phase_269_human_review_staging(
            cohort_dir=DEFAULT_PHASE268_COHORT_DIR,
            output_dir=out_dir,
            decision="held",
            operator="operator-runner",
            rationale="Test runner function",
            json_output=True,
        )
        assert ret == 0
        assert (out_dir / "canary-staging-manifest.json").is_file()

    def test_build_arg_parser_defaults(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args([])
        assert args.cohort_dir == DEFAULT_PHASE268_COHORT_DIR
        assert args.output_dir == DEFAULT_PHASE269_OUTPUT_DIR
        assert args.decision is None


class TestPhase269FailClosedSafetyAndZeroSecrets:
    """Test safety containment: no live orders, no credentials, zero secret leakage."""

    def test_safety_invariants_in_generated_artifacts(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        dec, man, summary = stage_canary_candidates(
            decision="approved_for_canary",
            operator_id="operator-safety",
            rationale="Safety invariant test",
            inspection=inspection,
        )

        for container in (
            dec.safety_invariants,
            man.safety_invariants,
            summary["safety_invariants"],
        ):
            assert container["paper_activation"] is False
            assert container["execution_authority"] is False
            assert container["exchange_access"] is False
            assert container["orders"] == 0
            assert container["api_keys_loaded"] == 0
            assert container["zero_secret_leakage"] is True

    def test_secret_scanner_catches_tokens(self) -> None:
        fake_gh_token = "".join(["g", "h", "p_", "A" * 36])
        with pytest.raises(DomainViolation, match="Secret pattern matched"):
            assert_zero_secrets(fake_gh_token, "test_token")

        fake_api_key = "".join(["A", "I", "z", "a", "SyB", "123456789012345678901234567890"])
        with pytest.raises(DomainViolation, match="Secret pattern matched"):
            assert_zero_secrets(fake_api_key, "api_key")

        # Clean strings pass without raising
        assert_zero_secrets("clean_token_string_here_no_secrets", "clean")
        assert_zero_secrets(None, "none")

    def test_secret_scanner_catches_openai_sk_token(self) -> None:
        fake_sk_token = "sk-" + "A" * 32
        with pytest.raises(DomainViolation, match="Secret pattern matched"):
            assert_zero_secrets(fake_sk_token, "openai_token")


class TestPhase269AdversarialHardening:
    """Targeted tests probing adversarial edge cases and fail-closed gates."""

    def test_fails_when_credential_contamination_in_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        monkeypatch.setenv("BINANCE_API_KEY", "adverse_live_key_999")

        # 1. Gate check fails
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=inspection.candidate_breakdowns,
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
        )
        assert chk.all_gates_passed is False
        assert chk.zero_api_keys_loaded is False
        assert any("credential_contamination_detected:1" in r for r in chk.failure_reasons)

        # 2. Canary staging fails closed
        with pytest.raises(DomainViolation, match="live exchange credentials detected"):
            stage_canary_candidates(
                decision="approved_for_canary",
                operator_id="operator-ops-001",
                rationale="Should fail due to env credentials",
                inspection=inspection,
            )

    def test_fails_when_unclosed_positions_detected(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=inspection.candidate_breakdowns,
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
            raw_summary={
                "portfolio_summary": {
                    "open_positions_count": 2,
                    "positions_reconciled": False,
                }
            },
        )
        assert chk.all_gates_passed is False
        assert chk.all_positions_closed is False
        assert any("unclosed_positions_detected:2" in r for r in chk.failure_reasons)
        assert any("positions_unreconciled" in r for r in chk.failure_reasons)

    def test_fails_when_candidate_pnl_drift_exceeded(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=inspection.candidate_breakdowns,
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
            realized_pnl=Decimal("10.00"),  # drastically different from candidate pnl sum (-3.2387)
        )
        assert chk.all_gates_passed is False
        assert chk.candidate_accounting_reconciled is False
        assert any("candidate_pnl_reconciliation_drift_exceeded" in r for r in chk.failure_reasons)

    def test_fails_when_upstream_artifact_tampered(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=inspection.candidate_breakdowns,
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
            upstream_integrity_verified=False,
            tampered_files=["paper-ledger.sqlite3:badbeef!=deadbeef"],
        )
        assert chk.all_gates_passed is False
        assert chk.upstream_integrity_verified is False
        assert any("upstream_artifact_hash_mismatch" in r for r in chk.failure_reasons)

    def test_fails_when_candidate_hash_mismatch_with_registry(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH)

        # Corrupt one entry in registry manifest to simulate mismatch
        corrupt_symbols = dict(manifest.symbols)
        corrupt_symbols["BTCUSDT"] = corrupt_symbols["BTCUSDT"].model_copy(
            update={"candidate_artifact_hash": "a" * 64}
        )
        corrupt_manifest = manifest.model_copy(update={"symbols": corrupt_symbols})

        with pytest.raises(DomainViolation, match="Candidate artifact hash mismatch"):
            stage_canary_candidates(
                decision="approved_for_canary",
                operator_id="operator-ops-001",
                rationale="Candidate hash mismatch test",
                inspection=inspection,
                registry_manifest=corrupt_manifest,
            )

    def test_fails_when_candidate_hash_missing_or_dummy_on_approval(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)

        # Empty candidates in raw summary
        corrupt_summary = dict(inspection.raw_summary)
        corrupt_summary["candidates"] = {
            "BTCUSDT": {"artifact_hash": "0" * 64, "qualification_hash": "0" * 64}
        }
        corrupt_inspection = inspection.model_copy(update={"raw_summary": corrupt_summary})

        with pytest.raises(DomainViolation, match="Missing valid candidate artifact hash"):
            stage_canary_candidates(
                decision="approved_for_canary",
                operator_id="operator-ops-001",
                rationale="Dummy hash test",
                inspection=corrupt_inspection,
                registry_manifest=None,
            )

    def test_exact_decimal_accounting_precision_preserved(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        btc = inspection.candidate_breakdowns["BTCUSDT"]
        eth = inspection.candidate_breakdowns["ETHUSDT"]
        sol = inspection.candidate_breakdowns["SOLUSDT"]

        # Exact 20-digit precision without float truncation
        assert btc.realized_pnl_usdt == Decimal("-1.0962967458302564112")
        assert eth.realized_pnl_usdt == Decimal("-1.14877107936705144624")
        assert sol.realized_pnl_usdt == Decimal("-0.9936529753003224")

        total_pnl = btc.realized_pnl_usdt + eth.realized_pnl_usdt + sol.realized_pnl_usdt
        assert total_pnl == Decimal("-3.23872080049763025744")
        assert total_pnl == inspection.realized_pnl

    def test_format_performance_table_includes_all_required_columns(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        table = format_performance_table(inspection)
        assert "Margin%" in table
        assert "Fees(USDT)" in table
        assert "Slip(USDT)" in table
        assert "Trades" in table
        assert "Win%" in table
        assert "PnL(USDT)" in table

    def test_audit_summary_includes_complete_candidate_metrics(self) -> None:
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        _, _, summary = stage_canary_candidates(
            decision="approved_for_canary",
            operator_id="operator-audit-test",
            rationale="Audit completeness test",
            inspection=inspection,
        )
        btc_summary = summary["candidates"]["BTCUSDT"]
        assert "margin_utilization" in btc_summary
        assert "cumulative_fees_usdt" in btc_summary
        assert "cumulative_slippage_usdt" in btc_summary
        assert "health_status" in btc_summary
        assert "maturity_status" in btc_summary
        assert "accounting_complete" in btc_summary
        assert btc_summary["accounting_complete"] is True

    def test_interactive_choice_case_insensitivity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_dir = tmp_path / "phase269_case_out"
        user_inputs = io.StringIO(
            "operator-case-lead\nAPPROVED_FOR_CANARY\nCase-insensitive prompt test\n"
        )
        monkeypatch.setattr(sys, "stdin", user_inputs)

        ret = review_cli_main(
            [
                "--cohort-dir",
                str(DEFAULT_PHASE268_COHORT_DIR),
                "--output-dir",
                str(out_dir),
                "--interactive",
            ]
        )
        assert ret == 0
        captured = capsys.readouterr().out
        assert "Decision:               approved_for_canary" in captured
        assert (out_dir / "canary-staging-manifest.json").is_file()


class TestPhase269AdversarialRound2Hardening:
    """Adversarial Round 2: Probe edge cases in CLI, EOF loops, missing files, and table."""

    def test_fails_when_upstream_artifact_deleted_on_disk(self, tmp_path: Path) -> None:
        """Verify that missing artifact in artifact_hashes fails integrity check."""
        import shutil

        cohort_copy = tmp_path / "cohort_tampered"
        shutil.copytree(DEFAULT_PHASE268_COHORT_DIR, cohort_copy)
        # Delete paper-ledger.sqlite3
        (cohort_copy / "paper-ledger.sqlite3").unlink()

        inspection = inspect_cohort(cohort_copy)
        assert inspection.prerequisite_checklist.upstream_integrity_verified is False
        assert inspection.prerequisite_checklist.all_gates_passed is False
        assert any(
            "paper-ledger.sqlite3:missing_on_disk" in r
            for r in inspection.prerequisite_checklist.failure_reasons
        )

    def test_interactive_cli_handles_eof_gracefully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify that unexpected EOF raises EOFError and exits with code 1 instead of hanging."""
        out_dir = tmp_path / "phase269_eof_out"
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))

        ret = review_cli_main(
            [
                "--cohort-dir",
                str(DEFAULT_PHASE268_COHORT_DIR),
                "--output-dir",
                str(out_dir),
                "--interactive",
            ]
        )
        assert ret == 1
        captured = capsys.readouterr().out
        assert "Review operation cancelled by operator." in captured

    def test_cli_batch_decision_case_insensitivity_and_aliases(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify batch --decision handles uppercase and aliases cleanly."""
        out_dir = tmp_path / "phase269_alias_out"
        # Test 1: APPROVED_FOR_CANARY
        ret = review_cli_main(
            [
                "--cohort-dir",
                str(DEFAULT_PHASE268_COHORT_DIR),
                "--output-dir",
                str(out_dir),
                "--decision",
                "APPROVED_FOR_CANARY",
                "--operator",
                "operator-alias-001",
                "--rationale",
                "Case insensitive batch flag test",
                "--json",
            ]
        )
        assert ret == 0
        captured = json.loads(capsys.readouterr().out)
        assert captured["decision"] == "approved_for_canary"

        # Test 2: 'rejected' alias 'REJECT'
        ret_rej = review_cli_main(
            [
                "--cohort-dir",
                str(DEFAULT_PHASE268_COHORT_DIR),
                "--output-dir",
                str(out_dir),
                "--decision",
                "REJECT",
                "--operator",
                "operator-alias-001",
                "--rationale",
                "Alias reject test",
                "--json",
            ]
        )
        assert ret_rej == 0
        captured_rej = json.loads(capsys.readouterr().out)
        assert captured_rej["decision"] == "rejected"

    def test_cli_fails_closed_on_corrupt_registry_manifest(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify CLI fails closed if provided registry manifest has invalid schema or hash."""
        corrupt_manifest = tmp_path / "corrupt_registry.json"
        corrupt_manifest.write_text('{"invalid": "json_data"}', encoding="utf-8")

        ret = review_cli_main(
            [
                "--cohort-dir",
                str(DEFAULT_PHASE268_COHORT_DIR),
                "--registry-path",
                str(corrupt_manifest),
                "--decision",
                "approved_for_canary",
                "--json",
            ]
        )
        assert ret == 2
        captured = json.loads(capsys.readouterr().out)
        assert captured["status"] == "error"
        assert captured["error_code"] in ("cohort_inspection_failed", "registry_manifest_invalid")
        assert "registry" in captured["error"].lower()

    def test_fails_when_registry_manifest_hash_mismatches_cohort(self, tmp_path: Path) -> None:
        """Verify inspect_cohort rejects candidate registry whose hash mismatches cohort record."""
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH)
        tampered_manifest = manifest.model_copy(update={"registry_hash": "b" * 64})
        reg_file = tmp_path / "tampered_reg.json"
        reg_file.write_text(tampered_manifest.model_dump_json(), encoding="utf-8")

        with pytest.raises(DomainViolation, match="hash mismatch"):
            inspect_cohort(DEFAULT_PHASE268_COHORT_DIR, registry_path=reg_file)

    def test_fails_when_candidate_missing_from_registry_manifest(self) -> None:
        """Verify stage_canary_candidates fails closed if an active symbol is missing."""
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH)
        incomplete_symbols = dict(manifest.symbols)
        del incomplete_symbols["SOLUSDT"]
        incomplete_manifest = manifest.model_copy(update={"symbols": incomplete_symbols})

        with pytest.raises(DomainViolation, match="not found in candidate registry manifest"):
            stage_canary_candidates(
                decision="approved_for_canary",
                operator_id="operator-reg-test",
                rationale="Incomplete registry test",
                inspection=inspection,
                registry_manifest=incomplete_manifest,
            )

    def test_fails_when_candidate_id_mismatches_registry_manifest(self) -> None:
        """Verify stage_canary_candidates fails closed if candidate_id mismatches registry."""
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH)
        mismatched_symbols = dict(manifest.symbols)
        mismatched_symbols["BTCUSDT"] = mismatched_symbols["BTCUSDT"].model_copy(
            update={"candidate_id": "cand-btcusdt-mismatch-999"}
        )
        mismatched_manifest = manifest.model_copy(update={"symbols": mismatched_symbols})

        with pytest.raises(DomainViolation, match="Candidate ID mismatch"):
            stage_canary_candidates(
                decision="approved_for_canary",
                operator_id="operator-reg-test",
                rationale="Mismatched candidate id test",
                inspection=inspection,
                registry_manifest=mismatched_manifest,
            )

    def test_fails_when_portfolio_accounting_unreconciled(self) -> None:
        """Verify prerequisite gates fail if portfolio accounting is flagged unreconciled."""
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        chk = verify_prerequisite_gates(
            cohort_status="ready_for_human_review",
            expected_candidates=EXPECTED_MANIFEST_V2_CANDIDATES,
            candidate_breakdowns=inspection.candidate_breakdowns,
            raw_readiness={"all_accounting_complete": True, "blocked_candidate_count": 0},
            drift=Decimal("0.0"),
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("96.76"),
            max_margin_utilization=Decimal("0.60"),
            min_reserve_buffer=Decimal("0.40"),
            raw_summary={"portfolio_summary": {"accounting_reconciled": False}},
        )
        assert chk.all_gates_passed is False
        assert any("portfolio_accounting_unreconciled" in r for r in chk.failure_reasons)

    def test_fail_closed_detects_all_binance_credential_variants(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify dynamic safety invariant catches all variants of Binance credentials."""
        for var in (
            "BINANCE_KEY",
            "BINANCE_SECRET_KEY",
            "BINANCE_TESTNET_API_KEY",
            "BINANCE_AUTH_TOKEN",
        ):
            monkeypatch.setenv(var, "secret_value_123")
            invariants = check_fail_closed_safety_invariants()
            assert invariants["api_keys_loaded"] > 0
            assert invariants["zero_secret_leakage"] is False
            monkeypatch.delenv(var)

    def test_invalid_operator_id_format_rejected(self) -> None:
        """Verify invalid operator IDs with spaces, colons, or traversal characters are rejected."""
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        for bad_op in ("operator:lead:1", "operator lead", "operator/lead", "operator..bad"):
            with pytest.raises(DomainViolation, match="Invalid operator_id"):
                stage_canary_candidates(
                    decision="approved_for_canary",
                    operator_id=bad_op,
                    rationale="Bad operator id test",
                    inspection=inspection,
                )

    def test_unicode_and_emojis_in_rationale_and_operator(self, tmp_path: Path) -> None:
        """Verify Unicode and astral plane emojis in rationale are accepted and preserved."""
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        dec, man, summary = stage_canary_candidates(
            decision="approved_for_canary",
            operator_id="operator-lead-001",
            rationale=(
                "🚀 Approved for canary deployment! All 14-day tests pass 💯 and verified 🎯"
            ),
            inspection=inspection,
        )
        assert "🚀" in dec.review_rationale
        assert "💯" in dec.review_rationale

        hashes = save_staging_artifacts(tmp_path, dec, man, summary)
        assert "canary-staging-manifest.json" in hashes

        # Verify disk serialization
        read_dec = json.loads((tmp_path / "human-review-decision.json").read_text(encoding="utf-8"))
        assert "🚀" in read_dec["review_rationale"]

    def test_table_formatting_columns_and_separators_exact_width(self) -> None:
        """Verify that table headers, separators, and data rows have uniform 108 character width."""
        inspection = inspect_cohort(DEFAULT_PHASE268_COHORT_DIR)
        table = format_performance_table(inspection)
        lines = table.splitlines()

        # Separators and headers
        assert len(lines[0]) == 108
        assert lines[0] == "=" * 108
        assert lines[1] == "PHASE 269: CANDIDATE PERFORMANCE & COHORT INSPECTION BREAKDOWN".center(
            108
        )
        assert lines[2] == "=" * 108

        # Find header and candidate rows
        header_idx = -1
        for i, line in enumerate(lines):
            if line.startswith("Symbol"):
                header_idx = i
                break
        assert header_idx > 0
        assert len(lines[header_idx]) == 108

        # Candidate rows
        for i in range(header_idx + 2, header_idx + 2 + len(inspection.candidate_breakdowns)):
            assert len(lines[i]) == 108
