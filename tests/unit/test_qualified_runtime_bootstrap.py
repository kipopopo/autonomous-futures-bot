import asyncio
import base64
import datetime as dt
import hashlib
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import run_qualified_runtime as runtime


def test_current_rejected_universe_cannot_bootstrap_live_runtime(tmp_path, monkeypatch):
    def credentials_must_not_be_read():
        raise AssertionError("Qualification rejection must precede credential/network access")

    monkeypatch.setattr(
        runtime,
        "admitted_portfolios",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("No genuinely qualified portfolio reports in admission manifest")
        ),
    )
    monkeypatch.setattr(runtime, "credentials", credentials_must_not_be_read)
    with pytest.raises(ValueError, match="No genuinely qualified"):
        asyncio.run(
            runtime.run(
                tmp_path,
                tmp_path / "lease",
                "ACCOUNT",
                tmp_path / "hawkes-calibration.json",
            )
        )
    assert not (tmp_path / "lease").exists()


def test_admitted_portfolio_resolves_and_halts_at_handoff_guard_before_credentials(
    tmp_path, monkeypatch
):
    reports, portfolio = runtime.resolve_runtime_admission(runtime.REPO)
    assert reports == {}
    assert portfolio is not None
    assert portfolio.portfolio_id == "macro-scalper-uninspected-3sym-medium-frequency-v1"
    assert len(portfolio.members) == 6

    class BlockingGuard:
        def assert_legacy_inactive(self):
            raise RuntimeError("legacy service still active")

    monkeypatch.setattr(runtime, "LegacyWriterHandoffGuard", BlockingGuard)

    def credentials_must_not_be_read():
        raise AssertionError("Handoff must be verified before credential access")

    monkeypatch.setattr(runtime, "credentials", credentials_must_not_be_read)
    with pytest.raises(RuntimeError, match="legacy service still active"):
        asyncio.run(
            runtime.run(
                tmp_path,
                tmp_path / "lease",
                "ACCOUNT",
                tmp_path / "hawkes-calibration.json",
                portfolio_id="macro-scalper-uninspected-3sym-medium-frequency-v1",
            )
        )
    assert not (tmp_path / "lease").exists()


def test_same_key_handoff_gate_blocks_before_credentials_or_network(tmp_path, monkeypatch):
    class BlockingGuard:
        def assert_legacy_inactive(self):
            raise RuntimeError("legacy service still active")

    monkeypatch.setattr(
        runtime,
        "admitted_reports",
        lambda *_args, **_kwargs: {("ICT_TWINS", "BTCUSDT"): tmp_path / "admitted-report.json"},
    )
    monkeypatch.setattr(runtime, "LegacyWriterHandoffGuard", BlockingGuard)

    def credentials_must_not_be_read():
        raise AssertionError("Handoff must be verified before credential access")

    monkeypatch.setattr(runtime, "credentials", credentials_must_not_be_read)
    with pytest.raises(RuntimeError, match="legacy service still active"):
        asyncio.run(
            runtime.run(
                tmp_path,
                tmp_path / "lease",
                "ACCOUNT",
                tmp_path / "hawkes-calibration.json",
            )
        )
    assert not (tmp_path / "lease").exists()


def test_bootstrap_requires_the_existing_testnet_key_pair(monkeypatch):
    names = ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_SECRET_KEY")
    for name in names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runtime, "_load_dotenv_fallback", lambda: None)
    with pytest.raises(ValueError, match="must be configured"):
        runtime.credentials()
    monkeypatch.setenv(names[0], "existing-fixture-key")
    monkeypatch.setenv(names[1], "existing-fixture-secret")
    assert runtime.credentials() == ("existing-fixture-key", "existing-fixture-secret")


@pytest.mark.parametrize(
    ("api_key", "api_secret"),
    [("mock-testnet-key", "real-shaped-secret"), ("real-shaped-key", "mock-secret")],
)
def test_bootstrap_rejects_mock_testnet_credentials(monkeypatch, api_key, api_secret):
    monkeypatch.setattr(runtime, "_load_dotenv_fallback", lambda: None)
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", api_key)
    monkeypatch.setenv("BINANCE_TESTNET_SECRET_KEY", api_secret)

    with pytest.raises(ValueError, match="must be configured"):
        runtime.credentials()


