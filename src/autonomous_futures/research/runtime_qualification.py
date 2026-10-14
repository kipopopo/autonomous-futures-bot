"""Causal qualification of the actual runtime strategy, with honest rejection evidence.

Recorded OHLCV replay is research evidence, never a claim of exchange executions.
The same trade planner used by live execution decides which signals are executable.
"""

from __future__ import annotations

import bisect
import csv
import dataclasses
import hashlib
import json
from collections import deque
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pandas as pd

from autonomous_futures.execution.daily_risk import DailyRisk
from autonomous_futures.execution.trade_plan import (
    DEFAULT_CAPITAL_POLICY,
    IneligibleTrade,
    RuntimeCapitalPolicy,
    SymbolFilters,
    TradePlan,
    scalper_plan,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    DEFAULT_RSI_THRESHOLD,
    DEFAULT_VOLUME_SPIKE_MULTIPLIER,
    Candle,
    MacroLiquidityDipScalper,
    MacroTrendFilter,
)

D = Decimal


@dataclasses.dataclass(frozen=True)
class RuntimeQualificationPolicy:
    windows: int = 5
    minimum_trades: int = 30
    minimum_profitable_windows: int = 3
    minimum_profit_factor: Decimal = D("1.10")
    maximum_drawdown_pct: Decimal = D("5")
    starting_equity: Decimal = D("100")
    maker_fee: Decimal = D("0.0002")
    taker_fee: Decimal = D("0.0004")
    stress_slippage: Decimal = D("0.0005")
    fee_stress_multiplier: Decimal = D("2")
    entry_ttl_ms: int = 300_000
    daily_loss_pct: Decimal = DEFAULT_CAPITAL_POLICY.daily_loss_pct
    trade_risk_pct: Decimal = DEFAULT_CAPITAL_POLICY.trade_risk_pct
    trading_day_ms: int = 86_400_000

    def __post_init__(self) -> None:
        if (
            not isinstance(self.starting_equity, Decimal)
            or not self.starting_equity.is_finite()
            or self.starting_equity <= 0
        ):
            raise ValueError("Starting equity must be a positive finite Decimal")

    def capital_policy(self) -> RuntimeCapitalPolicy:
        """Use the same explicit per-trade and daily percentages as runtime sizing."""
        return RuntimeCapitalPolicy(
            daily_loss_pct=self.daily_loss_pct,
            trade_risk_pct=self.trade_risk_pct,
        )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def repo_relative_source_path(path: Path, repo: Path) -> str:
    resolved = path.resolve()
    root = repo.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Qualification input must be inside the repository for portable evidence")
    return resolved.relative_to(root).as_posix()


