"""Run an admitted futures runtime after a verified single-writer handoff."""

from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

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

RuntimeEnvironment = Literal["testnet", "mainnet"]


def _environment_manifest_path(repo: Path, environment: RuntimeEnvironment) -> Path:
    if environment == "testnet":
        return repo / "deploy" / "qualification-admission.json"
    if environment == "mainnet":
        return repo / "deploy" / "mainnet-qualification-admission.json"
    raise ValueError(f"Unsupported runtime environment: {environment!r}")


def _require_environment_domain(
    execution_domain: dict[str, object] | None,
    *,
    environment: RuntimeEnvironment,
    identity: str,
) -> None:
    expected_testnet = environment == "testnet"
    if (
        not isinstance(execution_domain, dict)
        or type(execution_domain.get("testnet")) is not bool
        or execution_domain["testnet"] is not expected_testnet
    ):
        raise ValueError(f"{identity} qualification execution domain does not match {environment}")


def _validate_runtime_paths(
    directory: Path,
    lease_path: Path,
    *,
    environment: RuntimeEnvironment,
    repo: Path,
) -> None:
    if environment == "testnet":
        return
    if environment != "mainnet":
        raise ValueError(f"Unsupported runtime environment: {environment!r}")
    resolved_directory = directory.resolve()
    resolved_lease = lease_path.resolve()
    if resolved_directory.name != "qualified-mainnet":
        raise ValueError("Mainnet runtime storage directory must be named qualified-mainnet")
    if resolved_directory.is_relative_to(repo.resolve()):
        raise ValueError("Mainnet runtime storage must be outside the deployment repository")
    if resolved_lease == resolved_directory or not resolved_lease.is_relative_to(
        resolved_directory
    ):
        raise ValueError("Mainnet account lease must be inside its isolated storage directory")


def admitted_reports(
    repo: Path,
    *,
    environment: RuntimeEnvironment = "testnet",
    admission_manifest_path: Path | None = None,
) -> dict[tuple[str, str], Path]:
    manifest_path = (
        admission_manifest_path or _environment_manifest_path(repo, environment)
    ).resolve()
    if not manifest_path.is_relative_to(repo.resolve()):
        raise ValueError("Qualification admission manifest must be inside the repository")
    if not manifest_path.is_file():
        if environment == "mainnet":
            raise ValueError("Mainnet admission manifest is missing; Mainnet runtime is disabled")
        raise ValueError("Qualification admission manifest is missing")
    manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError("Qualification admission manifest must be a JSON object")
    if manifest.get("schema") != "runtime-qualification-admission-v1":
        raise ValueError("Unsupported reviewed qualification admission manifest")
    reports = {}
    approved_reports = manifest.get("approved_reports", [])
    if not isinstance(approved_reports, list):
        raise ValueError("approved_reports must be a list")
    for item in approved_reports:
        if not isinstance(item, dict):
            raise ValueError("approved_reports entries must be JSON objects")
        path = (repo / item["path"]).resolve()
        if not path.is_relative_to(repo.resolve()):
            raise ValueError("Admitted report must be inside the deployment repository")
        identity = (item["family"], item["symbol"])
        if identity in reports:
            raise ValueError("Duplicate admitted strategy report")
        receipt = verify_runtime_report(
            path,
            repo=repo,
            family=identity[0],
            symbol=identity[1],
            admission_manifest_path=manifest_path,
        )
        if receipt.execution_domain is None:
            raise ValueError("Admitted report has no researched runtime execution domain")
        _require_environment_domain(
            receipt.execution_domain,
            environment=environment,
            identity=f"{identity[0]} {identity[1]}",
        )
        reports[identity] = path
    return reports


def admitted_portfolios(
    repo: Path,
    *,
    require_execution_authority: bool = False,
    environment: RuntimeEnvironment = "testnet",
    admission_manifest_path: Path | None = None,
) -> tuple[VerifiedRuntimePortfolio, ...]:
    portfolios = load_admitted_portfolios(
        repo,
        require_execution_authority=require_execution_authority,
        admission_manifest_path=admission_manifest_path
        or _environment_manifest_path(repo, environment),
    )
    if not portfolios:
        raise ValueError("No genuinely qualified portfolio reports in admission manifest")
    for portfolio in portfolios:
        _require_environment_domain(
            portfolio.execution_domain,
            environment=environment,
            identity=f"Portfolio {portfolio.portfolio_id!r}",
        )
    return portfolios


