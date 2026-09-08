"""Adversarial stress-test suite for Milestone 3 (Google AI Studio Provider & Budget Governance).

Empirically challenges:
1. Credential Isolation & Precedence:
   - Priority order: GOOGLE_API_KEY > GEMINI_API_KEY > GOOGLE_AI_STUDIO_API_KEY > .env
   - Host isolation: never accesses ~/.gemini/oauth_creds.json, Path.home() / .env, etc.
   - MissingCredentialsError raised cleanly when no credentials exist.
2. Exit Code 3 Cleanliness:
   - CLI invocation with --provider google_ai_studio without credentials exits code 3.
   - Stdout is valid JSON with "missing_credentials" error_code.
   - Stdout and Stderr contain zero traceback.
3. Secret Scrubbing & Memory Leakage:
   - Forbidden CLI flags (--api-key, --key, etc.) exit code 2 and never echo the secret.
   - API key local variable deletion.
   - Artifact scanning (cycle-audit.json, autonomous-cycle-result.json) with strict regexes.
4. Bounded Transport Call Governor:
   - Hard budget ceiling of max 1 call per transport.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

# Ensure repo root and src are on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

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
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.qualification_artifacts import QualificationGateResult
from autonomous_futures.research.google_ai_studio_provider import (
    MissingCredentialsError,
    resolve_credential,
)
from scripts.run_autonomous_cycle import (
    BoundedTransportCallGovernor,
    _SECRET_PATTERN,
    _check_forbidden_credential_flags,
    main as run_cli_main,
)

PARQUET_PATH = _REPO_ROOT / "research/immutable-data/5m/canonical/BTCUSDT-5m.parquet"
BUNDLE_HASH = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
REGISTRY_HASH = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


# ============================================================================
# Helper fixtures & builders
# ============================================================================


def _build_candidate(
    cand_id: str,
    stop_atr: str = "0.5",
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


def _init_failing_test_ledger(
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


def _build_failing_feedback(cand: CreatorCandidateArtifact) -> CreatorQualificationFailureFeedback:
    return CreatorQualificationFailureFeedback(
        candidate_id=cand.candidate_id,
        candidate_artifact_hash=cand.artifact_hash,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        qualification_policy_id="paper-policy-cli-001",
        qualification_hash="a" * 64,
        failure_reason_codes=("paper_net_pnl_below_threshold",),
        failed_gates=(
            QualificationGateResult(
                gate_id="gate-paper-net-pnl",
                passed=False,
                reason_code="paper_net_pnl_below_threshold",
                observed=Decimal("-10.1"),
                threshold=Decimal("0.0"),
                comparator="gte",
            ),
        ),
        generated_at=NOW,
    )


# ============================================================================
# Challenge 1: Credential Isolation & Precedence
# ============================================================================


def test_credential_precedence_all_env_vars(tmp_path: Path) -> None:
    """GOOGLE_API_KEY beats GEMINI_API_KEY beats GOOGLE_AI_STUDIO_API_KEY in env."""
    mock_env = {
        "GOOGLE_API_KEY": "key_google",
        "GEMINI_API_KEY": "key_gemini",
        "GOOGLE_AI_STUDIO_API_KEY": "key_ai_studio",
    }
    assert resolve_credential(env=mock_env, repo_env_path=tmp_path / ".env") == "key_google"

    del mock_env["GOOGLE_API_KEY"]
    assert resolve_credential(env=mock_env, repo_env_path=tmp_path / ".env") == "key_gemini"

    del mock_env["GEMINI_API_KEY"]
    assert resolve_credential(env=mock_env, repo_env_path=tmp_path / ".env") == "key_ai_studio"


def test_credential_precedence_env_beats_dotenv(tmp_path: Path) -> None:
    """Any env var beats any .env var, even lowest priority env vs highest priority .env."""
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "GOOGLE_API_KEY=dotenv_google\n"
        "GEMINI_API_KEY=dotenv_gemini\n"
        "GOOGLE_AI_STUDIO_API_KEY=dotenv_studio\n",
        encoding="utf-8",
    )
    # Lowest priority env var beats highest priority .env var
    mock_env = {"GOOGLE_AI_STUDIO_API_KEY": "env_studio"}
    assert resolve_credential(env=mock_env, repo_env_path=dotenv) == "env_studio"

    # Empty env falls back to .env priority order
    empty_env: dict[str, str] = {}
    assert resolve_credential(env=empty_env, repo_env_path=dotenv) == "dotenv_google"

    dotenv.write_text(
        "GEMINI_API_KEY=dotenv_gemini\nGOOGLE_AI_STUDIO_API_KEY=dotenv_studio\n",
        encoding="utf-8",
    )
    assert resolve_credential(env=empty_env, repo_env_path=dotenv) == "dotenv_gemini"

    dotenv.write_text("GOOGLE_AI_STUDIO_API_KEY=dotenv_studio\n", encoding="utf-8")
    assert resolve_credential(env=empty_env, repo_env_path=dotenv) == "dotenv_studio"


def test_credential_dotenv_edge_cases_and_whitespace(tmp_path: Path) -> None:
    """Whitespace-only and commented values in env or .env are ignored."""
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# Comment line\n"
        'export GOOGLE_API_KEY="   "\n'
        "GEMINI_API_KEY='quoted_gemini_key'\n"
        "export GOOGLE_AI_STUDIO_API_KEY=studio_key # trailing comment\n",
        encoding="utf-8",
    )
    mock_env = {"GOOGLE_API_KEY": "   "}
    # Blank env var should be skipped, falling back to valid .env
    assert resolve_credential(env=mock_env, repo_env_path=dotenv) == "quoted_gemini_key"


def test_credential_host_isolation_never_touches_home_or_gemini(
    monkeypatch, tmp_path: Path
) -> None:
    """resolve_credential raises MissingCredentialsError and NEVER touches ~/.gemini/oauth_creds.json or Path.home()."""
    # 1. Instrument Path.home to detect any unauthorized access
    home_accessed = False
    original_home = Path.home

    def intercepted_home():
        nonlocal home_accessed
        home_accessed = True
        return tmp_path / "fake_home"

    monkeypatch.setattr(Path, "home", staticmethod(intercepted_home))

    # 2. Plant fake credential files in fake_home to prove they are never touched
    fake_gemini_dir = tmp_path / "fake_home" / ".gemini"
    fake_gemini_dir.mkdir(parents=True, exist_ok=True)
    fake_oauth = fake_gemini_dir / "oauth_creds.json"
    fake_oauth.write_text('{"token": "LEAKED_HOST_OAUTH_TOKEN"}', encoding="utf-8")

    fake_home_env = tmp_path / "fake_home" / ".env"
    fake_home_env.write_text("GOOGLE_API_KEY=LEAKED_HOME_ENV_KEY", encoding="utf-8")

    # 3. Call resolve_credential with empty env and nonexistent repo .env
    with pytest.raises(MissingCredentialsError) as exc_info:
        resolve_credential(env={}, repo_env_path=tmp_path / "nonexistent.env")

    assert "No Google AI Studio / Gemini credential found in environment or .env." in str(
        exc_info.value
    )
    assert not home_accessed, "Security Invariant Violated: Path.home() was accessed!"
    assert fake_oauth.read_text(encoding="utf-8") == '{"token": "LEAKED_HOST_OAUTH_TOKEN"}'


# ============================================================================
# Challenge 2: Exit Code 3 Cleanliness
# ============================================================================


def test_cli_exit_code_3_when_no_credentials_in_process(tmp_path: Path) -> None:
    """CLI exits with code 3, valid stdout JSON, and zero tracebacks when no credentials exist (in-process)."""
    cand = _build_candidate("cand-cli-m3-001")
    cand_path = tmp_path / "cand.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_failing_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "out"

    # Temporarily clean environment of any Google/Gemini keys
    clean_env = {k: v for k, v in os.environ.items() if "GOOGLE" not in k and "GEMINI" not in k}

    # Run CLI in-process
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
        "--provider",
        "google_ai_studio",
        "--now",
        "2026-08-06T06:00:00Z",
    ]

    import io
    from contextlib import redirect_stdout, redirect_stderr

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    original_environ = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(clean_env)
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            ret = run_cli_main(args)
    finally:
        os.environ.clear()
        os.environ.update(original_environ)

    out_str = stdout_buf.getvalue()
    err_str = stderr_buf.getvalue()

    assert ret == 3, f"Expected exit code 3, got {ret}"
    assert "Traceback (most recent call last):" not in out_str
    assert "Traceback (most recent call last):" not in err_str

    parsed_stdout = json.loads(out_str)
    assert parsed_stdout["error_code"] == "missing_credentials"
    assert (
        parsed_stdout["message"]
        == "No Google AI Studio / Gemini credential found in environment or .env."
    )


def test_cli_exit_code_3_subprocess_boundary(tmp_path: Path) -> None:
    """CLI exits with code 3, valid stdout JSON, and zero tracebacks at OS process boundary."""
    cand = _build_candidate("cand-cli-m3-002")
    cand_path = tmp_path / "cand.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_failing_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "out_sub"

    # Strict clean environment for subprocess
    sub_env = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": f"{_REPO_ROOT};{_REPO_ROOT / 'src'}",
    }

    cmd = [
        sys.executable,
        str(_REPO_ROOT / "scripts/run_autonomous_cycle.py"),
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
        "--provider",
        "google_ai_studio",
        "--now",
        "2026-08-06T06:00:00Z",
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(tmp_path),  # run in isolated tmp_path without any .env file
        env=sub_env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 3, (
        f"Expected returncode 3, got {proc.returncode}. Stderr: {proc.stderr}"
    )
    assert "Traceback (most recent call last):" not in proc.stdout
    assert "Traceback (most recent call last):" not in proc.stderr

    parsed = json.loads(proc.stdout)
    assert parsed["error_code"] == "missing_credentials"
    assert (
        parsed["message"] == "No Google AI Studio / Gemini credential found in environment or .env."
    )


# ============================================================================
# Challenge 3: Secret Scrubbing & Memory Leakage
# ============================================================================


def test_forbidden_credential_flags_exit_code_2_and_no_leakage() -> None:
    """All forbidden credential flags exit with code 2 and never echo the secret token."""
    secret_token = "AIzaSySecretTokenShouldNeverBePrinted9999"
    forbidden_variants = [
        ["--api-key", secret_token],
        [f"--api-key={secret_token}"],
        ["--api_key", secret_token],
        ["--key", secret_token],
        ["-key", secret_token],
        ["--apikey", secret_token],
        ["--google-api-key", secret_token],
        ["--google_api_key", secret_token],
        ["--gemini-api-key", secret_token],
        ["--gemini_api_key", secret_token],
        ["--google-ai-studio-api-key", secret_token],
        ["--token", secret_token],
        ["--api-token", secret_token],
        ["-k", secret_token],
    ]

    for variant in forbidden_variants:
        assert _check_forbidden_credential_flags(variant) is True

        proc = subprocess.run(
            [sys.executable, str(_REPO_ROOT / "scripts/run_autonomous_cycle.py"), *variant],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2, f"Failed on {variant}: got code {proc.returncode}"
        assert secret_token not in proc.stdout, f"Secret leaked in stdout for {variant}!"
        assert secret_token not in proc.stderr, f"Secret leaked in stderr for {variant}!"
        err_json = json.loads(proc.stderr)
        assert err_json["error_code"] == "forbidden_cli_argument"


def test_artifact_secret_scanning(tmp_path: Path) -> None:
    """Scan generated JSON artifacts (cycle-audit.json, autonomous-cycle-result.json) for secrets."""
    cand = _build_candidate("cand-cli-scan-001")
    cand_path = tmp_path / "cand.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_failing_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "out_artifacts"

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
        "cycle-cli-scan-001",
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
    assert result_file.is_file()
    assert audit_file.is_file()

    result_text = result_file.read_text(encoding="utf-8")
    audit_text = audit_file.read_text(encoding="utf-8")

    for name, content in [
        ("autonomous-cycle-result.json", result_text),
        ("cycle-audit.json", audit_text),
    ]:
        assert not _SECRET_PATTERN.search(content), f"Secret detected in {name}!"
        assert (
            "api_key" not in content.lower() or "forbidden_credential_flags" in content.lower()
        ), f"Potential secret key in {name}"
        assert "password" not in content.lower(), f"Potential password in {name}"
        assert "bearer " not in content.lower(), f"Bearer token in {name}"


# ============================================================================
# Challenge 4: Budget Governance (BoundedTransportCallGovernor)
# ============================================================================


def test_bounded_transport_governor_enforces_max_calls() -> None:
    """BoundedTransportCallGovernor strictly blocks more than max_calls."""
    mock_calls = 0

    def mock_transport(req: Any) -> dict[str, object]:
        nonlocal mock_calls
        mock_calls += 1
        return {"status": "ok"}

    governor = BoundedTransportCallGovernor(mock_transport, max_calls=1, name="critic")
    res = governor("call_1")
    assert res == {"status": "ok"}
    assert governor.call_count == 1

    with pytest.raises(RuntimeError) as exc_info:
        governor("call_2")

    assert "Budget ceiling breach: critic exceeded limit of 1" in str(exc_info.value)
    assert mock_calls == 1, "Underlying transport was called after breach!"


# ============================================================================
# Challenge 5: In-Depth Secret Scrubbing & Provider Lifecycle Verification
# ============================================================================


def _make_mock_handler():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        content_str = request.content.decode("utf-8", errors="ignore")
        req_json = json.loads(content_str)
        msgs = req_json.get("messages", [])
        user_msg = msgs[1]["content"] if len(msgs) > 1 else ""

        if "research_run_id=" in user_msg and "failure_feedback=" in user_msg:
            # Critic review prompt
            m_run = re.search(r"research_run_id=([^;]+);", user_msg)
            m_cand = re.search(r"candidate_id=([^;]+);", user_msg)
            m_fb = re.search(r"failure_feedback=({.*})\.\s*Produce", user_msg)
            run_id = m_run.group(1) if m_run else "run-critic-001"
            cand_id = m_cand.group(1) if m_cand else "cand-001"
            reasons = ["paper_net_pnl_below_threshold"]
            if m_fb:
                try:
                    fb_dict = json.loads(m_fb.group(1))
                    reasons = sorted(fb_dict.get("failure_reason_codes", reasons))
                except Exception:
                    pass
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "review_id": f"review-{cand_id}",
                                        "research_run_id": run_id,
                                        "candidate_id": cand_id,
                                        "decision": "revise",
                                        "failure_reason_codes": reasons,
                                        "revision_actions": ["adjust_stop_multiplier"],
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        else:
            # Creator proposal prompt
            m_run = re.search(r"research_run_id=([^;\s]+)", user_msg)
            run_id = m_run.group(1) if m_run else "run-creator-001"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "proposal_id": "proposal-btcusdt-revised-telemetry-001",
                                        "research_run_id": run_id,
                                        "hypothesis": "Adjusted stop multiplier",
                                        "expected_regime": "trending",
                                        "novelty_reason": "Critic feedback applied",
                                        "strategy": {
                                            "dsl_version": 2,
                                            "strategy_id": "cand-btcusdt-revised-telemetry-001",
                                            "family": "experimental",
                                            "universe": {
                                                "symbols": ["BTCUSDT"],
                                                "timeframe": "5m",
                                                "regime_context_timeframe": "15m",
                                            },
                                            "features": [
                                                {"name": "returns", "lookback": 3, "shift": 1}
                                            ],
                                            "entry": {
                                                "long": "returns > 0.001",
                                                "short": "returns < -0.001",
                                            },
                                            "exit": {
                                                "long": "returns < 0.0",
                                                "short": "returns > 0.0",
                                            },
                                            "vetoes": ["testing_only_no_promotion"],
                                            "risk": {
                                                "position_fraction": 0.10,
                                                "stop_atr_multiplier": 2.0,
                                                "take_profit_atr_multiplier": 3.0,
                                                "trailing_atr_multiplier": 1.0,
                                            },
                                        },
                                    }
                                )
                            }
                        }
                    ]
                },
            )

    return mock_handler


def test_local_scope_api_key_scrubbed_empirically(monkeypatch, tmp_path: Path) -> None:
    """Verify that 'api_key' is deleted from run_autonomous_cycle's local variables."""
    captured_locals: dict[str, Any] = {}

    from autonomous_futures.pipeline import autonomous_cycle as ac_mod

    original_exec = ac_mod.execute_autonomous_cycle

    def intercepted_exec(*args: Any, **kwargs: Any) -> Any:
        # Inspect caller frame (run_autonomous_cycle)
        frame = sys._getframe(1)
        captured_locals.update(frame.f_locals)
        return original_exec(*args, **kwargs)

    monkeypatch.setattr(ac_mod, "execute_autonomous_cycle", intercepted_exec)

    cand = _build_candidate("cand-cli-scrub-001")
    cand_path = tmp_path / "cand.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_failing_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "out_scrub"
    test_key = "AIzaSyTestMemoryKeyScrubVerification999"
    monkeypatch.setenv("GOOGLE_API_KEY", test_key)

    import httpx

    original_httpx_client = httpx.Client

    def mock_client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(_make_mock_handler())
        return original_httpx_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", mock_client_factory)

    cli_args = [
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
        "cycle-scrub-001",
        "--provider",
        "google_ai_studio",
        "--model",
        "gemma-4-31b-it",
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

    ret = run_cli_main(cli_args)
    assert ret == 0, f"Expected returncode 0, got {ret}"

    # Empirical assertion: api_key is NOT present in local variables
    assert "api_key" not in captured_locals, (
        "Secret Leak: 'api_key' was found in run_autonomous_cycle locals!"
    )


def test_provider_full_cycle_telemetry_and_secret_hygiene(monkeypatch, tmp_path: Path) -> None:
    """Verify that provider telemetry is recorded and the API key is completely absent from all disk artifacts."""
    cand = _build_candidate("cand-cli-telemetry-001")
    cand_path = tmp_path / "cand.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_failing_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "out_telemetry"
    secret_api_key = "AIzaSySuperSecretKeyForTelemetryTest456"
    monkeypatch.setenv("GOOGLE_API_KEY", secret_api_key)

    import httpx

    recorded_auth_headers: list[str] = []
    base_handler = _make_mock_handler()

    def mock_handler_with_auth_recording(request: httpx.Request) -> httpx.Response:
        auth_hdr = request.headers.get("Authorization", "")
        recorded_auth_headers.append(auth_hdr)
        return base_handler(request)

    original_httpx_client = httpx.Client

    def mock_client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(mock_handler_with_auth_recording)
        return original_httpx_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", mock_client_factory)

    cli_args = [
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
        "cycle-telemetry-001",
        "--provider",
        "google_ai_studio",
        "--model",
        "gemma-4-26b-a4b-it",
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

    ret = run_cli_main(cli_args)
    assert ret == 0

    # Verify authorization headers were properly formed in flight
    assert len(recorded_auth_headers) == 2, (
        f"Expected 2 HTTP calls (critic, creator), got {len(recorded_auth_headers)}"
    )
    for hdr in recorded_auth_headers:
        assert hdr == f"Bearer {secret_api_key}"

    # Verify telemetry in cycle result artifact
    result_path = output_dir / "autonomous-cycle-result.json"
    audit_path = output_dir / "cycle-audit.json"
    assert result_path.is_file()
    assert audit_path.is_file()

    result_json = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_json["provider"] == "google_ai_studio"
    assert result_json["model"] == "gemma-4-26b-a4b-it"
    assert result_json["call_status"] == "success"
    assert result_json["latency_ms"] >= 0.0

    audit_json = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_json["telemetry"]["provider"] == "google_ai_studio"
    assert audit_json["telemetry"]["model"] == "gemma-4-26b-a4b-it"
    assert audit_json["telemetry"]["call_status"] == "success"

    # Exhaustive secret scan across all files in output directory
    for f in output_dir.rglob("*"):
        if f.is_file():
            text = f.read_text(encoding="utf-8", errors="ignore")
            assert secret_api_key not in text, (
                f"CRITICAL: Secret API key leaked into disk artifact {f.name}!"
            )
            assert "AIza" not in text, f"CRITICAL: AIza pattern leaked into {f.name}!"


def test_provider_http_401_scrubs_secret_and_exits_code_3(monkeypatch, tmp_path: Path) -> None:
    """HTTP 401 error containing secret token is sanitized, exits code 3, zero traceback."""
    cand = _build_candidate("cand-cli-err-001")
    cand_path = tmp_path / "cand.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = tmp_path / "ledger.sqlite3"
    _init_failing_test_ledger(ledger_db, cand)

    output_dir = tmp_path / "out_err401"
    secret_key = "AIzaSyLeakedSecretInErrorBody12345"
    monkeypatch.setenv("GOOGLE_API_KEY", secret_key)

    import httpx

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "code": 401,
                    "message": f"API key {secret_key} is invalid.",
                    "status": "UNAUTHENTICATED",
                }
            },
        )

    original_httpx_client = httpx.Client

    def mock_client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        return original_httpx_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", mock_client_factory)

    import io
    from contextlib import redirect_stdout, redirect_stderr

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    cli_args = [
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
        "--provider",
        "google_ai_studio",
        "--now",
        "2026-08-06T06:00:00Z",
    ]

    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        ret = run_cli_main(cli_args)

    out = stdout_buf.getvalue()
    err = stderr_buf.getvalue()

    assert ret == 3, f"Expected exit code 3, got {ret}"
    assert "Traceback (most recent call last):" not in out
    assert "Traceback (most recent call last):" not in err
    assert secret_key not in out, "Secret key leaked into stdout!"
    assert secret_key not in err, "Secret key leaked into stderr!"

    parsed = json.loads(out)
    assert parsed["error_code"] == "provider_call_failed"


def test_unauthorized_model_rejected_with_exit_code_2() -> None:
    """Passing an unapproved model (e.g. gemini-1.5-pro) is rejected with exit code 2."""
    proc = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "scripts/run_autonomous_cycle.py"),
            "--symbol",
            "BTCUSDT",
            "--provider",
            "google_ai_studio",
            "--model",
            "gemini-1.5-pro",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "invalid choice: 'gemini-1.5-pro'" in proc.stderr
