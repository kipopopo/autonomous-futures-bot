"""Comprehensive unit tests for Phase 252 Multi-Asset Batch Campaign.

Covers:
- Prompt construction with 100 USDT equity baseline & dynamic leverage design guidelines.
- CLI argument parsing, flags, and parameter validation.
- Mock 4-asset batch execution (BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT).
- Candidate parsing, canonical SHA-256 cand-<hash> derivation, and artifact persistence.
- Dynamic request.research_run_id -> symbol mapping.
- Rejection handling and partial failure tolerance without batch abort.
- Read-only filesystem resilience under systemd sandboxing.
- Offline safety invariants (orders=0, exchange_access=false, etc.).
- Zero secret leakage guarantees across outputs and logs.
- Preflight integration hook (--batch-campaign) in scripts/preflight_kainode_staging.py.
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from autonomous_futures.phase_252_batch import (
    CAPITAL_AND_LEVERAGE_GUIDELINES,
    PHASE_252_DEFAULT_ASSETS,
    build_phase_252_batch_requests,
    execute_phase_252_batch_campaign,
    make_phase_252_run_id,
)
from autonomous_futures.research.creator_artifacts import (
    read_creator_candidate_artifact,
)
from autonomous_futures.research.creator_generator import (
    CreatorGenerationRequest,
)
from autonomous_futures.research.creator_prompts import (
    build_phase_252_proposal_messages,
)
from autonomous_futures.research.creator_proposals import (
    canonical_creator_candidate_id,
)
from autonomous_futures.research.google_ai_studio_provider import (
    ProviderJsonPayload,
    ProviderTransportError,
)


def _load_script_module(name: str) -> Any:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


batch_runner_mod = _load_script_module("run_phase_252_batch_campaign")
preflight_mod = _load_script_module("preflight_kainode_staging")

batch_runner_main: Callable[[list[str] | None], int] = batch_runner_mod.main
preflight_main: Callable[[list[str] | None], int] = preflight_mod.main


def _valid_proposal_dict(
    symbol: str,
    run_id: str,
    dsl_version: int = 2,
) -> dict[str, Any]:
    """Generate a syntactically valid proposal payload for testing."""
    strategy: dict[str, Any] = {
        "dsl_version": dsl_version,
        "strategy_id": "cand-placeholder-to-be-overwritten",
        "family": "regime_gated_breakout",
        "universe": {
            "symbols": [symbol],
            "timeframe": "5m",
            "regime_context_timeframe": "15m",
        },
        "features": [
            {"name": "rsi", "lookback": 14, "shift": 1},
            {"name": "atr", "lookback": 14, "shift": 1},
        ],
        "entry": {"long": "rsi <= 30", "short": "rsi >= 70"},
        "exit": {"long": "rsi >= 50", "short": "rsi <= 50"},
        "vetoes": ["funding_adverse"],
    }
    if dsl_version == 2:
        strategy["risk"] = {
            "position_fraction": Decimal("0.15"),
            "stop_atr_multiplier": Decimal("1.5"),
            "take_profit_atr_multiplier": Decimal("3.0"),
            "trailing_atr_multiplier": Decimal("1.0"),
        }
    return {
        "proposal_id": f"proposal-{symbol.lower()}-001",
        "research_run_id": run_id,
        "hypothesis": f"Dynamic leverage breakout on {symbol} with 100 USDT baseline equity",
        "expected_regime": "trending",
        "novelty_reason": "Dynamic leverage sized according to conviction threshold",
        "strategy": strategy,
    }


# ==============================================================================
# 1. Prompt Construction Tests
# ==============================================================================


def test_phase_252_prompt_incorporates_capital_and_leverage_guidelines() -> None:
    request = CreatorGenerationRequest(
        research_run_id="run-btcusdt-20260904-phase252",
        input_evidence_refs=("bundle/hash123",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )
    bundle_hash = "a" * 64
    system_msg, user_msg = build_phase_252_proposal_messages(
        request,
        bundle_hash=bundle_hash,
        symbol="BTCUSDT",
        starting_capital_usd=Decimal("100"),
    )

    # System prompt assertions
    assert system_msg["role"] == "system"
    assert "Return exactly one JSON object" in system_msg["content"]
    assert "dsl_version must be the integer 2" in system_msg["content"]
    assert "leverage is not supported" in system_msg["content"]

    # User prompt assertions
    user_content = user_msg["content"]
    assert user_msg["role"] == "user"
    assert "symbol=BTCUSDT" in user_content
    assert "starting_capital_usd=100" in user_content
    assert "Capital and Leverage Guidelines:" in user_content
    assert "Starting capital baseline is exactly 100 USDT." in user_content
    assert "prudent, confidence-scaled dynamic leverage" in user_content
    assert "strictly protect the 100 USDT account from liquidation" in user_content
    assert CAPITAL_AND_LEVERAGE_GUIDELINES in user_content


def test_phase_252_prompt_rejects_invalid_inputs() -> None:
    request = CreatorGenerationRequest(
        research_run_id="run-btc-test",
        input_evidence_refs=("bundle/hash",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )
    valid_hash = "b" * 64

    # Invalid bundle hash
    with pytest.raises(ValueError, match="bundle_hash must be a lowercase SHA-256"):
        build_phase_252_proposal_messages(request, bundle_hash="bad_hash", symbol="BTCUSDT")

    # Invalid symbol
    with pytest.raises(ValueError, match="symbol must be uppercase alphanumeric"):
        build_phase_252_proposal_messages(request, bundle_hash=valid_hash, symbol="btc_usdt")

    # Negative starting capital
    with pytest.raises(ValueError, match="starting_capital_usd must be positive"):
        build_phase_252_proposal_messages(
            request, bundle_hash=valid_hash, symbol="BTCUSDT", starting_capital_usd=Decimal("-50")
        )

    # Zero starting capital
    with pytest.raises(ValueError, match="starting_capital_usd must be positive"):
        build_phase_252_proposal_messages(
            request, bundle_hash=valid_hash, symbol="BTCUSDT", starting_capital_usd=0
        )


# ==============================================================================
# 2. Batch Request Construction & Run ID Derivation Tests
# ==============================================================================


def test_make_phase_252_run_id_deterministic_and_contract_compliant() -> None:
    run_id = make_phase_252_run_id("BTCUSDT", "creator-batch-20260904-phase252")
    assert run_id.startswith("run-btcusdt-")
    assert len(run_id) <= 68  # run- plus max 64 chars
    # Ensure regex matches CreatorGenerationRequest pattern
    import re

    assert re.match(r"^run-[a-z0-9][a-z0-9-]{0,63}$", run_id)


def test_build_phase_252_batch_requests_maps_all_4_assets() -> None:
    requests, symbol_map = build_phase_252_batch_requests(
        assets=("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"),
        campaign_id="campaign-phase252-test",
        bundle_hash="c" * 64,
    )
    assert len(requests) == 4
    assert len(symbol_map) == 4

    for req in requests:
        sym = symbol_map[req.research_run_id]
        assert sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")
        assert sym.lower() in req.research_run_id


def test_phase_252_default_assets_universe() -> None:
    assert PHASE_252_DEFAULT_ASSETS == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")


def test_build_phase_252_batch_requests_rejects_empty_or_duplicate() -> None:
    with pytest.raises(ValueError, match="assets sequence cannot be empty"):
        build_phase_252_batch_requests(assets=())

    with pytest.raises(ValueError, match="Duplicate asset symbol in batch"):
        build_phase_252_batch_requests(assets=("BTCUSDT", "ETHUSDT", "BTCUSDT"))


# ==============================================================================
# 3. Mock 4-Asset Batch Execution Tests
# ==============================================================================


def test_execute_phase_252_batch_campaign_all_accepted(tmp_path: Path) -> None:
    evidence_root = tmp_path / "phase252_all_accepted"
    assets = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")
    campaign_id = "creator-batch-20260904-phase252"

    # Mock transport dynamically mapping run_id to symbol payload
    def mock_transport(req: CreatorGenerationRequest) -> ProviderJsonPayload:
        # Determine symbol from run_id
        for sym in assets:
            if sym.lower() in req.research_run_id:
                payload = _valid_proposal_dict(sym, req.research_run_id, dsl_version=2)
                return ProviderJsonPayload(payload, metadata={"finish_reason": "stop"})
        raise ValueError(f"Unknown run_id in mock: {req.research_run_id}")

    summary = execute_phase_252_batch_campaign(
        api_key="AIzaSyMockKeyForBatchTesting12345",
        assets=assets,
        starting_capital_usd=Decimal("100"),
        evidence_root=evidence_root,
        campaign_id=campaign_id,
        transport_override=mock_transport,
        env={"PATH": "/usr/bin"},
    )

    # Summary level assertions
    assert summary["campaign_id"] == campaign_id
    assert summary["total_trials"] == 4
    assert summary["total_accepted"] == 4
    assert summary["request_count"] == 4
    assert summary["max_retries"] == 0
    assert summary["fallback_provider"] is False
    assert summary["persistence_status"] == "persisted"
    assert summary["starting_capital_usd"] == "100"

    # Offline safety assertions
    assert summary["safety_state"]["orders"] == 0
    assert summary["safety_state"]["exchange_access"] is False
    assert summary["safety_state"]["execution_authority"] is False
    assert summary["safety_state"]["paper_activation"] is False
    assert summary["safety_state"]["promotion_state"] == "unpromoted"

    # Verify trials and candidates
    assert len(summary["trials"]) == 4
    assert len(summary["accepted_candidate_ids"]) == 4

    for i, trial in enumerate(summary["trials"]):
        expected_sym = assets[i]
        assert trial["asset"] == expected_sym
        assert trial["decision"] == "accepted"
        assert trial["reason_codes"] == ["candidate_accepted_for_testing"]
        assert trial["candidate_id"] is not None
        assert trial["candidate_id"].startswith("cand-")
        assert len(trial["candidate_artifact_hash"]) == 64

        # Verify candidate artifact on disk
        cand_file = evidence_root / "candidates" / f"{trial['candidate_id']}.json"
        assert cand_file.is_file()
        artifact = read_creator_candidate_artifact(cand_file)
        assert artifact.candidate_id == trial["candidate_id"]
        assert artifact.candidate_id == canonical_creator_candidate_id(artifact.strategy)
        assert artifact.strategy.universe.symbols == (expected_sym,)
        assert artifact.strategy.risk is not None
        assert artifact.strategy.risk.position_fraction == Decimal("0.15")

        # Verify trial file on disk
        trial_file = evidence_root / "trials" / f"trial-{i:04d}-{trial['research_run_id']}.json"
        assert trial_file.is_file()

    # Verify summary JSON on disk
    summary_file = evidence_root / "campaign-summary.json"
    assert summary_file.is_file()
    disk_summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert disk_summary["total_accepted"] == 4


# ==============================================================================
# 4. Rejection & Partial Failure Tolerance Tests
# ==============================================================================


def test_execute_phase_252_batch_campaign_partial_rejection(tmp_path: Path) -> None:
    evidence_root = tmp_path / "phase252_partial_rejection"
    assets = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")

    def mock_partial_transport(req: CreatorGenerationRequest) -> ProviderJsonPayload:
        if "solusdt" in req.research_run_id:
            # Simulate HTTP 429 rate limit error for SOLUSDT
            raise ProviderTransportError(
                code="provider_http_error",
                status_code=429,
                error_code="http_429",
                error_status="RESOURCE_EXHAUSTED",
                error_reason="rate_limit_exceeded",
                metadata={"status_code": 429, "error_code": "http_429"},
            )
        if "dogeusdt" in req.research_run_id:
            # Simulate schema rejection (missing strategy)
            return ProviderJsonPayload(
                {"proposal_id": "bad-prop", "research_run_id": req.research_run_id},
                metadata={"finish_reason": "stop"},
            )
        # BTC and ETH succeed
        for sym in ("BTCUSDT", "ETHUSDT"):
            if sym.lower() in req.research_run_id:
                payload = _valid_proposal_dict(sym, req.research_run_id)
                return ProviderJsonPayload(payload, metadata={"finish_reason": "stop"})
        raise ValueError("Unknown run_id in mock")

    summary = execute_phase_252_batch_campaign(
        api_key="AIzaSyMockKeyForBatchTesting12345",
        assets=assets,
        evidence_root=evidence_root,
        transport_override=mock_partial_transport,
        env={"PATH": "/usr/bin"},
    )

    assert summary["total_trials"] == 4
    assert summary["total_accepted"] == 2
    assert len(summary["accepted_candidate_ids"]) == 2

    trials_by_asset = {t["asset"]: t for t in summary["trials"]}
    assert trials_by_asset["BTCUSDT"]["decision"] == "accepted"
    assert trials_by_asset["ETHUSDT"]["decision"] == "accepted"
    assert trials_by_asset["SOLUSDT"]["decision"] == "rejected"
    assert "provider_http_error" in trials_by_asset["SOLUSDT"]["reason_codes"]
    assert trials_by_asset["DOGEUSDT"]["decision"] == "rejected"
    assert "schema_rejected" in trials_by_asset["DOGEUSDT"]["reason_codes"]


# ==============================================================================
# 5. Read-Only Filesystem Resilience Tests
# ==============================================================================


def test_execute_phase_252_batch_campaign_read_only_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_root = tmp_path / "phase252_readonly"
    assets = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")

    def mock_transport(req: CreatorGenerationRequest) -> ProviderJsonPayload:
        sym = "BTCUSDT"
        for s in assets:
            if s.lower() in req.research_run_id:
                sym = s
                break
        payload = _valid_proposal_dict(sym, req.research_run_id)
        return ProviderJsonPayload(payload, metadata={"finish_reason": "stop"})

    # Simulate ProtectSystem=strict read-only filesystem error on Path.mkdir
    original_mkdir = Path.mkdir

    def failing_mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
        if "phase252_readonly" in str(self):
            raise OSError(30, "Read-only file system")
        original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", failing_mkdir)

    summary = execute_phase_252_batch_campaign(
        api_key="AIzaSyMockKeyForBatchTesting12345",
        assets=assets,
        evidence_root=evidence_root,
        transport_override=mock_transport,
        env={"PATH": "/usr/bin"},
    )

    # Must complete cleanly with read_only_filesystem_skipped status
    assert summary["persistence_status"] == "read_only_filesystem_skipped"
    assert summary["total_trials"] == 4
    assert summary["total_accepted"] == 4
    assert summary["safety_state"]["orders"] == 0


# ==============================================================================
# 6. Zero Secret Leakage & Offline Safety Invariant Tests
# ==============================================================================


def test_phase_252_batch_zero_secret_leakage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    canary_key = "AIzaSyCanarySecretBatchKey999888777"
    evidence_root = tmp_path / "phase252_leak_check"

    def mock_transport(req: CreatorGenerationRequest) -> ProviderJsonPayload:
        payload = _valid_proposal_dict("BTCUSDT", req.research_run_id)
        return ProviderJsonPayload(payload, metadata={"finish_reason": "stop"})

    summary = execute_phase_252_batch_campaign(
        api_key=canary_key,
        assets=("BTCUSDT",),
        evidence_root=evidence_root,
        transport_override=mock_transport,
        env={"PATH": "/usr/bin"},
    )

    serialized = json.dumps(summary)
    assert canary_key not in serialized

    # Check CLI output does not contain canary key even on failure / execution
    cli_evidence = tmp_path / "cli_canary_evidence"
    code = batch_runner_main(
        [
            "--api-key",
            canary_key,
            "--assets",
            "BTCUSDT",
            "--max-retries",
            "1",
            "--evidence-dir",
            str(cli_evidence),
        ]
    )
    assert code == 2
    captured = capsys.readouterr()
    assert canary_key not in captured.out
    assert canary_key not in captured.err


def test_phase_252_batch_blocks_on_binance_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "binance_active_trade_key")

    with pytest.raises(RuntimeError, match="Offline safety violation"):
        execute_phase_252_batch_campaign(
            api_key="AIzaSyMockKeyForTesting12345",
            assets=("BTCUSDT",),
            evidence_root=tmp_path / "evidence",
            env=dict(os.environ),
        )


# ==============================================================================
# 7. CLI Runner & Argument Validation Tests (scripts/run_phase_252_batch_campaign.py)
# ==============================================================================


def test_batch_runner_cli_argument_parsing(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Test unrecognized arg returns code 2
    code = batch_runner_main(["--unrecognized-foo-bar"])
    assert code == 2

    # Test invalid max-retries (> 0) returns code 2
    code = batch_runner_main(["--max-retries", "1"])
    assert code == 2
    err_out = capsys.readouterr().out
    assert "max_retries must be 0" in err_out

    # Test fallback-provider returns code 2
    code = batch_runner_main(["--fallback-provider"])
    assert code == 2
    err_out = capsys.readouterr().out
    assert "fallback_provider must be False" in err_out


def test_batch_runner_cli_successful_mock_invocation(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence_dir = tmp_path / "cli_batch_evidence"

    def mock_execute(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "campaign_id": "test-campaign",
            "total_trials": 4,
            "total_accepted": 4,
            "persistence_status": "persisted",
            "safety_state": {"orders": 0, "exchange_access": False},
        }

    monkeypatch.setattr(
        batch_runner_mod,
        "execute_phase_252_batch_campaign",
        mock_execute,
    )

    code = batch_runner_main(
        [
            "--api-key",
            "AIzaSyMockKeyForTesting12345",
            "--assets",
            "BTCUSDT",
            "ETHUSDT",
            "--capital-usd",
            "100",
            "--evidence-dir",
            str(evidence_dir),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["campaign_id"] == "test-campaign"
    assert parsed["total_trials"] == 4


# ==============================================================================
# 8. Staging Preflight Integration Hook Tests (scripts/preflight_kainode_staging.py)
# ==============================================================================


def test_preflight_cli_with_batch_campaign_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")

    cred_dir = tmp_path / "credentials"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_token_string_12345", encoding="utf-8"
    )

    monkeypatch.setattr(
        preflight_mod,
        "validate_staging_environment",
        lambda *args, **kwargs: type(
            "MockReport",
            (),
            {
                "ready": True,
                "status": "ready_for_staging_probe",
                "model_dump": lambda self, mode: {"ready": True},
            },
        )(),
    )

    batch_called = False

    def mock_batch_campaign(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal batch_called
        batch_called = True
        return {
            "campaign_id": "creator-batch-20260904-phase252",
            "total_trials": 4,
            "total_accepted": 4,
            "safety_state": {"orders": 0, "exchange_access": False},
        }

    monkeypatch.setattr(
        preflight_mod,
        "execute_phase_252_batch_campaign",
        mock_batch_campaign,
    )

    code = preflight_main(
        [
            "--source-credential-path",
            str(source_path),
            "--credential-dir",
            str(cred_dir),
            "--batch-campaign",
        ]
    )

    assert code == 0
    assert batch_called is True
    captured = capsys.readouterr().out
    assert "creator-batch-20260904-phase252" in captured


def test_preflight_cli_batch_campaign_via_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    cred_dir = tmp_path / "credentials"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_token_string_12345", encoding="utf-8"
    )

    monkeypatch.setattr(
        preflight_mod,
        "validate_staging_environment",
        lambda *args, **kwargs: type(
            "MockReport",
            (),
            {
                "ready": True,
                "status": "ready_for_staging_probe",
                "model_dump": lambda self, mode: {"ready": True},
            },
        )(),
    )

    batch_called = False

    def mock_batch_campaign(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal batch_called
        batch_called = True
        return {"campaign_id": "env-batch-test", "total_trials": 4}

    monkeypatch.setattr(
        preflight_mod,
        "execute_phase_252_batch_campaign",
        mock_batch_campaign,
    )
    monkeypatch.setenv("AUTONOMOUS_FUTURES_BATCH_CAMPAIGN", "1")

    code = preflight_main(
        [
            "--source-credential-path",
            str(source_path),
            "--credential-dir",
            str(cred_dir),
        ]
    )

    assert code == 0
    assert batch_called is True


def test_preflight_cli_batch_campaign_via_staging_auto_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_path = Path("/etc/autonomous-futures/credentials/google_ai_studio_api_key")
    cred_dir = tmp_path / "credentials"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_token_string_12345", encoding="utf-8"
    )

    monkeypatch.setattr(
        preflight_mod,
        "validate_staging_environment",
        lambda *args, **kwargs: type(
            "MockReport",
            (),
            {
                "ready": True,
                "status": "ready_for_staging_probe",
                "model_dump": lambda self, mode: {"ready": True},
            },
        )(),
    )

    batch_called = False

    def mock_batch_campaign(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal batch_called
        batch_called = True
        return {"campaign_id": "auto-detect-batch-test", "total_trials": 4}

    monkeypatch.setattr(
        preflight_mod,
        "execute_phase_252_batch_campaign",
        mock_batch_campaign,
    )
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(cred_dir))

    code = preflight_main(
        [
            "--source-credential-path",
            str(source_path),
            "--credential-dir",
            str(cred_dir),
        ]
    )

    assert code == 0
    assert batch_called is True
