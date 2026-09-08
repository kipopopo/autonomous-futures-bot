"""Unit tests for Google AI Studio cycle integration, CLI validation, and safety invariants."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pandas as pd
import pytest

# Ensure repository root is on sys.path for scripts import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.pipeline.autonomous_cycle import (  # noqa: E402
    AutonomousCycleConfig,
    autonomous_cycle_content_hash,
    execute_autonomous_cycle,
)
from autonomous_futures.research.cached_evaluation import (  # noqa: E402
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)
from autonomous_futures.research.creator_failure_feedback import (  # noqa: E402
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.creator_generator import (  # noqa: E402
    CreatorGenerationRequest,
    CreatorGenerator,
)
from autonomous_futures.research.creator_prompts import (  # noqa: E402
    build_creator_proposal_messages,
)
from autonomous_futures.research.google_ai_studio_provider import (  # noqa: E402
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    GoogleAIStudioJsonClient,
    GoogleAIStudioProposalTransport,
    GoogleAIStudioProviderConfig,
    MissingCredentialsError,
    ProviderTransportError,
    resolve_credential,
)
from autonomous_futures.research.learner_critic import (  # noqa: E402
    LearnerCritic,
    LearnerCriticRequest,
)
from autonomous_futures.research.learner_critic_provider import (  # noqa: E402
    GoogleAIStudioCriticTransport,
    GoogleAIStudioLearnerCriticTransport,
    build_learner_critic_messages,
)
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    QualificationGateResult,
    WalkForwardQualificationPolicy,
)
from autonomous_futures.research.trade_simulation import (  # noqa: E402
    EquityPoint,
    SimulatedTrade,
    TradeSimulationResult,
)
from scripts.run_autonomous_cycle import (  # noqa: E402
    FORBIDDEN_CREDENTIAL_FLAGS,
    BoundedTransportCallGovernor,
    _check_forbidden_credential_flags,
    _sanitize_error_text,
    _validate_temperature,
    build_cycle_audit,
    build_parser,
)
from scripts.run_autonomous_cycle import (  # noqa: E402
    main as run_cli_main,
)

MOCK_BUNDLE_HASH = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
MOCK_REGISTRY_HASH = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"
MOCK_TIMESTAMP = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _mock_fast_simulator(
    candidate: CreatorCandidateArtifact,
    frame: pd.DataFrame,
    window: CachedEvaluationWindow,
) -> TradeSimulationResult:
    ts = window.spec.time_start + timedelta(minutes=15)
    trade1 = SimulatedTrade(
        trade_id="trade-win-001",
        symbol=window.spec.symbol,
        side="LONG",
        entry_timestamp=ts,
        exit_timestamp=ts + timedelta(minutes=5),
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        entry_notional=Decimal("100"),
        exit_notional=Decimal("110"),
        entry_fee=Decimal("0.05"),
        exit_fee=Decimal("0.05"),
        fees=Decimal("0.10"),
        slippage_cost=Decimal("0.02"),
        gross_pnl=Decimal("10.00"),
        net_pnl=Decimal("9.90"),
        exit_reason="take_profit",
    )
    trade2 = SimulatedTrade(
        trade_id="trade-loss-001",
        symbol=window.spec.symbol,
        side="LONG",
        entry_timestamp=ts + timedelta(minutes=6),
        exit_timestamp=ts + timedelta(minutes=10),
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("95"),
        entry_notional=Decimal("100"),
        exit_notional=Decimal("95"),
        entry_fee=Decimal("0.05"),
        exit_fee=Decimal("0.05"),
        fees=Decimal("0.10"),
        slippage_cost=Decimal("0.02"),
        gross_pnl=Decimal("-5.00"),
        net_pnl=Decimal("-5.10"),
        exit_reason="stop_loss",
    )
    return TradeSimulationResult(
        symbol=window.spec.symbol,
        starting_equity=Decimal("100.00"),
        final_equity=Decimal("104.80"),
        total_fees=Decimal("0.20"),
        total_slippage_cost=Decimal("0.04"),
        trades=(trade1, trade2),
        equity_curve=(
            EquityPoint(timestamp=ts, equity=Decimal("100.00")),
            EquityPoint(timestamp=ts + timedelta(minutes=10), equity=Decimal("104.80")),
        ),
    )


def _make_mock_window(symbol: str = "BTCUSDT", n_bars: int = 20) -> CachedEvaluationWindow:
    timestamps = pd.date_range(datetime(2026, 8, 1, 0, 0, tzinfo=UTC), periods=n_bars, freq="5min")
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0] * n_bars,
            "high": [105.0] * n_bars,
            "low": [95.0] * n_bars,
            "close": [101.0] * n_bars,
            "volume": [1000.0] * n_bars,
        }
    )
    spec = CachedEvaluationWindowSpec(
        window_id="window-mock-001",
        symbol=symbol,
        bundle_hash=MOCK_BUNDLE_HASH,
        dataset_registry_hash=MOCK_REGISTRY_HASH,
        time_start=timestamps[0].to_pydatetime(),
        time_end=timestamps[-1].to_pydatetime() + timedelta(minutes=5),
    )
    return CachedEvaluationWindow(spec=spec, frame=df)


def _make_candidate(cand_id: str = "cand-001", symbol: str = "BTCUSDT") -> CreatorCandidateArtifact:
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
            stop_atr_multiplier=Decimal("1.0"),
            take_profit_atr_multiplier=Decimal("2.0"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=cand_id,
        strategy=strategy,
        bundle_hash=MOCK_BUNDLE_HASH,
        dataset_registry_hash=MOCK_REGISTRY_HASH,
        creator_run_id="run-creator-test",
        research_seed=42,
        created_at=MOCK_TIMESTAMP - timedelta(days=1),
    )


def _make_feedback(
    cand_id: str = "cand-001", symbol: str = "BTCUSDT"
) -> CreatorQualificationFailureFeedback:
    return CreatorQualificationFailureFeedback.model_validate(
        {
            "candidate_id": cand_id,
            "candidate_artifact_hash": "a" * 64,
            "bundle_hash": MOCK_BUNDLE_HASH,
            "dataset_registry_hash": MOCK_REGISTRY_HASH,
            "qualification_hash": "d" * 64,
            "qualification_policy_id": "policy-creator-001",
            "failed_gates": [
                {
                    "gate_id": "oos_profit_factor_min",
                    "passed": False,
                    "observed": "0.5",
                    "threshold": "1.0",
                    "comparator": "gte",
                    "reason_code": "oos_profit_factor_below_threshold",
                }
            ],
            "failure_reason_codes": ["oos_profit_factor_below_threshold"],
        }
    )


def _make_cycle_config(artifact_root: Path, symbol: str = "BTCUSDT") -> AutonomousCycleConfig:
    policy = WalkForwardQualificationPolicy(
        policy_id="policy-test-001",
        minimum_windows=1,
        minimum_trades=1,
        minimum_profit_factor=Decimal("0.10"),
        maximum_drawdown_pct=Decimal("50.0"),
        minimum_average_return_pct=Decimal("-10.0"),
    )
    return AutonomousCycleConfig(
        cycle_id="cycle-test-001",
        symbol=symbol,
        bundle_hash=MOCK_BUNDLE_HASH,
        dataset_registry_hash=MOCK_REGISTRY_HASH,
        qualification_policy=policy,
        artifact_root=artifact_root,
        max_attempts=1,
        require_flat=False,
    )


def _make_mock_critic_transport(
    decision: str = "revise",
    fail_http: bool = False,
) -> GoogleAIStudioCriticTransport:
    critic_payload = {
        "review_id": "review-cand-001",
        "research_run_id": "run-critic-cycle-test-001",
        "candidate_id": "cand-001",
        "decision": decision,
        "failure_reason_codes": ["oos_profit_factor_below_threshold"],
        "revision_actions": ["adjust_stop_multiplier", "adjust_take_profit_multiplier"],
    }

    def handler(_: httpx.Request) -> httpx.Response:
        if fail_http:
            return httpx.Response(500, text="Internal Server Error")
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

    config = GoogleAIStudioProviderConfig(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="mock-key-valid",
        model_id="gemma-4-31b-it",
    )
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    json_client = GoogleAIStudioJsonClient(config, client=http_client)
    return GoogleAIStudioCriticTransport(
        client=json_client,
        system_prompt="system",
        user_prompt_builder=lambda _: "user",
    )


def _make_mock_creator_transport() -> GoogleAIStudioProposalTransport:
    creator_payload = {
        "proposal_id": "proposal-btcusdt-revised-001",
        "research_run_id": "run-creator-cycle-test-001",
        "hypothesis": "Hypothesis for testing",
        "expected_regime": "trending",
        "novelty_reason": "Novelty reason for testing",
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

    def handler(_: httpx.Request) -> httpx.Response:
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

    config = GoogleAIStudioProviderConfig(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="mock-key-valid",
        model_id="gemma-4-31b-it",
    )
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    json_client = GoogleAIStudioJsonClient(config, client=http_client)
    return GoogleAIStudioProposalTransport(
        client=json_client,
        system_prompt="system",
        user_prompt_builder=lambda _: "user",
    )


# ==============================================================================
# Category 1: CLI Parameter Parsing & Validation (Tests 1–7)
# ==============================================================================


def test_cli_provider_parameter_valid_choices() -> None:
    """Verify --provider accepts demo and google_ai_studio, defaulting to demo."""
    parser = build_parser()
    assert parser.parse_args(["--symbol", "BTCUSDT"]).provider == "demo"
    assert (
        parser.parse_args(["--symbol", "BTCUSDT", "--provider", "google_ai_studio"]).provider
        == "google_ai_studio"
    )
    assert parser.parse_args(["--symbol", "BTCUSDT", "--provider", "demo"]).provider == "demo"


def test_cli_provider_parameter_invalid_choices(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify invalid --provider options trigger immediate rejection with exit code 2."""
    parser = build_parser()
    for choice in ["openai", "anthropic", "google", "azure", "gemini", ""]:
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--symbol", "BTCUSDT", "--provider", choice])
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "invalid choice" in captured.err
        assert _SECRET_PATTERN.search(captured.out) is None
        assert _SECRET_PATTERN.search(captured.err) is None


