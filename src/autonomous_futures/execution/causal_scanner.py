"""Actual canonical strategy evaluation on completed exchange candle histories."""

from __future__ import annotations

import asyncio
import dataclasses
import time
from pathlib import Path

from autonomous_futures.execution.account_evidence import finite_decimal, read_account
from autonomous_futures.execution.entry_risk import remaining_daily_budget
from autonomous_futures.execution.ict_reclaim_entry import IctReclaimEntryStore
from autonomous_futures.execution.qualification_domain import verify_execution_domain
from autonomous_futures.execution.qualification_receipts import (
    HistoricalQualification,
    verify_runtime_report,
)
from autonomous_futures.execution.runtime_session import QualifiedIntention
from autonomous_futures.execution.trade_plan import (
    IneligibleTrade,
    SymbolFilters,
    ict_plan,
    scalper_plan,
)
from autonomous_futures.feed.closed_history import ClosedHistoryReader
from autonomous_futures.feed.live_market_feed import LiveMarketFeed
from autonomous_futures.strategy.ict_mmxm import Candle as IctCandle
from autonomous_futures.strategy.ict_mmxm import IctMmxmEngine
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    MacroLiquidityDipScalper,
    MacroTrendFilter,
)


class CausalScanner:
    def __init__(
        self,
        feed: LiveMarketFeed,
        *,
        repo: Path,
        account_path: Path,
        reports: dict[tuple[str, str], Path],
    ) -> None:
        if not reports or any(
            family not in {"MACRO_SCALPER", "ICT_TWINS"} or symbol not in feed.monitor.symbols
            for family, symbol in reports
        ):
            raise ValueError("Scanner reports must bind canonical families and active feed symbols")
        self.feed, self.repo, self.account_path = feed, repo, account_path
        self.reports = tuple(reports.items())
        self.reader = ClosedHistoryReader(feed.gateway)
        self.cursor = 0
        self.receipts: dict[Path, HistoricalQualification] = {}
        self.reclaim_entries = IctReclaimEntryStore(
            account_path.with_name("ict-reclaim-entry-state.json"), repo
        )

    async def __call__(self) -> QualifiedIntention | None:
        (family, symbol), path = self.reports[self.cursor]
        self.cursor = (self.cursor + 1) % len(self.reports)
        receipt = self.receipts.get(path)
        if receipt is None:
            receipt = await asyncio.to_thread(
                verify_runtime_report, path, repo=self.repo, family=family, symbol=symbol
            )
            self.receipts[path] = receipt
        if self.feed.clock is None or not self.feed.connected:
            raise ValueError("Causal scan requires a connected observed exchange clock")
        local_ms = time.time_ns() // 1_000_000
        decision = self.feed.clock.completed_boundary(local_ms, 60_000)
        account = read_account(self.account_path, local_ms)
        budget = remaining_daily_budget(account)
        configuration = next(
            (row for row in account["symbol_configuration"] if row["symbol"] == symbol), None
        )
        if configuration is None:
            raise ValueError("Symbol leverage has no authenticated configuration")
        equity = finite_decimal(account["account"]["totalMarginBalance"])
        available = finite_decimal(account["account"]["availableBalance"])
        leverages = (int(configuration["leverage"]),)
        verify_execution_domain(receipt.execution_domain, account, leverage=leverages[0])
        filters = SymbolFilters.from_gateway(self.feed.gateway.symbol_specs[symbol])
        if family == "ICT_TWINS":
            ict = IctMmxmEngine()
            entry_mode = receipt.configuration.get("entry_mode", "limit_touch")
            if entry_mode not in {"limit_touch", "reclaim_retest"}:
                raise ValueError("ICT qualification uses an unsupported live entry mode")
            expected = {
                "history_bars": 250,
                "htf_pda_timeframes": ["4h", "1h"],
                **{key: str(value) for key, value in vars(ict).items()},
            }
            if "entry_mode" in receipt.configuration:
                expected["entry_mode"] = entry_mode
            if receipt.configuration != expected:
                raise ValueError("ICT runtime configuration differs from qualification")
            four, hourly, five, minute = await asyncio.gather(
                *(
                    self.reader.read(symbol, timeframe, decision)
                    for timeframe in ("4h", "1h", "5m", "1m")
                )
            )
            if entry_mode == "reclaim_retest":
                candidate = self.reclaim_entries.get(symbol)
                if candidate is not None:
                    readiness_ms = self.reclaim_entries.advance(
                        symbol,
                        minute,
                        decision,
                        report_path=path,
                        report_hash=receipt.report_hash,
                        entry_ttl_ms=int(receipt.policy["entry_ttl_ms"]),
                    )
                    if readiness_ms is not None:
                        return QualifiedIntention(
                            candidate.plan, path, readiness_ms, candidate.report_hash
                        )
                    if self.reclaim_entries.get(symbol) is not None:
                        return None
            setup = await asyncio.to_thread(
                ict.evaluate_twins_setup, symbol, four, hourly, [], five, minute, filters.tick_size
            )
            if not setup.step_6_ready:
                return None
            try:
                plan = ict_plan(setup, decision, filters, leverages, equity, available, budget)
            except IneligibleTrade:
                return None
            if entry_mode == "reclaim_retest":
                self.reclaim_entries.begin(
                    plan,
                    path,
                    receipt.report_hash,
                    entry_ttl_ms=int(receipt.policy["entry_ttl_ms"]),
                )
                return None
        else:
            scalper = MacroLiquidityDipScalper()
            expected = {key: str(value) for key, value in vars(scalper).items()}
            if receipt.configuration != expected:
                raise ValueError("Scalper runtime configuration differs from qualification")
            raw, btc_hour, btc_four = await asyncio.gather(
                self.reader.read(symbol, "15m", decision),
                self.reader.read("BTCUSDT", "1h", decision),
                self.reader.read("BTCUSDT", "4h", decision),
            )

            def convert(bars: tuple[IctCandle, ...]) -> list[Candle]:
                return [Candle(**dataclasses.asdict(bar)) for bar in bars]

            bars = convert(raw)
            macro_regime = MacroTrendFilter().evaluate_regime(convert(btc_hour), convert(btc_four))
            signal = scalper.evaluate_15m_bar(symbol, bars[-1], bars[:-1], macro_regime)
            if signal is None:
                return None
            try:
                plan = scalper_plan(signal, filters, leverages, equity, available, budget)
            except IneligibleTrade:
                return None
        return QualifiedIntention(plan, path, report_hash=receipt.report_hash)