def authenticated_equity_scenario(path: Path, repo: Path) -> dict[str, Any]:
    """Validate a flat authenticated Testnet snapshot for historical sizing only.

    A current balance is a reproducible sizing seed. It is not evidence of the
    UTC day-start equity used by the live daily-loss circuit breaker.
    """
    root = repo.resolve()
    source_path = path if path.is_absolute() else root / path
    source_path = source_path.resolve()
    if not source_path.is_relative_to(root):
        raise ValueError("Capital evidence must be inside the repository")
    raw = source_path.read_bytes()
    evidence = json.loads(raw)
    if (
        evidence.get("source") != "binance_authenticated_rest"
        or evidence.get("testnet") is not True
    ):
        raise ValueError("Capital evidence must be an authenticated Testnet account snapshot")
    if evidence.get("execution_authority") is not False:
        raise ValueError("Capital evidence cannot grant execution authority")
    reconciliation = evidence.get("reconciliation", {})
    if reconciliation.get("verified") is not True:
        raise ValueError("Capital evidence has no verified account reconciliation")
    try:
        equity = D(str(reconciliation["starting_equity"]))
        wallet_drift = D(str(reconciliation["wallet_drift"]))
        equity_drift = D(str(reconciliation["equity_drift"]))
        observed_ms = evidence["timestamp_ms"]
        observation_sha = evidence["account_observation_sha256"]
    except (KeyError, TypeError, ArithmeticError) as exc:
        raise ValueError("Capital evidence is incomplete") from exc
    if (
        not equity.is_finite()
        or equity <= 0
        or not wallet_drift.is_finite()
        or not equity_drift.is_finite()
        or wallet_drift != 0
        or equity_drift != 0
    ):
        raise ValueError("Capital evidence has invalid equity or non-zero ledger drift")
    if type(observed_ms) is not int or observed_ms <= 0:
        raise ValueError("Capital evidence has an invalid observation timestamp")
    if (
        not isinstance(observation_sha, str)
        or len(observation_sha) != 64
        or any(character not in "0123456789abcdef" for character in observation_sha)
    ):
        raise ValueError("Capital evidence has an invalid account-observation digest")
    if any(
        type(evidence.get(key)) is not int or evidence[key] != 0
        for key in ("open_position_count", "ordinary_orders", "conditional_orders")
    ):
        raise ValueError("Capital sizing evidence must describe a flat account with no open orders")
    return {
        "schema": "authenticated-testnet-equity-scenario-v1",
        "evidence": {
            "path": repo_relative_source_path(source_path, root),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "source": evidence["source"],
        "testnet": True,
        "observed_ms": observed_ms,
        "starting_equity": str(equity),
        "account_observation_sha256": observation_sha,
        "wallet_and_equity_reconciled": True,
        "flat_account": True,
        "utc_day_start_baseline_verified": evidence.get("daily_risk", {}).get("verified") is True,
        "purpose": "historical_sizing_seed_only_not_live_daily_risk_evidence",
        "execution_authority": False,
    }


def qualification_capital(
    *,
    repo: Path,
    starting_equity: Decimal | None = None,
    equity_evidence_path: Path | None = None,
) -> tuple[RuntimeQualificationPolicy, dict[str, Any] | None]:
    """Resolve an explicit research capital scenario without inventing live baselines."""
    if starting_equity is not None and equity_evidence_path is not None:
        raise ValueError("Choose either --starting-equity or --equity-evidence")
    if equity_evidence_path is not None:
        scenario = authenticated_equity_scenario(equity_evidence_path, repo)
        return RuntimeQualificationPolicy(starting_equity=D(scenario["starting_equity"])), scenario
    if starting_equity is not None:
        return RuntimeQualificationPolicy(starting_equity=starting_equity), None
    return RuntimeQualificationPolicy(), None


def bind_commission_policy(
    policy: RuntimeQualificationPolicy,
    commissions_path: Path,
    symbol: str,
    repo: Path,
) -> tuple[RuntimeQualificationPolicy, dict[str, Any]]:
    """Freeze the symbol's authenticated Testnet maker/taker rates into replay policy."""
    source_path = commissions_path if commissions_path.is_absolute() else repo / commissions_path
    source_path = source_path.resolve()
    raw = source_path.read_bytes()
    evidence = json.loads(raw)
    if (
        evidence.get("source") != "https://testnet.binancefuture.com/fapi/v1/commissionRate"
        or type(evidence.get("observed_ms")) is not int
        or evidence["observed_ms"] <= 0
        or not isinstance(evidence.get("rates"), list)
    ):
        raise ValueError("Commission evidence must be an authenticated Testnet snapshot")
    matches = [row for row in evidence["rates"] if row.get("symbol") == symbol]
    if len(matches) != 1:
        raise ValueError("Commission evidence must contain exactly one record for the symbol")
    rate = matches[0]
    try:
        maker, taker = D(str(rate["maker"])), D(str(rate["taker"]))
    except (KeyError, TypeError, ArithmeticError) as exc:
        raise ValueError("Commission evidence is incomplete") from exc
    response_sha = rate.get("response_sha256")
    if (
        not maker.is_finite()
        or not taker.is_finite()
        or not 0 <= maker < 1
        or not 0 <= taker < 1
        or not isinstance(response_sha, str)
        or len(response_sha) != 64
        or any(character not in "0123456789abcdef" for character in response_sha)
    ):
        raise ValueError("Commission evidence contains invalid rates or response identity")
    resolved = dataclasses.replace(policy, maker_fee=maker, taker_fee=taker)
    binding = {
        "path": repo_relative_source_path(source_path, repo),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source": evidence["source"],
        "observed_ms": evidence["observed_ms"],
        "symbol": symbol,
        "maker": str(maker),
        "taker": str(taker),
    }
    return resolved, binding


def bind_equity_scenario(
    report: dict[str, Any], scenario: dict[str, Any] | None, repo: Path
) -> dict[str, Any]:
    """Attach the sizing snapshot to report provenance and recompute its identity."""
    if scenario is None:
        return report
    result = json.loads(json.dumps(report, default=str))
    if D(str(result["policy"]["starting_equity"])) != D(str(scenario["starting_equity"])):
        raise ValueError("Capital evidence does not match the frozen starting equity")
    if scenario.get("execution_authority") is not False:
        raise ValueError("Capital evidence cannot grant execution authority")
    verified_scenario = authenticated_equity_scenario(Path(str(scenario["evidence"]["path"])), repo)
    if verified_scenario != scenario:
        raise ValueError("Capital evidence changed after the replay was frozen")
    sources = dict(result["sources"])
    if "capital_scenario" in sources:
        raise ValueError("Report already contains capital-scenario provenance")
    sources["capital_scenario"] = dict(scenario["evidence"])
    result["sources"] = sources
    result["source_files"] = source_file_index(sources, repo)
    result["capital_scenario"] = scenario
    result.pop("report_hash", None)
    result["report_hash"] = content_hash(result)
    return cast(dict[str, Any], json.loads(json.dumps(result, default=str)))


def source_file_index(sources: dict[str, Any], repo: Path) -> list[dict[str, str]]:
    """Index every path/hash pair embedded in report provenance and verify its bytes."""
    indexed: dict[str, str] = {}
    required: set[str] = set()

    def collect(item: Any) -> None:
        if isinstance(item, dict):
            path_value = item.get("path")
            sha = item.get("sha256")
            if isinstance(path_value, str) and isinstance(sha, str):
                path = Path(path_value)
                candidate = path if path.is_absolute() else repo / path
                relative = repo_relative_source_path(candidate, repo)
                if digest(repo / relative) != sha:
                    raise ValueError(f"Qualification source bytes changed: {relative}")
                previous = indexed.setdefault(relative, sha)
                if previous != sha:
                    raise ValueError(f"Conflicting qualification source hashes: {relative}")
            for value in item.values():
                collect(value)
        elif isinstance(item, list):
            for value in item:
                collect(value)
        elif (
            isinstance(item, str)
            and len(item) == 64
            and all(character in "0123456789abcdef" for character in item)
        ):
            required.add(item)

    collect(sources)
    if not indexed:
        raise ValueError("Qualification report has no indexed source files")
    if not required.issubset(set(indexed.values())):
        raise ValueError("Qualification source provenance contains an unindexed hash")
    return [{"path": path, "sha256": indexed[path]} for path in sorted(indexed)]


def verified_bars(
    root: Path, symbol: str, timeframe: str, *, repo: Path | None = None
) -> tuple[list[Candle], dict[str, Any]]:
    manifest_path = root / timeframe / "manifests" / f"{symbol}-{timeframe}.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    path = root / timeframe / "canonical" / f"{symbol}-{timeframe}.parquet"
    expected = next(
        item
        for item in manifest["source_files"]
        if item["relative_path"] == f"canonical/{symbol}-{timeframe}.parquet"
    )
    if digest(path) != expected["sha256"]:
        raise ValueError(f"Dataset hash mismatch: {path}")
    frame = pd.read_parquet(path)
    if len(frame) != expected["rows"]:
        raise ValueError("Dataset row count disagrees with the source manifest")
    duration = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000}[timeframe]
    bars: list[Candle] = []
    for row in frame.itertuples(index=False):
        ts = int(row.timestamp.value // 1_000_000)
        bar = Candle(ts, row.open, row.high, row.low, row.close, row.volume)
        if (
            not all(v.is_finite() for v in (bar.open, bar.high, bar.low, bar.close, bar.volume))
            or min(bar.open, bar.high, bar.low, bar.close) <= 0
            or bar.volume < 0
            or bar.high < max(bar.open, bar.close, bar.low)
            or bar.low > min(bar.open, bar.close)
            or int(row.close_time.value // 1_000_000) != ts + duration - 1
        ):
            raise ValueError("Invalid or unclosed source candle")
        if bars and ts - bars[-1].timestamp_ms != duration:
            raise ValueError("Unrepaired source gap; qualification must not interpolate")
        bars.append(bar)
    common = {
        "rows": len(bars),
        "first_ms": bars[0].timestamp_ms,
        "last_close_ms": bars[-1].timestamp_ms + duration,
    }
    if repo is None:
        return bars, {
            "path": str(path),
            "sha256": expected["sha256"],
            **common,
            "manifest_sha256": digest(manifest_path),
        }
    return bars, {
        "dataset": {
            "path": repo_relative_source_path(path, repo),
            "sha256": expected["sha256"],
        },
        "manifest": {
            "path": repo_relative_source_path(manifest_path, repo),
            "sha256": digest(manifest_path),
        },
        **common,
    }


def four_hour_bars(hourly: list[Candle]) -> list[Candle]:
    """Aggregate only complete, consecutive recorded hours; never synthesize gaps."""
    buckets: dict[int, list[Candle]] = {}
    for bar in hourly:
        buckets.setdefault(bar.timestamp_ms // 14_400_000 * 14_400_000, []).append(bar)
    result = []
    for start, bars in buckets.items():
        if [b.timestamp_ms for b in bars] != [start + i * 3_600_000 for i in range(4)]:
            continue
        result.append(
            Candle(
                start,
                bars[0].open,
                max(b.high for b in bars),
                min(b.low for b in bars),
                bars[-1].close,
                sum((b.volume for b in bars), D("0")),
            )
        )
    return result


def exact_scalper_candidates(
    bars: list[Candle],
    *,
    rsi_threshold: Decimal = DEFAULT_RSI_THRESHOLD,
    volume_multiplier: Decimal = DEFAULT_VOLUME_SPIKE_MULTIPLIER,
) -> list[int]:
    """Exact Decimal RSI/volume screen; every full-runtime signal passes this screen.

    The short setup uses the symmetric overbought threshold. EMA, ATR and directional
    macro confirmation are evaluated by the actual runtime implementation.
    """
    gains: deque[Decimal] = deque()
    losses: deque[Decimal] = deque()
    volumes: deque[Decimal] = deque()
    gain_sum = loss_sum = volume_sum = D("0")
    result = []
    for index, bar in enumerate(bars):
        delta = bar.close - bars[index - 1].close if index else D("0")
        gain, loss = max(delta, D("0")), max(-delta, D("0"))
        gains.append(gain)
        losses.append(loss)
        gain_sum += gain
        loss_sum += loss
        volumes.append(bar.volume)
        volume_sum += bar.volume
        if len(gains) > 14:
            gain_sum -= gains.popleft()
            loss_sum -= losses.popleft()
        if len(volumes) > 20:
            volume_sum -= volumes.popleft()
        if index < 20:
            continue
        if loss_sum == 0:
            rsi = D("100") if gain_sum > 0 else D("50")
        else:
            rsi = D("100") - D("100") / (D("1") + gain_sum / loss_sum)
        volume_average = volume_sum / 20
        if (
            volume_average > 0
            and (rsi < rsi_threshold or rsi > D("100") - rsi_threshold)
            and bar.volume > volume_average * volume_multiplier
        ):
            result.append(index)
    return result


def load_funding(path: Path, symbol: str) -> list[tuple[int, Decimal, Decimal | None]]:
    result = []
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if row["symbol"] != symbol:
                raise ValueError("Funding symbol mismatch")
            rate = D(row["fundingRate"])
            mark = D(row["markPrice"]) if row["markPrice"] else None
            if not rate.is_finite() or (mark is not None and (not mark.is_finite() or mark <= 0)):
                raise ValueError("Invalid funding observation")
            result.append((int(row["fundingTime"]), rate, mark))
    if result != sorted(result, key=lambda item: item[0]) or len({r[0] for r in result}) != len(
        result
    ):
        raise ValueError("Funding observations must be ordered and unique")
    return result


def replay_plan(
    plan: TradePlan,
    execution: list[Candle],
    funding: list[tuple[int, Decimal, Decimal | None]],
    policy: RuntimeQualificationPolicy,
    window_end_ms: int,
    *,
    execution_opens: list[int] | None = None,
    wallet: Decimal | None = None,
    day_start_equity: Decimal | None = None,
    risk_day: int | None = None,
) -> dict[str, Any] | None:
    """Require a post-decision trade-through; resolve ambiguous candles against the strategy."""
    opens = (
        execution_opens if execution_opens is not None else [bar.timestamp_ms for bar in execution]
    )
    index = bisect.bisect_left(opens, plan.decision_ms)
    entry_bar = None
    for candidate_index in range(index, len(execution)):
        bar = execution[candidate_index]
        if bar.timestamp_ms >= min(plan.decision_ms + policy.entry_ttl_ms, window_end_ms):
            break
        if (
            bar.low < plan.entry <= bar.open
            if plan.side == "BUY"
            else bar.high > plan.entry >= bar.open
        ):
            entry_bar = bar
            break
    if entry_bar is None:
        return None
    sign = D("1") if plan.side == "BUY" else D("-1")
    exit_price, reason, exit_ms = None, "TIME_STOP", 0
    deadline = min(entry_bar.timestamp_ms + plan.hold_ms, window_end_ms)
    wallet = policy.starting_equity if wallet is None else wallet
    day_start_equity = wallet if day_start_equity is None else day_start_equity
    risk_day = entry_bar.timestamp_ms // policy.trading_day_ms if risk_day is None else risk_day
    entry_fee = plan.notional * policy.maker_fee
    accrued_funding = D("0")
    funding_cursor = bisect.bisect_right([f[0] for f in funding], entry_bar.timestamp_ms)
    prior_mark = plan.entry
    minimum_equity = wallet - entry_fee
    for bar_index in range(bisect.bisect_left(opens, entry_bar.timestamp_ms), len(execution)):
        bar = execution[bar_index]
        if bar.timestamp_ms >= window_end_ms:
            break
        current_day = bar.timestamp_ms // policy.trading_day_ms
        if current_day != risk_day:
            # UTC boundary valuation uses only the last closed candle, never the next close.
            day_start_equity = (
                wallet
                - entry_fee
                - accrued_funding
                + sign * (prior_mark - plan.entry) * plan.quantity
            )
            risk_day = current_day
        while funding_cursor < len(funding) and funding[funding_cursor][0] <= bar.timestamp_ms:
            _, rate, mark = funding[funding_cursor]
            accrued_funding += sign * plan.quantity * (prior_mark if mark is None else mark) * rate
            funding_cursor += 1
        adverse = bar.low if sign == 1 else bar.high
        adverse_equity = (
            wallet - entry_fee - accrued_funding + sign * (adverse - plan.entry) * plan.quantity
        )
        # A protective stop truncates the adverse candle path unless the candle opens beyond it.
        protected_price = min(plan.stop, bar.open) if sign == 1 else max(plan.stop, bar.open)
        protected_equity = (
            wallet
            - entry_fee
            - accrued_funding
            + sign * (protected_price - plan.entry) * plan.quantity
        )
        minimum_equity = min(minimum_equity, max(adverse_equity, protected_equity))
        daily = DailyRisk(day_start_equity, adverse_equity, limit_pct=policy.daily_loss_pct)
        stop_hit = bar.low <= plan.stop if sign == 1 else bar.high >= plan.stop
        # Filling and crossing a stop in the same OHLC candle is adverse, not a free profit.
        target_hit = bar.high > plan.tp1 if sign == 1 else bar.low < plan.tp1
        stop_equity = (
            wallet - entry_fee - accrued_funding + sign * (plan.stop - plan.entry) * plan.quantity
        )
        daily_precedes_stop = DailyRisk(
            day_start_equity, stop_equity, limit_pct=policy.daily_loss_pct
        ).breached
        if stop_hit and not daily_precedes_stop:
            exit_price = min(plan.stop, bar.open) if sign == 1 else max(plan.stop, bar.open)
            reason = "STOP_LOSS"
        elif daily.breached:
            loss_price = (
                plan.entry
                + sign
                * (
                    day_start_equity * (1 - policy.daily_loss_pct / 100)
                    - wallet
                    + entry_fee
                    + accrued_funding
                )
                / plan.quantity
            )
            exit_price = min(loss_price, bar.open) if sign == 1 else max(loss_price, bar.open)
            reason = "DAILY_LOSS"
        elif bar.timestamp_ms > entry_bar.timestamp_ms and target_hit:
            exit_price, reason = plan.tp1, "TAKE_PROFIT"
        elif bar.timestamp_ms + 300_000 >= deadline:
            exit_price = bar.close
        if exit_price is not None:
            exit_ms = bar.timestamp_ms + 300_000
            break
        prior_mark = bar.close
    if exit_price is None:
        return None
    gross = sign * (exit_price - plan.entry) * plan.quantity
    exit_fee_rate = policy.maker_fee if reason == "TAKE_PROFIT" else policy.taker_fee
    fees = plan.notional * policy.maker_fee + plan.quantity * exit_price * exit_fee_rate
    funding_paid = D("0")
    approximate_marks = 0
    for when, rate, mark in funding:
        if entry_bar.timestamp_ms < when <= exit_ms:
            if mark is None:
                prior = max(0, bisect.bisect_left(opens, when) - 1)
                mark = execution[prior].close
                approximate_marks += 1
            funding_paid += sign * plan.quantity * mark * rate
    stress_cost = (
        fees * policy.fee_stress_multiplier
        + (plan.notional + plan.quantity * exit_price) * policy.stress_slippage
    )
    return {
        "risk_day": risk_day,
        "day_start_equity": str(day_start_equity),
        "minimum_equity": str(minimum_equity),
        "plan": plan.to_dict(),
        "entry_ms": entry_bar.timestamp_ms,
        "exit_ms": exit_ms,
        "exit_price": str(exit_price),
        "reason": reason,
        "gross_pnl": str(gross),
        "fees": str(fees),
        "funding_payment": str(funding_paid),
        "net_pnl": str(gross - fees - funding_paid),
        "stress_net_pnl": str(gross - stress_cost - funding_paid),
        "funding_mark_approximations": approximate_marks,
    }


def qualify_scalper(
    *,
    cache: Path,
    funding_path: Path,
    filters_path: Path,
    commissions_path: Path,
    symbol: str,
    oos_start_ms: int,
    repo: Path,
    policy: RuntimeQualificationPolicy,
) -> dict[str, Any]:
    resolved_policy, commission_evidence = bind_commission_policy(
        policy, commissions_path, symbol, repo
    )
    if resolved_policy != policy:
        raise ValueError("Frozen qualification fees do not match authenticated commission rates")
    bars, market_evidence = verified_bars(cache, symbol, "15m", repo=repo)
    execution, execution_evidence = verified_bars(cache, symbol, "5m", repo=repo)
    btc, macro_evidence = verified_bars(cache, "BTCUSDT", "1h", repo=repo)
    btc4h = four_hour_bars(btc)
    filters_data = json.loads(filters_path.read_text(encoding="utf-8"))
    filters = SymbolFilters(
        **{key: D(value) for key, value in filters_data["specs"][symbol].items()}
    )
    funding = load_funding(funding_path, symbol)
    if (
        not funding
        or funding[0][0] > oos_start_ms
        or funding[-1][0] < bars[-1].timestamp_ms - 28_800_000
    ):
        raise ValueError("Funding observations do not cover the OOS period")
    sources = {
        "market": market_evidence,
        "execution": execution_evidence,
        "macro": macro_evidence,
        "funding": {
            "path": repo_relative_source_path(funding_path, repo),
            "sha256": digest(funding_path),
        },
        "commissions": commission_evidence,
        "exchange_filters": {
            "path": repo_relative_source_path(filters_path, repo),
            "sha256": digest(filters_path),
            "source": filters_data["source"],
            "observed_ms": filters_data["observed_ms"],
        },
    }
    source_files = source_file_index(sources, repo)
    implementation = {
        name: digest(repo / name)
        for name in (
            "src/autonomous_futures/strategy/macro_liquidity_scalper.py",
            "src/autonomous_futures/execution/trade_plan.py",
            "src/autonomous_futures/execution/daily_risk.py",
            "src/autonomous_futures/research/runtime_qualification.py",
        )
    }
    end_ms = min(bars[-1].timestamp_ms + 900_000, execution[-1].timestamp_ms + 300_000)
    width = (end_ms - oos_start_ms) // policy.windows // 300_000 * 300_000
    if width <= 0:
        raise ValueError("No OOS interval")
    windows: list[dict[str, Any]] = [
        {
            "start_ms": oos_start_ms + i * width,
            "end_ms": end_ms if i == policy.windows - 1 else oos_start_ms + (i + 1) * width,
            "trades": [],
            "signals": 0,
            "ineligible": 0,
            "unfilled": 0,
        }
        for i in range(policy.windows)
    ]
    engine, macro = MacroLiquidityDipScalper(), MacroTrendFilter()
    hour_closes = [b.timestamp_ms + 3_600_000 for b in btc]
    four_closes = [b.timestamp_ms + 14_400_000 for b in btc4h]
    next_available = oos_start_ms
    execution_opens = [b.timestamp_ms for b in execution]
    wallet = day_start_equity = policy.starting_equity
    risk_day = oos_start_ms // policy.trading_day_ms
    rejection_reasons: dict[str, int] = {}
    for index in exact_scalper_candidates(
        bars,
        rsi_threshold=engine.rsi_threshold,
        volume_multiplier=engine.vol_spike_multiplier,
    ):
        bar = bars[index]
        decision_ms = bar.timestamp_ms + 900_000
        if not oos_start_ms <= decision_ms < end_ms or decision_ms < next_available:
            continue
        hi = bisect.bisect_right(hour_closes, decision_ms)
        fi = bisect.bisect_right(four_closes, decision_ms)
        regime = macro.evaluate_regime(btc[max(0, hi - 250) : hi], btc4h[max(0, fi - 250) : fi])
        signal = engine.evaluate_15m_bar(symbol, bar, bars[max(0, index - 249) : index], regime)
        if signal is None:
            continue
        window = windows[min(policy.windows - 1, (decision_ms - oos_start_ms) // width)]
        window["signals"] += 1
        current_day = decision_ms // policy.trading_day_ms
        if current_day != risk_day:
            day_start_equity, risk_day = wallet, current_day
        daily = DailyRisk(day_start_equity, wallet, limit_pct=policy.daily_loss_pct)
        if daily.breached or wallet <= 0:
            window["ineligible"] += 1
            rejection_reasons["Daily loss budget exhausted"] = (
                rejection_reasons.get("Daily loss budget exhausted", 0) + 1
            )
            continue
        try:
            plan = scalper_plan(
                signal,
                filters,
                tuple(filters_data.get("allowed_leverages", {}).get(symbol, [1])),
                capital=policy.capital_policy(),
                equity=wallet,
                available_margin=wallet,
                remaining_daily_risk=daily.remaining_usdt,
            )
        except IneligibleTrade as exc:
            window["ineligible"] += 1
            rejection_reasons[str(exc)] = rejection_reasons.get(str(exc), 0) + 1
            continue
        trade = replay_plan(
            plan,
            execution,
            funding,
            policy,
            window["end_ms"],
            execution_opens=execution_opens,
            wallet=wallet,
            day_start_equity=day_start_equity,
            risk_day=risk_day,
        )
        if trade is None:
            window["unfilled"] += 1
            continue
        window["trades"].append(trade)
        next_available = trade["exit_ms"]
        wallet += D(trade["net_pnl"])
        day_start_equity, risk_day = D(trade["day_start_equity"]), int(trade["risk_day"])
    trades = [trade for window in windows for trade in window["trades"]]
    profits = sum((max(D(t["net_pnl"]), D("0")) for t in trades), D("0"))
    losses = sum((max(-D(t["net_pnl"]), D("0")) for t in trades), D("0"))
    net, stress_net = profits - losses, sum((D(t["stress_net_pnl"]) for t in trades), D("0"))
    peak = equity = policy.starting_equity
    drawdown = D("0")
    for trade in trades:
        drawdown = max(drawdown, peak - D(trade["minimum_equity"]))
        equity += D(trade["net_pnl"])
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    profitable_windows = sum(
        sum((D(t["net_pnl"]) for t in w["trades"]), D("0")) > 0 for w in windows
    )
    gates = {
        "sufficient_oos_samples": len(trades) >= policy.minimum_trades,
        "positive_net_edge": net > 0,
        "profit_factor": bool(trades)
        and (losses == 0 or profits / losses >= policy.minimum_profit_factor),
        "drawdown": drawdown / policy.starting_equity * 100 <= policy.maximum_drawdown_pct,
        "window_consistency": profitable_windows >= policy.minimum_profitable_windows,
        "stress_positive": stress_net > 0,
    }
    if source_file_index(sources, repo) != source_files:
        raise ValueError("Qualification inputs changed during replay")
    report = {
        "version": 1,
        "family": "MACRO_SCALPER",
        "symbol": symbol,
        "policy": dataclasses.asdict(policy),
        "policy_hash": content_hash(dataclasses.asdict(policy)),
        "sources": sources,
        "source_files": source_files,
        "implementation": implementation,
        "configuration": dataclasses.asdict(engine)
        if dataclasses.is_dataclass(engine)
        else {key: str(value) for key, value in vars(engine).items()},
        "windows": windows,
        "rejection_reasons": rejection_reasons,
        "metrics": {
            "trade_count": len(trades),
            "net_pnl": str(net),
            "stress_net_pnl": str(stress_net),
            "drawdown_usdt": str(drawdown),
            "profitable_windows": profitable_windows,
        },
        "gates": gates,
        "decision": "QUALIFIED" if all(gates.values()) else "REJECTED",
        "execution_authority": False,
        "assumptions": [
            "current deployment filters apply; leverage defaults to 1 without verified brackets",
            "single-symbol research equity; this is not exchange or portfolio qualification",
            "daily loss is 5% of UTC day-start equity; OHLC execution is approximate",
            "maker fill requires subsequent candle trade-through",
            "ambiguous entry/stop candles resolve against the strategy",
            "missing historical funding marks use the last closed execution candle",
            "historical OHLCV replay does not qualify live microstructure by itself",
        ],
    }
    report["report_hash"] = content_hash(report)
    return cast(dict[str, Any], json.loads(json.dumps(report, default=str)))
