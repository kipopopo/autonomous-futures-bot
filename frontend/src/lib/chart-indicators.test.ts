import { describe, expect, it } from 'vitest'
import {
  calculateEma,
  calculateOhlcSummary,
  calculateVolumeSeries,
  generateSyntheticKlines,
  type MarketKline,
} from './chart-indicators'

function makeKline(
  timestamp: number,
  open: number,
  high: number,
  low: number,
  close: number,
  volume: number = 1000,
): MarketKline {
  return { timestamp, open, high, low, close, volume }
}

describe('calculateEma', () => {
  it('returns empty array when input data is empty, null, or undefined', () => {
    expect(calculateEma([], 50)).toEqual([])
    expect(calculateEma(null, 50)).toEqual([])
    expect(calculateEma(undefined, 50)).toEqual([])
  })

  it('returns empty array when period is zero or negative', () => {
    const klines = [makeKline(100, 10, 15, 8, 12)]
    expect(calculateEma(klines, 0)).toEqual([])
    expect(calculateEma(klines, -5)).toEqual([])
  })

  it('correctly calculates SMA seed and subsequent EMA when data.length >= period', () => {
    // 5 bars, period = 3.
    // Multiplier k = 2 / (3 + 1) = 0.5.
    // Closes: 10, 20, 30, 40, 50
    // Initial SMA for first 3 bars: (10 + 20 + 30) / 3 = 20.
    // Point 1 (time 300): 20
    // Point 2 (time 400): 40 * 0.5 + 20 * 0.5 = 30
    // Point 3 (time 500): 50 * 0.5 + 30 * 0.5 = 40
    const klines: MarketKline[] = [
      makeKline(100, 10, 12, 9, 10),
      makeKline(200, 20, 22, 19, 20),
      makeKline(300, 30, 32, 29, 30),
      makeKline(400, 40, 42, 39, 40),
      makeKline(500, 50, 52, 49, 50),
    ]

    const ema = calculateEma(klines, 3)
    expect(ema).toHaveLength(3)
    expect(ema[0]).toEqual({ time: 300, value: 20 })
    expect(ema[1]).toEqual({ time: 400, value: 30 })
    expect(ema[2]).toEqual({ time: 500, value: 40 })
  })

  it('handles warmup mode when data.length < period by seeding from index 0', () => {
    // 2 bars, period = 5.
    // Multiplier k = 2 / (5 + 1) = 2/6 = 1/3 ~ 0.333333...
    // Bar 0 close = 10 -> initial seed = 10
    // Bar 1 close = 20 -> EMA = 20 * (1/3) + 10 * (2/3) = 6.666667 + 6.666667 = 13.3333
    const klines: MarketKline[] = [
      makeKline(1000, 10, 12, 9, 10),
      makeKline(1060, 20, 22, 19, 20),
    ]

    const ema = calculateEma(klines, 5)
    expect(ema).toHaveLength(2)
    expect(ema[0]).toEqual({ time: 1000, value: 10 })
    expect(ema[1].time).toBe(1060)
    expect(ema[1].value).toBeCloseTo(13.3333, 3)
  })

  it('computes EMA 50 on realistic 100-candle series with proper length and continuity', () => {
    const klines = generateSyntheticKlines('SOLUSDT', '15m', 100)
    const ema50 = calculateEma(klines, 50)

    // With 100 bars and period 50: length should be 100 - 50 + 1 = 51 points
    expect(ema50).toHaveLength(51)
    expect(ema50[0].time).toBe(klines[49].timestamp)
    expect(ema50[ema50.length - 1].time).toBe(klines[99].timestamp)

    for (const pt of ema50) {
      expect(Number.isFinite(pt.value)).toBe(true)
      expect(pt.value).toBeGreaterThan(0)
    }
  })

  it('computes EMA 200 on 100-candle series using warmup mode without errors', () => {
    const klines = generateSyntheticKlines('BTCUSDT', '15m', 100)
    const ema200 = calculateEma(klines, 200)

    // Since 100 < 200, warmup mode outputs all 100 bars
    expect(ema200).toHaveLength(100)
    expect(ema200[0].time).toBe(klines[0].timestamp)
    expect(ema200[0].value).toBe(Number(klines[0].close.toFixed(4)))

    for (const pt of ema200) {
      expect(Number.isFinite(pt.value)).toBe(true)
      expect(pt.value).toBeGreaterThan(0)
    }
  })

  it('handles single candle input', () => {
    const kline = [makeKline(500, 100, 105, 95, 102)]
    const ema1 = calculateEma(kline, 1)
    expect(ema1).toEqual([{ time: 500, value: 102 }])

    const ema10 = calculateEma(kline, 10)
    expect(ema10).toEqual([{ time: 500, value: 102 }])
  })
})

