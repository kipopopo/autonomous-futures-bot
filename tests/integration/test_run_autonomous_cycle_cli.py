"""Integration tests for scripts/run_autonomous_cycle.py CLI runner."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)
from autonomous_futures.research.google_ai_studio_provider import (
    resolve_credential,
)

# Ensure repository root is on sys.path for scripts import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_autonomous_cycle import main as run_cli_main  # noqa: E402

PARQUET_PATH = Path("research/immutable-data/5m/canonical/BTCUSDT-5m.parquet")
BUNDLE_HASH = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
REGISTRY_HASH = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _build_candidate(
    cand_id: str,
    stop_atr: str = "1.0",
    tp_atr: str = "2.0",
    symbol: str = "BTCUSDT",
) -> CreatorCandidateArtifact:
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=cand_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=3, shift=1),),
        entry=EntryExit(long="returns > 0.001", short="returns < -0.001"),
        exit=EntryExit(long="returns < 0.0", short="returns > 0.0"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal(stop_atr),
            take_profit_atr_multiplier=Decimal(tp_atr),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=cand_id,
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="run-cli-001",
        research_seed=42,
        created_at=NOW - timedelta(days=1),
    )


def _init_test_ledger(
    db_path: Path, cand: CreatorCandidateArtifact, symbol: str = "BTCUSDT"
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_artifact_hash TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                fill_price TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                approval_id TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                slippage_cost TEXT,
                gross_pnl TEXT,
                net_pnl TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES (
                1, 'open', 'trade-fail-001', ?, ?, ?, 'LONG', '0.002', '50000.0',
                ?, 'app-01', '0.05', NULL, '0.01', NULL, NULL
            );
            """,
            (
                cand.candidate_id,
                cand.artifact_hash,
                symbol,
                (NOW - timedelta(hours=1)).isoformat(),
            ),
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES (
                2, 'close', 'trade-fail-001', ?, ?, ?, 'LONG', '0.002', '45000.0',
                ?, 'app-02', '0.05', '0.05', '0.01', '-10.0', '-10.1'
            );
            """,
            (cand.candidate_id, cand.artifact_hash, symbol, NOW.isoformat()),
        )


def test_cli_help_flag() -> None:
    """Verify that --help exits with code 0."""
    result = subprocess.run(
        [sys.executable, "scripts/run_autonomous_cycle.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Autonomous Cycle CLI Runner" in result.stdout


def test_cli_invalid_arguments_exit_code_2() -> None:
    """Verify that missing required arguments exit with code 2."""
    ret = run_cli_main(["--symbol", "INVALID_LOWER_CASE"])
    assert ret == 2


def test_cli_missing_database_exit_code_3(tmp_path: Path) -> None:
    """Verify that missing ledger DB file exits with code 3."""
    ret = run_cli_main(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(tmp_path / "nonexistent.sqlite3"),
            "--parquet-path",
            str(PARQUET_PATH),
        ]
    )
    assert ret == 3


def test_cli_end_to_end_real_data(tmp_path: Path) -> None:
    """Full execution of CLI runner with real BTCUSDT 5m Parquet data."""
    cand = _build_candidate("cand-cli-init-001", stop_atr="0.5")
    cand_path = tmp_path / "cand-cli-init-001.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "cycle_output"
    args = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(ledger_db),
        "--parquet-path",
        str(PARQUET_PATH),
        "--output-dir",
        str(output_dir),
        "--candidate-path",
        str(cand_path),
        "--cycle-id",
        "cycle-cli-e2e-001",
        "--windows-count",
        "1",
        "--min-windows",
        "1",
        "--min-profit-factor",
        "0.10",
        "--min-trades",
        "10",
        "--max-drawdown-pct",
        "50.0",
        "--min-average-return-pct",
        "-10.0",
        "--now",
        "2026-08-06T06:00:00Z",
    ]

    ret = run_cli_main(args)
    assert ret == 0

    result_file = output_dir / "autonomous-cycle-result.json"
    audit_file = output_dir / "cycle-audit.json"
    assert result_file.exists()
    assert audit_file.exists()

    result_data = json.loads(result_file.read_text(encoding="utf-8"))
    assert result_data["cycle_status"] == "completed_admitted"
    assert result_data["qualification_decision"] == "qualified"
    assert result_data["admission_decision"] == "admitted"
    assert result_data["data_source"] == "cached_only"
    assert result_data["execution_authority"] is False


def test_cli_idempotent_reexecution(tmp_path: Path) -> None:
    """Running CLI twice into the same output directory produces identical audit hashes."""
    cand = _build_candidate("cand-cli-init-001", stop_atr="0.5")
    cand_path = tmp_path / "cand-cli-init-001.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "cycle_output"
    args = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(ledger_db),
        "--parquet-path",
        str(PARQUET_PATH),
        "--output-dir",
        str(output_dir),
        "--candidate-path",
        str(cand_path),
        "--cycle-id",
        "cycle-cli-idempotent-001",
        "--windows-count",
        "1",
        "--min-windows",
        "1",
        "--min-profit-factor",
        "0.10",
        "--min-trades",
        "10",
        "--max-drawdown-pct",
        "50.0",
        "--min-average-return-pct",
        "-10.0",
        "--now",
        "2026-08-06T06:00:00Z",
    ]

    ret1 = run_cli_main(args)
    assert ret1 == 0
    audit1 = json.loads((output_dir / "cycle-audit.json").read_text(encoding="utf-8"))

    ret2 = run_cli_main(args)
    assert ret2 == 0
    audit2 = json.loads((output_dir / "cycle-audit.json").read_text(encoding="utf-8"))

    assert audit1["audit_hash"] == audit2["audit_hash"]
    assert audit1["cycle_hash"] == audit2["cycle_hash"]


def test_cli_help_shows_provider_and_model_options() -> None:
    """Verify that --help displays --provider, --model, and --temperature with strict choices."""
    result = subprocess.run(
        [sys.executable, "scripts/run_autonomous_cycle.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    stdout = result.stdout

    assert "--provider {demo,google_ai_studio}" in stdout
    assert "Strategy revision provider transport (default: demo)" in stdout
    assert "--model {gemma-4-31b-it,gemma-4-26b-a4b-it}" in stdout
    assert "Gemma model ID for Google AI Studio provider" in stdout
    assert "--temperature TEMPERATURE" in stdout
    assert "Sampling temperature for provider completions" in stdout
    assert "--demo" in stdout


@pytest.mark.parametrize(
    "secret_flag",
    [
        "--api-key",
        "--api_key",
        "--key",
        "-k",
        "--token",
        "--gemini-api-key",
        "--google-ai-studio-api-key",
    ],
)
def test_cli_rejects_api_key_flag_exit_code_2(
    capsys: pytest.CaptureFixture[str], secret_flag: str
) -> None:
    """Forbidden credential flags exit code 2 with clean JSON stderr and no secret reflection."""
    secret_value = "AIzaSyFakeSecretKeyForTestingOnly12345"
    ret = run_cli_main([secret_flag, secret_value, "--symbol", "BTCUSDT"])
    assert ret == 2

    captured = capsys.readouterr()

    # Zero reflection of sensitive secret
    assert secret_value not in captured.err
    assert secret_value not in captured.out
    assert SECRET_PATTERN.search(captured.out) is None
    assert SECRET_PATTERN.search(captured.err) is None

    # Clean JSON on stderr
    err_json = json.loads(captured.err)
    assert err_json["error_code"] == "forbidden_cli_argument"
    assert "Passing API keys or credentials via CLI flags is forbidden" in err_json["message"]
    assert "Traceback" not in captured.err


def test_cli_missing_credentials_exit_code_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running with --provider google_ai_studio when no creds exist cleanly exits code 3."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_AI_STUDIO_API_KEY", raising=False)
    monkeypatch.setattr(
        "scripts.run_autonomous_cycle._REPO_ENV_PATH",
        tmp_path / ".env_nonexistent",
    )
    assert resolve_credential.__kwdefaults__ is not None
    monkeypatch.setitem(
        resolve_credential.__kwdefaults__,
        "repo_env_path",
        tmp_path / ".env_nonexistent",
    )

    cand = _build_candidate("cand-cli-init-001", stop_atr="0.5")
    cand_path = tmp_path / "cand-cli-init-001.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "cycle_output_missing_creds"
    args = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(ledger_db),
        "--candidate-path",
        str(cand_path),
        "--parquet-path",
        str(PARQUET_PATH),
        "--output-dir",
        str(output_dir),
        "--provider",
        "google_ai_studio",
    ]

    ret = run_cli_main(args)
    assert ret == 3

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    assert SECRET_PATTERN.search(captured.out) is None
    assert SECRET_PATTERN.search(captured.err) is None

    out_data = json.loads(captured.out)
    assert out_data["error_code"] == "missing_credentials"
    assert (
        out_data["message"]
        == "No Google AI Studio / Gemini credential found in environment or .env."
    )


def test_cli_end_to_end_google_ai_studio_mocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Full CLI run with --provider google_ai_studio using mocked Gemma 4 HTTP responses."""
    mock_secret = "AIzaSyFakeSecretKeyForTestingOnly12345"
    monkeypatch.setenv("GOOGLE_API_KEY", mock_secret)

    cand = _build_candidate("cand-cli-init-001", stop_atr="0.5")
    cand_path = tmp_path / "cand-cli-init-001.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "cycle_output_gemma"

    captured_requests: list[httpx.Request] = []
    call_idx = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        call_idx += 1
        captured_requests.append(request)

        if call_idx == 1:
            critic_payload = {
                "review_id": "review-cand-cli-init-001",
                "research_run_id": "run-critic-cycle-cli-gemma-001",
                "candidate_id": "cand-cli-init-001",
                "decision": "revise",
                "failure_reason_codes": [
                    "paper_net_pnl_below_threshold",
                    "paper_profit_factor_below_threshold",
                    "paper_trades_below_threshold",
                    "paper_win_rate_below_threshold",
                ],
                "revision_actions": [
                    "adjust_stop_multiplier",
                    "adjust_take_profit_multiplier",
                ],
            }
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(critic_payload)},
                        }
                    ]
                },
            )

        if call_idx == 2:
            creator_payload = {
                "proposal_id": "proposal-btcusdt-revised-001",
                "research_run_id": "run-creator-cycle-cli-gemma-001",
                "hypothesis": "Momentum revision based on Gemma 4 recommendations",
                "expected_regime": "trending",
                "novelty_reason": "Critique incorporated on real historical bars",
                "strategy": {
                    "dsl_version": 2,
                    "strategy_id": "cand-btcusdt-revised-001",
                    "family": "experimental",
                    "universe": {
                        "symbols": ["BTCUSDT"],
                        "timeframe": "5m",
                        "regime_context_timeframe": "15m",
                    },
                    "features": [{"name": "returns", "lookback": 3, "shift": 1}],
                    "entry": {"long": "returns > 0.001", "short": "returns < -0.001"},
                    "exit": {"long": "returns < 0.0", "short": "returns > 0.0"},
                    "vetoes": ["testing_only_no_promotion"],
                    "risk": {
                        "position_fraction": 0.10,
                        "stop_atr_multiplier": 2.0,
                        "take_profit_atr_multiplier": 3.0,
                        "trailing_atr_multiplier": 1.0,
                    },
                },
            }
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(creator_payload)},
                        }
                    ]
                },
            )

        return httpx.Response(500, text="Unexpected call index")

    orig_client_cls = httpx.Client
    monkeypatch.setattr(
        "scripts.run_autonomous_cycle.httpx.Client",
        lambda *a, **kw: orig_client_cls(transport=httpx.MockTransport(mock_handler)),
    )

    args = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(ledger_db),
        "--parquet-path",
        str(PARQUET_PATH),
        "--output-dir",
        str(output_dir),
        "--candidate-path",
        str(cand_path),
        "--cycle-id",
        "cycle-cli-gemma-001",
        "--windows-count",
        "1",
        "--min-windows",
        "1",
        "--min-profit-factor",
        "0.10",
        "--min-trades",
        "10",
        "--max-drawdown-pct",
        "50.0",
        "--min-average-return-pct",
        "-10.0",
        "--now",
        "2026-08-06T06:00:00Z",
        "--provider",
        "google_ai_studio",
        "--model",
        "gemma-4-31b-it",
        "--temperature",
        "0.2",
    ]

    ret = run_cli_main(args)
    assert ret == 0

    captured = capsys.readouterr()
    assert SECRET_PATTERN.search(captured.out) is None
    assert SECRET_PATTERN.search(captured.err) is None
    assert mock_secret not in captured.out
    assert mock_secret not in captured.err

    assert len(captured_requests) == 2
    assert captured_requests[0].headers["authorization"] == f"Bearer {mock_secret}"
    assert captured_requests[1].headers["authorization"] == f"Bearer {mock_secret}"

    result_file = output_dir / "autonomous-cycle-result.json"
    audit_file = output_dir / "cycle-audit.json"
    assert result_file.exists()
    assert audit_file.exists()

    result_raw = result_file.read_text(encoding="utf-8")
    audit_raw = audit_file.read_text(encoding="utf-8")

    # Zero credential leakage check
    assert SECRET_PATTERN.search(result_raw) is None
    assert SECRET_PATTERN.search(audit_raw) is None
    assert mock_secret not in result_raw
    assert mock_secret not in audit_raw

    result_data = json.loads(result_raw)
    assert result_data["cycle_status"] == "completed_admitted"
    assert result_data["qualification_decision"] == "qualified"
    assert result_data["admission_decision"] == "admitted"
    assert result_data["provider"] == "google_ai_studio"
    assert result_data["model"] == "gemma-4-31b-it"
    assert result_data["call_status"] == "success"
    assert result_data["latency_ms"] > 0.0

    audit_data = json.loads(audit_raw)
    assert audit_data["telemetry"]["provider"] == "google_ai_studio"
    assert audit_data["telemetry"]["model"] == "gemma-4-31b-it"
    assert audit_data["telemetry"]["call_status"] == "success"
    assert audit_data["telemetry"]["latency_ms"] > 0.0
    assert audit_data["safety_invariants"]["data_source"] == "cached_only"
    assert audit_data["safety_invariants"]["execution_authority"] is False