def test_cli_model_parameter_valid_choices() -> None:
    """Verify --model accepts gemma-4-31b-it and gemma-4-26b-a4b-it, defaulting to 31b."""
    parser = build_parser()
    assert parser.parse_args(["--symbol", "BTCUSDT"]).model == "gemma-4-31b-it"
    assert (
        parser.parse_args(["--symbol", "BTCUSDT", "--model", "gemma-4-26b-a4b-it"]).model
        == "gemma-4-26b-a4b-it"
    )
    assert (
        parser.parse_args(["--symbol", "BTCUSDT", "--model", "gemma-4-31b-it"]).model
        == "gemma-4-31b-it"
    )


def test_cli_model_parameter_invalid_choices(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify unapproved model IDs are rejected with exit code 2."""
    parser = build_parser()
    for choice in ["gemini-1.5-pro", "gemma-2-9b", "gpt-4o", "gemma-4-31b", "gemma-4-8b", ""]:
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--symbol", "BTCUSDT", "--model", choice])
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "invalid choice" in captured.err
        assert _SECRET_PATTERN.search(captured.out) is None
        assert _SECRET_PATTERN.search(captured.err) is None


def test_cli_temperature_parameter_valid_boundaries() -> None:
    """Verify --temperature validates and preserves float boundaries within [0.0, 2.0]."""
    parser = build_parser()
    cases = [
        ("0.0", 0.0),
        ("2.0", 2.0),
        ("0.2", 0.2),
        ("0.5", 0.5),
        ("1.0", 1.0),
        ("0.0001", 0.0001),
        ("1.9999", 1.9999),
    ]
    for val_str, expected in cases:
        assert _validate_temperature(val_str) == expected
        args = parser.parse_args(["--symbol", "BTCUSDT", "--temperature", val_str])
        assert args.temperature == expected


def test_cli_temperature_parameter_invalid_values() -> None:
    """Verify non-float, non-finite, and out-of-range temperature inputs raise error."""
    invalid_cases = [
        "abc",
        "",
        "1.2.3",
        "None",
        "True",
        "-0.001",
        "-0.5",
        "-1.0",
        "-10.0",
        "2.001",
        "2.5",
        "3.0",
        "100.0",
        "nan",
        "NaN",
        "inf",
        "-inf",
        "+inf",
        "Infinity",
        "-Infinity",
    ]
    for invalid in invalid_cases:
        with pytest.raises(argparse.ArgumentTypeError):
            _validate_temperature(invalid)


def test_cli_forbidden_credential_flags_rejected_with_exit_code_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify all 13 forbidden credential flags are intercepted with code 2 and clean JSON."""
    secret_val = "AIzaSySuperSecretTokenForTestingOnly999"
    for flag in FORBIDDEN_CREDENTIAL_FLAGS:
        assert _check_forbidden_credential_flags([flag, secret_val]) is True
        assert _check_forbidden_credential_flags([f"{flag}={secret_val}"]) is True

        ret = run_cli_main([flag, secret_val, "--symbol", "BTCUSDT"])
        assert ret == 2

        captured = capsys.readouterr()
        assert secret_val not in captured.err
        assert secret_val not in captured.out
        assert _SECRET_PATTERN.search(captured.out) is None
        assert _SECRET_PATTERN.search(captured.err) is None
        assert "Traceback" not in captured.err

        err_json = json.loads(captured.err)
        assert err_json["error_code"] == "forbidden_cli_argument"
        assert "Passing API keys or credentials via CLI flags is forbidden" in err_json["message"]

        ret_eq = run_cli_main([f"{flag}={secret_val}", "--symbol", "BTCUSDT"])
        assert ret_eq == 2

        captured_eq = capsys.readouterr()
        assert secret_val not in captured_eq.err
        assert secret_val not in captured_eq.out
        assert _SECRET_PATTERN.search(captured_eq.out) is None
        assert _SECRET_PATTERN.search(captured_eq.err) is None
        assert "Traceback" not in captured_eq.err


# ==============================================================================
# Category 2: Credential Resolution Cascade & Isolation (Tests 8–11)
# ==============================================================================


def test_resolve_credential_precedence_env_variables() -> None:
    """Verify priority cascade among environment variables."""
    # Priority 1: GOOGLE_API_KEY
    res1 = resolve_credential(
        env={
            "GOOGLE_API_KEY": "key1",
            "GEMINI_API_KEY": "key2",
            "GOOGLE_AI_STUDIO_API_KEY": "key3",
        }
    )
    assert res1 == "key1"

    # Priority 2: GEMINI_API_KEY when GOOGLE_API_KEY missing
    res2 = resolve_credential(
        env={
            "GEMINI_API_KEY": "key2",
            "GOOGLE_AI_STUDIO_API_KEY": "key3",
        }
    )
    assert res2 == "key2"

    # Priority 3: GOOGLE_AI_STUDIO_API_KEY when earlier missing
    res3 = resolve_credential(
        env={
            "GOOGLE_AI_STUDIO_API_KEY": "key3",
        }
    )
    assert res3 == "key3"

    # Whitespace in higher priority is skipped
    res4 = resolve_credential(
        env={
            "GOOGLE_API_KEY": "   ",
            "GEMINI_API_KEY": "key2",
        }
    )
    assert res4 == "key2"


def test_resolve_credential_precedence_repo_dotenv(tmp_path: Path) -> None:
    """Verify resolution from repository .env following priority cascade."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # Leading comments
        export GOOGLE_API_KEY="file_k1"
        GEMINI_API_KEY='file_k2'
        GOOGLE_AI_STUDIO_API_KEY=file_k3
        """,
        encoding="utf-8",
    )
    assert resolve_credential(env={}, repo_env_path=env_file) == "file_k1"

    # Without GOOGLE_API_KEY
    env_file.write_text(
        """
        # Comments and blank lines

        export GEMINI_API_KEY="file_k2"
        GOOGLE_AI_STUDIO_API_KEY=file_k3
        """,
        encoding="utf-8",
    )
    assert resolve_credential(env={}, repo_env_path=env_file) == "file_k2"

    # Only GOOGLE_AI_STUDIO_API_KEY
    env_file.write_text("GOOGLE_AI_STUDIO_API_KEY='file_k3'\n", encoding="utf-8")
    assert resolve_credential(env={}, repo_env_path=env_file) == "file_k3"


