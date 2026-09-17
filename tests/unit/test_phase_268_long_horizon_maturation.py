"""Unit tests for Phase 268 Multi-Week Paper Trading Cohort Observation Scaling & Maturation."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.admission import StrategyAdmissionDecision  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    read_candidate_registry,
)
from autonomous_futures.paper.cohort import PaperCohortReadinessReport  # noqa: E402
from autonomous_futures.paper.live_engine import (  # noqa: E402
    DEFAULT_MAX_MARGIN_UTILIZATION,
    DEFAULT_MIN_RESERVE_BUFFER,
    DEFAULT_STARTING_CAPITAL,
)
from autonomous_futures.paper.maturity import _slot_start  # noqa: E402
from scripts.run_phase_268_long_horizon_maturation import (  # noqa: E402
    DEFAULT_CANONICAL_6H_SLOTS,
    DEFAULT_CANONICAL_15M_BARS,
    DEFAULT_CANONICAL_HISTORY_DIR,
    DEFAULT_OBSERVATION_DAYS,
    DEFAULT_OBSERVATION_TICKS,
    EXPECTED_MANIFEST_V2_CANDIDATES,
    _assert_zero_secrets,
    _load_canonical_df,
    _sqlite_row_count,
    _verify_sqlite_unlocked,
    build_arg_parser,
    clear_parquet_cache,
    main,
    replay_long_horizon_cohort_observations,
    replay_multi_day_cohort_observations,
    run_phase_268_long_horizon_maturation,
    seed_engine_history_from_canonical,
    validate_manifest_v2,
    verify_strict_safety_invariants,
)


class MockWebSocketSession:
    """Mock WebSocket session simulating Binance Futures public stream frames."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = list(messages)
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str = ""

    def __aiter__(self) -> MockWebSocketSession:
        return self

    async def __anext__(self) -> str:
        if not self._messages:
            await asyncio.sleep(0.05)
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class MockConnectContext:
    def __init__(self, ws: MockWebSocketSession) -> None:
        self._ws = ws

    async def __aenter__(self) -> MockWebSocketSession:
        return self._ws

    async def __aexit__(self, exc_type: type | None, exc: Exception | None, tb: object) -> None:
        await self._ws.close()


