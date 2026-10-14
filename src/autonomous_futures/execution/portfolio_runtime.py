"""Runtime multi-variant shared-wallet portfolio adapter and causal scanner.

Connects a cryptographically verified `SHARED_WALLET_PORTFOLIO` qualification receipt
(such as the 6-member `macro-scalper-uninspected-3sym-medium-frequency-v1` portfolio)
to live completed-bar evaluation (`PortfolioCausalScanner`) and entry admission while
enforcing:
- deterministic `(symbol, member_id)` priority ordering across variants on the same symbol
- strict one-active-order-or-position-per-symbol confinement
- shared-wallet researched execution domain (`verify_execution_domain`)
- 0.5% trade risk and 5% UTC daily loss limit
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from autonomous_futures.execution.account_evidence import finite_decimal, read_account
from autonomous_futures.execution.entry_risk import remaining_daily_budget
from autonomous_futures.execution.qualification_domain import verify_execution_domain
from autonomous_futures.execution.qualification_receipts import (
    PortfolioHistoricalQualification,
    verify_runtime_portfolio_report,
)
from autonomous_futures.execution.runtime_session import QualifiedIntention
from autonomous_futures.execution.trade_plan import (
    IneligibleTrade,
    SymbolFilters,
    scalper_plan,
)
from autonomous_futures.feed.closed_history import ClosedHistoryReader
from autonomous_futures.feed.live_market_feed import LiveMarketFeed
from autonomous_futures.strategy.ict_mmxm import Candle as IctCandle
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    MacroLiquidityDipScalper,
    MacroTrendFilter,
)


@dataclasses.dataclass(frozen=True)
class RuntimePortfolioMember:
    portfolio_id: str
    member_id: str
    symbol: str
    family: str = "MACRO_SCALPER"
    distance_threshold: Decimal = Decimal("-2.8")
    target_atr_multiplier: Decimal = Decimal("1.8")
    stop_atr_multiplier: Decimal = Decimal("1.2")
    rsi_threshold: Decimal = Decimal("26.0")
    vol_spike_multiplier: Decimal = Decimal("2.2")
    max_hold_bars: int = 8

    def __post_init__(self) -> None:
        if self.family != "MACRO_SCALPER":
            raise ValueError(f"Unsupported runtime portfolio member family: {self.family}")
        if not self.member_id or not self.symbol:
            raise ValueError("Portfolio member requires non-empty member_id and symbol")
        if self.distance_threshold >= Decimal("0"):
            raise ValueError("Portfolio member distance_threshold must be negative")
        if self.target_atr_multiplier <= Decimal("0") or self.stop_atr_multiplier <= Decimal("0"):
            raise ValueError("Portfolio member ATR multipliers must be positive")
        if not Decimal("0") < self.rsi_threshold < Decimal("100"):
            raise ValueError("Portfolio member rsi_threshold must be in (0, 100)")
        if self.vol_spike_multiplier <= Decimal("0"):
            raise ValueError("Portfolio member vol_spike_multiplier must be positive")
        if type(self.max_hold_bars) is not int or self.max_hold_bars < 1:
            raise ValueError("Portfolio member max_hold_bars must be a positive integer")

    def create_engine(self) -> MacroLiquidityDipScalper:
        return MacroLiquidityDipScalper(
            rsi_threshold=self.rsi_threshold,
            vol_spike_multiplier=self.vol_spike_multiplier,
            dist_atr_threshold=self.distance_threshold,
            tp_atr_mult=self.target_atr_multiplier,
            sl_atr_mult=self.stop_atr_multiplier,
            max_hold_bars=self.max_hold_bars,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "member_id": self.member_id,
            "symbol": self.symbol,
            "family": self.family,
            "distance_threshold": str(self.distance_threshold),
            "target_atr_multiplier": str(self.target_atr_multiplier),
            "stop_atr_multiplier": str(self.stop_atr_multiplier),
            "rsi_threshold": str(self.rsi_threshold),
            "vol_spike_multiplier": str(self.vol_spike_multiplier),
            "max_hold_bars": self.max_hold_bars,
        }


@dataclasses.dataclass(frozen=True)
class VerifiedRuntimePortfolio:
    portfolio_id: str
    family: str
    symbols: tuple[str, ...]
    report_path: Path
    report_hash: str
    selection_hash: str
    development_report_hash: str
    members: tuple[RuntimePortfolioMember, ...]
    members_by_symbol: dict[str, tuple[RuntimePortfolioMember, ...]]
    policy: dict[str, Any]
    execution_domain: dict[str, Any]
    execution_authority: bool = False

    def get_member(self, member_id: str) -> RuntimePortfolioMember:
        for member in self.members:
            if member.member_id == member_id:
                return member
        raise ValueError(f"Unknown member_id {member_id!r} in portfolio {self.portfolio_id!r}")


def build_verified_runtime_portfolio(
    receipt: PortfolioHistoricalQualification,
    *,
    report_path: Path,
) -> VerifiedRuntimePortfolio:
    """Construct a validated `VerifiedRuntimePortfolio` from a verified receipt."""
    if receipt.execution_domain is None:
        raise ValueError("Admitted portfolio report has no researched runtime execution domain")
    parsed_members: list[RuntimePortfolioMember] = []
    seen_ids: set[str] = set()
    for raw in receipt.members:
        member_id = str(raw["member_id"])
        if member_id in seen_ids:
            raise ValueError(f"Duplicate portfolio member_id: {member_id}")
        seen_ids.add(member_id)
        symbol = str(raw["symbol"])
        if symbol not in receipt.symbols:
            raise ValueError(f"Portfolio member symbol {symbol} outside receipt symbols")
        parsed_members.append(
            RuntimePortfolioMember(
                portfolio_id=receipt.portfolio_id,
                member_id=member_id,
                symbol=symbol,
                family=str(raw.get("family", receipt.family)),
                distance_threshold=finite_decimal(raw["distance_threshold"]),
                target_atr_multiplier=finite_decimal(raw["target_atr_multiplier"]),
                stop_atr_multiplier=finite_decimal(raw["stop_atr_multiplier"]),
                rsi_threshold=finite_decimal(raw["rsi_threshold"]),
                vol_spike_multiplier=finite_decimal(raw["vol_spike_multiplier"]),
                max_hold_bars=int(raw["max_hold_bars"]),
            )
        )
    if not parsed_members:
        raise ValueError("Portfolio receipt contains no members")
    sorted_members = tuple(sorted(parsed_members, key=lambda m: (m.symbol, m.member_id)))
    by_symbol: dict[str, tuple[RuntimePortfolioMember, ...]] = {}
    for sym in receipt.symbols:
        sym_members = tuple(m for m in sorted_members if m.symbol == sym)
        if not sym_members:
            raise ValueError(f"Portfolio symbol {sym} has no assigned members")
        by_symbol[sym] = sym_members
    return VerifiedRuntimePortfolio(
        portfolio_id=receipt.portfolio_id,
        family=receipt.family,
        symbols=receipt.symbols,
        report_path=report_path,
        report_hash=receipt.report_hash,
        selection_hash=receipt.selection_hash or "",
        development_report_hash=receipt.development_report_hash or "",
        members=sorted_members,
        members_by_symbol=by_symbol,
        policy=dict(receipt.policy),
        execution_domain=dict(receipt.execution_domain),
        execution_authority=receipt.execution_authority,
    )


def load_admitted_portfolios(
    repo: Path,
    *,
    require_execution_authority: bool = False,
) -> tuple[VerifiedRuntimePortfolio, ...]:
    """Load and cryptographically verify all admitted portfolio receipts."""
    manifest_path = repo / "deploy" / "qualification-admission.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "runtime-qualification-admission-v1":
        raise ValueError("Unsupported reviewed qualification admission manifest")
    entries = manifest.get("approved_portfolio_reports", [])
    if not isinstance(entries, list):
        raise ValueError("approved_portfolio_reports must be a list")
    portfolios: list[VerifiedRuntimePortfolio] = []
    seen_ids: set[str] = set()
    for item in entries:
        pid = str(item["portfolio_id"])
        if pid in seen_ids:
            raise ValueError(f"Duplicate admitted portfolio_id: {pid}")
        seen_ids.add(pid)
        rel_path = str(item.get("holdout_report_path") or item["path"])
        path = (repo / rel_path).resolve()
        if not path.is_relative_to(repo.resolve()):
            raise ValueError("Admitted portfolio report must be inside the deployment repository")
        receipt = verify_runtime_portfolio_report(path, repo=repo, portfolio_id=pid)
        portfolio = build_verified_runtime_portfolio(receipt, report_path=path)
        if require_execution_authority and not portfolio.execution_authority:
            raise ValueError(
                f"Admitted portfolio {pid!r} has execution_authority=False; "
                "live order dispatch remains locked"
            )
        portfolios.append(portfolio)
    return tuple(portfolios)


def symbol_is_occupied(
    symbol: str,
    account: dict[str, Any],
    *,
    pending_symbols: tuple[str, ...] = (),
) -> bool:
    """Return True if `symbol` already has an active position, open order, or pending entry."""
    if symbol in pending_symbols:
        return True
    if any(
        row.get("symbol") == symbol and finite_decimal(row.get("positionAmt", "0")) != Decimal("0")
        for row in account.get("positions", [])
    ):
        return True
    return any(
        row.get("symbol") == symbol and row.get("reduceOnly") not in (True, "true")
        for row in account.get("open_orders", [])
    )


class PortfolioCausalScanner:
    """Evaluate a verified multi-variant shared-wallet portfolio on completed exchange bars."""

    def __init__(
        self,
        feed: LiveMarketFeed,
        *,
        repo: Path,
        account_path: Path,
        portfolio: VerifiedRuntimePortfolio,
        pending_symbols_provider: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        if portfolio.family != "MACRO_SCALPER":
            raise ValueError("PortfolioCausalScanner requires a MACRO_SCALPER portfolio")
        missing = [
            sym for sym in (*portfolio.symbols, "BTCUSDT") if sym not in feed.monitor.symbols
        ]
        if missing:
            raise ValueError(
                f"Portfolio symbols missing from active market feed: {', '.join(missing)}"
            )
        self.feed = feed
        self.repo = repo
        self.account_path = account_path
        self.portfolio = portfolio
        self.reader = ClosedHistoryReader(feed.gateway)
        self.cursor = 0
        self._verified = False
        self._pending_symbols_provider = pending_symbols_provider

    def _pending_symbols(self) -> tuple[str, ...]:
        if self._pending_symbols_provider is not None:
            return self._pending_symbols_provider()
        owned_path = self.account_path.with_name("owned-trades.json")
        if not owned_path.is_file():
            return ()
        try:
            trades = json.loads(owned_path.read_text(encoding="utf-8"))
            return tuple(
                sorted(
                    {
                        str(trade["plan"]["symbol"])
                        for trade in trades.values()
                        if not trade.get("closed", False)
                    }
                )
            )
        except Exception:
            return ()

    async def __call__(self) -> QualifiedIntention | None:
        symbol = self.portfolio.symbols[self.cursor]
        self.cursor = (self.cursor + 1) % len(self.portfolio.symbols)
        if not self._verified:
            receipt = await asyncio.to_thread(
                verify_runtime_portfolio_report,
                self.portfolio.report_path,
                repo=self.repo,
                portfolio_id=self.portfolio.portfolio_id,
            )
            if receipt.report_hash != self.portfolio.report_hash:
                raise ValueError("Portfolio report hash changed since scanner initialization")
            self._verified = True
        if self.feed.clock is None or not self.feed.connected:
            raise ValueError("Causal portfolio scan requires a connected observed exchange clock")
        local_ms = time.time_ns() // 1_000_000
        decision = self.feed.clock.completed_boundary(local_ms, 60_000)
        account = read_account(self.account_path, local_ms)
        budget = remaining_daily_budget(account)
        configuration = next(
            (row for row in account["symbol_configuration"] if row["symbol"] == symbol),
            None,
        )
        if configuration is None:
            raise ValueError("Symbol leverage has no authenticated configuration")
        equity = finite_decimal(account["account"]["totalMarginBalance"])
        available = finite_decimal(account["account"]["availableBalance"])
        leverages = (int(configuration["leverage"]),)
        pending_syms = self._pending_symbols()
        verify_execution_domain(
            self.portfolio.execution_domain,
            account,
            leverage=leverages[0],
            pending_symbols=pending_syms,
        )
        if symbol_is_occupied(symbol, account, pending_symbols=pending_syms):
            return None
        filters = SymbolFilters.from_gateway(self.feed.gateway.symbol_specs[symbol])
        raw, btc_hour, btc_four = await asyncio.gather(
            self.reader.read(symbol, "15m", decision),
            self.reader.read("BTCUSDT", "1h", decision),
            self.reader.read("BTCUSDT", "4h", decision),
        )

        def convert(bars: tuple[IctCandle, ...]) -> list[Candle]:
            return [Candle(**dataclasses.asdict(bar)) for bar in bars]

        bars = convert(raw)
        macro_regime = MacroTrendFilter().evaluate_regime(convert(btc_hour), convert(btc_four))
        for member in self.portfolio.members_by_symbol[symbol]:
            scalper = member.create_engine()
            signal = scalper.evaluate_15m_bar(symbol, bars[-1], bars[:-1], macro_regime)
            if signal is None:
                continue
            try:
                plan = scalper_plan(signal, filters, leverages, equity, available, budget)
            except IneligibleTrade:
                continue
            return QualifiedIntention(
                plan=plan,
                report_path=self.portfolio.report_path,
                readiness_ms=None,
                report_hash=self.portfolio.report_hash,
                portfolio_id=self.portfolio.portfolio_id,
                member_id=member.member_id,
            )
        return None
