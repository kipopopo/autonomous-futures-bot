"""Offline, causal strategy-family screening on cached Binance USD-M data.

No network imports, no exchange client, no API credentials, and no order path.
This is a deliberately small hypothesis screen—not a deployable backtest.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
PRIMARY_INTERVAL = "5m"
CONTEXT_INTERVAL = "15m"
PRIMARY_INTERVAL_MS = 300_000
PANDAS_PRIMARY_FREQ = "5min"
PER_SIDE_FEE = 0.0004  # conservative taker assumption; verify signed account rate later
PER_SIDE_SLIPPAGE = 0.0002  # research stress assumption
PER_SIDE_COST = PER_SIDE_FEE + PER_SIDE_SLIPPAGE
PERIODS_PER_YEAR = 365 * 24 * 60 // 5

TRAIN = (pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC"))
VALID = (pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC"))
TEST = (pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp.max.tz_localize("UTC"))


@dataclass(frozen=True)
class Candidate:
    family: str
    params: dict[str, float | int]
    signal_fn: Callable[[pd.DataFrame, dict[str, float | int]], pd.Series]


def align_closed_context(primary_index: pd.DatetimeIndex, closed_context: pd.Series) -> pd.Series:
    """Forward-fill only context values whose source candle had already closed."""
    return closed_context.reindex(primary_index, method="ffill")


def load_symbol(symbol: str, data_dir: Path = DATA) -> pd.DataFrame:
    frame = pd.read_csv(data_dir / f"{symbol}-{PRIMARY_INTERVAL}.csv")
    frame.index = pd.to_datetime(frame.pop("open_time"), unit="ms", utc=True)
    numeric = ["open", "high", "low", "close", "volume"]
    frame[numeric] = frame[numeric].astype(float)
    funding = pd.read_csv(data_dir / f"{symbol}-funding.csv")
    funding.index = pd.to_datetime(funding.pop("fundingTime"), unit="ms", utc=True).dt.floor(
        PANDAS_PRIMARY_FREQ
    )
    rates = funding["fundingRate"].astype(float).groupby(level=0).sum()
    frame["funding_rate"] = rates.reindex(frame.index).fillna(0.0)

    context = pd.read_csv(data_dir / f"{symbol}-{CONTEXT_INTERVAL}.csv")
    context["close"] = context["close"].astype(float)
    # Binance close_time is inclusive (e.g. 00:14:59.999); the candle becomes usable at 00:15.
    context.index = pd.to_datetime(context.pop("close_time"), unit="ms", utc=True) + pd.Timedelta(
        milliseconds=1
    )
    fast = context["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    slow = context["close"].ewm(span=60, adjust=False, min_periods=60).mean()
    closed_trend = np.sign(fast - slow)
    frame["context_trend"] = align_closed_context(frame.index, closed_trend)
    return frame


def rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def adx(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = frame["high"], frame["low"], frame["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = pd.concat(
        [(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().fillna(0.0)


def state_machine(index: pd.Index, decisions: Callable[[int, int], int]) -> pd.Series:
    state = 0
    values = np.zeros(len(index), dtype=np.int8)
    for i in range(len(index)):
        state = decisions(i, state)
        values[i] = state
    return pd.Series(values, index=index, dtype=float)


def ema_signal(frame: pd.DataFrame, p: dict[str, float | int]) -> pd.Series:
    fast = frame["close"].ewm(span=int(p["fast"]), adjust=False).mean()
    slow = frame["close"].ewm(span=int(p["slow"]), adjust=False).mean()
    raw = np.sign(fast - slow)
    warmup = int(p["slow"])
    raw.iloc[:warmup] = 0
    return raw.astype(float)


def donchian_signal(frame: pd.DataFrame, p: dict[str, float | int]) -> pd.Series:
    entry, exit_ = int(p["entry"]), int(p["exit"])
    upper = frame["high"].rolling(entry).max().shift(1).to_numpy()
    lower = frame["low"].rolling(entry).min().shift(1).to_numpy()
    exit_high = frame["high"].rolling(exit_).max().shift(1).to_numpy()
    exit_low = frame["low"].rolling(exit_).min().shift(1).to_numpy()
    close = frame["close"].to_numpy()

    def decide(i: int, state: int) -> int:
        if not all(np.isfinite(x) for x in (upper[i], lower[i], exit_high[i], exit_low[i])):
            return 0
        if state == 0:
            if close[i] > upper[i]:
                return 1
            if close[i] < lower[i]:
                return -1
        elif state == 1 and close[i] < exit_low[i]:
            return 0
        elif state == -1 and close[i] > exit_high[i]:
            return 0
        return state

    return state_machine(frame.index, decide)


def bollinger_signal(frame: pd.DataFrame, p: dict[str, float | int]) -> pd.Series:
    period, z = int(p["period"]), float(p["z"])
    mean = frame["close"].rolling(period).mean().shift(1).to_numpy()
    std = frame["close"].rolling(period).std(ddof=0).shift(1).to_numpy()
    close = frame["close"].to_numpy()

    def decide(i: int, state: int) -> int:
        if not np.isfinite(mean[i]) or not np.isfinite(std[i]) or std[i] <= 0:
            return 0
        if state == 0:
            if close[i] < mean[i] - z * std[i]:
                return 1
            if close[i] > mean[i] + z * std[i]:
                return -1
        elif state == 1 and close[i] >= mean[i]:
            return 0
        elif state == -1 and close[i] <= mean[i]:
            return 0
        return state

    return state_machine(frame.index, decide)


def rsi_reversion_signal(frame: pd.DataFrame, p: dict[str, float | int]) -> pd.Series:
    value = rsi(frame["close"], int(p["period"])).to_numpy()
    low, high = float(p["low"]), float(p["high"])

    def decide(i: int, state: int) -> int:
        if state == 0:
            if value[i] < low:
                return 1
            if value[i] > high:
                return -1
        elif state == 1 and value[i] >= 50:
            return 0
        elif state == -1 and value[i] <= 50:
            return 0
        return state

    return state_machine(frame.index, decide)


def regime_hybrid_signal(frame: pd.DataFrame, p: dict[str, float | int]) -> pd.Series:
    trend_level = float(p["trend_adx"])
    range_level = float(p["range_adx"])
    trend = ema_signal(frame, {"fast": int(p["fast"]), "slow": int(p["slow"])}).to_numpy()
    reversion = bollinger_signal(
        frame, {"period": int(p["bb_period"]), "z": float(p["z"])}
    ).to_numpy()
    strength = adx(frame, int(p["adx_period"])).shift(1).to_numpy()
    context_trend = frame["context_trend"].fillna(0.0).to_numpy()
    values = np.zeros(len(frame), dtype=float)
    previous = 0.0
    for i in range(len(frame)):
        if strength[i] >= trend_level:
            previous = trend[i]
        elif strength[i] <= range_level:
            previous = reversion[i]
        else:
            # Neutral transition band: keep exposure only if the selected sub-strategy agrees.
            if previous != trend[i] and previous != reversion[i]:
                previous = 0.0
        # A 5m entry may only agree with the last fully closed 15m regime candle.
        if previous > 0 and context_trend[i] < 0:
            previous = 0.0
        elif previous < 0 and context_trend[i] > 0:
            previous = 0.0
        values[i] = previous
    return pd.Series(values, index=frame.index)


def candidates() -> list[Candidate]:
    out: list[Candidate] = []
    # Preserve approximately the prior 1h time horizons while receiving a fresh 5m bar cadence.
    for fast, slow in ((144, 576), (288, 1440), (576, 2880), (864, 4320)):
        out.append(Candidate("ema_trend", {"fast": fast, "slow": slow}, ema_signal))
    for entry, exit_ in ((288, 144), (864, 288), (2016, 864), (4032, 1440)):
        out.append(Candidate("donchian_breakout", {"entry": entry, "exit": exit_}, donchian_signal))
    for period, z in itertools.product((240, 576, 1152), (1.5, 2.0, 2.5)):
        out.append(Candidate("bollinger_reversion", {"period": period, "z": z}, bollinger_signal))
    for period, low in itertools.product((84, 168, 336), (20, 30, 35)):
        out.append(
            Candidate(
                "rsi_reversion",
                {"period": period, "low": low, "high": 100 - low},
                rsi_reversion_signal,
            )
        )
    for fast, slow, trend_adx, range_adx in (
        (288, 1440, 25, 18),
        (576, 2880, 25, 18),
        (288, 1440, 30, 20),
    ):
        out.append(
            Candidate(
                "regime_hybrid",
                {
                    "fast": fast,
                    "slow": slow,
                    "trend_adx": trend_adx,
                    "range_adx": range_adx,
                    "adx_period": 168,
                    "bb_period": 576,
                    "z": 2.0,
                },
                regime_hybrid_signal,
            )
        )
    return out


def simulate(frame: pd.DataFrame, signal: pd.Series) -> pd.DataFrame:
    # A signal formed at candle t close may only control the open(t+1)->open(t+2) return.
    position = signal.shift(1).fillna(0.0).clip(-1, 1)
    gross = position * frame["open"].pct_change().shift(-1).fillna(0.0)
    turnover = position.diff().abs().fillna(position.abs())
    execution_cost = turnover * PER_SIDE_COST
    funding_pnl = -position * frame["funding_rate"]
    net = gross - execution_cost + funding_pnl
    entries = ((position != 0) & (position.shift(1).fillna(0) != position)).astype(int)
    return pd.DataFrame(
        {
            "net": net,
            "gross": gross,
            "execution_cost": execution_cost,
            "funding_pnl": funding_pnl,
            "position": position,
            "entries": entries,
        },
        index=frame.index,
    )


def metrics(result: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float | int]:
    sample = result[(result.index >= start) & (result.index < end)].copy()
    returns = sample["net"].replace([np.inf, -np.inf], np.nan).dropna()
    if returns.empty:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "trades": 0,
            "cost_drag": 0.0,
            "funding_pnl": 0.0,
            "bars": 0,
        }
    equity = (1 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1
    std = float(returns.std(ddof=0))
    total = float(equity.iloc[-1] - 1)
    annual = (
        float(equity.iloc[-1] ** (PERIODS_PER_YEAR / len(returns)) - 1)
        if equity.iloc[-1] > 0
        else -1.0
    )
    sharpe = float(returns.mean() / std * math.sqrt(PERIODS_PER_YEAR)) if std > 0 else 0.0
    return {
        "total_return": total,
        "annual_return": annual,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "trades": int(sample["entries"].sum()),
        "cost_drag": float(sample["execution_cost"].sum()),
        "funding_pnl": float(sample["funding_pnl"].sum()),
        "bars": int(len(returns)),
    }


def portfolio_metrics(
    results: dict[str, pd.DataFrame], period: tuple[pd.Timestamp, pd.Timestamp]
) -> dict[str, float | int]:
    combined = pd.concat({symbol: frame for symbol, frame in results.items()}, axis=1)
    net = combined.xs("net", axis=1, level=1).mean(axis=1)
    gross = combined.xs("gross", axis=1, level=1).mean(axis=1)
    cost = combined.xs("execution_cost", axis=1, level=1).mean(axis=1)
    funding = combined.xs("funding_pnl", axis=1, level=1).mean(axis=1)
    entries = combined.xs("entries", axis=1, level=1).sum(axis=1)
    synthetic = pd.DataFrame(
        {
            "net": net,
            "gross": gross,
            "execution_cost": cost,
            "funding_pnl": funding,
            "entries": entries,
        },
        index=combined.index,
    )
    return metrics(synthetic, *period)


def round_metrics(values: dict[str, float | int]) -> dict[str, float | int]:
    return {
        key: (round(value, 6) if isinstance(value, float) else value)
        for key, value in values.items()
    }


def main() -> None:
    frames = {symbol: load_symbol(symbol) for symbol in SYMBOLS}
    evaluated: list[dict[str, object]] = []
    for candidate in candidates():
        results = {
            symbol: simulate(frame, candidate.signal_fn(frame, candidate.params))
            for symbol, frame in frames.items()
        }
        record: dict[str, object] = {"family": candidate.family, "params": candidate.params}
        for label, period in (("train", TRAIN), ("validation", VALID), ("test_2026_ytd", TEST)):
            record[label] = round_metrics(portfolio_metrics(results, period))
            record[f"{label}_symbols"] = {
                symbol: round_metrics(metrics(result, *period))
                for symbol, result in results.items()
            }
        evaluated.append(record)

    selected: list[dict[str, object]] = []
    for family in sorted({str(row["family"]) for row in evaluated}):
        family_rows = [row for row in evaluated if row["family"] == family]
        admissible = [
            row
            for row in family_rows
            if row["train"]["trades"] >= 100 and row["train"]["max_drawdown"] >= -0.50
        ]
        pool = admissible or family_rows
        winner = max(pool, key=lambda row: (row["train"]["sharpe"], row["train"]["total_return"]))
        selected.append(winner)

    payload = {
        "method": {
            "data": (
                "Cached Binance USD-M 5m primary BTCUSDT/ETHUSDT/SOLUSDT "
                "with closed-bar 15m EMA regime context"
            ),
            "timeframe_contract": {
                "primary": PRIMARY_INTERVAL,
                "context": CONTEXT_INTERVAL,
                "annualization_periods": PERIODS_PER_YEAR,
            },
            "selection": (
                "One shared parameter set per family selected only on 2023-2024 portfolio Sharpe, "
                "min 100 entries, max train drawdown 50% where possible"
            ),
            "validation": "2025 frozen parameters",
            "test": "2026 YTD frozen parameters",
            "execution": (
                "Signal at close t; next-open position; 1x notional; "
                "equal-weight robustness portfolio"
            ),
            "per_side_fee": PER_SIDE_FEE,
            "per_side_slippage": PER_SIDE_SLIPPAGE,
            "funding": "Actual public historical funding rates, position-signed",
            "warning": (
                "Screening evidence only; no protective stop/liquidation model; "
                "equal-weight three-symbol portfolio is not directly executable with a $100 wallet "
                "and current symbol minimum notionals."
            ),
        },
        "selected": selected,
        "all_candidates": evaluated,
    }
    output = ROOT / "strategy_screen_results.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("SELECTED FAMILY RESULTS")
    for row in selected:
        print(
            json.dumps(
                {
                    key: row[key]
                    for key in ("family", "params", "train", "validation", "test_2026_ytd")
                },
                indent=2,
            )
        )
    print("WROTE", output)


if __name__ == "__main__":
    main()
