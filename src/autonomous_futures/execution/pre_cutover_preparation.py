"""Non-executing pre-cutover preparation for the qualified shared-wallet portfolio runtime.

Safely normalizes Binance Futures Testnet symbol leverage to the researched portfolio
execution domain (`1x` on `AVAXUSDT`, `ETHUSDT`, `SOLUSDT`) and bootstraps authentic
UTC day-start equity evidence (`daily-risk.json` + `exchange-account.json`) when the
account is provably flat with zero intraday trading income ambiguity.

Never submits, modifies, or cancels any exchange order (`execution_authority = False`).
"""

from __future__ import annotations

import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from autonomous_futures.execution.account_evidence import (
    EXTERNAL_BASIS_INCOME_TYPES,
    SNAPSHOT_NAME,
    TRADING_INCOME_TYPES,
    atomic_json,
    exchange_bool,
    finite_decimal,
    observe_account,
    unique_income,
)
from autonomous_futures.execution.binance_gateway import (
    BinanceAPIError,
    BinanceFuturesGateway,
)
from autonomous_futures.execution.daily_risk import (
    DEFAULT_DAILY_LOSS_PCT,
    DailyRiskTracker,
)
from autonomous_futures.execution.entry_risk import remaining_daily_budget
from autonomous_futures.execution.portfolio_runtime import load_admitted_portfolios
from autonomous_futures.execution.qualification_domain import verify_execution_domain

DAY_MS = 86_400_000


async def set_symbol_leverage(
    gateway: BinanceFuturesGateway,
    symbol: str,
    leverage: int,
) -> dict[str, Any]:
    """Set initial symbol leverage via signed `POST /fapi/v1/leverage`; no orders submitted."""
    if type(leverage) is not int or not 1 <= leverage <= 125:
        raise ValueError("Target leverage must be an integer between 1 and 125")
    if gateway.offline_mode:
        raise ValueError("Cannot normalize exchange symbol leverage in offline mode")
    sym = symbol.upper()
    signed_params = gateway.sign_payload({"symbol": sym, "leverage": leverage})
    headers = {"X-MBX-APIKEY": gateway.api_key}
    async with gateway._get_http_client() as client:
        resp = await client.post("/fapi/v1/leverage", params=signed_params, headers=headers)
        if resp.status_code != 200:
            try:
                err_json = resp.json()
                raise BinanceAPIError(
                    int(err_json.get("code", resp.status_code)),
                    str(err_json.get("msg", resp.text)),
                    status_code=resp.status_code,
                )
            except json.JSONDecodeError:
                raise BinanceAPIError(
                    resp.status_code,
                    resp.text,
                    status_code=resp.status_code,
                ) from None
        payload = cast(dict[str, Any], resp.json())
    if payload.get("symbol") != sym or int(payload.get("leverage", -1)) != leverage:
        raise ValueError(
            "Exchange leverage acknowledgement did not match requested symbol/leverage"
        )
    return payload


async def verify_flat_one_way_account(gateway: BinanceFuturesGateway) -> dict[str, Any]:
    """Require one-way position mode, single-asset USDT margin, and zero positions/orders."""
    if gateway.offline_mode:
        raise ValueError("Pre-cutover account verification requires authenticated exchange access")
    dual_side = await gateway.get_position_mode()
    if dual_side:
        raise ValueError(
            "Qualified runtime requires one-way position mode (dualSidePosition=false)"
        )
    account = await gateway.get_account_balance()
    if exchange_bool(account.get("multiAssetsMargin")):
        raise ValueError("USDT reconciliation requires single-asset margin mode")
    positions = await gateway.get_position_risk()
    open_orders = await gateway.get_open_orders()
    open_algo_orders = await gateway.get_open_algo_orders()

    non_flat = [
        str(row["symbol"])
        for row in positions
        if finite_decimal(row.get("positionAmt", "0")) != Decimal("0")
    ]
    if non_flat or open_orders or open_algo_orders:
        raise ValueError(
            "Pre-cutover preparation requires a flat account with zero open or conditional orders"
        )
    wallet = finite_decimal(account["totalWalletBalance"])
    equity = finite_decimal(account["totalMarginBalance"])
    upnl = finite_decimal(account["totalUnrealizedProfit"])
    if upnl != Decimal("0") or abs(equity - wallet) >= Decimal("1e-15"):
        raise ValueError("Flat account has non-zero unrealized profit or wallet/equity drift")
    return {
        "account": account,
        "positions": positions,
        "open_orders": open_orders,
        "open_algo_orders": open_algo_orders,
        "wallet_usdt": wallet,
        "equity_usdt": equity,
    }