def runtime_execution_evidence_context(
    repo: Path,
    *,
    environment: RuntimeEnvironment,
    reports: dict[tuple[str, str], Path],
    portfolio: VerifiedRuntimePortfolio | None,
) -> dict[str, object]:
    """Bind future event evidence to the exact admission and source receipts."""
    manifest_path = _environment_manifest_path(repo, environment).resolve()
    if not manifest_path.is_relative_to(repo.resolve()) or not manifest_path.is_file():
        raise ValueError("Execution evidence requires the selected admission manifest")

    candidates: list[dict[str, object]] = []
    report_paths = (
        [(None, portfolio.report_path)]
        if portfolio is not None
        else sorted(reports.items(), key=lambda item: item[0])
    )
    for identity, report_path in report_paths:
        report_path = report_path.resolve()
        if not report_path.is_relative_to(repo.resolve()) or not report_path.is_file():
            raise ValueError("Execution evidence report must be inside the deployment repository")
        raw = report_path.read_bytes()
        report = json.loads(raw)
        if not isinstance(report, dict) or not isinstance(report.get("implementation"), dict):
            raise ValueError("Execution evidence report has no implementation hash binding")
        implementation = report["implementation"]
        if not implementation or any(
            not isinstance(path, str)
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for path, digest in implementation.items()
        ):
            raise ValueError("Execution evidence report has invalid implementation hashes")
        candidate: dict[str, object] = {
            "report_path": report_path.relative_to(repo.resolve()).as_posix(),
            "report_hash": portfolio.report_hash
            if portfolio is not None
            else report.get("report_hash"),
            "report_file_sha256": hashlib.sha256(raw).hexdigest(),
            "implementation_hashes": dict(sorted(implementation.items())),
        }
        if portfolio is not None:
            candidate.update(
                {
                    "portfolio_id": portfolio.portfolio_id,
                    "selection_hash": portfolio.selection_hash,
                    "symbols": list(portfolio.symbols),
                }
            )
        else:
            assert identity is not None
            candidate.update({"family": identity[0], "symbol": identity[1]})
        candidates.append(candidate)
    return {
        "environment": environment,
        "admission_manifest_path": manifest_path.relative_to(repo.resolve()).as_posix(),
        "admission_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "candidates": candidates,
    }


def resolve_runtime_admission(
    repo: Path,
    *,
    portfolio_id: str | None = None,
    environment: RuntimeEnvironment = "testnet",
) -> tuple[dict[tuple[str, str], Path], VerifiedRuntimePortfolio | None]:
    """Load verified single-strategy reports or fall back to verified portfolio admission."""
    manifest_path = _environment_manifest_path(repo, environment)
    reports = admitted_reports(
        repo,
        environment=environment,
        admission_manifest_path=manifest_path,
    )
    if reports and portfolio_id is None:
        return reports, None
    portfolios = admitted_portfolios(
        repo,
        require_execution_authority=False,
        environment=environment,
        admission_manifest_path=manifest_path,
    )
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


def credentials(environment: RuntimeEnvironment = "testnet") -> tuple[str, str]:
    """Read only the key pair belonging to the explicitly selected environment."""
    _load_dotenv_fallback()
    if environment == "testnet":
        names = ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_SECRET_KEY")
    elif environment == "mainnet":
        names = ("BINANCE_MAINNET_API_KEY", "BINANCE_MAINNET_SECRET_KEY")
    else:
        raise ValueError(f"Unsupported runtime environment: {environment!r}")
    values = tuple(os.environ.get(name, "").strip() for name in names)
    if not all(values) or any(value.startswith("mock-") for value in values):
        raise ValueError(f"Authenticated {environment} API key pair must be configured")
    return values[0], values[1]


