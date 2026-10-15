import asyncio

import pytest

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
        lambda repo: {("ICT_TWINS", "BTCUSDT"): tmp_path / "admitted-report.json"},
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
