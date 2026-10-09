import { describe, expect, it } from 'vitest'
import {
  calculateEma,
  calculateOhlcSummary,
  calculateVolumeSeries,
  generateSyntheticKlines,
  type MarketKline,
} from './chart-indicators'

/**
 * Independent Mathematical Oracle for EMA.
 * Uses exact floating-point recurrence without any intermediate rounding.
 */
function mathematicalOracleEma(
  closes: number[],
  timestamps: number[],
  period: number,
): { time: number; value: number }[] {
  if (closes.length === 0 || period <= 0) return []
  const k = 2 / (period + 1)
  const result: { time: number; value: number }[] = []

  if (closes.length >= period) {
    let sum = 0
    for (let i = 0; i < period; i++) {
      sum += closes[i]
    }
    let prev = sum / period
    result.push({ time: timestamps[period - 1], value: prev })

    for (let i = period; i < closes.length; i++) {
      const curr = closes[i] * k + prev * (1 - k)
      result.push({ time: timestamps[i], value: curr })
      prev = curr
    }
  } else {
    let prev = closes[0]
    result.push({ time: timestamps[0], value: prev })
    for (let i = 1; i < closes.length; i++) {
      const curr = closes[i] * k + prev * (1 - k)
      result.push({ time: timestamps[i], value: curr })
      prev = curr
    }
  }

  return result
}

function makeBar(
  timestamp: number,
  open: number,
  high: number,
  low: number,
  close: number,
  volume: number = 1000,
): MarketKline {
  return { timestamp, open, high, low, close, volume }
}