async def reconstruct_utc_day_start_baseline(
    gateway: BinanceFuturesGateway,
    *,
    equity_basis: str = "ACCOUNT",
    limit_pct: Decimal = DEFAULT_DAILY_LOSS_PCT,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Reconstruct authentic UTC midnight equity when the account has zero intraday trades."""
    if equity_basis != "ACCOUNT":
        raise ValueError("An explicitly selected ACCOUNT equity basis is required")
    flat_check = await verify_flat_one_way_account(gateway)
    current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    day = current_ms // DAY_MS
    day_start_ms = day * DAY_MS

    daily_rows = unique_income(await gateway.get_income_history(day_start_ms, current_ms))
    net_external = Decimal("0")
    for row in daily_rows:
        if row.get("asset") != "USDT":
            raise ValueError("Non-USDT income requires separate asset accounting")
        income_type = str(row.get("incomeType", ""))
        if income_type in TRADING_INCOME_TYPES:
            raise ValueError(
                "Cannot reconstruct UTC midnight baseline mid-day when intraday "
                "trading income exists"
            )
        if income_type not in EXTERNAL_BASIS_INCOME_TYPES:
            raise ValueError(f"Unclassified authenticated income type: {income_type}")
        flow_ms = int(row["time"])
        if not day_start_ms <= flow_ms <= current_ms:
            raise ValueError("External flow falls outside the observed UTC day")
        if flow_ms == day_start_ms:
            raise ValueError("External flow timing is ambiguous at the UTC day-start boundary")
        net_external += finite_decimal(row["income"])

    current_wallet = cast(Decimal, flat_check["wallet_usdt"])
    day_start_equity = current_wallet - net_external
    if not day_start_equity.is_finite() or day_start_equity <= Decimal("0"):
        raise ValueError("Reconstructed UTC day-start equity must be positive and finite")

    return {
        "day": day,
        "day_start_equity": str(day_start_equity),
        "captured_ms": day_start_ms,
        "testnet": bool(gateway.testnet),
        "limit_pct": str(limit_pct),
        "equity_basis": "ACCOUNT",
        "breached": False,
        "last_observed_ms": day_start_ms,
    }


async def prepare_portfolio_cutover(
    *,
    repo: Path,
    storage_dir: Path,
    gateway: BinanceFuturesGateway | None = None,
    equity_basis: str = "ACCOUNT",
    apply_leverage: bool = False,
    bootstrap_daily_risk: bool = False,
) -> dict[str, Any]:
    """Verify and optionally apply 1x leverage normalization and UTC day-start risk bootstrap."""
    if equity_basis != "ACCOUNT":
        raise ValueError("Pre-cutover preparation requires equity_basis='ACCOUNT'")
    portfolios = load_admitted_portfolios(repo, require_execution_authority=False)
    if not portfolios:
        raise ValueError("No admitted portfolio qualification receipts found in manifest")

    target_symbols_set: set[str] = set()
    allowed_leverages_set: set[int] = set()
    for p in portfolios:
        target_symbols_set.update(p.symbols)
        dom_levs = p.execution_domain.get("leverages", [])
        if not isinstance(dom_levs, list) or len(dom_levs) != 1 or type(dom_levs[0]) is not int:
            raise ValueError(
                f"Portfolio {p.portfolio_id} execution domain must specify a single "
                "integer leverage"
            )
        allowed_leverages_set.add(dom_levs[0])

    if len(allowed_leverages_set) != 1:
        raise ValueError("Admitted portfolios disagree on required symbol leverage")
    target_leverage = next(iter(allowed_leverages_set))
    target_symbols = tuple(sorted(target_symbols_set))

    gw = gateway or BinanceFuturesGateway(testnet=True, offline_mode=False)
    clock_offset_ms = await gw.sync_clock_drift()
    flat_state = await verify_flat_one_way_account(gw)

    before_configs = await gw.get_symbol_configuration()
    before_map = {
        str(row["symbol"]): int(row["leverage"])
        for row in before_configs
        if "symbol" in row and "leverage" in row
    }
    observed_before: dict[str, int] = {}
    for sym in target_symbols:
        if sym not in before_map:
            raise ValueError(f"Portfolio symbol {sym} is missing from exchange symbolConfig")
        observed_before[sym] = before_map[sym]

    changed_symbols: dict[str, dict[str, int]] = {}
    if apply_leverage:
        for sym in target_symbols:
            if observed_before[sym] != target_leverage:
                await set_symbol_leverage(gw, sym, target_leverage)
                changed_symbols[sym] = {
                    "previous_leverage": observed_before[sym],
                    "new_leverage": target_leverage,
                }
        after_configs = await gw.get_symbol_configuration()
        after_map = {
            str(row["symbol"]): int(row["leverage"])
            for row in after_configs
            if "symbol" in row and "leverage" in row
        }
        observed_after = {sym: after_map[sym] for sym in target_symbols}
        if any(lev != target_leverage for lev in observed_after.values()):
            raise ValueError(
                "Exchange symbolConfig still disagrees with target leverage after update"
            )
    else:
        observed_after = dict(observed_before)

    leverage_ready = all(lev == target_leverage for lev in observed_after.values())

    storage_dir.mkdir(parents=True, exist_ok=True)
    daily_risk_path = storage_dir / "daily-risk.json"
    account_path = storage_dir / SNAPSHOT_NAME

    daily_bootstrapped = False
    daily_risk_summary: dict[str, Any] = {"verified": False}
    domain_verified = False

    if bootstrap_daily_risk:
        now_ms = int(time.time() * 1000)
        current_day = now_ms // DAY_MS
        existing_valid = False
        if daily_risk_path.is_file():
            try:
                existing_state = json.loads(daily_risk_path.read_text(encoding="utf-8"))
                existing_valid = (
                    isinstance(existing_state, dict)
                    and existing_state.get("day") == current_day
                    and existing_state.get("testnet") is bool(gw.testnet)
                    and existing_state.get("equity_basis") == "ACCOUNT"
                    and existing_state.get("limit_pct") == str(DEFAULT_DAILY_LOSS_PCT)
                )
            except Exception:
                existing_valid = False

        if not existing_valid:
            baseline = await reconstruct_utc_day_start_baseline(
                gw,
                equity_basis=equity_basis,
                limit_pct=DEFAULT_DAILY_LOSS_PCT,
                now_ms=now_ms,
            )
            atomic_json(daily_risk_path, baseline, durable=True)
            daily_bootstrapped = True

        tracker = DailyRiskTracker(daily_risk_path, equity_basis=equity_basis)
        snapshot = await observe_account(gw, account_path, risk_tracker=tracker)
        remaining_usdt = remaining_daily_budget(snapshot)
        daily_risk_summary = {
            "verified": True,
            "bootstrapped": daily_bootstrapped,
            "day": snapshot["daily_risk"]["day"],
            "day_start_equity_usdt": snapshot["daily_risk"]["day_start_equity"],
            "captured_ms": snapshot["daily_risk"]["captured_ms"],
            "observed_ms": snapshot["daily_risk"]["observed_ms"],
            "limit_usdt": snapshot["daily_risk"]["limit_usdt"],
            "loss_usdt": snapshot["daily_risk"]["loss_usdt"],
            "remaining_usdt": str(remaining_usdt),
        }
        if leverage_ready:
            for p in portfolios:
                verify_execution_domain(
                    p.execution_domain,
                    snapshot,
                    leverage=target_leverage,
                )
            domain_verified = True

    result: dict[str, Any] = {
        "schema": "portfolio-pre-cutover-preparation-v1",
        "testnet": bool(gw.testnet),
        "clock_offset_ms": clock_offset_ms,
        "flat_one_way_account_verified": True,
        "wallet_balance_usdt": str(flat_state["wallet_usdt"]),
        "margin_balance_usdt": str(flat_state["equity_usdt"]),
        "portfolio_ids": [p.portfolio_id for p in portfolios],
        "target_symbols": list(target_symbols),
        "target_leverage": target_leverage,
        "leverage": {
            "apply_requested": apply_leverage,
            "observed_before": observed_before,
            "observed_after": observed_after,
            "changed_symbols": changed_symbols,
            "matches_domain": leverage_ready,
        },
        "daily_risk": daily_risk_summary,
        "execution_domain_verified": domain_verified,
        "storage_dir": str(storage_dir),
        "account_path": str(account_path) if account_path.is_file() else None,
        "daily_risk_path": str(daily_risk_path) if daily_risk_path.is_file() else None,
        "execution_authority": False,
    }
    result["preparation_hash"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    atomic_json(storage_dir / "pre-cutover-preparation.json", result, durable=True)
    return result
