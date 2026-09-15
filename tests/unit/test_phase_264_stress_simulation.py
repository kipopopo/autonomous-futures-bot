"""Unit test suite for Phase 264 multi-vector stress testing and adverse conditions simulation."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.data.parquet import DataQualityError  # noqa: E402
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    CandidateRegistryManifest,
    compute_registry_hash,
    read_candidate_registry,
    validate_manifest_candidate_artifacts,
)
from autonomous_futures.paper.circuit_breakers import (  # noqa: E402
    calculate_adverse_gap_fill,
)
from autonomous_futures.paper.stress_vectors import (  # noqa: E402
    _infer_interval,
)
from scripts.run_phase_264_stress_simulation import (  # noqa: E402
    DEFAULT_MAX_MARGIN_UTILIZATION,
    DEFAULT_MIN_RESERVE_BUFFER,
    DEFAULT_PHASE264_OUTPUT_DIR,
    TRACK_DEFINITIONS,
    Phase264SharedMarginAccount,
    apply_track_shocks,
    main,
    run_phase_264_simulation,
    run_single_phase_264_track,
)


class TestPhase264ManifestAndConfig:
    """Test Manifest Version 2 compliance and track specifications."""

    def test_candidate_registry_manifest_v2_active_candidates(self) -> None:
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
        assert manifest.registry_version >= 2
        assert set(manifest.symbols.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

        assert manifest.symbols["BTCUSDT"].candidate_id == "cand-btcusdt-dcb-002"
        assert manifest.symbols["ETHUSDT"].candidate_id == "cand-ethusdt-dcb-003"
        assert manifest.symbols["SOLUSDT"].candidate_id == "cand-solusdt-rgb-001"

        candidates = validate_manifest_candidate_artifacts(manifest)
        assert len(candidates) == 3
        assert candidates["BTCUSDT"].strategy.universe.timeframe == "15m"
        assert candidates["ETHUSDT"].strategy.universe.timeframe == "15m"
        assert candidates["SOLUSDT"].strategy.universe.timeframe == "1h"

    def test_run_phase_264_simulation_rejects_manifest_v1(self, tmp_path: Path) -> None:
        baseline_reg = Path("artifacts/research/phase262/baseline_candidate_registry.json")
        if not baseline_reg.is_file():
            pytest.skip("baseline_candidate_registry.json not found")

        output_dir = tmp_path / "phase264_reject_test"
        with pytest.raises(DomainViolation, match="requires candidate registry version >= 2"):
            run_phase_264_simulation(
                output_dir=output_dir,
                registry_path=baseline_reg,
                days=1,
                selected_track="0",
            )

    def test_track_definitions_completeness(self) -> None:
        assert len(TRACK_DEFINITIONS) == 6
        track_names = [t["name"] for t in TRACK_DEFINITIONS]
        assert track_names == [
            "baseline",
            "flash_crash",
            "slippage_surge",
            "fee_spread_blowout",
            "volatility_whipsaw",
            "composite_crisis",
        ]

        # Track 0: Baseline (2.0 bps, 0.04% fee)
        assert TRACK_DEFINITIONS[0]["slippage_bps"] == Decimal("2.0")
        assert TRACK_DEFINITIONS[0]["fee_rate"] == Decimal("0.0004")

        # Track 1: Flash Crash (-20% adverse drop)
        assert TRACK_DEFINITIONS[1]["price_shock_pct"] == Decimal("-0.20")

        # Track 2: Slippage Surge (elevated slippage >= 50 bps)
        assert TRACK_DEFINITIONS[2]["slippage_bps"] >= Decimal("50.0")

        # Track 3: Fee & Spread Blowout (doubled fee 0.08% / 8 bps)
        assert TRACK_DEFINITIONS[3]["fee_rate"] == Decimal("0.0008")
        assert TRACK_DEFINITIONS[3]["slippage_bps"] >= Decimal("20.0")

        # Track 4: Volatility Whipsaw (high volatility triggers)
        assert TRACK_DEFINITIONS[4]["shock_type"] == "volatility_whipsaw"
        assert TRACK_DEFINITIONS[4]["whipsaw_bars"] == 12

        # Track 5: Composite Crisis (simultaneous adverse shocks)
        assert TRACK_DEFINITIONS[5]["shock_type"] == "composite_crisis"
        assert TRACK_DEFINITIONS[5]["price_shock_pct"] == Decimal("-0.20")
        assert TRACK_DEFINITIONS[5]["fee_rate"] == Decimal("0.0008")
        assert TRACK_DEFINITIONS[5]["slippage_bps"] >= Decimal("50.0")


class TestPhase264AdverseExecutionAndMechanics:
    """Test adverse gap calculations and simulation mechanics."""

    def test_adverse_gap_fill_calculation_long_and_short(self) -> None:
        # Long gap down: bar opens below stop price -> fill is worse than stop
        raw_exit, fill_price = calculate_adverse_gap_fill(
            side="LONG",
            bar_open=Decimal("90.00"),
            stop_price=Decimal("95.00"),
            slippage_rate=Decimal("0.001"),  # 10 bps
        )
        assert raw_exit == Decimal("90.00")
        assert fill_price == Decimal("90.00") * Decimal("0.999")

        # Short gap up: bar opens above stop price -> fill is worse than stop
        raw_exit_s, fill_price_s = calculate_adverse_gap_fill(
            side="SHORT",
            bar_open=Decimal("110.00"),
            stop_price=Decimal("105.00"),
            slippage_rate=Decimal("0.001"),  # 10 bps
        )
        assert raw_exit_s == Decimal("110.00")
        assert fill_price_s == Decimal("110.00") * Decimal("1.001")


class TestPhase264SimulationTracks:
    """Test execution of stress tracks in isolated temporary directories."""

    def test_run_phase_264_short_slice_baseline_and_flash_crash(self, tmp_path: Path) -> None:
        out_baseline = tmp_path / "baseline_test"
        res_baseline = run_phase_264_simulation(
            output_dir=out_baseline,
            days=2,
            starting_equity=Decimal("100.00"),
            selected_track="0",
        )
        assert res_baseline.all_tracks_survived is True
        t0 = res_baseline.track_results["baseline"]
        assert t0.final_cash > Decimal("0")
        assert t0.scenario_result.max_observed_margin_utilization <= DEFAULT_MAX_MARGIN_UTILIZATION
        assert t0.scenario_result.min_observed_equity_buffer >= DEFAULT_MIN_RESERVE_BUFFER
        assert t0.cash_drift < Decimal("1e-15")
        assert (out_baseline / "paper-ledger.sqlite3").is_file()
        assert (out_baseline / "stress-track-summary.json").is_file()
        assert (out_baseline / "paper-summary.json").is_file()

    def test_run_phase_264_short_slice_slippage_and_fee_surge(self, tmp_path: Path) -> None:
        out_slip = tmp_path / "slippage_test"
        res_slip = run_phase_264_simulation(
            output_dir=out_slip,
            days=2,
            starting_equity=Decimal("100.00"),
            selected_track="2",
        )
        t2 = res_slip.track_results["slippage_surge"]
        assert t2.final_cash > Decimal("0")
        assert t2.cash_drift < Decimal("1e-15")
        assert t2.scenario_result.max_observed_margin_utilization <= DEFAULT_MAX_MARGIN_UTILIZATION

    def test_run_phase_264_short_slice_flash_crash(self, tmp_path: Path) -> None:
        out_flash = tmp_path / "flash_crash_test"
        res_flash = run_phase_264_simulation(
            output_dir=out_flash,
            days=2,
            starting_equity=Decimal("100.00"),
            selected_track="1",
        )
        assert res_flash.all_tracks_survived is True
        t1 = res_flash.track_results["flash_crash"]
        assert t1.final_cash > Decimal("0")
        assert t1.scenario_result.max_observed_margin_utilization <= DEFAULT_MAX_MARGIN_UTILIZATION
        assert t1.scenario_result.min_observed_equity_buffer >= DEFAULT_MIN_RESERVE_BUFFER
        assert t1.cash_drift < Decimal("1e-15")

    def test_run_phase_264_short_slice_composite_and_whipsaw(self, tmp_path: Path) -> None:
        out_comp = tmp_path / "composite_test"
        res_comp = run_phase_264_simulation(
            output_dir=out_comp,
            days=2,
            starting_equity=Decimal("100.00"),
            selected_track="5",
        )
        assert res_comp.all_tracks_survived is True
        t5 = res_comp.track_results["composite_crisis"]
        assert t5.final_cash > Decimal("0")
        assert t5.cash_drift < Decimal("1e-15")
        assert t5.scenario_result.max_observed_margin_utilization <= DEFAULT_MAX_MARGIN_UTILIZATION

    def test_infer_interval_robustness_with_gaps_and_unsorted(self) -> None:
        t0 = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)
        # Regular 15m
        df15 = pd.DataFrame({"timestamp": [t0 + timedelta(minutes=15 * i) for i in range(10)]})
        assert _infer_interval(df15) == timedelta(minutes=15)

        # Irregular gap at start (maintenance downtime), rest 15m
        df_gap = pd.DataFrame(
            {
                "timestamp": [
                    t0,
                    t0 + timedelta(hours=3),
                    t0 + timedelta(hours=3, minutes=15),
                    t0 + timedelta(hours=3, minutes=30),
                    t0 + timedelta(hours=3, minutes=45),
                ]
            }
        )
        assert _infer_interval(df_gap) == timedelta(minutes=15)

        # Unsorted sequence
        df_unsorted = pd.DataFrame(
            {"timestamp": [t0 + timedelta(minutes=45), t0, t0 + timedelta(minutes=15)]}
        )
        assert _infer_interval(df_unsorted) == timedelta(minutes=15)

        # Single row fallback to default
        df_single = pd.DataFrame({"timestamp": [t0]})
        assert _infer_interval(df_single, default=timedelta(minutes=5)) == timedelta(minutes=5)

    def test_phase_264_cli_execution(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_cli = tmp_path / "cli_test"
        code = main(
            [
                "--output-dir",
                str(out_cli),
                "--days",
                "1",
                "--track",
                "0",
                "--json",
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["phase"] == "phase_264"
        assert data["registry_version"] >= 2
        assert data["all_tracks_survived"] is True
        assert data["zero_balance_drift_verified"] is True


class TestPhase264PersistedProductionArtifacts:
    """Validate authoritative persistent artifacts in artifacts/research/phase264/."""

    def test_persisted_databases_and_reports_exist(self) -> None:
        out = DEFAULT_PHASE264_OUTPUT_DIR
        assert out.is_dir(), f"Phase 264 artifact directory missing: {out}"

        # SQLite stores
        assert (out / "paper-ledger.sqlite3").is_file()
        assert (out / "paper-lifecycle.sqlite3").is_file()
        assert (out / "paper-observations.sqlite3").is_file()

        # Reports
        assert (out / "stress-track-summary.json").is_file()
        assert (out / "paper-summary.json").is_file()
        assert (out / "paper-cohort-readiness-report.json").is_file()
        assert (out / "paper-health-report-BTCUSDT.json").is_file()
        assert (out / "paper-health-report-ETHUSDT.json").is_file()
        assert (out / "paper-health-report-SOLUSDT.json").is_file()

        # Track subdirectories
        tracks_dir = out / "tracks"
        assert tracks_dir.is_dir()
        for t in TRACK_DEFINITIONS:
            t_dir = tracks_dir / f"track_{t['id']}_{t['name']}"
            assert t_dir.is_dir(), f"Missing track directory: {t_dir}"
            assert (t_dir / "paper-ledger.sqlite3").is_file()
            assert (t_dir / "paper-lifecycle.sqlite3").is_file()
            assert (t_dir / "paper-observations.sqlite3").is_file()

    def test_persisted_stress_track_summary_content(self) -> None:
        summary_path = DEFAULT_PHASE264_OUTPUT_DIR / "stress-track-summary.json"
        data = json.loads(summary_path.read_text(encoding="utf-8"))

        assert data["phase"] == "phase_264"
        assert data["registry_version"] == 2
        assert data["total_tracks"] == 6
        assert data["all_tracks_survived"] is True
        assert data["max_utilization_cap_satisfied"] is True
        assert data["min_reserve_buffer_satisfied"] is True
        assert data["zero_balance_drift_verified"] is True

        matrix = data["portfolio_survival_matrix"]
        assert len(matrix) == 6
        for row in matrix:
            assert row["capital_survived"] is True
            assert row["margin_cap_satisfied"] is True
            assert row["zero_balance_drift"] is True
            end_cash = Decimal(row["ending_equity_usdt"])
            assert end_cash > Decimal("0.00")
            util_pct = Decimal(row["max_margin_utilization_pct"].rstrip("%"))
            assert util_pct <= Decimal("80.00")
            buf_pct = Decimal(row["min_reserve_buffer_pct"].rstrip("%"))
            assert buf_pct >= Decimal("20.00")
            drift = Decimal(row["balance_drift"])
            assert drift < Decimal("1e-15")

        # Offline safety invariants
        safety = data["safety_invariants"]
        assert safety["paper_activation"] is False
        assert safety["execution_authority"] is False
        assert safety["exchange_access"] is False
        assert safety["orders"] == 0
        assert safety["zero_secret_leakage"] is True

        # Cryptographic checksums
        hashes = data["artifact_hashes"]
        assert "paper-ledger.sqlite3" in hashes
        assert "paper-lifecycle.sqlite3" in hashes
        assert "paper-observations.sqlite3" in hashes
        for k, sha in hashes.items():
            assert len(sha) == 64, f"Invalid SHA-256 for {k}: {sha}"

    def test_persisted_paper_summary_content(self) -> None:
        paper_path = DEFAULT_PHASE264_OUTPUT_DIR / "paper-summary.json"
        data = json.loads(paper_path.read_text(encoding="utf-8"))

        assert data["phase"] == "phase_264"
        assert data["registry_version"] == 2
        assert set(data["candidates"].keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        assert data["candidates"]["ETHUSDT"]["candidate_id"] == "cand-ethusdt-dcb-003"
        assert data["candidates"]["BTCUSDT"]["candidate_id"] == "cand-btcusdt-dcb-002"
        assert data["candidates"]["SOLUSDT"]["candidate_id"] == "cand-solusdt-rgb-001"

        margin = data["shared_portfolio_margin"]
        assert Decimal(margin["starting_equity_usdt"]) == Decimal("100.00")
        assert Decimal(margin["final_cash_usdt"]) > Decimal("0.00")
        assert Decimal(margin["max_observed_margin_utilization"]) <= Decimal("0.80")

        summary = data["portfolio_summary"]
        assert summary["positions_reconciled"] is True
        assert summary["accounting_reconciled"] is True
        assert summary["zero_balance_drift"] is True


class TestPhase264AdversarialEdgeCases:
    """Adversarial challenge tests attacking boundary conditions, tampered manifests,

    and data corruption.
    """

    def test_run_phase_264_simulation_rejects_missing_or_tampered_candidates(
        self, tmp_path: Path
    ) -> None:
        orig = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH)
        d = orig.model_dump(mode="json")

        # Attack 1: Missing SOLUSDT
        d_no_sol = json.loads(json.dumps(d))
        del d_no_sol["symbols"]["SOLUSDT"]
        m_no_sol = CandidateRegistryManifest.model_validate(d_no_sol)
        d_no_sol["registry_hash"] = compute_registry_hash(m_no_sol)
        p_no_sol = tmp_path / "reg_no_sol.json"
        p_no_sol.write_text(json.dumps(d_no_sol), encoding="utf-8")

        with pytest.raises(DomainViolation, match="requires active SOLUSDT candidate"):
            run_phase_264_simulation(output_dir=tmp_path / "out1", registry_path=p_no_sol, days=1)

        # Attack 2: Missing BTCUSDT
        d_no_btc = json.loads(json.dumps(d))
        del d_no_btc["symbols"]["BTCUSDT"]
        m_no_btc = CandidateRegistryManifest.model_validate(d_no_btc)
        d_no_btc["registry_hash"] = compute_registry_hash(m_no_btc)
        p_no_btc = tmp_path / "reg_no_btc.json"
        p_no_btc.write_text(json.dumps(d_no_btc), encoding="utf-8")

        with pytest.raises(DomainViolation, match="requires active BTCUSDT candidate"):
            run_phase_264_simulation(output_dir=tmp_path / "out2", registry_path=p_no_btc, days=1)

        # Attack 3: Tampered candidate ID for BTC
        d_bad_btc = json.loads(json.dumps(d))
        d_bad_btc["symbols"]["BTCUSDT"]["candidate_id"] = "cand-btcusdt-dcb-wrong"
        m_bad_btc = CandidateRegistryManifest.model_validate(d_bad_btc)
        d_bad_btc["registry_hash"] = compute_registry_hash(m_bad_btc)
        p_bad_btc = tmp_path / "reg_bad_btc.json"
        p_bad_btc.write_text(json.dumps(d_bad_btc), encoding="utf-8")

        with pytest.raises(DomainViolation, match="requires active BTCUSDT candidate"):
            run_phase_264_simulation(output_dir=tmp_path / "out3", registry_path=p_bad_btc, days=1)

    def test_run_phase_264_simulation_rejects_invalid_inputs(self, tmp_path: Path) -> None:
        with pytest.raises(DomainViolation, match="starting_equity > 0"):
            run_phase_264_simulation(
                output_dir=tmp_path / "out_eq0", starting_equity=Decimal("0.00"), days=1
            )

        with pytest.raises(DomainViolation, match="starting_equity > 0"):
            run_phase_264_simulation(
                output_dir=tmp_path / "out_neg_eq", starting_equity=Decimal("-10.00"), days=1
            )

        with pytest.raises(DomainViolation, match="days >= 1"):
            run_phase_264_simulation(output_dir=tmp_path / "out_days0", days=0)

    def test_run_phase_264_simulation_enforces_1h_data_quality(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate missing 1h parquet for 1h candidate (SOLUSDT)
        orig_is_file = Path.is_file

        def fake_is_file(self: Path) -> bool:
            if "SOLUSDT-1h" in str(self):
                return False
            return orig_is_file(self)

        monkeypatch.setattr(Path, "is_file", fake_is_file)
        with pytest.raises(DataQualityError, match="Missing required 1h canonical dataset"):
            run_phase_264_simulation(output_dir=tmp_path / "out_no_1h", days=1, selected_track="0")

    def test_apply_track_shocks_1h_scaling_isolation(self) -> None:
        t0 = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)
        frames_15m = {
            "SOLUSDT": pd.DataFrame(
                {
                    "timestamp": [t0 + timedelta(minutes=15 * i) for i in range(48)],
                    "open": [Decimal("150.00")] * 48,
                    "high": [Decimal("155.00")] * 48,
                    "low": [Decimal("148.00")] * 48,
                    "close": [Decimal("152.00")] * 48,
                    "volume": [Decimal("100.00")] * 48,
                }
            )
        }
        frames_1h = {
            "SOLUSDT": pd.DataFrame(
                {
                    "timestamp": [t0 + timedelta(hours=i) for i in range(12)],
                    "open": [Decimal("150.00")] * 12,
                    "high": [Decimal("155.00")] * 12,
                    "low": [Decimal("148.00")] * 12,
                    "close": [Decimal("152.00")] * 12,
                    "volume": [Decimal("400.00")] * 12,
                }
            )
        }
        s15, s1h = apply_track_shocks(frames_15m, frames_1h, TRACK_DEFINITIONS[5])
        assert len(s15["SOLUSDT"]) == 48
        assert len(s1h["SOLUSDT"]) == 12
        df_mod_1h = s1h["SOLUSDT"]
        assert (df_mod_1h["high"] >= df_mod_1h["low"]).all()
        assert (df_mod_1h["high"] >= df_mod_1h["open"]).all()
        assert (df_mod_1h["high"] >= df_mod_1h["close"]).all()

    def test_run_phase_264_simulation_rejects_extra_manifest_candidates(
        self, tmp_path: Path
    ) -> None:
        orig = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH)
        d = orig.model_dump(mode="json")
        d_extra = json.loads(json.dumps(d))
        d_extra["symbols"]["DOGEUSDT"] = {
            "admitted_at": "2026-09-15T16:10:54.132807+00:00",
            "artifact_path": "artifacts/paper_live/candidates/cand-dogeusdt-rogue.json",
            "candidate_artifact_hash": "0" * 64,
            "candidate_id": "cand-dogeusdt-rogue",
            "qualification_hash": "1" * 64,
        }
        m_extra = CandidateRegistryManifest.model_validate(d_extra)
        d_extra["registry_hash"] = compute_registry_hash(m_extra)
        p_extra = tmp_path / "reg_extra.json"
        p_extra.write_text(json.dumps(d_extra), encoding="utf-8")

        with pytest.raises(DomainViolation, match="requires exactly active candidates"):
            run_phase_264_simulation(
                output_dir=tmp_path / "out_extra", registry_path=p_extra, days=1
            )

    def test_run_phase_264_simulation_rejects_timezone_naive_start_time(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(DomainViolation, match="timezone-aware UTC"):
            run_phase_264_simulation(
                output_dir=tmp_path / "out_naive",
                start_time=datetime(2026, 7, 30, 0, 0),  # naive datetime
                days=1,
            )

    def test_run_phase_264_simulation_rejects_unknown_track(self, tmp_path: Path) -> None:
        with pytest.raises(DomainViolation, match="Unknown track specified"):
            run_phase_264_simulation(
                output_dir=tmp_path / "out_unknown_track",
                selected_track="non_existent_track_999",
                days=1,
            )

    def test_track_filter_accepts_directory_style_name(self, tmp_path: Path) -> None:
        res = run_phase_264_simulation(
            output_dir=tmp_path / "out_dir_track",
            selected_track="track_0_baseline",
            days=1,
        )
        assert res.all_tracks_survived is True
        assert len(res.track_results) == 1
        assert "baseline" in res.track_results

    def test_run_single_phase_264_track_enforces_1h_shocked_presence(self, tmp_path: Path) -> None:
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
        candidates = validate_manifest_candidate_artifacts(manifest)
        q_hashes = {sym: entry.qualification_hash for sym, entry in manifest.symbols.items()}

        t0 = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)
        frames_15m = {
            sym: pd.DataFrame(
                {
                    "timestamp": [t0 + timedelta(minutes=15 * i) for i in range(96)],
                    "open": [Decimal("100.00")] * 96,
                    "high": [Decimal("105.00")] * 96,
                    "low": [Decimal("95.00")] * 96,
                    "close": [Decimal("101.00")] * 96,
                    "volume": [Decimal("50.0")] * 96,
                }
            )
            for sym in candidates
        }
        # Pass empty raw_frames_1h so 1h candidate (SOLUSDT) has no 1h frame
        with pytest.raises(DataQualityError, match="Missing shocked 1h frame"):
            run_single_phase_264_track(
                track_spec=TRACK_DEFINITIONS[0],
                output_dir=tmp_path / "track_no_1h",
                candidates=candidates,
                qualification_hashes=q_hashes,
                raw_frames_15m=frames_15m,
                raw_frames_1h={},
                total_bars_15m=96,
                start_time=t0,
                days=1,
            )

    def test_run_phase_264_simulation_short_horizon_reports_accurate_maturity(
        self, tmp_path: Path
    ) -> None:
        res = run_phase_264_simulation(
            output_dir=tmp_path / "out_short_health",
            days=2,
            selected_track="0",
        )
        t0 = res.track_results["baseline"]
        for _sym, hr in t0.health_reports.items():
            # Horizon is accurately evaluated for 2 days; no slot missing errors
            assert "paper_observation_slot_missing" not in hr.reason_codes
            assert hr.as_of == datetime(2026, 8, 1, 0, 0, tzinfo=UTC)

    def test_allocate_order_rejects_non_positive_mark_price(self) -> None:
        account = Phase264SharedMarginAccount(starting_capital=Decimal("100.00"))
        # Zero mark price
        assert (
            account.allocate_order(
                symbol="BTCUSDT",
                confidence=Decimal("0.80"),
                mark_price=Decimal("0.00"),
                current_equity=Decimal("100.00"),
            )
            is None
        )
        # Negative mark price
        assert (
            account.allocate_order(
                symbol="BTCUSDT",
                confidence=Decimal("0.80"),
                mark_price=Decimal("-500.00"),
                current_equity=Decimal("100.00"),
            )
            is None
        )
