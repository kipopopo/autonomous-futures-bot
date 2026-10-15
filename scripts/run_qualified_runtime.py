"""Run the qualified Testnet trader after a verified existing-key writer handoff."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.execution.binance_gateway import (  # noqa: E402
    BinanceFuturesGateway,
    _load_dotenv_fallback,
)
from autonomous_futures.execution.causal_scanner import CausalScanner  # noqa: E402
from autonomous_futures.execution.daily_risk import DailyRiskTracker  # noqa: E402
from autonomous_futures.execution.entry_admission import EntryAdmission  # noqa: E402
from autonomous_futures.execution.exit_invalidation import CausalExitReader  # noqa: E402
from autonomous_futures.execution.lifecycle_coordinator import LifecycleCoordinator  # noqa: E402
from autonomous_futures.execution.portfolio_runtime import (  # noqa: E402
    VerifiedRuntimePortfolio,
    load_admitted_portfolios,
)
from autonomous_futures.execution.qualification_receipts import verify_runtime_report  # noqa: E402
from autonomous_futures.execution.runtime_session import RuntimeSession  # noqa: E402
from autonomous_futures.execution.single_writer_guard import (  # noqa: E402
    LegacyWriterHandoffGuard,
)
from autonomous_futures.execution.writer_lease import ExecutionLease  # noqa: E402
from autonomous_futures.feed.authenticated_user_stream import (  # noqa: E402
    AuthenticatedUserDataStream,
)
from autonomous_futures.feed.closed_history import ClosedHistoryReader  # noqa: E402
from autonomous_futures.feed.kline_sequencer import ACTIVE_PAIRS  # noqa: E402
from autonomous_futures.feed.live_market_feed import LiveMarketFeed  # noqa: E402
from autonomous_futures.feed.runtime_hawkes_calibration import (  # noqa: E402
    load_runtime_hawkes_calibration,
)
from autonomous_futures.feed.runtime_microstructure import RuntimeMicrostructure  # noqa: E402


def admitted_reports(repo: Path) -> dict[tuple[str, str], Path]:
    manifest = json.loads((repo / "deploy/qualification-admission.json").read_bytes())
    reports = {}
    for item in manifest["approved_reports"]:
        path = (repo / item["path"]).resolve()
        if not path.is_relative_to(repo.resolve()):
            raise ValueError("Admitted report must be inside the deployment repository")
        identity = (item["family"], item["symbol"])
        if identity in reports:
            raise ValueError("Duplicate admitted strategy report")
        receipt = verify_runtime_report(path, repo=repo, family=identity[0], symbol=identity[1])
        if receipt.execution_domain is None:
            raise ValueError("Admitted report has no researched runtime execution domain")
        reports[identity] = path
    if not reports:
        raise ValueError("No genuinely qualified deployment reports; runtime cannot activate")
    return reports


def admitted_portfolios(
    repo: Path,
    *,
    require_execution_authority: bool = False,
) -> tuple[VerifiedRuntimePortfolio, ...]:
    portfolios = load_admitted_portfolios(
        repo,
        require_execution_authority=require_execution_authority,
    )
    if not portfolios:
        raise ValueError("No genuinely qualified portfolio reports in admission manifest")
    return portfolios


def resolve_runtime_admission(
    repo: Path,
    *,
    portfolio_id: str | None = None,
) -> tuple[dict[tuple[str, str], Path], VerifiedRuntimePortfolio | None]:
    """Load verified single-strategy reports or fall back to verified portfolio admission."""
    try:
        reports = admitted_reports(repo)
    except ValueError:
        reports = {}
    if reports and portfolio_id is None:
        return reports, None
    portfolios = admitted_portfolios(repo, require_execution_authority=False)
    if portfolio_id is not None:
        matched = [p for p in portfolios if p.portfolio_id == portfolio_id]
        if not matched:
            raise ValueError(
                f"Requested portfolio_id {portfolio_id!r} is not in admission manifest"
            )
        return {}, matched[0]
    if len(portfolios) != 1:
        raise ValueError(
            "Multiple admitted portfolios require an explicit --portfolio-id selection"
        )
    return {}, portfolios[0]


def credentials() -> tuple[str, str]:
    """Read the existing Testnet key pair; no separate writer credential is created."""
    _load_dotenv_fallback()
    names = ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_SECRET_KEY")
    values = tuple(os.environ.get(name, "").strip() for name in names)
    if not all(values) or any(value.startswith("mock-") for value in values):
        raise ValueError("The existing authenticated Testnet API key pair must be configured")
    return values[0], values[1]


async def run(
    directory: Path,
    lease_path: Path,
    equity_basis: str,
    hawkes_calibration_path: Path,
    *,
    repo: Path = REPO,
    portfolio_id: str | None = None,
) -> None:
    reports, portfolio = await asyncio.to_thread(
        resolve_runtime_admission,
        repo,
        portfolio_id=portfolio_id,
    )
    single_writer_guard = LegacyWriterHandoffGuard()
    await asyncio.to_thread(single_writer_guard.assert_legacy_inactive)
    calibration = load_runtime_hawkes_calibration(hawkes_calibration_path, repo)
    writer_key, writer_secret = credentials()
    gateway = BinanceFuturesGateway(writer_key, writer_secret, testnet=True, offline_mode=False)
    lease = ExecutionLease(lease_path)
    lease.acquire()
    try:
        await gateway.sync_clock_drift()
        await gateway.refresh_exchange_filters()
        coordinator = LifecycleCoordinator(gateway, directory, lease=lease)
        monitor = RuntimeMicrostructure(tuple(ACTIVE_PAIRS), calibration=calibration)
        feed = LiveMarketFeed(gateway, monitor)
        coordinator.exit_reader = CausalExitReader(ClosedHistoryReader(gateway), lambda: feed.clock)
        daily = DailyRiskTracker(directory / "daily-risk.json", equity_basis=equity_basis)
        user_stream = AuthenticatedUserDataStream(gateway)
        admission = EntryAdmission(
            coordinator,
            monitor,
            repo=repo,
            single_writer_guard=single_writer_guard,
            user_stream_guard=user_stream.assert_entry_ready,
        )
        scanner = CausalScanner(
            feed,
            repo=repo,
            account_path=coordinator.entries.account_path,
            reports=reports or None,
            portfolio=portfolio,
        )
        await RuntimeSession(coordinator, admission, feed, daily, user_stream).run(scanner)
    finally:
        lease.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-dir", type=Path, required=True)
    parser.add_argument("--account-lease", type=Path, required=True)
    parser.add_argument("--equity-basis", choices=["ACCOUNT"], required=True)
    parser.add_argument("--hawkes-calibration", type=Path, required=True)
    parser.add_argument("--portfolio-id", type=str, default=None)
    args = parser.parse_args()
    asyncio.run(
        run(
            args.storage_dir,
            args.account_lease,
            args.equity_basis,
            args.hawkes_calibration,
            portfolio_id=args.portfolio_id,
        )
    )


if __name__ == "__main__":
    main()