def test_resolve_credential_env_overrides_repo_dotenv(tmp_path: Path) -> None:
    """Verify environment variable overrides any variable from repository .env."""
    env_file = tmp_path / ".env"
    env_file.write_text("GOOGLE_API_KEY=file_google_key\n", encoding="utf-8")

    # Even lowest priority env overrides highest file priority
    res = resolve_credential(
        env={"GOOGLE_AI_STUDIO_API_KEY": "env_studio_key"},
        repo_env_path=env_file,
    )
    assert res == "env_studio_key"


def test_resolve_credential_isolation_never_reads_host_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify resolve_credential never touches Path.home() or operator host directories."""
    monkeypatch.setattr(Path, "home", MagicMock(side_effect=RuntimeError("FORBIDDEN_HOST_ACCESS")))
    with pytest.raises(MissingCredentialsError) as exc_info:
        resolve_credential(env={}, repo_env_path=tmp_path / ".env_empty")
    assert _SECRET_PATTERN.search(str(exc_info.value)) is None


# ==============================================================================
# Category 3: Missing Credential Handling & Exit Code 3 (Tests 12–13)
# ==============================================================================


def test_resolve_credential_raises_missing_credentials_error(tmp_path: Path) -> None:
    """Verify MissingCredentialsError is raised with exact sanitized message."""
    with pytest.raises(MissingCredentialsError) as exc_info:
        resolve_credential(env={}, repo_env_path=tmp_path / ".env_nonexistent")
    assert (
        str(exc_info.value)
        == "No Google AI Studio / Gemini credential found in environment or .env."
    )
    assert str(tmp_path) not in str(exc_info.value)
    assert _SECRET_PATTERN.search(str(exc_info.value)) is None


def test_cli_main_missing_credentials_exits_code_3_with_clean_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify CLI terminates with exit code 3 and clean JSON when credentials missing."""
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

    fb = _make_feedback("cand-cli-init-001")
    fb_path = tmp_path / "feedback.json"
    fb_path.write_text(fb.model_dump_json(indent=2), encoding="utf-8")

    ret = run_cli_main(
        [
            "--symbol",
            "BTCUSDT",
            "--provider",
            "google_ai_studio",
            "--feedback-path",
            str(fb_path),
        ]
    )
    assert ret == 3

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    assert _SECRET_PATTERN.search(captured.out) is None
    assert _SECRET_PATTERN.search(captured.err) is None

    out_data = json.loads(captured.out)
    assert out_data["error_code"] == "missing_credentials"
    assert (
        out_data["message"]
        == "No Google AI Studio / Gemini credential found in environment or .env."
    )


