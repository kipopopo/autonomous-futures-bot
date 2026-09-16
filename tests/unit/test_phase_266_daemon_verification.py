"""Unit tests for Phase 266 Autonomous Paper Trading Daemon Lifecycle Verification."""

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
from scripts.run_phase_266_daemon_verification import (  # noqa: E402
    DEFAULT_CANONICAL_HISTORY_DIR,
    DEFAULT_MAX_MARGIN_UTILIZATION,
    DEFAULT_MIN_RESERVE_BUFFER,
    DEFAULT_STARTING_CAPITAL,
    EXPECTED_MANIFEST_V2_CANDIDATES,
    _assert_zero_secrets,
    build_arg_parser,
    main,
    run_phase_266_daemon_verification,
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
            # Sleep briefly to simulate open connection before ending
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


class TestPhase266ManifestAndConfig:
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
        # Tamper candidate artifact hash for BTCUSDT
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
        missing_file = tmp_path / "missing_symbol_manifest.json"
        missing_file.write_text(json.dumps(raw_manifest), encoding="utf-8")

        with pytest.raises(DomainViolation, match="Missing required active candidate BTCUSDT"):
            validate_manifest_v2(missing_file)

    def test_validate_manifest_v2_rejects_tampered_qualification_hash(self, tmp_path: Path) -> None:
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
        raw_manifest = manifest.model_dump(mode="json")
        raw_manifest["symbols"]["BTCUSDT"]["qualification_hash"] = "0" * 64
        tampered_file = tmp_path / "tampered_qual_manifest.json"
        tampered_file.write_text(json.dumps(raw_manifest), encoding="utf-8")

        with pytest.raises(DomainViolation):
            validate_manifest_v2(tampered_file)

    def test_validate_manifest_v2_rejects_missing_qualification_file(self, tmp_path: Path) -> None:
        manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
        raw_manifest = manifest.model_dump(mode="json")
        raw_manifest["symbols"]["BTCUSDT"]["candidate_id"] = "cand-nonexistent-999"
        tampered_file = tmp_path / "missing_qual_manifest.json"
        tampered_file.write_text(json.dumps(raw_manifest), encoding="utf-8")

        with pytest.raises((DomainViolation, FileNotFoundError)):
            validate_manifest_v2(tampered_file)


class TestPhase266StrategyAdmission:
    """Test StrategyAdmissionDecider evaluation on daemon startup."""

    @pytest.mark.anyio
    async def test_admission_decisions_all_admitted_on_startup(self, tmp_path: Path) -> None:
        res = await run_phase_266_daemon_verification(
            output_dir=tmp_path / "admission_test",
            registry_path=DEFAULT_CANDIDATE_REGISTRY_PATH,
            history_dir=DEFAULT_CANONICAL_HISTORY_DIR,
            ticks=5,
            offline=True,
        )
        assert res.output_dir.is_dir()
        summary = json.loads(res.daemon_summary_path.read_text(encoding="utf-8"))
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            assert summary["candidates"][sym]["admission_decision"] == "admitted"

    @pytest.mark.anyio
    async def test_daemon_rejects_blocked_candidate_decision(self, tmp_path: Path) -> None:
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
                await run_phase_266_daemon_verification(
                    output_dir=tmp_path / "blocked_admission_test",
                    ticks=5,
                    offline=True,
                )


class TestPhase266BoundedDaemonExecution:
    """Test bounded daemon execution in batch ticks and mock live streaming modes."""

    @pytest.mark.anyio
    async def test_daemon_batch_ticks_mode_execution(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "batch_ticks_test"
        res = await run_phase_266_daemon_verification(
            output_dir=out_dir,
            registry_path=DEFAULT_CANDIDATE_REGISTRY_PATH,
            history_dir=DEFAULT_CANONICAL_HISTORY_DIR,
            ticks=15,
            offline=True,
        )
        assert res.accounting_reconciled is True
        assert res.zero_balance_drift is True
        assert res.starting_equity == Decimal("100.00")
        assert res.final_cash == Decimal("100.00")
        assert res.drift < Decimal("1e-15")

        # Verify all 9 artifacts exist
        expected_artifacts = [
            "paper-ledger.sqlite3",
            "paper-lifecycle.sqlite3",
            "paper-observations.sqlite3",
            "paper-cohort-readiness-report.json",
            "paper-health-report-BTCUSDT.json",
            "paper-health-report-ETHUSDT.json",
            "paper-health-report-SOLUSDT.json",
            "daemon-summary.json",
            "paper-summary.json",
        ]
        for art in expected_artifacts:
            assert (out_dir / art).is_file(), f"Missing artifact: {art}"

    @pytest.mark.anyio
    async def test_daemon_mock_websocket_streaming_execution(self, tmp_path: Path) -> None:
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
            res = await run_phase_266_daemon_verification(
                output_dir=out_dir,
                duration=1.0,
                mode="live",
            )

        assert res.accounting_reconciled is True
        assert res.zero_balance_drift is True
        assert (out_dir / "daemon-summary.json").is_file()
        assert (out_dir / "paper-summary.json").is_file()

    @pytest.mark.anyio
    async def test_daemon_auto_fallback_to_batch_on_stream_error(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "auto_fallback_test"

        with patch(
            "autonomous_futures.feed.client.BinancePublicFeedClient.connect_and_stream",
            side_effect=OSError("Network unreachable"),
        ):
            res = await run_phase_266_daemon_verification(
                output_dir=out_dir,
                ticks=5,
                mode="auto",
            )

        assert res.accounting_reconciled is True
        assert (out_dir / "daemon-summary.json").is_file()

    @pytest.mark.anyio
    async def test_daemon_live_mode_propagates_stream_error(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "live_error_test"

        with patch(
            "autonomous_futures.feed.client.BinancePublicFeedClient.connect_and_stream",
            side_effect=OSError("Network unreachable"),
        ):
            with pytest.raises(OSError, match="Network unreachable"):
                await run_phase_266_daemon_verification(
                    output_dir=out_dir,
                    duration=1.0,
                    mode="live",
                )

    @pytest.mark.anyio
    async def test_daemon_auto_fallback_when_feed_receives_zero_messages(
        self, tmp_path: Path
    ) -> None:
        """When stream finishes with 0 messages, auto mode falls back to batch."""
        from typing import Any

        out_dir = tmp_path / "zero_msg_fallback_test"

        async def mock_connect_empty(*args: Any, **kwargs: Any) -> None:
            return

        with patch(
            "autonomous_futures.feed.client.BinancePublicFeedClient.connect_and_stream",
            side_effect=mock_connect_empty,
        ):
            res = await run_phase_266_daemon_verification(
                output_dir=out_dir,
                ticks=5,
                mode="auto",
            )
        assert res.accounting_reconciled is True
        assert (out_dir / "daemon-summary.json").is_file()
        assert (out_dir / "paper-observations.sqlite3").is_file()

    @pytest.mark.anyio
    async def test_daemon_live_mode_fails_fast_on_zero_messages_reconnect_loop(
        self, tmp_path: Path
    ) -> None:
        """When mode is live and reconnect count > 0 with 0 messages, ConnectionError is raised."""
        from typing import Any

        out_dir = tmp_path / "live_fail_fast_test"

        async def mock_connect_reconnecting(self_feed: Any, *args: Any, **kwargs: Any) -> None:
            self_feed.reconnect_count = 3
            return

        with patch(
            "autonomous_futures.feed.client.BinancePublicFeedClient.connect_and_stream",
            mock_connect_reconnecting,
        ):
            with pytest.raises(
                ConnectionError, match="Live feed connection failed to receive messages"
            ):
                await run_phase_266_daemon_verification(
                    output_dir=out_dir,
                    duration=1.0,
                    mode="live",
                )

    @pytest.mark.anyio
    async def test_batch_bar_ticks_replay_disparate_symbol_timestamps(self, tmp_path: Path) -> None:
        """Replaying batch ticks with disjoint symbol timestamps executes all timestamps cleanly."""
        from autonomous_futures.paper.live_engine import LivePaperTradingEngine
        from scripts.run_phase_266_daemon_verification import replay_batch_bar_ticks

        hist_dir = tmp_path / "staggered_history"
        hist_dir.mkdir()

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        df_btc = pd.DataFrame(
            [
                {
                    "timestamp": base_time + timedelta(minutes=5 * i),
                    "close_time": base_time + timedelta(minutes=5 * (i + 1)),
                    "open": 90000.0,
                    "high": 90100.0,
                    "low": 89900.0,
                    "close": 90050.0,
                    "volume": 10.0,
                    "quote_volume": 900500.0,
                    "trades": 100,
                    "taker_buy_base": 5.0,
                    "taker_buy_quote": 450250.0,
                }
                for i in range(3)
            ]
        )
        df_eth = pd.DataFrame(
            [
                {
                    "timestamp": base_time + timedelta(minutes=5 * (i + 1)),
                    "close_time": base_time + timedelta(minutes=5 * (i + 2)),
                    "open": 3000.0,
                    "high": 3010.0,
                    "low": 2990.0,
                    "close": 3005.0,
                    "volume": 50.0,
                    "quote_volume": 150250.0,
                    "trades": 80,
                    "taker_buy_base": 25.0,
                    "taker_buy_quote": 75125.0,
                }
                for i in range(3)
            ]
        )
        df_btc.to_parquet(hist_dir / "BTCUSDT-5m.parquet")
        df_eth.to_parquet(hist_dir / "ETHUSDT-5m.parquet")

        engine = LivePaperTradingEngine(
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
        )
        ticks_replayed = await replay_batch_bar_ticks(
            engine=engine,
            history_dir=hist_dir,
            symbols=("BTCUSDT", "ETHUSDT"),
            max_ticks=5,
        )
        assert ticks_replayed == 4


class TestPhase266AccountingAndRiskInvariants:
    """Test exact double-entry accounting reconciliation and risk limits."""

    @pytest.mark.anyio
    async def test_exact_double_entry_balance_reconciliation(self, tmp_path: Path) -> None:
        res = await run_phase_266_daemon_verification(
            output_dir=tmp_path / "reconciliation_test",
            ticks=10,
            offline=True,
        )
        assert res.drift < Decimal("1e-15")
        assert res.final_cash == res.starting_equity + res.realized_pnl

    @pytest.mark.anyio
    async def test_margin_utilization_and_reserve_buffer_limits(self, tmp_path: Path) -> None:
        res = await run_phase_266_daemon_verification(
            output_dir=tmp_path / "risk_limits_test",
            ticks=10,
            offline=True,
            max_margin_utilization=Decimal("0.80"),
            min_reserve_buffer=Decimal("0.20"),
        )
        assert res.max_margin_utilization <= Decimal("0.80")
        assert res.min_reserve_buffer >= Decimal("0.20")

    @pytest.mark.anyio
    async def test_single_position_invariant_maintained(self, tmp_path: Path) -> None:
        res = await run_phase_266_daemon_verification(
            output_dir=tmp_path / "single_pos_test",
            ticks=10,
            offline=True,
        )
        assert res.positions_reconciled is True

    @pytest.mark.anyio
    async def test_single_position_invariant_violation_raises(self, tmp_path: Path) -> None:
        from typing import Any
        from unittest.mock import MagicMock

        from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger

        real_load = SqlitePaperLedger.load
        mock_p1 = MagicMock(symbol="BTCUSDT", entry_fee=None)
        mock_p2 = MagicMock(symbol="BTCUSDT", entry_fee=None)

        call_count = 0

        def load_side_effect(self: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return real_load(self)
            mock_ledger = MagicMock()
            mock_ledger.open_positions.return_value = [mock_p1, mock_p2]
            mock_ledger.entries = []
            return mock_ledger

        with patch(
            "autonomous_futures.paper.sqlite_ledger.SqlitePaperLedger.load",
            side_effect=load_side_effect,
            autospec=True,
        ):
            with pytest.raises(DomainViolation, match="Single-position invariant violated"):
                await run_phase_266_daemon_verification(
                    output_dir=tmp_path / "single_pos_violation",
                    ticks=5,
                    offline=True,
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
            res = await run_phase_266_daemon_verification(
                output_dir=tmp_path / "open_pos_accounting",
                ticks=5,
                offline=True,
            )
            assert res.accounting_reconciled is True
            assert res.drift < Decimal("1e-15")

    def test_reconcile_balances_strict_drift_precision_ceiling(self, tmp_path: Path) -> None:
        """LivePaperTradingEngine.reconcile_balances strictly enforces < 1e-15 drift tolerance."""
        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        engine = LivePaperTradingEngine(
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
        )
        # Inject micro-drift of 0.00005 (which previously slipped past 0.0001)
        engine.account.cash += Decimal("0.00005")
        with pytest.raises(DomainViolation, match="Cash balance drift detected"):
            engine.reconcile_balances()


class TestPhase266PersistenceAndCohortReporting:
    """Test isolated SQLite persistence, cohort reports, and artifact hashes."""

    @pytest.mark.anyio
    async def test_isolated_sqlite_and_artifact_hashes(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "artifacts_test"
        res = await run_phase_266_daemon_verification(
            output_dir=out_dir,
            ticks=10,
            offline=True,
        )

        assert len(res.artifact_hashes) >= 9
        assert "paper-ledger.sqlite3" in res.artifact_hashes
        assert "paper-lifecycle.sqlite3" in res.artifact_hashes
        assert "paper-observations.sqlite3" in res.artifact_hashes
        assert "paper-cohort-readiness-report.json" in res.artifact_hashes
        assert "daemon-summary.json" in res.artifact_hashes
        assert "paper-summary.json" in res.artifact_hashes

        for fname, fhash in res.artifact_hashes.items():
            assert len(fhash) == 64
            assert (out_dir / fname).is_file()

        # Check cohort readiness report
        cohort_json = json.loads(
            (out_dir / "paper-cohort-readiness-report.json").read_text(encoding="utf-8")
        )
        assert cohort_json["expected_candidate_count"] == 3
        assert cohort_json["reported_candidate_count"] == 3

    @pytest.mark.anyio
    async def test_sqlite_file_handles_closed_cleanly(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "sqlite_cleanup_test"
        res = await run_phase_266_daemon_verification(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )
        assert res.accounting_reconciled is True
        for db_name in (
            "paper-ledger.sqlite3",
            "paper-lifecycle.sqlite3",
            "paper-observations.sqlite3",
        ):
            db_path = out_dir / db_name
            assert db_path.is_file()
            # On Windows, renaming/unlinking succeeds only if all file handles are closed
            renamed_path = out_dir / f"{db_name}.closed_check"
            db_path.rename(renamed_path)
            renamed_path.unlink()

    @pytest.mark.anyio
    async def test_summary_handles_empty_sqlite_files_without_tables(self, tmp_path: Path) -> None:
        """Summary generation handles preexisting empty 0-byte SQLite files without crashing."""
        out_dir = tmp_path / "empty_sqlite_test"
        out_dir.mkdir(parents=True)
        # Touch empty databases
        (out_dir / "paper-ledger.sqlite3").touch()
        (out_dir / "paper-lifecycle.sqlite3").touch()
        (out_dir / "paper-observations.sqlite3").touch()

        res = await run_phase_266_daemon_verification(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )
        assert res.accounting_reconciled is True
        summary = json.loads(res.daemon_summary_path.read_text(encoding="utf-8"))
        assert "sqlite_persistence" in summary


class TestPhase266FailClosedAndZeroSecrets:
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

    @pytest.mark.anyio
    async def test_generated_reports_contain_zero_secrets(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "secret_scan_test"
        await run_phase_266_daemon_verification(
            output_dir=out_dir,
            ticks=5,
            offline=True,
        )

        for jfile in out_dir.glob("*.json"):
            content = jfile.read_text(encoding="utf-8")
            _assert_zero_secrets(content, jfile.name)

    def test_zero_secret_patterns_detects_multiple_token_formats(self) -> None:
        """_assert_zero_secrets detects GitHub tokens, PATs, and AWS keys."""
        # Clean passes
        _assert_zero_secrets("nominal_string_with_no_tokens", "test")

        # GitHub token format
        with pytest.raises(DomainViolation, match="Secret pattern matched"):
            _assert_zero_secrets("ghp_1234567890abcdefghijklmnopqrstuvwxyz", "test_ghp")

        # GitHub PAT format
        pat = "github_pat_" + "a" * 82
        with pytest.raises(DomainViolation, match="Secret pattern matched"):
            _assert_zero_secrets(pat, "test_pat")

        # AWS Access Key format
        with pytest.raises(DomainViolation, match="Secret pattern matched"):
            _assert_zero_secrets("AKIAIOSFODNN7EXAMPLE", "test_aws")


class TestPhase266CLI:
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

    def test_main_cli_execution_batch(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "cli_test"
        ret = main(["--output-dir", str(out_dir), "--ticks", "5", "--offline"])
        assert ret == 0
        assert (out_dir / "daemon-summary.json").is_file()

    def test_main_cli_json_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        out_dir = tmp_path / "cli_json_test"
        ret = main(["--output-dir", str(out_dir), "--ticks", "5", "--offline", "--json"])
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["phase"] == "phase_266"
        assert data["shared_portfolio_margin"]["starting_capital_usdt"] == "100.00"

    def test_main_cli_smoke_test_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_dir = tmp_path / "cli_smoke_test"
        ret = main(["--output-dir", str(out_dir), "--offline", "--smoke-test", "--json"])
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["phase"] == "phase_266"


class TestPhase266DataAggregationAndRobustness:
    """Test get_bar_dataframe aggregation, preaggregated bar pass-through, and gap handling."""

    def test_get_bar_dataframe_with_preaggregated_bars(self, tmp_path: Path) -> None:
        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        engine = LivePaperTradingEngine(
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
        )
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        # Feed 15m bars directly into _bar_history
        engine._bar_history["BTCUSDT"] = [
            {
                "timestamp": (base_time + timedelta(minutes=15 * i)).isoformat(),
                "open": "90000.0",
                "high": "90100.0",
                "low": "89900.0",
                "close": "90050.0",
                "volume": "10.0",
            }
            for i in range(10)
        ]
        df_15m = engine.get_bar_dataframe("BTCUSDT", timeframe="15m")
        assert not df_15m.empty
        assert len(df_15m) == 10

    def test_get_bar_dataframe_resampling_drops_historic_gaps(self, tmp_path: Path) -> None:
        from autonomous_futures.paper.live_engine import LivePaperTradingEngine

        engine = LivePaperTradingEngine(
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
        )
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        # Create 5m bars with a gap in the middle (e.g. at i=6)
        records = []
        for i in range(12):
            if i in (6, 7):  # missing 2 bars creates incomplete 15m bucket
                continue
            records.append(
                {
                    "timestamp": (base_time + timedelta(minutes=5 * i)).isoformat(),
                    "open": "90000.0",
                    "high": "90100.0",
                    "low": "89900.0",
                    "close": "90050.0",
                    "volume": "10.0",
                }
            )
        engine._bar_history["BTCUSDT"] = records
        df_resamp = engine.get_bar_dataframe("BTCUSDT", timeframe="15m")
        # Should return contiguous trailing partition without crashing
        assert not df_resamp.empty
        diffs = df_resamp["timestamp"].diff()
        valid_diffs = diffs[diffs.notna()]
        assert (valid_diffs == pd.Timedelta(minutes=15)).all()