def _authorized_mainnet_targets(
    repo: Path,
    reports: dict[tuple[str, str], Path],
    portfolio: VerifiedRuntimePortfolio | None,
) -> None:
    """Require an offline-signed Mainnet authority separate from research receipts."""
    path = repo / "deploy" / "mainnet-execution-authorization.json"
    if not path.is_file():
        raise ValueError("Mainnet execution authorization is missing; Mainnet runtime is disabled")
    authorization = json.loads(path.read_bytes())
    if not isinstance(authorization, dict):
        raise ValueError("Mainnet execution authorization must be a JSON object")
    if (
        authorization.get("schema") != "runtime-mainnet-execution-authorization-v1"
        or authorization.get("environment") != "mainnet"
        or authorization.get("execution_authority") is not True
    ):
        raise ValueError("Mainnet execution authorization is invalid or disabled")
    if not all(
        isinstance(authorization.get(key), str) and authorization[key].strip()
        for key in ("authorization_id", "approved_by", "approved_at_utc", "expires_at_utc")
    ):
        raise ValueError("Mainnet execution authorization is missing its review metadata")
    try:
        approved_at = dt.datetime.fromisoformat(
            authorization["approved_at_utc"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("Mainnet authorization approved_at_utc is invalid") from exc
    if approved_at.tzinfo is None or approved_at.utcoffset() is None:
        raise ValueError("Mainnet authorization approved_at_utc must include a timezone")
    try:
        expires_at = dt.datetime.fromisoformat(
            authorization["expires_at_utc"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("Mainnet authorization expires_at_utc is invalid") from exc
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("Mainnet authorization expires_at_utc must include a timezone")
    now = dt.datetime.now(dt.UTC)
    if approved_at > now + dt.timedelta(minutes=2):
        raise ValueError("Mainnet authorization approval time is in the future")
    if expires_at <= now or expires_at <= approved_at:
        raise ValueError("Mainnet authorization is expired or has an invalid expiry")
    if expires_at - approved_at > dt.timedelta(days=30):
        raise ValueError("Mainnet authorization validity cannot exceed 30 days")

    unsigned = dict(authorization)
    declared_hash = unsigned.pop("authorization_hash", None)
    signature = unsigned.pop("authorization_signature_ed25519", None)
    canonical_payload = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    actual_hash = hashlib.sha256(canonical_payload).hexdigest()
    if not isinstance(declared_hash, str) or declared_hash != actual_hash:
        raise ValueError("Mainnet execution authorization hash is invalid")
    if not isinstance(signature, str) or not signature:
        raise ValueError("Mainnet authorization requires an offline Ed25519 signature")

    public_key_value = os.environ.get("AFBOT_MAINNET_AUTHORIZATION_PUBLIC_KEY_FILE", "").strip()
    if not public_key_value:
        raise ValueError(
            "Mainnet authorization public key is not configured; Mainnet runtime is disabled"
        )
    public_key_path = Path(public_key_value).expanduser().resolve()
    if not public_key_path.is_absolute() or public_key_path.is_relative_to(repo.resolve()):
        raise ValueError(
            "Mainnet authorization public key must be configured outside the repository"
        )
    if not public_key_path.is_file():
        raise ValueError("Mainnet authorization public key file is missing")
    try:
        public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("Mainnet authorization public key must use Ed25519")
        public_key.verify(base64.b64decode(signature, validate=True), canonical_payload)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ValueError("Mainnet authorization signature or public key is invalid") from exc

    if portfolio is not None:
        targets = authorization.get("approved_portfolios", [])
        if not isinstance(targets, list):
            raise ValueError("approved_portfolios must be a list")
        matches = [
            item
            for item in targets
            if isinstance(item, dict) and item.get("portfolio_id") == portfolio.portfolio_id
        ]
        if len(matches) != 1:
            raise ValueError("Mainnet authorization does not uniquely bind the selected portfolio")
        target = matches[0]
        if (
            target.get("report_hash") != portfolio.report_hash
            or target.get("selection_hash") != portfolio.selection_hash
        ):
            raise ValueError("Mainnet authorization does not bind the selected portfolio hashes")
        return

    targets = authorization.get("approved_reports", [])
    if not isinstance(targets, list):
        raise ValueError("approved_reports must be a list")
    for (family, symbol), report_path in reports.items():
        report = json.loads(report_path.read_bytes())
        report_hash = report.get("report_hash")
        matches = [
            item
            for item in targets
            if isinstance(item, dict)
            and item.get("family") == family
            and item.get("symbol") == symbol
        ]
        if len(matches) != 1 or matches[0].get("report_hash") != report_hash:
            raise ValueError(f"Mainnet authorization does not bind {family} {symbol}")


async def run(
    directory: Path,
    lease_path: Path,
    equity_basis: str,
    hawkes_calibration_path: Path,
    *,
    repo: Path = REPO,
    portfolio_id: str | None = None,
    environment: RuntimeEnvironment = "testnet",
) -> None:
    _validate_runtime_paths(directory, lease_path, environment=environment, repo=repo)
    reports, portfolio = await asyncio.to_thread(
        resolve_runtime_admission,
        repo,
        portfolio_id=portfolio_id,
        environment=environment,
    )
    if environment == "mainnet":
        _authorized_mainnet_targets(repo, reports, portfolio)
    single_writer_guard = LegacyWriterHandoffGuard()
    await asyncio.to_thread(single_writer_guard.assert_legacy_inactive)
    execution_evidence_context = await asyncio.to_thread(
        runtime_execution_evidence_context,
        repo,
        environment=environment,
        reports=reports,
        portfolio=portfolio,
    )
    calibration = load_runtime_hawkes_calibration(hawkes_calibration_path, repo)
    writer_key, writer_secret = credentials(environment)
    gateway = BinanceFuturesGateway(
        writer_key,
        writer_secret,
        testnet=environment == "testnet",
        offline_mode=False,
    )
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
            admission_manifest_path=_environment_manifest_path(repo, environment),
        )
        scanner = CausalScanner(
            feed,
            repo=repo,
            account_path=coordinator.entries.account_path,
            reports=reports or None,
            portfolio=portfolio,
            admission_manifest_path=_environment_manifest_path(repo, environment),
        )
        await RuntimeSession(
            coordinator,
            admission,
            feed,
            daily,
            user_stream,
            execution_evidence_context=execution_evidence_context,
        ).run(scanner)
    finally:
        lease.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-dir", type=Path, required=True)
    parser.add_argument("--account-lease", type=Path, required=True)
    parser.add_argument("--equity-basis", choices=["ACCOUNT"], required=True)
    parser.add_argument("--hawkes-calibration", type=Path, required=True)
    parser.add_argument("--portfolio-id", type=str, default=None)
    parser.add_argument(
        "--environment",
        choices=("testnet", "mainnet"),
        default="testnet",
        help=(
            "Execution environment; Mainnet requires its own qualified receipt and reviewed "
            "authorization."
        ),
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            args.storage_dir,
            args.account_lease,
            args.equity_basis,
            args.hawkes_calibration,
            portfolio_id=args.portfolio_id,
            environment=args.environment,
        )
    )


if __name__ == "__main__":
    main()