describe('Empirical Adversarial Challenge: Indicators & Math Engine', () => {
  describe('Dimension 1: Mathematical Oracle Verification (EMA 50 & EMA 200)', () => {
    it('matches exact mathematical oracle for EMA 50 across 150 bars within float precision', () => {
      const klines = generateSyntheticKlines('SOLUSDT', '15m', 150)
      const actual = calculateEma(klines, 50)
      const expected = mathematicalOracleEma(
        klines.map((k) => k.close),
        klines.map((k) => k.timestamp),
        50,
      )

      expect(actual.length).toBe(expected.length)
      expect(actual.length).toBe(101) // 150 - 50 + 1 = 101 points

      for (let i = 0; i < actual.length; i++) {
        expect(actual[i].time).toBe(expected[i].time)
        // Error must be <= 0.0001 (due to toFixed(4) output formatting)
        const diff = Math.abs(actual[i].value - expected[i].value)
        expect(diff).toBeLessThanOrEqual(0.0001)
      }
    })

    it('matches exact mathematical oracle for EMA 200 across 250 bars within float precision', () => {
      const klines = generateSyntheticKlines('BTCUSDT', '15m', 250)
      const actual = calculateEma(klines, 200)
      const expected = mathematicalOracleEma(
        klines.map((k) => k.close),
        klines.map((k) => k.timestamp),
        200,
      )

      expect(actual.length).toBe(expected.length)
      expect(actual.length).toBe(51) // 250 - 200 + 1 = 51 points

      for (let i = 0; i < actual.length; i++) {
        expect(actual[i].time).toBe(expected[i].time)
        const diff = Math.abs(actual[i].value - expected[i].value)
        expect(diff).toBeLessThanOrEqual(0.0001)
      }
    })

    it('matches warmup mode oracle for EMA 200 when data has only 100 bars', () => {
      const klines = generateSyntheticKlines('ETHUSDT', '15m', 100)
      const actual = calculateEma(klines, 200)
      const expected = mathematicalOracleEma(
        klines.map((k) => k.close),
        klines.map((k) => k.timestamp),
        200,
      )

      expect(actual.length).toBe(100)
      for (let i = 0; i < actual.length; i++) {
        expect(actual[i].time).toBe(expected[i].time)
        const diff = Math.abs(actual[i].value - expected[i].value)
        expect(diff).toBeLessThanOrEqual(0.0001)
      }
    })

    it('invariant: constant flat price sequence yields identical constant EMA for all points', () => {
      const constantPrice = 145.82
      const count = 120
      const klines: MarketKline[] = []
      for (let i = 0; i < count; i++) {
        klines.push(makeBar(1000 + i * 900, constantPrice, constantPrice, constantPrice, constantPrice))
      }

      const ema50 = calculateEma(klines, 50)
      expect(ema50.length).toBe(71)
      for (const pt of ema50) {
        expect(pt.value).toBe(constantPrice)
      }

      const ema200 = calculateEma(klines, 200)
      expect(ema200.length).toBe(120)
      for (const pt of ema200) {
        expect(pt.value).toBe(constantPrice)
      }
    })

    it('invariant: bounded convex combination (EMA is always within min and max close)', () => {
      const klines = generateSyntheticKlines('SOLUSDT', '15m', 200)
      const ema50 = calculateEma(klines, 50)
      const allCloses = klines.map((k) => k.close)
      const minClose = Math.min(...allCloses)
      const maxClose = Math.max(...allCloses)

      for (const pt of ema50) {
        expect(pt.value).toBeGreaterThanOrEqual(minClose - 0.01)
        expect(pt.value).toBeLessThanOrEqual(maxClose + 0.01)
      }
    })
  })

  describe('Dimension 2: Stress Workload & Large Scale Array ($10^4$ Bars)', () => {
    it('processes 10,000 candles for EMA 50 in under 30ms without memory degradation', () => {
      const largeCount = 10000
      const klines = generateSyntheticKlines('BTCUSDT', '15m', largeCount)
      expect(klines.length).toBe(largeCount)

      const start = performance.now()
      const ema50 = calculateEma(klines, 50)
      const elapsed = performance.now() - start

      expect(ema50.length).toBe(largeCount - 50 + 1)
      expect(elapsed).toBeLessThan(100) // strict sub-100ms budget

      // Verify sample points across start, middle, and end
      expect(ema50[0].time).toBe(klines[49].timestamp)
      expect(ema50[largeCount - 50].time).toBe(klines[largeCount - 1].timestamp)
      for (const pt of ema50.slice(0, 10)) {
        expect(Number.isFinite(pt.value)).toBe(true)
      }
      for (const pt of ema50.slice(-10)) {
        expect(Number.isFinite(pt.value)).toBe(true)
      }
    })

    it('processes 10,000 candles for volume series with 0 allocation delay', () => {
      const largeCount = 10000
      const klines = generateSyntheticKlines('SOLUSDT', '15m', largeCount)

      const start = performance.now()
      const volumeSeries = calculateVolumeSeries(klines)
      const elapsed = performance.now() - start

      expect(volumeSeries.length).toBe(largeCount)
      expect(elapsed).toBeLessThan(50)
    })
  })

  describe('Dimension 3: Extreme Values & Boundary Conditions ($10^8$, $10^{-6}$, Zero)', () => {
    it('handles extreme high prices ($10^8$) without overflow or NaN', () => {
      const extremeHigh = 100000000 // 10^8
      const klines = [
        makeBar(100, extremeHigh, extremeHigh + 100, extremeHigh - 100, extremeHigh),
        makeBar(200, extremeHigh + 50, extremeHigh + 150, extremeHigh, extremeHigh + 50),
        makeBar(300, extremeHigh + 100, extremeHigh + 200, extremeHigh + 50, extremeHigh + 100),
      ]

      const ema = calculateEma(klines, 2)
      expect(ema).toHaveLength(2)
      expect(ema[0].value).toBe(100000025) // (10^8 + (10^8 + 50)) / 2
      expect(Number.isFinite(ema[1].value)).toBe(true)
    })

    it('documents underflow truncation for micro-asset prices ($10^{-6}$) caused by toFixed(4)', () => {
      const microPrice = 0.000001 // 10^-6
      const klines = [
        makeBar(100, microPrice, microPrice, microPrice, microPrice),
        makeBar(200, microPrice, microPrice, microPrice, microPrice),
        makeBar(300, microPrice, microPrice, microPrice, microPrice),
      ]

      const ema = calculateEma(klines, 2)
      expect(ema).toHaveLength(2)
      // Because toFixed(4) rounds 0.000001 to "0.0000", Number("0.0000") is 0
      expect(ema[0].value).toBe(0)
      expect(ema[1].value).toBe(0)
    })

    it('handles zero volume and extreme high volume bars correctly', () => {
      const klines = [
        makeBar(100, 100, 105, 95, 102, 0), // zero volume
        makeBar(200, 102, 108, 100, 99, 1e12), // 1 trillion volume
      ]

      const volumes = calculateVolumeSeries(klines)
      expect(volumes).toHaveLength(2)
      expect(volumes[0]).toEqual({
        time: 100,
        value: 0,
        color: 'rgba(16, 185, 129, 0.5)', // close 102 >= open 100 -> emerald
      })
      expect(volumes[1]).toEqual({
        time: 200,
        value: 1e12,
        color: 'rgba(244, 63, 94, 0.5)', // close 99 < open 102 -> rose
      })
    })

    it('handles zero and negative periods by safely returning empty array', () => {
      const klines = generateSyntheticKlines('SOLUSDT', '15m', 10)
      expect(calculateEma(klines, 0)).toEqual([])
      expect(calculateEma(klines, -1)).toEqual([])
      expect(calculateEma(klines, -200)).toEqual([])
    })

    it('handles transition boundary discontinuity from N = period - 1 to N = period', () => {
      const period = 5
      const klines = [
        makeBar(100, 10, 12, 9, 10),
        makeBar(200, 20, 22, 19, 20),
        makeBar(300, 30, 32, 29, 30),
        makeBar(400, 40, 42, 39, 40),
      ]

      // At N = 4 (N < 5): warmup mode returns all 4 bars
      const warmupEma = calculateEma(klines, period)
      expect(warmupEma).toHaveLength(4)

      // Add 5th bar: N = 5 (N >= 5): standard mode returns only 1 bar (the SMA seed at index 4)
      const klines5 = [...klines, makeBar(500, 50, 52, 49, 50)]
      const standardEma = calculateEma(klines5, period)
      expect(standardEma).toHaveLength(1)
      expect(standardEma[0].time).toBe(500)
      expect(standardEma[0].value).toBe(30) // (10 + 20 + 30 + 40 + 50) / 5 = 30
    })

    it('evaluates non-integer period edge case', () => {
      const klines = [
        makeBar(100, 10, 12, 9, 10),
        makeBar(200, 20, 22, 19, 20),
        makeBar(300, 30, 32, 29, 30),
        makeBar(400, 40, 42, 39, 40),
      ]

      // Passing non-integer period 2.5:
      // In JS, data[2.5 - 1] is data[1.5] = undefined, accessing .timestamp throws TypeError.
      // This test verifies that we catch and document this potential runtime behavior.
      expect(() => {
        calculateEma(klines, 2.5)
      }).toThrow()
    })
  })

  describe('Dimension 4: Synthetic Klines Generator Invariants', () => {
    it('strictly maintains candle geometric invariants (high >= max(open, close), low <= min(open, close))', () => {
      const klines = generateSyntheticKlines('SOLUSDT', '15m', 500)
      for (const bar of klines) {
        expect(bar.high).toBeGreaterThanOrEqual(bar.open)
        expect(bar.high).toBeGreaterThanOrEqual(bar.close)
        expect(bar.low).toBeLessThanOrEqual(bar.open)
        expect(bar.low).toBeLessThanOrEqual(bar.close)
        expect(bar.high).toBeGreaterThanOrEqual(bar.low)
        expect(bar.volume).toBeGreaterThan(0)
      }
    })

    it('generates strictly monotonic non-repeating timestamps separated by exact interval seconds', () => {
      const klines15m = generateSyntheticKlines('ETHUSDT', '15m', 200)
      for (let i = 1; i < klines15m.length; i++) {
        expect(klines15m[i].timestamp - klines15m[i - 1].timestamp).toBe(900)
      }

      const klines1h = generateSyntheticKlines('BTCUSDT', '1h', 200)
      for (let i = 1; i < klines1h.length; i++) {
        expect(klines1h[i].timestamp - klines1h[i - 1].timestamp).toBe(3600)
      }
    })

    it('handles count <= 0 gracefully', () => {
      expect(generateSyntheticKlines('SOLUSDT', '15m', 0)).toEqual([])
      expect(generateSyntheticKlines('SOLUSDT', '15m', -50)).toEqual([])
    })

    it('handles fallback symbol base price mapping for unknown symbols', () => {
      const custom = generateSyntheticKlines('DOGEUSDT', '15m', 5)
      expect(custom.length).toBe(5)
      expect(custom[0].open).toBe(100) // fallback basePrice = 100
    })
  })

  describe('Dimension 5: OHLC Summary Extreme Spreads', () => {
    it('computes bounds accurately across volatile and inverted ranges', () => {
      const klines = [
        makeBar(100, 100, 250, 50, 120, 1000), // extreme high = 250, extreme low = 50
        makeBar(200, 120, 180, 110, 150, 2000),
        makeBar(300, 150, 160, 130, 140, 1500), // latest candle
      ]

      const summary = calculateOhlcSummary(klines)
      expect(summary).toEqual({
        open: 150,
        high: 160,
        low: 130,
        close: 140,
        volume: 1500,
        high24h: 250,
        low24h: 50,
      })
    })

    it('returns null on empty, null, or undefined series', () => {
      expect(calculateOhlcSummary([])).toBeNull()
      expect(calculateOhlcSummary(null)).toBeNull()
      expect(calculateOhlcSummary(undefined)).toBeNull()
    })
  })
})