# ==============================================================================
# Category 4: Canonical Prompt Formulation (Tests 14–17)
# ==============================================================================


def test_build_creator_proposal_messages_structure() -> None:
    """Verify build_creator_proposal_messages constructs canonical system and user messages."""
    req = CreatorGenerationRequest(
        research_run_id="run-creator-001",
        input_evidence_refs=("ref1", "ref2"),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )
    system, user = build_creator_proposal_messages(
        req, bundle_hash=MOCK_BUNDLE_HASH, symbol="BTCUSDT"
    )

    assert system["role"] == "system"
    assert user["role"] == "user"
    assert "dsl_version must be the integer 2" in system["content"]
    assert "features must use only" in system["content"]
    assert "position_fraction must be greater than 0 and at most 0.5" in system["content"]
    assert "research_run_id=run-creator-001" in user["content"]
    assert "symbol=BTCUSDT" in user["content"]
    assert f"bundle_hash={MOCK_BUNDLE_HASH}" in user["content"]
    assert "output_schema=creator-proposal-v1" in user["content"]


def test_build_creator_proposal_messages_validation_errors() -> None:
    """Verify bundle hash and symbol format validation."""
    req = CreatorGenerationRequest(
        research_run_id="run-001",
        input_evidence_refs=("ref1",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )
    with pytest.raises(ValueError, match="bundle_hash must be a lowercase SHA-256"):
        build_creator_proposal_messages(req, bundle_hash="invalid_hash", symbol="BTCUSDT")

    with pytest.raises(ValueError, match="bundle_hash must be a lowercase SHA-256"):
        build_creator_proposal_messages(req, bundle_hash="A" * 64, symbol="BTCUSDT")

    with pytest.raises(ValueError, match="symbol must be uppercase alphanumeric"):
        build_creator_proposal_messages(req, bundle_hash=MOCK_BUNDLE_HASH, symbol="btcusdt")

    with pytest.raises(ValueError, match="symbol must be uppercase alphanumeric"):
        build_creator_proposal_messages(req, bundle_hash=MOCK_BUNDLE_HASH, symbol="BTC-USDT")


def test_build_learner_critic_messages_structure() -> None:
    """Verify build_learner_critic_messages constructs system prompt and serialized feedback."""
    feedback = _make_feedback()
    req = LearnerCriticRequest(
        research_run_id="run-critic-001",
        candidate_id=feedback.candidate_id,
        candidate_artifact_hash=feedback.candidate_artifact_hash,
        feedback=feedback,
        input_evidence_refs=("ref1", "ref2"),
        output_schema_id="learner-critic-v1",
        attempt=1,
    )
    system, user = build_learner_critic_messages(req)

    assert system["role"] == "system"
    assert user["role"] == "user"
    assert "decision must be revise or stop" in system["content"]
    assert "revision_actions must be a non-empty JSON array of strings" in system["content"]
    assert "failure_feedback=" in user["content"]
    assert "research_run_id=run-critic-001" in user["content"]
    assert "oos_profit_factor_below_threshold" in user["content"]


def test_build_learner_critic_messages_handles_none_gate_values() -> None:
    """Verify build_learner_critic_messages handles None observed/threshold without error."""
    gate = QualificationGateResult(
        gate_id="oos_profit_factor_min",
        passed=False,
        observed=None,
        threshold=None,
        comparator="gte",
        reason_code="oos_profit_factor_below_threshold",
    )
    feedback = CreatorQualificationFailureFeedback.model_validate(
        {
            "candidate_id": "cand-none-001",
            "candidate_artifact_hash": "a" * 64,
            "bundle_hash": MOCK_BUNDLE_HASH,
            "dataset_registry_hash": MOCK_REGISTRY_HASH,
            "qualification_hash": "d" * 64,
            "qualification_policy_id": "policy-creator-001",
            "failed_gates": [gate],
            "failure_reason_codes": ["oos_profit_factor_below_threshold"],
        }
    )
    req = LearnerCriticRequest(
        research_run_id="run-critic-none-001",
        candidate_id=feedback.candidate_id,
        candidate_artifact_hash=feedback.candidate_artifact_hash,
        feedback=feedback,
        input_evidence_refs=("ref1",),
        output_schema_id="learner-critic-v1",
        attempt=1,
    )
    system, user = build_learner_critic_messages(req)
    assert '"observed":null' in user["content"]
    assert '"threshold":null' in user["content"]


# ==============================================================================
# Category 5: Offline Mock Transport Execution (Tests 18–21)
# ==============================================================================


def test_google_ai_studio_proposal_transport_offline_mock() -> None:
    """Verify proposal transport formats OpenAI request and integrates with CreatorGenerator."""
    captured: list[httpx.Request] = []
    proposal_data = {
        "proposal_id": "proposal-btcusdt-revised-001",
        "research_run_id": "run-creator-mock-001",
        "hypothesis": "Hypothesis for testing",
        "expected_regime": "trending",
        "novelty_reason": "Novelty reason for testing",
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

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(proposal_data)},
                    }
                ]
            },
        )

    config = GoogleAIStudioProviderConfig(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="mock-key-for-test",
        model_id="gemma-4-31b-it",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        json_client = GoogleAIStudioJsonClient(config, client=http_client)
        transport = GoogleAIStudioProposalTransport(
            client=json_client,
            system_prompt="Return only valid JSON.",
            user_prompt_builder=lambda r: f"research_run_id={r.research_run_id}",
            temperature=0.2,
            max_output_tokens=2048,
        )
        req = CreatorGenerationRequest(
            research_run_id="run-creator-mock-001",
            input_evidence_refs=("ref1",),
            output_schema_id="creator-proposal-v1",
            attempt=1,
        )
        result = CreatorGenerator(transport=transport).generate(req)

    assert result.decision == "accepted"
    assert result.proposal is not None
    assert len(captured) == 1
    assert captured[0].url == f"{GOOGLE_AI_STUDIO_OPENAI_BASE_URL}/chat/completions"
    assert captured[0].headers["authorization"] == "Bearer mock-key-for-test"
    req_body = json.loads(captured[0].content)
    assert req_body["model"] == "gemma-4-31b-it"
    assert req_body["temperature"] == 0.2
    assert req_body["max_tokens"] == 2048


def test_google_ai_studio_critic_transport_offline_mock() -> None:
    """Verify critic transport and alias identity and integration with LearnerCritic."""
    assert GoogleAIStudioLearnerCriticTransport is GoogleAIStudioCriticTransport

    critic_data = {
        "review_id": "review-cand-001",
        "research_run_id": "run-critic-mock-001",
        "candidate_id": "cand-001",
        "decision": "revise",
        "failure_reason_codes": ["oos_profit_factor_below_threshold"],
        "revision_actions": ["adjust_stop_multiplier", "adjust_take_profit_multiplier"],
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(critic_data)},
                    }
                ]
            },
        )

    config = GoogleAIStudioProviderConfig(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="mock-key-for-test",
        model_id="gemma-4-31b-it",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        json_client = GoogleAIStudioJsonClient(config, client=http_client)
        transport = GoogleAIStudioCriticTransport(
            client=json_client,
            system_prompt="Return only valid JSON.",
            user_prompt_builder=lambda r: f"candidate_id={r.candidate_id}",
            temperature=0.2,
            max_output_tokens=4096,
        )
        fb = _make_feedback("cand-001")
        req = LearnerCriticRequest(
            research_run_id="run-critic-mock-001",
            candidate_id="cand-001",
            candidate_artifact_hash=fb.candidate_artifact_hash,
            feedback=fb,
            input_evidence_refs=("ref1",),
            output_schema_id="learner-critic-v1",
            attempt=1,
        )
        res = LearnerCritic(transport=transport).review(req)

    assert res.decision == "accepted"
    assert res.critique is not None
    assert len(res.critique.revision_actions) == 2


def test_google_ai_studio_transport_handles_markdown_code_fences() -> None:
    """Verify transport extracts JSON from fenced markdown blocks preserving Decimals."""
    fenced_proposal = {
        "proposal_id": "proposal-test-fenced-001",
        "research_run_id": "run-fenced-001",
        "hypothesis": "Hypothesis inside code fences",
        "expected_regime": "trending",
        "novelty_reason": "Code fence stripping test",
        "strategy": {
            "dsl_version": 2,
            "strategy_id": "cand-test-fenced-001",
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
                "position_fraction": 0.1,
                "stop_atr_multiplier": 2.5,
                "take_profit_atr_multiplier": 3.5,
                "trailing_atr_multiplier": 1.5,
            },
        },
    }
    content = "```json\n" + json.dumps(fenced_proposal) + "\n```"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    config = GoogleAIStudioProviderConfig(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="mock-key-for-test",
        model_id="gemma-4-31b-it",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = GoogleAIStudioJsonClient(config, client=http_client)
        payload = client.complete_json(
            messages=({"role": "user", "content": "return JSON"},),
            temperature=0.2,
            max_output_tokens=2048,
        )

    assert payload["proposal_id"] == "proposal-test-fenced-001"
    strat = payload["strategy"]
    assert isinstance(strat, dict)
    strat_risk = strat["risk"]
    assert isinstance(strat_risk, dict)
    assert strat_risk["position_fraction"] == Decimal("0.1")
    assert strat_risk["stop_atr_multiplier"] == Decimal("2.5")


@pytest.mark.parametrize("status_code", [400, 429, 500])
def test_google_ai_studio_transport_converts_http_error_to_provider_transport_error(
    status_code: int,
) -> None:
    """Verify HTTP status errors are converted to ProviderTransportError with redaction."""
    secret_body = "Server Internal Error with secret AIzaSySecret12345678901234567890"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=secret_body)

    config = GoogleAIStudioProviderConfig(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="mock-key-for-test",
        model_id="gemma-4-31b-it",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = GoogleAIStudioJsonClient(config, client=http_client)
        with pytest.raises(ProviderTransportError) as exc_info:
            client.complete_json(
                messages=({"role": "user", "content": "return JSON"},),
                temperature=0.2,
                max_output_tokens=100,
            )

    assert exc_info.value.code == "provider_http_error"
    assert exc_info.value.status_code == status_code
    assert "AIzaSySecret12345678901234567890" not in str(exc_info.value)
    assert _SECRET_PATTERN.search(str(exc_info.value)) is None


# ==============================================================================
# Category 6: Hard Budget Governance (Tests 22–25)
# ==============================================================================


def test_governor_allows_single_call_and_records_telemetry() -> None:
    """Verify governor permits call #1, increments count, and tracks latency."""
    mock_fn = MagicMock(return_value={"result": "ok"})
    gov = BoundedTransportCallGovernor(mock_fn, max_calls=1, name="test_transport")

    out = gov("request_data")
    assert out == {"result": "ok"}
    assert gov.call_count == 1
    assert gov.total_latency_ms >= 0.0
    mock_fn.assert_called_once_with("request_data")


def test_governor_strictly_blocks_subsequent_calls() -> None:
    """Verify governor blocks call #2 and #3 with RuntimeError."""
    mock_fn = MagicMock(return_value={"result": "ok"})
    gov = BoundedTransportCallGovernor(mock_fn, max_calls=1, name="test_transport")

    gov("call1")
    assert gov.call_count == 1

    with pytest.raises(
        RuntimeError, match="Budget ceiling breach: test_transport exceeded limit of 1"
    ):
        gov("call2")

    with pytest.raises(
        RuntimeError, match="Budget ceiling breach: test_transport exceeded limit of 1"
    ):
        gov("call3")

    assert mock_fn.call_count == 1


def test_governor_strictly_blocks_retries_on_failure() -> None:
    """Verify governor blocks subsequent retries even if first attempt raised an exception."""
    mock_fn = MagicMock(side_effect=ValueError("simulated failure"))
    gov = BoundedTransportCallGovernor(mock_fn, max_calls=1, name="test_transport")

    with pytest.raises(ValueError, match="simulated failure"):
        gov("call1")
    assert gov.call_count == 1

    with pytest.raises(
        RuntimeError, match="Budget ceiling breach: test_transport exceeded limit of 1"
    ):
        gov("call2")

    assert mock_fn.call_count == 1


def test_governor_enforced_in_autonomous_cycle_execution(tmp_path: Path) -> None:
    """Verify execute_autonomous_cycle wires through governors enforcing max 1 call each."""
    critic_raw = _make_mock_critic_transport()
    creator_raw = _make_mock_creator_transport()

    critic_gov = BoundedTransportCallGovernor(critic_raw, max_calls=1, name="critic")
    creator_gov = BoundedTransportCallGovernor(creator_raw, max_calls=1, name="creator")

    config = _make_cycle_config(tmp_path)
    windows = (_make_mock_window(),)
    feedback = _make_feedback()

    result = execute_autonomous_cycle(
        config=config,
        windows=windows,
        prior_feedback=feedback,
        critic_transport=critic_gov,
        creator_transport=creator_gov,
        simulator=_mock_fast_simulator,
        now=MOCK_TIMESTAMP,
        provider="google_ai_studio",
        model="gemma-4-31b-it",
    )

    assert result.cycle_status == "completed_admitted"
    assert critic_gov.call_count == 1
    assert creator_gov.call_count == 1

    with pytest.raises(RuntimeError, match="Budget ceiling breach: critic exceeded limit of 1"):
        critic_gov(None)

    with pytest.raises(RuntimeError, match="Budget ceiling breach: creator exceeded limit of 1"):
        creator_gov(None)


# ==============================================================================
# Category 7: Secret Leakage Assertions (Tests 26–28)
# ==============================================================================


def test_sanitize_error_text_redacts_keys_tokens_and_prompts() -> None:
    """Verify _sanitize_error_text redacts API keys, OAuth tokens, and Bearer strings."""
    t1 = "Failed with key AIzaSyFakeKey1234567890123456789012 in request"
    assert "AIzaSy" not in _sanitize_error_text(t1)
    assert "[REDACTED_SECRET]" in _sanitize_error_text(t1)
    assert _SECRET_PATTERN.search(_sanitize_error_text(t1)) is None

    t2 = "OAuth failure: Bearer ya29.a0AfH6SMSECRET_BEARER_TOKEN"
    assert "ya29" not in _sanitize_error_text(t2)
    assert "[REDACTED_SECRET]" in _sanitize_error_text(t2)
    assert _SECRET_PATTERN.search(_sanitize_error_text(t2)) is None

    t3 = "Header bearer token-string-here-1234567"
    assert "token-string" not in _sanitize_error_text(t3)
    assert "[REDACTED_SECRET]" in _sanitize_error_text(t3)
    assert _SECRET_PATTERN.search(_sanitize_error_text(t3)) is None


def test_cycle_audit_and_result_contain_zero_credentials(tmp_path: Path) -> None:
    """Verify cycle audit and result payloads contain zero credentials under regex scan."""
    critic_raw = _make_mock_critic_transport()
    creator_raw = _make_mock_creator_transport()

    config = _make_cycle_config(tmp_path)
    windows = (_make_mock_window(),)
    feedback = _make_feedback()

    result = execute_autonomous_cycle(
        config=config,
        windows=windows,
        prior_feedback=feedback,
        critic_transport=critic_raw,
        creator_transport=creator_raw,
        simulator=_mock_fast_simulator,
        now=MOCK_TIMESTAMP,
        provider="google_ai_studio",
        model="gemma-4-31b-it",
    )

    args = argparse.Namespace(
        symbol="BTCUSDT",
        ledger_db=None,
        parquet_path=None,
        windows_count=1,
        bars_per_window=20,
        require_flat=False,
        provider="google_ai_studio",
    )
    audit = build_cycle_audit(result, args)

    result_json = result.model_dump_json(indent=2)
    audit_json = json.dumps(audit, indent=2)

    assert _SECRET_PATTERN.search(result_json) is None
    assert _SECRET_PATTERN.search(audit_json) is None

    # Check for absence of sensitive keys anywhere in payloads
    for sensitive_key in ("api_key", "secret", "authorization", "token"):
        assert f'"{sensitive_key}"' not in result_json.lower()
        assert f'"{sensitive_key}"' not in audit_json.lower()


def test_cli_error_handling_sanitizes_secret_in_exceptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify CLI error handler sanitizes sensitive credentials in unexpected exceptions."""
    secret = "AIzaSyFakeSecretKey1234567890123456789012"

    def mock_failing_cycle(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(f"Unexpected explosion with secret: {secret}")

    monkeypatch.setattr("scripts.run_autonomous_cycle.run_autonomous_cycle", mock_failing_cycle)

    fb = _make_feedback("cand-cli-init-001")
    fb_path = tmp_path / "feedback.json"
    fb_path.write_text(fb.model_dump_json(indent=2), encoding="utf-8")

    ret = run_cli_main(["--symbol", "BTCUSDT", "--feedback-path", str(fb_path)])
    assert ret == 3

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert _SECRET_PATTERN.search(captured.out) is None
    assert _SECRET_PATTERN.search(captured.err) is None
    assert "[REDACTED_SECRET]" in captured.out


# ==============================================================================
# Category 8: Execution Telemetry & Invariants (Tests 29–32)
# ==============================================================================


def test_autonomous_cycle_result_telemetry_google_ai_studio(tmp_path: Path) -> None:
    """Verify AutonomousCycleResult captures provider, model, call status, and latency."""
    critic_raw = _make_mock_critic_transport()
    creator_raw = _make_mock_creator_transport()

    config = _make_cycle_config(tmp_path)
    windows = (_make_mock_window(),)
    feedback = _make_feedback()

    result = execute_autonomous_cycle(
        config=config,
        windows=windows,
        prior_feedback=feedback,
        critic_transport=critic_raw,
        creator_transport=creator_raw,
        simulator=_mock_fast_simulator,
        now=MOCK_TIMESTAMP,
        provider="google_ai_studio",
        model="gemma-4-31b-it",
    )

    assert result.provider == "google_ai_studio"
    assert result.model == "gemma-4-31b-it"
    assert result.call_status == "success"
    assert result.latency_ms >= 0.0


def test_autonomous_cycle_result_telemetry_demo_mode_latency_zero(tmp_path: Path) -> None:
    """Verify demo mode with now parameter sets latency_ms to 0.0 for determinism."""
    critic_raw = _make_mock_critic_transport()
    creator_raw = _make_mock_creator_transport()

    config = _make_cycle_config(tmp_path)
    windows = (_make_mock_window(),)
    feedback = _make_feedback()

    result = execute_autonomous_cycle(
        config=config,
        windows=windows,
        prior_feedback=feedback,
        critic_transport=critic_raw,
        creator_transport=creator_raw,
        simulator=_mock_fast_simulator,
        now=MOCK_TIMESTAMP,
        provider="demo",
    )

    assert result.provider == "demo"
    assert result.model == "deterministic-heuristic"
    assert result.latency_ms == 0.0


def test_autonomous_cycle_result_telemetry_failed_call_status(tmp_path: Path) -> None:
    """Verify failed provider transport call updates call_status and cycle_status to failed."""
    failing_critic = _make_mock_critic_transport(fail_http=True)
    creator_raw = _make_mock_creator_transport()

    config = _make_cycle_config(tmp_path)
    windows = (_make_mock_window(),)
    feedback = _make_feedback()

    result = execute_autonomous_cycle(
        config=config,
        windows=windows,
        prior_feedback=feedback,
        critic_transport=failing_critic,
        creator_transport=creator_raw,
        simulator=_mock_fast_simulator,
        now=MOCK_TIMESTAMP,
        provider="google_ai_studio",
        model="gemma-4-31b-it",
    )

    assert result.cycle_status == "failed"
    assert result.call_status == "failed"
    assert "provider_http_error" in result.stop_reasons


def test_autonomous_cycle_content_hash_includes_telemetry_fields(tmp_path: Path) -> None:
    """Verify changing telemetry fields (provider, model, call_status, latency_ms) alters hash."""
    critic_raw = _make_mock_critic_transport()
    creator_raw = _make_mock_creator_transport()

    config = _make_cycle_config(tmp_path)
    windows = (_make_mock_window(),)
    feedback = _make_feedback()

    base_result = execute_autonomous_cycle(
        config=config,
        windows=windows,
        prior_feedback=feedback,
        critic_transport=critic_raw,
        creator_transport=creator_raw,
        simulator=_mock_fast_simulator,
        now=MOCK_TIMESTAMP,
        provider="google_ai_studio",
        model="gemma-4-31b-it",
    )

    h_base = base_result.cycle_hash
    h_provider = autonomous_cycle_content_hash(
        base_result.model_copy(update={"provider": "custom_provider"})
    )
    h_model = autonomous_cycle_content_hash(
        base_result.model_copy(update={"model": "gemma-4-26b-a4b-it"})
    )
    h_status = autonomous_cycle_content_hash(
        base_result.model_copy(update={"call_status": "failed"})
    )
    h_latency = autonomous_cycle_content_hash(base_result.model_copy(update={"latency_ms": 99.99}))

    # Verify all 5 hashes are distinct
    all_hashes = {h_base, h_provider, h_model, h_status, h_latency}
    assert len(all_hashes) == 5