class TestPhase268ManifestAndConfig:
    """Test Manifest Version 2 compliance, candidate artifact hashes, and qualifications."""

    def test_candidate_registry_manifest_v2_active_candidates(self) -> None:
        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        assert manifest.registry_version >= 2
        assert set(manifest.symbols.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        for sym, expected_id in EXPECTED_MANIFEST_V2_CANDIDATES.items():
            assert manifest.symbols[sym].candidate_id == expected_id

    def test_horizon_scaling_defaults_match_spec(self) -> None:
        assert DEFAULT_OBSERVATION_DAYS == 14.0
        assert DEFAULT_OBSERVATION_TICKS == 4032
        assert DEFAULT_CANONICAL_15M_BARS == 1344
        assert DEFAULT_CANONICAL_6H_SLOTS == 56

    def test_compatibility_aliases(self) -> None:
        assert replay_multi_day_cohort_observations is replay_long_horizon_cohort_observations

    def test_validate_manifest_v2_rejects_missing_file(self, tmp_path: Path) -> None:
        missing_path = tmp_path / "nonexistent_manifest.json"
        with pytest.raises(FileNotFoundError):
            validate_manifest_v2(missing_path)

    def test_validate_manifest_v2_rejects_v1_manifest(self, tmp_path: Path) -> None:
        baseline_path = Path("artifacts/research/phase262/baseline_candidate_registry.json")
        if not baseline_path.is_file():
            pytest.skip("baseline_candidate_registry.json not found")
        with pytest.raises(DomainViolation, match="Manifest version must be >= 2"):
            validate_manifest_v2(baseline_path)

    def test_validate_manifest_v2_rejects_tampered_candidate_hash(self, tmp_path: Path) -> None:
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
        raw_manifest = manifest.model_dump(mode="json")
        raw_manifest["symbols"]["BTCUSDT"]["candidate_artifact_hash"] = "0" * 64
        tampered_file = tmp_path / "tampered_candidate_manifest.json"
        tampered_file.write_text(json.dumps(raw_manifest), encoding="utf-8")

        with pytest.raises(DomainViolation):
            validate_manifest_v2(tampered_file)

    def test_validate_manifest_v2_rejects_missing_symbol(self, tmp_path: Path) -> None:
        from autonomous_futures.paper.candidate_registry import (
            CandidateRegistryManifest,
            compute_registry_hash,
        )

        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
        raw_manifest = manifest.model_dump(mode="json")
        del raw_manifest["symbols"]["BTCUSDT"]
        m_obj = CandidateRegistryManifest.model_validate(raw_manifest)
        raw_manifest["registry_hash"] = compute_registry_hash(m_obj)
        missing_symbol_file = tmp_path / "missing_symbol_manifest.json"
        missing_symbol_file.write_text(json.dumps(raw_manifest), encoding="utf-8")

        with pytest.raises(DomainViolation, match="Missing required active candidate BTCUSDT"):
            validate_manifest_v2(missing_symbol_file)

    def test_validate_manifest_v2_rejects_tampered_qualification_hash(self, tmp_path: Path) -> None:
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
        raw_manifest = manifest.model_dump(mode="json")
        raw_manifest["symbols"]["ETHUSDT"]["qualification_hash"] = "f" * 64
        tampered_file = tmp_path / "tampered_qual_manifest.json"
        tampered_file.write_text(json.dumps(raw_manifest), encoding="utf-8")

        with pytest.raises(DomainViolation):
            validate_manifest_v2(tampered_file)

    def test_validate_manifest_v2_rejects_missing_qualification_file(self, tmp_path: Path) -> None:
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
        raw_manifest = manifest.model_dump(mode="json")
        raw_manifest["symbols"]["SOLUSDT"]["candidate_id"] = "cand-nonexistent-001"
        tampered_file = tmp_path / "missing_qual_manifest.json"
        tampered_file.write_text(json.dumps(raw_manifest), encoding="utf-8")

        with pytest.raises((DomainViolation, FileNotFoundError)):
            validate_manifest_v2(tampered_file)

    def test_validate_manifest_v2_rejects_unexpected_symbol(self, tmp_path: Path) -> None:
        from autonomous_futures.paper.candidate_registry import (
            CandidateRegistryManifest,
            compute_registry_hash,
        )

        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
        raw_manifest = manifest.model_dump(mode="json")
        raw_manifest["symbols"]["BNBUSDT"] = {
            "candidate_id": "cand-bnbusdt-dcb-001",
            "candidate_artifact_hash": "a" * 64,
            "qualification_hash": "b" * 64,
            "artifact_path": "artifacts/paper_live/candidates/cand-bnbusdt-dcb-001.json",
            "admitted_at": "2026-09-15T16:10:54.132807+00:00",
        }
        m_obj = CandidateRegistryManifest.model_validate(raw_manifest)
        raw_manifest["registry_hash"] = compute_registry_hash(m_obj)
        unexpected_file = tmp_path / "unexpected_symbol_manifest.json"
        unexpected_file.write_text(json.dumps(raw_manifest), encoding="utf-8")

        with pytest.raises(DomainViolation, match="Unexpected candidate symbols in manifest v2"):
            validate_manifest_v2(unexpected_file)


class TestPhase268StrategyAdmission:
    """Test StrategyAdmissionDecider evaluation on cohort runner startup."""

    @pytest.mark.anyio
    async def test_admission_decisions_all_admitted_on_startup(self, tmp_path: Path) -> None:
        res = await run_phase_268_long_horizon_maturation(
            output_dir=tmp_path / "admission_test",
            registry_path=DEFAULT_CANDIDATE_REGISTRY_PATH,
            history_dir=DEFAULT_CANONICAL_HISTORY_DIR,
            ticks=5,
            offline=True,
        )
        assert res.output_dir.is_dir()
        summary = json.loads(res.maturation_summary_path.read_text(encoding="utf-8"))
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            assert summary["candidates"][sym]["admission_decision"] == "admitted"

    @pytest.mark.anyio
    async def test_cohort_runner_rejects_blocked_candidate_decision(self, tmp_path: Path) -> None:
        from autonomous_futures.paper.admission import strategy_admission_content_hash

        blocked_decision = StrategyAdmissionDecision(
            decision_id="admission-test-blocked",
            candidate_id="cand-btcusdt-dcb-002",
            candidate_artifact_hash="91f41e529a106520fbe41adc86c57c9a1a4ee53bfa084404095ff19b76200bfb",
            qualification_hash="e4ac97e0a09e67921c53acee5b868d4c8f15e319a037c640b278a8701a04a2e1",
            symbol="BTCUSDT",
            decision="blocked_unqualified",
            reason_codes=("unqualified",),
            evaluated_at=datetime.now(UTC),
            active_trade_retained=False,
            decision_hash="0" * 64,
        )
        blocked_decision = blocked_decision.model_copy(
            update={"decision_hash": strategy_admission_content_hash(blocked_decision)}
        )
        with patch(
            "autonomous_futures.paper.admission.StrategyAdmissionDecider.evaluate_admission",
            return_value=blocked_decision,
        ):
            with pytest.raises(DomainViolation, match="admission blocked"):
                await run_phase_268_long_horizon_maturation(
                    output_dir=tmp_path / "blocked_admission_test",
                    ticks=5,
                    offline=True,
                )


class TestPhase268BoundedCohortExecution:
    """Test bounded cohort execution in batch ticks and mock live streaming modes."""

    @pytest.mark.anyio
    async def test_cohort_batch_ticks_mode_execution(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "batch_ticks_test"
        res = await run_phase_268_long_horizon_maturation(
            output_dir=out_dir,
            registry_path=DEFAULT_CANDIDATE_REGISTRY_PATH,
            history_dir=DEFAULT_CANONICAL_HISTORY_DIR,
            ticks=5,
            offline=True,
        )
        assert res.accounting_reconciled is True
        assert res.zero_balance_drift is True
        assert res.starting_equity == Decimal("100.00")
        assert res.final_cash == Decimal("100.00")
        assert res.drift < Decimal("1e-15")
        assert res.ticks_processed == 5

        # Verify all 10 artifacts exist
        expected_artifacts = [
            "paper-ledger.sqlite3",
            "paper-lifecycle.sqlite3",
            "paper-observations.sqlite3",
            "paper-cohort-readiness-report.json",
            "paper-cohort-maturation-report.json",
            "paper-health-report-BTCUSDT.json",
            "paper-health-report-ETHUSDT.json",
            "paper-health-report-SOLUSDT.json",
            "maturation-summary.json",
            "paper-summary.json",
        ]
        for art in expected_artifacts:
            assert (out_dir / art).is_file(), f"Missing artifact: {art}"

    @pytest.mark.anyio
    async def test_cohort_mock_websocket_streaming_execution(self, tmp_path: Path) -> None:
        mock_messages = [
            json.dumps(
                {
                    "stream": "btcusdt@bookTicker",
                    "data": {
                        "e": "bookTicker",
                        "u": 10001,
                        "s": "BTCUSDT",
                        "b": "85000.10",
                        "B": "1.500",
                        "a": "85000.20",
                        "A": "2.100",
                        "T": 1772700000000,
                        "E": 1772700000050,
                    },
                }
            ),
            json.dumps(
                {
                    "stream": "ethusdt@bookTicker",
                    "data": {
                        "e": "bookTicker",
                        "u": 10002,
                        "s": "ETHUSDT",
                        "b": "3100.10",
                        "B": "5.000",
                        "a": "3100.20",
                        "A": "4.500",
                        "T": 1772700000010,
                        "E": 1772700000060,
                    },
                }
            ),
            json.dumps(
                {
                    "stream": "solusdt@bookTicker",
                    "data": {
                        "e": "bookTicker",
                        "u": 10003,
                        "s": "SOLUSDT",
                        "b": "165.10",
                        "B": "15.000",
                        "a": "165.20",
                        "A": "12.500",
                        "T": 1772700000020,
                        "E": 1772700000070,
                    },
                }
            ),
        ]
        mock_ws = MockWebSocketSession(mock_messages)
        out_dir = tmp_path / "mock_stream_test"

        with patch("websockets.connect", return_value=MockConnectContext(mock_ws)):
            res = await run_phase_268_long_horizon_maturation(
                output_dir=out_dir,
                duration=1.0,
                mode="live",
            )

        assert res.accounting_reconciled is True
        assert res.zero_balance_drift is True
        assert (out_dir / "maturation-summary.json").is_file()
        assert (out_dir / "paper-summary.json").is_file()
        assert (out_dir / "paper-cohort-maturation-report.json").is_file()

    @pytest.mark.anyio
    async def test_cohort_auto_fallback_to_batch_on_stream_error(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "auto_fallback_test"

        with patch(
            "autonomous_futures.feed.client.BinancePublicFeedClient.connect_and_stream",
            side_effect=OSError("Network unreachable"),
        ):
            res = await run_phase_268_long_horizon_maturation(
                output_dir=out_dir,
                ticks=5,
                mode="auto",
            )

        assert res.accounting_reconciled is True
        assert (out_dir / "maturation-summary.json").is_file()

    @pytest.mark.anyio
    async def test_multi_day_batch_ticks_replay_disparate_symbol_timestamps(
        self, tmp_path: Path
    ) -> None:
        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        symbols = tuple(s.upper() for s in manifest.symbols.keys())

        data_dir = tmp_path / "disparate_data"
        data_dir.mkdir()

        base_t = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        for i, sym in enumerate(symbols):
            timestamps = [base_t + timedelta(minutes=5 * (j + i)) for j in range(10)]
            df = pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "close_time": [t + timedelta(minutes=5, milliseconds=-1) for t in timestamps],
                    "open": [Decimal("100.0")] * 10,
                    "high": [Decimal("105.0")] * 10,
                    "low": [Decimal("95.0")] * 10,
                    "close": [Decimal("102.0")] * 10,
                    "volume": [Decimal("50.0")] * 10,
                    "quote_volume": [Decimal("5100.0")] * 10,
                    "trades": [100] * 10,
                    "taker_buy_base": [Decimal("25.0")] * 10,
                    "taker_buy_quote": [Decimal("2550.0")] * 10,
                }
            )
            df.to_parquet(data_dir / f"{sym}-5m.parquet")

        engine = LivePaperTradingEngine(
            registry_manifest=manifest,
            ledger_db=tmp_path / "disp-ledger.sqlite3",
            lifecycle_db=tmp_path / "disp-lifecycle.sqlite3",
            observations_db=tmp_path / "disp-obs.sqlite3",
            require_flat=False,
        )
        ticks = await replay_long_horizon_cohort_observations(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            max_ticks=5,
        )
        await engine.stop()
        assert ticks == 5


class TestPhase268AccountingAndRiskInvariants:
    """Test exact double-entry accounting reconciliation and risk limits."""

    @pytest.mark.anyio
    async def test_exact_double_entry_balance_reconciliation(self, tmp_path: Path) -> None:
        res = await run_phase_268_long_horizon_maturation(
            output_dir=tmp_path / "reconciliation_test",
            ticks=5,
            offline=True,
        )
        assert res.drift < Decimal("1e-15")
        assert res.final_cash == res.starting_equity + res.realized_pnl

    @pytest.mark.anyio
    async def test_margin_utilization_and_reserve_buffer_limits(self, tmp_path: Path) -> None:
        res = await run_phase_268_long_horizon_maturation(
            output_dir=tmp_path / "risk_limits_test",
            ticks=5,
            offline=True,
            max_margin_utilization=Decimal("0.80"),
            min_reserve_buffer=Decimal("0.20"),
        )
        assert res.max_margin_utilization <= Decimal("0.80")
        assert res.min_reserve_buffer >= Decimal("0.20")

    @pytest.mark.anyio
    async def test_single_position_invariant_maintained(self, tmp_path: Path) -> None:
        res = await run_phase_268_long_horizon_maturation(
            output_dir=tmp_path / "single_pos_test",
            ticks=5,
            offline=True,
        )
        assert res.positions_reconciled is True

    @pytest.mark.anyio
    async def test_runner_rejects_invalid_risk_bounds(self, tmp_path: Path) -> None:
        with pytest.raises(DomainViolation, match="Starting capital must be strictly positive"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "zero_cap",
                ticks=5,
                offline=True,
                starting_capital=Decimal("0.0"),
            )

        with pytest.raises(DomainViolation, match="Max margin utilization must be in"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "bad_util",
                ticks=5,
                offline=True,
                max_margin_utilization=Decimal("1.50"),
            )

        with pytest.raises(DomainViolation, match="Min reserve buffer must be in"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "bad_buffer",
                ticks=5,
                offline=True,
                min_reserve_buffer=Decimal("-0.10"),
            )

        with pytest.raises(DomainViolation, match="cannot exceed 1.0"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "bad_sum",
                ticks=5,
                offline=True,
                max_margin_utilization=Decimal("0.90"),
                min_reserve_buffer=Decimal("0.20"),
            )

    @pytest.mark.anyio
    async def test_accounting_reconciled_with_open_position(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger

        real_load = SqlitePaperLedger.load
        mock_open = MagicMock(
            symbol="BTCUSDT",
            trade_id="mock-open-trade",
            event="open",
            entry_fee=Decimal("0.008"),
            net_pnl=None,
        )

        call_count = 0

        def load_side_effect(self: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return real_load(self)
            mock_ledger = MagicMock()
            mock_ledger.open_positions.return_value = [mock_open]
            mock_ledger.entries = [mock_open]
            return mock_ledger

        def mock_reconcile(self: Any) -> dict[str, Any]:
            self.account.cash = self.account.starting_capital - Decimal("0.008")
            return {
                "starting_capital": str(self.account.starting_capital),
                "actual_cash": str(self.account.cash),
                "expected_cash": str(self.account.cash),
                "drift": "0",
                "zero_balance_drift": True,
                "closed_trades_count": 0,
                "open_positions_count": 1,
                "total_realized_pnl": "0",
                "total_open_entry_fees": "0.008",
            }

        with (
            patch(
                "autonomous_futures.paper.live_engine.LivePaperTradingEngine.reconcile_balances",
                mock_reconcile,
            ),
            patch(
                "autonomous_futures.paper.sqlite_ledger.SqlitePaperLedger.load",
                side_effect=load_side_effect,
                autospec=True,
            ),
        ):
            res = await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "open_pos_accounting",
                ticks=5,
                offline=True,
            )
            assert res.accounting_reconciled is True
            assert res.drift < Decimal("1e-15")


class TestPhase268PersistenceAndMaturationReporting:
    """Test isolated SQLite persistence, maturation reports, and artifact hashes."""

    @pytest.mark.anyio
    async def test_isolated_sqlite_and_artifact_hashes(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "artifacts_test"
        res = await run_phase_268_long_horizon_maturation(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )

        assert len(res.artifact_hashes) == 10
        assert "paper-ledger.sqlite3" in res.artifact_hashes
        assert "paper-lifecycle.sqlite3" in res.artifact_hashes
        assert "paper-observations.sqlite3" in res.artifact_hashes
        assert "paper-cohort-readiness-report.json" in res.artifact_hashes
        assert "paper-cohort-maturation-report.json" in res.artifact_hashes
        assert "maturation-summary.json" in res.artifact_hashes
        assert "paper-summary.json" in res.artifact_hashes

        for fname, fhash in res.artifact_hashes.items():
            assert len(fhash) == 64
            assert (out_dir / fname).is_file()

        # Validate paper-cohort-maturation-report.json schema
        maturation_json = (out_dir / "paper-cohort-maturation-report.json").read_text(
            encoding="utf-8"
        )
        report = PaperCohortReadinessReport.model_validate_json(maturation_json)
        assert report.expected_candidate_count == 3
        assert report.reported_candidate_count == 3
        assert report.cohort_status in (
            "unavailable",
            "not_ready",
            "blocked",
            "ready_for_human_review",
        )

    @pytest.mark.anyio
    async def test_sqlite_file_handles_closed_cleanly(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "handle_leak_test"
        res = await run_phase_268_long_horizon_maturation(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )
        assert res.output_dir.is_dir()

        sqlite_dbs = (
            "paper-ledger.sqlite3",
            "paper-lifecycle.sqlite3",
            "paper-observations.sqlite3",
        )
        for db_name in sqlite_dbs:
            db_path = out_dir / db_name
            import sqlite3

            conn = sqlite3.connect(db_path, timeout=1.0)
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM sqlite_master;")
            cur.fetchall()
            conn.close()

    @pytest.mark.anyio
    async def test_observation_deduplication_guards(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "dedup_test"
        await run_phase_268_long_horizon_maturation(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )
        obs_file = out_dir / "paper-observations.sqlite3"
        import sqlite3

        conn = sqlite3.connect(obs_file)
        rows = conn.execute(
            "SELECT candidate_id, observed_at FROM paper_observations ORDER BY observed_at ASC"
        ).fetchall()
        conn.close()

        cand_slots: dict[str, set[datetime]] = {}
        for cand_id, raw_ts in rows:
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            slot = _slot_start(ts)
            cand_slots.setdefault(cand_id, set())
            assert slot not in cand_slots[cand_id], f"Duplicate slot {slot} for {cand_id}"
            cand_slots[cand_id].add(slot)

    @pytest.mark.anyio
    async def test_maturation_progression_schema_and_status_codes(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "progression_test"
        res = await run_phase_268_long_horizon_maturation(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )
        summary = json.loads(res.maturation_summary_path.read_text(encoding="utf-8"))
        assert "maturation_progression" in summary
        assert "observation_horizon" in summary

        horizon = summary["observation_horizon"]
        assert horizon["canonical_days"] == 14.0
        assert horizon["canonical_5m_bars"] == 4032
        assert horizon["canonical_15m_bars"] == 1344
        assert horizon["canonical_6h_slots"] == 56
        assert horizon["replayed_ticks"] == 5

        prog = summary["maturation_progression"]
        assert prog["cohort_status"] in (
            "unavailable",
            "not_ready",
            "blocked",
            "ready_for_human_review",
        )
        assert "valid_status_codes" in prog
        assert "valid_per_symbol_health_status" in prog
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            cand_info = prog["per_symbol_maturation"][sym]
            assert "trades_count" in cand_info
            assert "sample_size" in cand_info
            assert "observed_slots" in cand_info
            assert cand_info["health_status"] in (
                "evaluating",
                "maturing",
                "healthy",
                "attention",
                "blocked",
                "unavailable",
            )
            assert cand_info["maturity_status"] in (
                "evaluating",
                "maturing",
                "mature",
                "blocked",
                "unavailable",
            )


class TestPhase268FailClosedAndZeroSecrets:
    """Test safety invariants, fail-closed boundaries, and zero secret leakage."""

    def test_strict_safety_invariants_pass_clean(self) -> None:
        invariants = verify_strict_safety_invariants(orders_submitted=0)
        assert invariants["orders_submitted"] == 0
        assert invariants["orders"] == 0
        assert invariants["execution_authority"] is False
        assert invariants["paper_activation"] is False
        assert invariants["exchange_access"] is False
        assert invariants["zero_secret_leakage"] is True

    def test_strict_safety_invariants_fail_on_live_orders(self) -> None:
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
            verify_strict_safety_invariants(orders_submitted=1)

    def test_strict_safety_invariants_fail_on_private_keys(self) -> None:
        with patch.dict(os.environ, {"BINANCE_API_KEY": "dummy_secret_key_123"}):
            with pytest.raises(RuntimeError, match="SAFETY VIOLATION: private credentials"):
                verify_strict_safety_invariants(orders_submitted=0)

    def test_zero_secret_leakage_assertion(self) -> None:
        clean_text = json.dumps({"status": "clean", "orders": 0})
        _assert_zero_secrets(clean_text, "test_clean")

        leaked_text = json.dumps({"api_key": "AIzaSyDummySecretKey12345678901234"})
        with pytest.raises(DomainViolation, match="Secret pattern matched"):
            _assert_zero_secrets(leaked_text, "test_leaked")

    def test_zero_secret_patterns_detects_multiple_token_formats(self) -> None:
        tokens = [
            "ya29.a0AfH6SMDUMMY_TOKEN",
            "ghp_123456789012345678901234567890123456",
            "AKIAIOSFODNN7EXAMPLE",
        ]
        for token in tokens:
            with pytest.raises(DomainViolation, match="Secret pattern matched"):
                _assert_zero_secrets(f'{{"key": "{token}"}}', "pattern_test")

    def test_runner_source_syntax_valid(self) -> None:
        script_path = _REPO_ROOT / "scripts" / "run_phase_268_long_horizon_maturation.py"
        assert script_path.is_file()
        content = script_path.read_text(encoding="utf-8")
        compile(content, str(script_path), "exec")

    @pytest.mark.anyio
    async def test_generated_reports_contain_zero_secrets(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "secret_scan_test"
        await run_phase_268_long_horizon_maturation(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )

        for jfile in out_dir.glob("*.json"):
            content = jfile.read_text(encoding="utf-8")
            _assert_zero_secrets(content, jfile.name)


class TestPhase268CLI:
    """Test CLI argument parsing and entrypoint execution."""

    def test_build_arg_parser_defaults(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args([])
        assert args.duration == 10.0
        assert args.smoke_test is False
        assert args.mode == "auto"
        assert args.starting_capital == DEFAULT_STARTING_CAPITAL
        assert args.max_margin_utilization == DEFAULT_MAX_MARGIN_UTILIZATION
        assert args.min_reserve_buffer == DEFAULT_MIN_RESERVE_BUFFER
        assert args.days is None
        assert args.ticks is None
        assert args.required_days == 7

    def test_main_cli_execution_batch(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "cli_test"
        ret = main(["--output-dir", str(out_dir), "--ticks", "5", "--offline"])
        assert ret == 0
        assert (out_dir / "maturation-summary.json").is_file()
        assert (out_dir / "paper-cohort-maturation-report.json").is_file()

    def test_main_cli_json_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        out_dir = tmp_path / "cli_json_test"
        ret = main(["--output-dir", str(out_dir), "--ticks", "5", "--offline", "--json"])
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["phase"] == "phase_268"
        assert data["shared_portfolio_margin"]["starting_capital_usdt"] == "100.00"

    def test_main_cli_smoke_test_flag(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "smoke_cli_test"
        ret = main(["--output-dir", str(out_dir), "--smoke-test", "--offline"])
        assert ret == 0
        assert (out_dir / "maturation-summary.json").is_file()

    def test_main_cli_days_flag(self, tmp_path: Path) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--days", "14.0"])
        assert args.days == 14.0

    def test_cli_rejects_conflicting_days_and_ticks_exit_code_1(self, tmp_path: Path) -> None:
        ret = main(
            [
                "--output-dir",
                str(tmp_path / "cli_conflict"),
                "--days",
                "1.0",
                "--ticks",
                "10",
                "--offline",
            ]
        )
        assert ret == 1

    def test_cli_rejects_negative_ticks_exit_code_1(self, tmp_path: Path) -> None:
        ret = main(["--output-dir", str(tmp_path / "cli_neg_ticks"), "--ticks", "-5", "--offline"])
        assert ret == 1

    def test_cli_rejects_zero_and_negative_days_exit_code_1(self, tmp_path: Path) -> None:
        ret = main(["--output-dir", str(tmp_path / "cli_zero_days"), "--days", "0", "--offline"])
        assert ret == 1
        ret_neg = main(
            ["--output-dir", str(tmp_path / "cli_neg_days"), "--days", "-2.0", "--offline"]
        )
        assert ret_neg == 1

    def test_cli_rejects_nonpositive_starting_capital_exit_code_1(self, tmp_path: Path) -> None:
        ret = main(
            [
                "--output-dir",
                str(tmp_path / "cli_zero_cap"),
                "--starting-capital",
                "0",
                "--ticks",
                "5",
                "--offline",
            ]
        )
        assert ret == 1

    def test_cli_rejects_nonpositive_required_days_exit_code_1(self, tmp_path: Path) -> None:
        ret = main(
            [
                "--output-dir",
                str(tmp_path / "cli_bad_req_days"),
                "--required-days",
                "0",
                "--ticks",
                "5",
                "--offline",
            ]
        )
        assert ret == 1


class TestPhase268AdversarialDataRobustnessAndEdgeCases:
    """Adversarial stress tests for parquet cache isolation, malformed data, and timeline gaps."""

    def test_parquet_cache_invalidation_and_isolation(self, tmp_path: Path) -> None:
        clear_parquet_cache()
        pfile = tmp_path / "cache_test.parquet"
        base_t = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

        df1 = pd.DataFrame(
            {
                "timestamp": [base_t, base_t + timedelta(minutes=5)],
                "close": [Decimal("100.0"), Decimal("101.0")],
            }
        )
        df1.to_parquet(pfile)

        loaded1 = _load_canonical_df(pfile)
        assert len(loaded1) == 2
        assert loaded1["close"].iloc[0] == Decimal("100.0")

        loaded1["close"] = Decimal("999999.0")

        loaded2 = _load_canonical_df(pfile)
        assert loaded2["close"].iloc[0] == Decimal("100.0")

        clear_parquet_cache()

        df2 = pd.DataFrame(
            {
                "timestamp": [
                    base_t,
                    base_t + timedelta(minutes=5),
                    base_t + timedelta(minutes=10),
                ],
                "close": [Decimal("200.0"), Decimal("201.0"), Decimal("202.0")],
            }
        )
        df2.to_parquet(pfile)

        loaded3 = _load_canonical_df(pfile)
        assert len(loaded3) == 3
        assert loaded3["close"].iloc[0] == Decimal("200.0")

    def test_parquet_malformed_nat_and_null_timestamps_sanitization(self, tmp_path: Path) -> None:
        clear_parquet_cache()
        pfile = tmp_path / "nat_test.parquet"
        base_t = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

        df = pd.DataFrame(
            {
                "timestamp": [pd.NaT, base_t, None],
                "close": [Decimal("100.0"), Decimal("101.0"), Decimal("102.0")],
            }
        )
        df.to_parquet(pfile)

        loaded = _load_canonical_df(pfile)
        assert len(loaded) == 1
        assert loaded["timestamp"].iloc[0] == base_t

    def test_parquet_missing_and_invalid_close_time_reconstruction(self, tmp_path: Path) -> None:
        clear_parquet_cache()
        pfile = tmp_path / "close_time_test.parquet"
        base_t = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

        df = pd.DataFrame(
            {
                "timestamp": [base_t],
                "close": [Decimal("100.0")],
            }
        )
        df.to_parquet(pfile)

        loaded = _load_canonical_df(pfile)
        assert "close_time" in loaded.columns
        expected_close = base_t + timedelta(minutes=5, milliseconds=-1)
        assert loaded["close_time"].iloc[0] == expected_close

        pfile_inv = tmp_path / "close_time_inv.parquet"
        df_inv = pd.DataFrame(
            {
                "timestamp": [base_t],
                "close_time": [base_t - timedelta(minutes=1)],
                "close": [Decimal("100.0")],
            }
        )
        df_inv.to_parquet(pfile_inv)

        loaded_inv = _load_canonical_df(pfile_inv)
        assert loaded_inv["close_time"].iloc[0] == expected_close

    def test_parquet_duplicate_timestamps_deduplication(self, tmp_path: Path) -> None:
        clear_parquet_cache()
        pfile = tmp_path / "dedup_ts.parquet"
        base_t = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

        df = pd.DataFrame(
            {
                "timestamp": [base_t, base_t],
                "close": [Decimal("100.0"), Decimal("105.0")],
            }
        )
        df.to_parquet(pfile)

        loaded = _load_canonical_df(pfile)
        assert len(loaded) == 1
        assert loaded["close"].iloc[0] == Decimal("105.0")

    @pytest.mark.anyio
    async def test_replay_with_asynchronous_timestamp_gaps_and_missing_partitions(
        self, tmp_path: Path
    ) -> None:
        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        symbols = tuple(s.upper() for s in manifest.symbols.keys())

        data_dir = tmp_path / "gap_data"
        data_dir.mkdir()

        base_t = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        for i, sym in enumerate(symbols):
            timestamps = [base_t + timedelta(minutes=5 * (j + i * 2)) for j in range(8)]
            df = pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "open": [Decimal("100.0")] * 8,
                    "high": [Decimal("105.0")] * 8,
                    "low": [Decimal("95.0")] * 8,
                    "close": [Decimal("102.0")] * 8,
                    "volume": [Decimal("50.0")] * 8,
                    "trades": [100] * 8,
                }
            )
            df.to_parquet(data_dir / f"{sym}-5m.parquet")

        engine = LivePaperTradingEngine(
            registry_manifest=manifest,
            ledger_db=tmp_path / "gap-ledger.sqlite3",
            lifecycle_db=tmp_path / "gap-lifecycle.sqlite3",
            observations_db=tmp_path / "gap-obs.sqlite3",
            require_flat=False,
        )

        ticks = await replay_long_horizon_cohort_observations(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            max_ticks=4,
        )
        await engine.stop()
        assert ticks == 4

    @pytest.mark.anyio
    async def test_replay_zero_max_ticks_returns_zero(self, tmp_path: Path) -> None:
        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        symbols = tuple(s.upper() for s in manifest.symbols.keys())

        engine = LivePaperTradingEngine(
            registry_manifest=manifest,
            ledger_db=tmp_path / "zero-ledger.sqlite3",
            lifecycle_db=tmp_path / "zero-lifecycle.sqlite3",
            observations_db=tmp_path / "zero-obs.sqlite3",
            require_flat=False,
        )
        ticks = await replay_long_horizon_cohort_observations(
            engine=engine,
            history_dir=DEFAULT_CANONICAL_HISTORY_DIR,
            symbols=symbols,
            max_ticks=0,
        )
        await engine.stop()
        assert ticks == 0

    def test_seed_engine_history_edge_cases(self, tmp_path: Path) -> None:
        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        symbols = tuple(s.upper() for s in manifest.symbols.keys())

        data_dir = tmp_path / "seed_edge_data"
        data_dir.mkdir()

        base_t = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        for sym in symbols:
            df = pd.DataFrame(
                {
                    "timestamp": [base_t + timedelta(minutes=5 * j) for j in range(3)],
                    "open": [Decimal("100.0")] * 3,
                    "high": [Decimal("105.0")] * 3,
                    "low": [Decimal("95.0")] * 3,
                    "close": [Decimal("102.0")] * 3,
                    "volume": [Decimal("50.0")] * 3,
                }
            )
            df.to_parquet(data_dir / f"{sym}-5m.parquet")

        engine = LivePaperTradingEngine(
            registry_manifest=manifest,
            ledger_db=tmp_path / "seed-ledger.sqlite3",
            lifecycle_db=tmp_path / "seed-lifecycle.sqlite3",
            observations_db=tmp_path / "seed-obs.sqlite3",
            require_flat=False,
        )

        seed_engine_history_from_canonical(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            warmup_bars=300,
            offset_ticks=10,
        )
        seed_engine_history_from_canonical(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            warmup_bars=300,
            offset_ticks=1,
        )
        assert True

    def test_sqlite_sidecar_cleanup_on_clean(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "sqlite_clean_test"
        out_dir.mkdir()

        for db_name in (
            "paper-ledger.sqlite3",
            "paper-lifecycle.sqlite3",
            "paper-observations.sqlite3",
        ):
            for suffix in ("", "-wal", "-shm", "-journal"):
                sidecar = out_dir / f"{db_name}{suffix}"
                sidecar.write_text("test_data", encoding="utf-8")
                assert sidecar.is_file()

        res = asyncio.run(
            run_phase_268_long_horizon_maturation(
                output_dir=out_dir,
                clean=True,
                offline=True,
                ticks=1,
            )
        )
        assert res is not None

        for db_name in (
            "paper-ledger.sqlite3",
            "paper-lifecycle.sqlite3",
            "paper-observations.sqlite3",
        ):
            for suffix in ("-wal", "-shm", "-journal"):
                assert not (out_dir / f"{db_name}{suffix}").exists()

    def test_sqlite_row_count_locked_retry_and_resilience(self, tmp_path: Path) -> None:
        import sqlite3
        from contextlib import closing

        db_file = tmp_path / "test_count.sqlite3"
        with closing(sqlite3.connect(db_file)) as conn:
            conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO test_table (val) VALUES ('a'), ('b'), ('c')")
            conn.commit()

        assert _sqlite_row_count(db_file, "test_table") == 3
        assert _sqlite_row_count(tmp_path / "nonexistent.sqlite3", "test_table") == 0
        assert _sqlite_row_count(db_file, "nonexistent_table") == 0

        real_connect = sqlite3.connect
        attempts = 0

        def flaky_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                raise sqlite3.OperationalError("database is locked")
            conn: sqlite3.Connection = real_connect(*args, **kwargs)
            return conn

        with patch(
            "scripts.run_phase_268_long_horizon_maturation.sqlite3.connect",
            side_effect=flaky_connect,
        ):
            count = _sqlite_row_count(db_file, "test_table", max_retries=5, retry_delay=0.01)
            assert count == 3
            assert attempts == 3

    @pytest.mark.anyio
    async def test_abnormal_shutdown_guarantees_engine_and_monitor_cleanup(
        self, tmp_path: Path
    ) -> None:
        out_dir = tmp_path / "abnormal_shutdown"
        out_dir.mkdir()

        with patch(
            "scripts.run_phase_268_long_horizon_maturation.replay_long_horizon_cohort_observations",
            side_effect=RuntimeError("Simulated unhandled failure in replay loop"),
        ):
            with pytest.raises(RuntimeError, match="Simulated unhandled failure in replay loop"):
                await run_phase_268_long_horizon_maturation(
                    output_dir=out_dir,
                    offline=True,
                    ticks=5,
                )

    def test_rapid_multi_symbol_order_signals_approaching_80_percent_margin_ceiling(
        self, tmp_path: Path
    ) -> None:
        from autonomous_futures.paper.circuit_breakers import HardenedSharedMarginAccount

        account = HardenedSharedMarginAccount(
            starting_capital=Decimal("100.00"),
            max_utilization=Decimal("0.80"),
            base_allocation_fraction=Decimal("0.20"),
            min_reserve_buffer=Decimal("0.20"),
        )

        cur_eq = Decimal("100.00")

        alloc1 = account.allocate_order("BTCUSDT", Decimal("0.8"), Decimal("50000.0"), cur_eq)
        assert alloc1 is not None
        base1, lev1, _ = alloc1
        assert base1 == Decimal("20.00")
        account.record_open("t1", base1, lev1, Decimal("0.008"), cur_eq)
        assert account.margin_utilization(cur_eq) == Decimal("0.20")

        alloc2 = account.allocate_order("ETHUSDT", Decimal("0.8"), Decimal("3000.0"), cur_eq)
        assert alloc2 is not None
        base2, lev2, _ = alloc2
        assert base2 == Decimal("20.00")
        account.record_open("t2", base2, lev2, Decimal("0.008"), cur_eq)
        assert account.margin_utilization(cur_eq) == Decimal("0.40")

        alloc3 = account.allocate_order("SOLUSDT", Decimal("0.8"), Decimal("150.0"), cur_eq)
        assert alloc3 is not None
        base3, lev3, _ = alloc3
        assert base3 == Decimal("20.00")
        account.record_open("t3", base3, lev3, Decimal("0.008"), cur_eq)
        assert account.margin_utilization(cur_eq) == Decimal("0.60")

        alloc4 = account.allocate_order("DOGEUSDT", Decimal("0.8"), Decimal("0.10"), cur_eq)
        assert alloc4 is not None
        base4, lev4, _ = alloc4
        assert base4 == Decimal("20.00")
        account.record_open("t4", base4, lev4, Decimal("0.008"), cur_eq)
        assert account.margin_utilization(cur_eq) == Decimal("0.80")

        alloc5 = account.allocate_order("ADAUSDT", Decimal("0.8"), Decimal("0.50"), cur_eq)
        assert alloc5 is None, "Order exceeding 80% ceiling must be rejected"

        assert account.max_observed_utilization <= Decimal("0.80")
        assert account.min_observed_buffer >= Decimal("0.20")

        account.record_close("t1", Decimal("2.00"), Decimal("0.008"))
        account.record_close("t2", Decimal("-1.00"), Decimal("0.008"))
        account.record_close("t3", Decimal("3.00"), Decimal("0.008"))
        account.record_close("t4", Decimal("0.50"), Decimal("0.008"))

        expected_cash = Decimal("100.00") + Decimal("4.436")
        assert abs(account.cash - expected_cash) < Decimal("1e-15")

    @pytest.mark.anyio
    async def test_parquet_inverted_and_degenerate_ohlc_bars_sanitization(
        self, tmp_path: Path
    ) -> None:
        clear_parquet_cache()
        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        symbols = tuple(s.upper() for s in manifest.symbols.keys())

        data_dir = tmp_path / "anomalous_data"
        data_dir.mkdir()

        base_t = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        for sym in symbols:
            df = pd.DataFrame(
                {
                    "timestamp": [
                        base_t,
                        base_t + timedelta(minutes=5),
                        base_t + timedelta(minutes=10),
                    ],
                    "close_time": [
                        base_t,
                        base_t + timedelta(minutes=10),
                        base_t + timedelta(minutes=15),
                    ],
                    "open": [Decimal("100.0"), Decimal("105.0"), None],
                    "high": [Decimal("102.0"), Decimal("90.0"), None],
                    "low": [Decimal("98.0"), Decimal("110.0"), None],
                    "close": [Decimal("101.0"), Decimal("100.0"), Decimal("102.0")],
                    "volume": [Decimal("10.0"), Decimal("20.0"), Decimal("-10.0")],
                    "trades": [5, 10, -3],
                }
            )
            df.to_parquet(data_dir / f"{sym}-5m.parquet")

        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        engine = LivePaperTradingEngine(
            registry_manifest=manifest,
            ledger_db=tmp_path / "anom-ledger.sqlite3",
            lifecycle_db=tmp_path / "anom-lifecycle.sqlite3",
            observations_db=tmp_path / "anom-obs.sqlite3",
            require_flat=False,
        )

        ticks = await replay_long_horizon_cohort_observations(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            max_ticks=3,
        )
        await engine.stop()
        assert ticks == 3

    def test_parquet_corrupted_file_handling(self, tmp_path: Path) -> None:
        clear_parquet_cache()
        corrupt_file = tmp_path / "corrupt.parquet"
        corrupt_file.write_bytes(b"THIS_IS_NOT_A_VALID_PARQUET_FILE_CORRUPTED_BYTES")

        df = _load_canonical_df(corrupt_file)
        assert df.empty, "Corrupted parquet file must return empty DataFrame"

    def test_dirty_position_update_intent_detection(self, tmp_path: Path) -> None:
        from autonomous_futures.paper.ledger import PaperRestartRecoveryError
        from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger

        ledger_path = tmp_path / "dirty-ledger.sqlite3"
        ledger = SqlitePaperLedger(ledger_path)

        ledger.begin_position_update("trade-1234", "open")

        with pytest.raises(
            PaperRestartRecoveryError, match="dirty paper position update intent remains"
        ):
            ledger.require_no_position_update_intents()

        ledger.clear_position_update("trade-1234")
        ledger.require_no_position_update_intents()

    @pytest.mark.anyio
    async def test_runner_rejects_negative_and_zero_ticks(self, tmp_path: Path) -> None:
        with pytest.raises(DomainViolation, match="Replay ticks must be strictly positive"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "zero_ticks",
                ticks=0,
                offline=True,
            )

        with pytest.raises(DomainViolation, match="Replay ticks must be strictly positive"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "neg_ticks",
                ticks=-5,
                offline=True,
            )

    @pytest.mark.anyio
    async def test_runner_rejects_negative_and_zero_days(self, tmp_path: Path) -> None:
        with pytest.raises(
            DomainViolation, match="Observation replay days must be strictly positive"
        ):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "zero_days",
                days=0.0,
                offline=True,
            )

        with pytest.raises(
            DomainViolation, match="Observation replay days must be strictly positive"
        ):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "neg_days",
                days=-2.5,
                offline=True,
            )

    @pytest.mark.anyio
    async def test_runner_rejects_conflicting_days_and_ticks(self, tmp_path: Path) -> None:
        with pytest.raises(DomainViolation, match="Cannot specify both 'days' and 'ticks'"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "both_days_ticks",
                days=1.0,
                ticks=100,
                offline=True,
            )

    @pytest.mark.anyio
    async def test_runner_rejects_negative_fee_rate_and_slippage_and_duration(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(DomainViolation, match="Taker fee rate must be non-negative"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "neg_fee",
                ticks=5,
                offline=True,
                fee_rate=Decimal("-0.0001"),
            )

        with pytest.raises(DomainViolation, match="Slippage bps must be non-negative"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "neg_slip",
                ticks=5,
                offline=True,
                slippage_bps=Decimal("-1.0"),
            )

        with pytest.raises(DomainViolation, match="Session duration must be strictly positive"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "neg_dur",
                ticks=5,
                offline=True,
                duration=-5.0,
            )

        with pytest.raises(DomainViolation, match="Session duration must be strictly positive"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "zero_dur",
                ticks=5,
                offline=True,
                duration=0.0,
            )

    @pytest.mark.anyio
    async def test_runner_rejects_nonexistent_history_directory_in_batch_mode(
        self, tmp_path: Path
    ) -> None:
        missing_dir = tmp_path / "completely_nonexistent_history_directory"
        with pytest.raises(FileNotFoundError, match="Canonical history directory not found"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "missing_hist",
                history_dir=missing_dir,
                ticks=5,
                offline=True,
            )

    def test_sqlite_unlocked_verification_detects_exclusive_locks(self, tmp_path: Path) -> None:
        import sqlite3
        from contextlib import closing

        db_file = tmp_path / "lock_test.sqlite3"
        with closing(sqlite3.connect(db_file)) as conn:
            conn.execute("CREATE TABLE t (x INT)")
            conn.commit()

        assert _verify_sqlite_unlocked(tmp_path / "nonexistent.sqlite3") is True
        assert _verify_sqlite_unlocked(db_file) is True

        holder = sqlite3.connect(db_file)
        holder.execute("BEGIN EXCLUSIVE;")
        try:
            assert _verify_sqlite_unlocked(db_file) is False
        finally:
            holder.rollback()
            holder.close()

        assert _verify_sqlite_unlocked(db_file) is True

    def test_load_canonical_df_zero_and_negative_tail_rows(self, tmp_path: Path) -> None:
        clear_parquet_cache()
        pfile = tmp_path / "tail_zero_test.parquet"
        base_t = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "timestamp": [base_t, base_t + timedelta(minutes=5)],
                "close": [Decimal("100.0"), Decimal("101.0")],
            }
        )
        df.to_parquet(pfile)

        loaded_zero = _load_canonical_df(pfile, tail_rows=0)
        assert len(loaded_zero) == 0
        assert set(df.columns).issubset(set(loaded_zero.columns))

        loaded_neg = _load_canonical_df(pfile, tail_rows=-5)
        assert len(loaded_neg) == 0

    @pytest.mark.anyio
    async def test_parquet_non_numeric_and_inf_values_sanitization(self, tmp_path: Path) -> None:
        clear_parquet_cache()
        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        symbols = tuple(s.upper() for s in manifest.symbols.keys())

        data_dir = tmp_path / "bad_strings_data"
        data_dir.mkdir()

        base_t = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        for sym in symbols:
            df = pd.DataFrame(
                {
                    "timestamp": [
                        base_t,
                        base_t + timedelta(minutes=5),
                        base_t + timedelta(minutes=10),
                    ],
                    "close": ["100.0", "101.0", "102.0"],
                    "open": ["not_a_number", "inf", None],
                    "high": ["invalid_high", "Infinity", "105.0"],
                    "low": ["-Infinity", "bad_low", "95.0"],
                    "volume": ["corrupt_vol", "-10.0", "50.0"],
                    "quote_volume": ["corrupt_qvol", None, "5100.0"],
                    "trades": ["not_an_int", "-5", "10"],
                    "taker_buy_base": ["bad_tbb", None, "25.0"],
                    "taker_buy_quote": ["bad_tbq", None, "2550.0"],
                }
            )
            df.to_parquet(data_dir / f"{sym}-5m.parquet")

        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        engine = LivePaperTradingEngine(
            registry_manifest=manifest,
            ledger_db=tmp_path / "bad-num-ledger.sqlite3",
            lifecycle_db=tmp_path / "bad-num-lifecycle.sqlite3",
            observations_db=tmp_path / "bad-num-obs.sqlite3",
            require_flat=False,
        )

        ticks = await replay_long_horizon_cohort_observations(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            max_ticks=3,
        )
        await engine.stop()
        assert ticks == 3

    def test_sqlite_row_count_sql_injection_defense(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test_injection.sqlite3"
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(db_file)) as conn:
            conn.execute("CREATE TABLE valid_table (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO valid_table DEFAULT VALUES")
            conn.commit()

        assert _sqlite_row_count(db_file, "valid_table") == 1
        assert _sqlite_row_count(db_file, "valid_table; DROP TABLE valid_table;") == 0
        assert _sqlite_row_count(db_file, "table with spaces") == 0
        assert _sqlite_row_count(db_file, "table'--") == 0

    def test_seed_engine_history_zero_and_negative_warmup(self, tmp_path: Path) -> None:
        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        symbols = tuple(s.upper() for s in manifest.symbols.keys())

        engine = LivePaperTradingEngine(
            registry_manifest=manifest,
            ledger_db=tmp_path / "seed-zero-ledger.sqlite3",
            lifecycle_db=tmp_path / "seed-zero-lifecycle.sqlite3",
            observations_db=tmp_path / "seed-zero-obs.sqlite3",
            require_flat=False,
        )

        seed_engine_history_from_canonical(
            engine=engine,
            history_dir=DEFAULT_CANONICAL_HISTORY_DIR,
            symbols=symbols,
            warmup_bars=0,
        )
        seed_engine_history_from_canonical(
            engine=engine,
            history_dir=DEFAULT_CANONICAL_HISTORY_DIR,
            symbols=symbols,
            warmup_bars=-10,
            offset_ticks=-5,
        )
        assert True

    @pytest.mark.anyio
    async def test_runner_rejects_empty_ws_url(self, tmp_path: Path) -> None:
        with pytest.raises(DomainViolation, match="ws_url must not be empty"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "empty_ws",
                ticks=5,
                offline=True,
                ws_url="",
            )

        with pytest.raises(DomainViolation, match="ws_url must not be empty"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "space_ws",
                ticks=5,
                offline=True,
                ws_url="   ",
            )

    @pytest.mark.anyio
    async def test_runner_rejects_nonpositive_required_days(self, tmp_path: Path) -> None:
        with pytest.raises(
            DomainViolation, match="Required days for cohort evaluation must be positive"
        ):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "bad_req_days_0",
                ticks=5,
                offline=True,
                required_days=0,
            )
        with pytest.raises(
            DomainViolation, match="Required days for cohort evaluation must be positive"
        ):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "bad_req_days_neg",
                ticks=5,
                offline=True,
                required_days=-3,
            )

    def test_seed_history_with_corrupt_open_high_low_volume(self, tmp_path: Path) -> None:
        clear_parquet_cache()
        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        symbols = tuple(s.upper() for s in manifest.symbols.keys())

        data_dir = tmp_path / "corrupt_warmup_data"
        data_dir.mkdir()

        base_t = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        for sym in symbols:
            df = pd.DataFrame(
                {
                    "timestamp": [base_t + timedelta(minutes=5 * i) for i in range(10)],
                    "close": [100.0 + i for i in range(10)],
                    "open": ["not_a_num" if i % 2 == 0 else str(100.0 + i) for i in range(10)],
                    "high": ["invalid_high" if i % 3 == 0 else str(105.0 + i) for i in range(10)],
                    "low": ["bad_low" if i % 2 == 1 else str(95.0 + i) for i in range(10)],
                    "volume": ["corrupt_vol" if i == 0 else "10.0" for i in range(10)],
                }
            )
            df.to_parquet(data_dir / f"{sym}-5m.parquet")

        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        engine = LivePaperTradingEngine(
            registry_manifest=manifest,
            ledger_db=tmp_path / "warmup-corrupt-ledger.sqlite3",
            lifecycle_db=tmp_path / "warmup-corrupt-lifecycle.sqlite3",
            observations_db=tmp_path / "warmup-corrupt-obs.sqlite3",
            require_flat=False,
        )

        seed_engine_history_from_canonical(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            warmup_bars=10,
        )
        for sym in symbols:
            assert len(engine._bar_history.get(sym, [])) == 10

    @pytest.mark.anyio
    async def test_parquet_taker_volume_exceeds_total_volume_sanitization(
        self, tmp_path: Path
    ) -> None:
        clear_parquet_cache()
        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        symbols = tuple(s.upper() for s in manifest.symbols.keys())

        data_dir = tmp_path / "excess_taker_data"
        data_dir.mkdir()

        base_t = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        for sym in symbols:
            df = pd.DataFrame(
                {
                    "timestamp": [
                        base_t,
                        base_t + timedelta(minutes=5),
                        base_t + timedelta(minutes=10),
                    ],
                    "close": ["100.0", "101.0", "102.0"],
                    "open": ["100.0", "101.0", "102.0"],
                    "high": ["105.0", "106.0", "107.0"],
                    "low": ["95.0", "96.0", "97.0"],
                    "volume": ["10.0", "10.0", "10.0"],
                    "quote_volume": ["1000.0", "1010.0", "1020.0"],
                    "trades": ["5", "5", "5"],
                    "taker_buy_base": ["25.0", "50.0", "100.0"],  # Exceeds volume 10.0!
                    "taker_buy_quote": ["2500.0", "5000.0", "10000.0"],  # Exceeds quote_volume!
                }
            )
            df.to_parquet(data_dir / f"{sym}-5m.parquet")

        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        engine = LivePaperTradingEngine(
            registry_manifest=manifest,
            ledger_db=tmp_path / "excess-taker-ledger.sqlite3",
            lifecycle_db=tmp_path / "excess-taker-lifecycle.sqlite3",
            observations_db=tmp_path / "excess-taker-obs.sqlite3",
            require_flat=False,
        )

        ticks = await replay_long_horizon_cohort_observations(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            max_ticks=3,
        )
        await engine.stop()
        assert ticks == 3

    @pytest.mark.anyio
    async def test_runner_rejects_nan_and_inf_numeric_parameters(self, tmp_path: Path) -> None:
        with pytest.raises(
            DomainViolation, match="Observation replay days must be strictly positive"
        ):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "days_nan",
                days=float("nan"),
                offline=True,
            )

        with pytest.raises(
            DomainViolation, match="Observation replay days must be strictly positive"
        ):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "days_inf",
                days=float("inf"),
                offline=True,
            )

        with pytest.raises(DomainViolation, match="Session duration must be strictly positive"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "dur_nan",
                duration=float("nan"),
                ticks=5,
                offline=True,
            )

        with pytest.raises(DomainViolation, match="Starting capital must be strictly positive"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "cap_nan",
                starting_capital=Decimal("NaN"),
                ticks=5,
                offline=True,
            )

        with pytest.raises(DomainViolation, match="Starting capital must be strictly positive"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "cap_inf",
                starting_capital=Decimal("Infinity"),
                ticks=5,
                offline=True,
            )

        with pytest.raises(DomainViolation, match="Max margin utilization must be in"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "util_nan",
                max_margin_utilization=Decimal("NaN"),
                ticks=5,
                offline=True,
            )

        with pytest.raises(DomainViolation, match="Taker fee rate must be non-negative"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "fee_inf",
                fee_rate=Decimal("Infinity"),
                ticks=5,
                offline=True,
            )

    @pytest.mark.anyio
    async def test_runner_rejects_invalid_mode(self, tmp_path: Path) -> None:
        with pytest.raises(DomainViolation, match="Invalid mode 'bogus_mode'"):
            await run_phase_268_long_horizon_maturation(
                output_dir=tmp_path / "bad_mode",
                mode="bogus_mode",
                ticks=5,
                offline=True,
            )

    def test_load_canonical_df_missing_close_column_returns_empty(self, tmp_path: Path) -> None:
        clear_parquet_cache()
        pfile = tmp_path / "no_close.parquet"
        base_t = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "timestamp": [base_t, base_t + timedelta(minutes=5)],
                "volume": [10.0, 20.0],
            }
        )
        df.to_parquet(pfile)

        loaded = _load_canonical_df(pfile)
        assert len(loaded) == 0
        assert loaded.empty

    def test_parquet_cache_bounded_size(self, tmp_path: Path) -> None:
        from scripts.run_phase_268_long_horizon_maturation import _PARQUET_CACHE

        clear_parquet_cache()
        base_t = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "timestamp": [base_t],
                "close": [100.0],
            }
        )

        for i in range(70):
            p = tmp_path / f"test_cache_{i}.parquet"
            df.to_parquet(p)
            _load_canonical_df(p)

        assert len(_PARQUET_CACHE) <= 64