def test_mainnet_uses_only_mainnet_credentials(monkeypatch):
    monkeypatch.setattr(runtime, "_load_dotenv_fallback", lambda: None)
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_SECRET_KEY", raising=False)
    monkeypatch.setenv("BINANCE_MAINNET_API_KEY", "mainnet-fixture-key")
    monkeypatch.setenv("BINANCE_MAINNET_SECRET_KEY", "mainnet-fixture-secret")

    assert runtime.credentials("mainnet") == (
        "mainnet-fixture-key",
        "mainnet-fixture-secret",
    )

    monkeypatch.delenv("BINANCE_MAINNET_API_KEY")
    monkeypatch.delenv("BINANCE_MAINNET_SECRET_KEY")
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "testnet-fixture-key")
    monkeypatch.setenv("BINANCE_TESTNET_SECRET_KEY", "testnet-fixture-secret")
    with pytest.raises(ValueError, match="Authenticated mainnet API key pair"):
        runtime.credentials("mainnet")


def test_mainnet_rejects_testnet_execution_domain_before_credentials():
    with pytest.raises(ValueError, match="does not match mainnet"):
        runtime._require_environment_domain(
            {"testnet": True},
            environment="mainnet",
            identity="MACRO_SCALPER SOLUSDT",
        )


def test_mainnet_runtime_requires_isolated_storage(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    storage = tmp_path / "runtime" / "qualified-mainnet"
    storage.mkdir(parents=True)

    runtime._validate_runtime_paths(
        storage,
        storage / "account-writer.lock",
        environment="mainnet",
        repo=repo,
    )

    with pytest.raises(ValueError, match="outside the deployment repository"):
        runtime._validate_runtime_paths(
            repo / "runtime" / "qualified-mainnet",
            repo / "runtime" / "qualified-mainnet" / "account-writer.lock",
            environment="mainnet",
            repo=repo,
        )
    with pytest.raises(ValueError, match="must be named qualified-mainnet"):
        runtime._validate_runtime_paths(
            tmp_path / "runtime" / "mainnet",
            tmp_path / "runtime" / "mainnet" / "account-writer.lock",
            environment="mainnet",
            repo=repo,
        )
    with pytest.raises(ValueError, match="inside its isolated storage directory"):
        runtime._validate_runtime_paths(
            storage,
            tmp_path / "outside.lock",
            environment="mainnet",
            repo=repo,
        )


def test_mainnet_admission_uses_separate_manifest_and_domain(tmp_path, monkeypatch):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    report_path = tmp_path / "reports" / "mainnet.json"
    report_path.parent.mkdir()
    report_path.write_text("{}", encoding="utf-8")
    manifest_path = deploy / "mainnet-qualification-admission.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "runtime-qualification-admission-v1",
                "approved_reports": [
                    {"family": "MACRO_SCALPER", "symbol": "ETHUSDT", "path": "reports/mainnet.json"}
                ],
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def verify_report(path, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(execution_domain={"testnet": False})

    monkeypatch.setattr(runtime, "verify_runtime_report", verify_report)

    admitted = runtime.admitted_reports(tmp_path, environment="mainnet")

    assert admitted == {("MACRO_SCALPER", "ETHUSDT"): report_path.resolve()}
    assert captured["admission_manifest_path"] == manifest_path.resolve()


def test_runtime_evidence_context_binds_report_and_implementation_hashes(tmp_path):
    repo = tmp_path
    deploy = repo / "deploy"
    reports_dir = repo / "reports"
    deploy.mkdir()
    reports_dir.mkdir()
    manifest_path = deploy / "qualification-admission.json"
    manifest_path.write_text('{"schema":"runtime-qualification-admission-v1"}', encoding="utf-8")
    report_path = reports_dir / "portfolio.json"
    report = {
        "report_hash": "a" * 64,
        "implementation": {"src/autonomous_futures/strategy.py": "b" * 64},
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    portfolio = SimpleNamespace(
        report_path=report_path,
        report_hash=report["report_hash"],
        portfolio_id="portfolio-fixture",
        selection_hash="c" * 64,
        symbols=("ETHUSDT", "LINKUSDT"),
    )

    context = runtime.runtime_execution_evidence_context(
        repo,
        environment="testnet",
        reports={},
        portfolio=portfolio,
    )

    candidate = context["candidates"][0]
    assert context["environment"] == "testnet"
    assert context["admission_manifest_path"] == "deploy/qualification-admission.json"
    assert (
        context["admission_manifest_sha256"]
        == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )
    assert candidate["portfolio_id"] == portfolio.portfolio_id
    assert candidate["report_hash"] == portfolio.report_hash
    assert candidate["selection_hash"] == portfolio.selection_hash
    assert candidate["implementation_hashes"] == report["implementation"]


def test_mainnet_requires_separate_admission_before_credentials(tmp_path, monkeypatch):
    credentials_read = False

    def forbidden_credentials(_environment="testnet"):
        nonlocal credentials_read
        credentials_read = True
        raise AssertionError("Mainnet admission must be checked before credentials")

    monkeypatch.setattr(runtime, "credentials", forbidden_credentials)
    repo = tmp_path / "repo"
    repo.mkdir()
    storage = tmp_path / "runtime" / "qualified-mainnet"
    with pytest.raises(ValueError, match="Mainnet admission manifest is missing"):
        asyncio.run(
            runtime.run(
                storage,
                storage / "account-writer.lock",
                "ACCOUNT",
                tmp_path / "hawkes-calibration.json",
                repo=repo,
                environment="mainnet",
            )
        )
    assert credentials_read is False
    assert not (storage / "account-writer.lock").exists()


def test_mainnet_authorization_must_bind_exact_portfolio_hashes(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    deploy = repo / "deploy"
    deploy.mkdir(parents=True)
    key_path = tmp_path / "mainnet-authorization-public.pem"
    private_key = Ed25519PrivateKey.generate()
    key_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    monkeypatch.setenv("AFBOT_MAINNET_AUTHORIZATION_PUBLIC_KEY_FILE", str(key_path))
    portfolio = SimpleNamespace(
        portfolio_id="candidate-1",
        report_hash="a" * 64,
        selection_hash="b" * 64,
    )
    now = dt.datetime.now(dt.UTC)
    authorization = {
        "schema": "runtime-mainnet-execution-authorization-v1",
        "environment": "mainnet",
        "execution_authority": True,
        "authorization_id": "approval-1",
        "approved_by": "owner",
        "approved_at_utc": (now - dt.timedelta(minutes=5)).isoformat(),
        "expires_at_utc": (now + dt.timedelta(days=1)).isoformat(),
        "approved_portfolios": [
            {
                "portfolio_id": portfolio.portfolio_id,
                "report_hash": portfolio.report_hash,
                "selection_hash": portfolio.selection_hash,
            }
        ],
    }

    def sign_document(document):
        document.pop("authorization_hash", None)
        document.pop("authorization_signature_ed25519", None)
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        document["authorization_hash"] = hashlib.sha256(payload).hexdigest()
        document["authorization_signature_ed25519"] = base64.b64encode(
            private_key.sign(payload)
        ).decode("ascii")

    sign_document(authorization)
    authorization_path = deploy / "mainnet-execution-authorization.json"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    runtime._authorized_mainnet_targets(repo, {}, portfolio)

    tampered = json.loads(json.dumps(authorization))
    tampered["approved_by"] = "different-reviewer"
    tampered.pop("authorization_hash")
    tampered_payload_object = dict(tampered)
    tampered_payload_object.pop("authorization_signature_ed25519")
    tampered_payload = json.dumps(
        tampered_payload_object, sort_keys=True, separators=(",", ":")
    ).encode()
    tampered["authorization_hash"] = hashlib.sha256(tampered_payload).hexdigest()
    authorization_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="signature or public key is invalid"):
        runtime._authorized_mainnet_targets(repo, {}, portfolio)

    expired = json.loads(json.dumps(authorization))
    expired["expires_at_utc"] = (now - dt.timedelta(days=1)).isoformat()
    sign_document(expired)
    authorization_path.write_text(json.dumps(expired), encoding="utf-8")
    with pytest.raises(ValueError, match="is expired or has an invalid expiry"):
        runtime._authorized_mainnet_targets(repo, {}, portfolio)

    mismatched = json.loads(json.dumps(authorization))
    mismatched["approved_portfolios"][0]["report_hash"] = "c" * 64
    sign_document(mismatched)
    authorization_path.write_text(json.dumps(mismatched), encoding="utf-8")
    with pytest.raises(ValueError, match="does not bind the selected portfolio hashes"):
        runtime._authorized_mainnet_targets(repo, {}, portfolio)