describe('calculateVolumeSeries', () => {
  it('returns empty array when input data is empty, null, or undefined', () => {
    expect(calculateVolumeSeries([])).toEqual([])
    expect(calculateVolumeSeries(null)).toEqual([])
    expect(calculateVolumeSeries(undefined)).toEqual([])
  })

  it('assigns emerald color for bullish and doji candles (close >= open)', () => {
    const klines: MarketKline[] = [
      makeKline(100, 100, 110, 95, 105, 5000), // Bullish: close > open
      makeKline(200, 105, 115, 100, 105, 3000), // Doji: close == open
    ]

    const volumeSeries = calculateVolumeSeries(klines)
    expect(volumeSeries).toHaveLength(2)
    expect(volumeSeries[0]).toEqual({
      time: 100,
      value: 5000,
      color: 'rgba(16, 185, 129, 0.5)',
    })
    expect(volumeSeries[1]).toEqual({
      time: 200,
      value: 3000,
      color: 'rgba(16, 185, 129, 0.5)',
    })
  })

  it('assigns rose color for bearish candles (close < open)', () => {
    const klines: MarketKline[] = [
      makeKline(100, 105, 110, 95, 98, 4200), // Bearish: close < open
    ]

    const volumeSeries = calculateVolumeSeries(klines)
    expect(volumeSeries).toHaveLength(1)
    expect(volumeSeries[0]).toEqual({
      time: 100,
      value: 4200,
      color: 'rgba(244, 63, 94, 0.5)',
    })
  })
})

describe('calculateOhlcSummary', () => {
  it('returns null for empty, null, or undefined input', () => {
    expect(calculateOhlcSummary([])).toBeNull()
    expect(calculateOhlcSummary(null)).toBeNull()
    expect(calculateOhlcSummary(undefined)).toBeNull()
  })

  it('computes latest candle and 24h high/low bounds across series', () => {
    const klines: MarketKline[] = [
      makeKline(100, 100, 120, 90, 105, 1500),
      makeKline(200, 105, 140, 102, 135, 2500), // max high = 140
      makeKline(300, 135, 138, 85, 95, 4000), // min low = 85
      makeKline(400, 95, 110, 92, 108, 3200), // latest candle
    ]

    const summary = calculateOhlcSummary(klines)
    expect(summary).toEqual({
      open: 95,
      high: 110,
      low: 92,
      close: 108,
      volume: 3200,
      high24h: 140,
      low24h: 85,
    })
  })
})

describe('generateSyntheticKlines', () => {
  it('returns requested count of candles', () => {
    const klines = generateSyntheticKlines('SOLUSDT', '15m', 25)
    expect(klines).toHaveLength(25)
  })

  it('returns empty array when count <= 0', () => {
    expect(generateSyntheticKlines('SOLUSDT', '15m', 0)).toEqual([])
    expect(generateSyntheticKlines('SOLUSDT', '15m', -10)).toEqual([])
  })

  it('generates candles with monotonically increasing timestamps separated by interval', () => {
    const klines15m = generateSyntheticKlines('ETHUSDT', '15m', 10)
    for (let i = 1; i < klines15m.length; i++) {
      expect(klines15m[i].timestamp - klines15m[i - 1].timestamp).toBe(900)
    }

    const klines1h = generateSyntheticKlines('BTCUSDT', '1h', 10)
    for (let i = 1; i < klines1h.length; i++) {
      expect(klines1h[i].timestamp - klines1h[i - 1].timestamp).toBe(3600)
    }
  })

  it('satisfies strict OHLC mathematical invariants on every bar', () => {
    const klines = generateSyntheticKlines('SOLUSDT', '15m', 50)
    for (const bar of klines) {
      expect(bar.high).toBeGreaterThanOrEqual(bar.low)
      expect(bar.high).toBeGreaterThanOrEqual(bar.open)
      expect(bar.high).toBeGreaterThanOrEqual(bar.close)
      expect(bar.low).toBeLessThanOrEqual(bar.open)
      expect(bar.low).toBeLessThanOrEqual(bar.close)
      expect(bar.volume).toBeGreaterThan(0)
    }
  })

  it('uses realistic base prices for supported symbols', () => {
    const btc = generateSyntheticKlines('BTCUSDT', '15m', 5)
    expect(btc[0].close).toBeGreaterThan(50000)

    const eth = generateSyntheticKlines('ETHUSDT', '15m', 5)
    expect(eth[0].close).toBeGreaterThan(1500)
    expect(eth[0].close).toBeLessThan(10000)

    const sol = generateSyntheticKlines('SOLUSDT', '15m', 5)
    expect(sol[0].close).toBeGreaterThan(100)
    expect(sol[0].close).toBeLessThan(1000)
  })
})
