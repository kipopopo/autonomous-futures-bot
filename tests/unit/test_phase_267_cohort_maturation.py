"""Unit tests for Phase 267 Multi-Day Paper Trading Cohort Observation & Maturation Evaluation."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
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
from autonomous_futures.paper.maturity import _slot_start  # noqa: E402
from scripts.run_phase_267_cohort_maturation import (  # noqa: E402
    DEFAULT_CANONICAL_HISTORY_DIR,
    DEFAULT_MAX_MARGIN_UTILIZATION,
    DEFAULT_MIN_RESERVE_BUFFER,
    DEFAULT_STARTING_CAPITAL,
    EXPECTED_MANIFEST_V2_CANDIDATES,
    _assert_zero_secrets,
    _load_canonical_df,
    build_arg_parser,
    clear_parquet_cache,
    main,
    replay_multi_day_cohort_observations,
    run_phase_267_cohort_maturation,
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


class TestPhase267ManifestAndConfig:
    """Test Manifest Version 2 compliance, candidate artifact hashes, and qualifications."""

    def test_candidate_registry_manifest_v2_active_candidates(self) -> None:
        manifest = validate_manifest_v2(DEFAULT_CANDIDATE_REGISTRY_PATH)
        assert manifest.registry_version >= 2
        assert set(manifest.symbols.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        for sym, expected_id in EXPECTED_MANIFEST_V2_CANDIDATES.items():
            assert manifest.symbols[sym].candidate_id == expected_id

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


class TestPhase267StrategyAdmission:
    """Test StrategyAdmissionDecider evaluation on cohort runner startup."""

    @pytest.mark.anyio
    async def test_admission_decisions_all_admitted_on_startup(self, tmp_path: Path) -> None:
        res = await run_phase_267_cohort_maturation(
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
                await run_phase_267_cohort_maturation(
                    output_dir=tmp_path / "blocked_admission_test",
                    ticks=5,
                    offline=True,
                )


class TestPhase267BoundedCohortExecution:
    """Test bounded cohort execution in batch ticks and mock live streaming modes."""

    @pytest.mark.anyio
    async def test_cohort_batch_ticks_mode_execution(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "batch_ticks_test"
        res = await run_phase_267_cohort_maturation(
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
            res = await run_phase_267_cohort_maturation(
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
            res = await run_phase_267_cohort_maturation(
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

        # Create synthetic test parquets with disparate timestamps
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
        ticks = await replay_multi_day_cohort_observations(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            max_ticks=5,
        )
        await engine.stop()
        assert ticks == 5


class TestPhase267AccountingAndRiskInvariants:
    """Test exact double-entry accounting reconciliation and risk limits."""

    @pytest.mark.anyio
    async def test_exact_double_entry_balance_reconciliation(self, tmp_path: Path) -> None:
        res = await run_phase_267_cohort_maturation(
            output_dir=tmp_path / "reconciliation_test",
            ticks=5,
            offline=True,
        )
        assert res.drift < Decimal("1e-15")
        assert res.final_cash == res.starting_equity + res.realized_pnl

    @pytest.mark.anyio
    async def test_margin_utilization_and_reserve_buffer_limits(self, tmp_path: Path) -> None:
        res = await run_phase_267_cohort_maturation(
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
        res = await run_phase_267_cohort_maturation(
            output_dir=tmp_path / "single_pos_test",
            ticks=5,
            offline=True,
        )
        assert res.positions_reconciled is True

    @pytest.mark.anyio
    async def test_runner_rejects_invalid_risk_bounds(self, tmp_path: Path) -> None:
        with pytest.raises(DomainViolation, match="Starting capital must be strictly positive"):
            await run_phase_267_cohort_maturation(
                output_dir=tmp_path / "zero_cap",
                ticks=5,
                offline=True,
                starting_capital=Decimal("0.0"),
            )

        with pytest.raises(DomainViolation, match="Max margin utilization must be in"):
            await run_phase_267_cohort_maturation(
                output_dir=tmp_path / "bad_util",
                ticks=5,
                offline=True,
                max_margin_utilization=Decimal("1.50"),
            )

        with pytest.raises(DomainViolation, match="Min reserve buffer must be in"):
            await run_phase_267_cohort_maturation(
                output_dir=tmp_path / "bad_buffer",
                ticks=5,
                offline=True,
                min_reserve_buffer=Decimal("-0.10"),
            )

        with pytest.raises(DomainViolation, match="cannot exceed 1.0"):
            await run_phase_267_cohort_maturation(
                output_dir=tmp_path / "bad_sum",
                ticks=5,
                offline=True,
                max_margin_utilization=Decimal("0.90"),
                min_reserve_buffer=Decimal("0.20"),
            )

    @pytest.mark.anyio
    async def test_accounting_reconciled_with_open_position(self, tmp_path: Path) -> None:
        from typing import Any
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
            res = await run_phase_267_cohort_maturation(
                output_dir=tmp_path / "open_pos_accounting",
                ticks=5,
                offline=True,
            )
            assert res.accounting_reconciled is True
            assert res.drift < Decimal("1e-15")


class TestPhase267PersistenceAndMaturationReporting:
    """Test isolated SQLite persistence, maturation reports, and artifact hashes."""

    @pytest.mark.anyio
    async def test_isolated_sqlite_and_artifact_hashes(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "artifacts_test"
        res = await run_phase_267_cohort_maturation(
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
        res = await run_phase_267_cohort_maturation(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )
        assert res.output_dir.is_dir()

        # Try opening and modifying SQLite databases to prove no dangling locks
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
        await run_phase_267_cohort_maturation(
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

        # Check that no candidate has multiple observations in the same 6-hour slot
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
        res = await run_phase_267_cohort_maturation(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )
        summary = json.loads(res.maturation_summary_path.read_text(encoding="utf-8"))
        assert "maturation_progression" in summary
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


class TestPhase267FailClosedAndZeroSecrets:
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
        script_path = _REPO_ROOT / "scripts" / "run_phase_267_cohort_maturation.py"
        assert script_path.is_file()
        content = script_path.read_text(encoding="utf-8")
        compile(content, str(script_path), "exec")

    @pytest.mark.anyio
    async def test_generated_reports_contain_zero_secrets(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "secret_scan_test"
        await run_phase_267_cohort_maturation(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )

        for jfile in out_dir.glob("*.json"):
            content = jfile.read_text(encoding="utf-8")
            _assert_zero_secrets(content, jfile.name)


class TestPhase267CLI:
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
        assert data["phase"] == "phase_267"
        assert data["shared_portfolio_margin"]["starting_capital_usdt"] == "100.00"

    def test_main_cli_smoke_test_flag(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "smoke_cli_test"
        ret = main(["--output-dir", str(out_dir), "--smoke-test", "--offline"])
        assert ret == 0
        assert (out_dir / "maturation-summary.json").is_file()

    def test_main_cli_days_flag(self, tmp_path: Path) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--days", "7.0"])
        assert args.days == 7.0


class TestPhase267AdversarialDataRobustnessAndEdgeCases:
    """Adversarial stress tests for parquet cache isolation, malformed data, and timeline gaps."""

    def test_parquet_cache_invalidation_and_isolation(self, tmp_path: Path) -> None:
        clear_parquet_cache()
        pfile = tmp_path / "cache_test.parquet"
        base_t = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

        # Initial DataFrame
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

        # Mutate the loaded copy in-place
        loaded1["close"] = Decimal("999999.0")

        # Load again: cache should NOT be mutated
        loaded2 = _load_canonical_df(pfile)
        assert loaded2["close"].iloc[0] == Decimal("100.0")

        # Clear cache explicitly
        clear_parquet_cache()

        # Overwrite file with new data (different size/content)
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

        # Missing close_time column
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

        # close_time before timestamp (invalid)
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
        # Should keep the last row
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
        # Create asynchronous gaps: BTC starts at T+0, ETH at T+5m, SOL at T+10m
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

        # Replay with max_ticks=4
        ticks = await replay_multi_day_cohort_observations(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            max_ticks=4,
        )
        await engine.stop()
        # Strictly bounded at max_ticks
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
        ticks = await replay_multi_day_cohort_observations(
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
            # Only 3 bars
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

        # Seeding with offset_ticks (10) larger than total rows (3)
        seed_engine_history_from_canonical(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            warmup_bars=300,
            offset_ticks=10,
        )
        # Seeding with offset_ticks=1
        seed_engine_history_from_canonical(
            engine=engine,
            history_dir=data_dir,
            symbols=symbols,
            warmup_bars=300,
            offset_ticks=1,
        )
        assert True