def test_cli_provider_api_error_exit_code_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Upstream 500 error exits code 3, logs failure in audit, and scrubs error text."""
    mock_secret = "AIzaSyMockUpstream500Key9876543210"
    monkeypatch.setenv("GOOGLE_API_KEY", mock_secret)

    cand = _build_candidate("cand-cli-init-001", stop_atr="0.5")
    cand_path = tmp_path / "cand-cli-init-001.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "cycle_output_500"

    def mock_500_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error: Gemini Cluster Overloaded")

    orig_client_cls = httpx.Client
    monkeypatch.setattr(
        "scripts.run_autonomous_cycle.httpx.Client",
        lambda *a, **kw: orig_client_cls(transport=httpx.MockTransport(mock_500_handler)),
    )

    args = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(ledger_db),
        "--parquet-path",
        str(PARQUET_PATH),
        "--output-dir",
        str(output_dir),
        "--candidate-path",
        str(cand_path),
        "--cycle-id",
        "cycle-cli-500-001",
        "--provider",
        "google_ai_studio",
    ]

    ret = run_cli_main(args)
    assert ret == 3

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert mock_secret not in captured.out
    assert mock_secret not in captured.err
    assert SECRET_PATTERN.search(captured.out) is None
    assert SECRET_PATTERN.search(captured.err) is None

    out_data = json.loads(captured.out)
    assert out_data["error_code"] == "provider_call_failed"
    assert "provider_http_error" in out_data["message"]

    result_file = output_dir / "autonomous-cycle-result.json"
    audit_file = output_dir / "cycle-audit.json"
    assert result_file.exists()
    assert audit_file.exists()

    result_raw = result_file.read_text(encoding="utf-8")
    audit_raw = audit_file.read_text(encoding="utf-8")
    assert SECRET_PATTERN.search(result_raw) is None
    assert SECRET_PATTERN.search(audit_raw) is None
    assert mock_secret not in result_raw
    assert mock_secret not in audit_raw

    audit_data = json.loads(audit_raw)
    assert audit_data["cycle_status"] == "failed"
    assert audit_data["telemetry"]["call_status"] == "failed"
    assert "provider_http_error" in audit_data["lineage"]["stop_reasons"]

    result_data = json.loads(result_file.read_text(encoding="utf-8"))
    assert result_data["cycle_status"] == "failed"
    assert "provider_http_error" in result_data["stop_reasons"]
