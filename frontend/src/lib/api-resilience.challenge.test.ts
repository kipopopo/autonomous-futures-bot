import { describe, it, expect, vi, afterEach } from 'vitest'
import { fetchMarketKlines } from './api'
import {
  calculateEma,
  calculateVolumeSeries,
  calculateOhlcSummary,
  generateSyntheticKlines,
} from './chart-indicators'

function jsonResponse(status: number, body?: unknown, headers: Record<string, string> = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    headers: new Headers({ 'Content-Type': 'application/json', ...headers }),
    json: () => (body !== undefined ? Promise.resolve(body) : Promise.reject(new SyntaxError('Unexpected end of JSON input'))),
    text: () => Promise.resolve(typeof body === 'string' ? body : JSON.stringify(body ?? '')),
  } as unknown as Response
}

function malformedJsonResponse(status: number = 200, rawText: string = '<html>502 Bad Gateway</html>'): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'OK',
    headers: new Headers({ 'Content-Type': 'text/html' }),
    json: () => Promise.reject(new SyntaxError(`Unexpected token '<', "${rawText}" is not valid JSON`)),
    text: () => Promise.resolve(rawText),
  } as unknown as Response
}

describe('Empirical Adversarial Challenge: fetchMarketKlines & Fallback Cascade', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // =========================================================================
  // 1. NETWORK DROPOUTS & TRANSPORT FAILURES
  // =========================================================================
  describe('1. Network Dropouts & Transport Failures', () => {
    it('cascades to Tier 2 when Tier 1 throws TypeError (Network offline / DNS failure)', async () => {
      const binanceKlines = [
        [1791569700000, '100.0', '105.0', '98.0', '102.5', '1234.5', 1791570599999, '0', 10, '0', '0', '0'],
      ]

      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.reject(new TypeError('Failed to fetch (net::ERR_INTERNET_DISCONNECTED)'))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(jsonResponse(200, binanceKlines))
        }
        return Promise.reject(new Error('Unknown URL'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('SOLUSDT', '15m', 10)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      expect(result).toHaveLength(1)
      expect(result[0].timestamp).toBe(1791569700)
      expect(result[0].open).toBe(100.0)
      expect(result[0].close).toBe(102.5)
    })

    it('cascades to Tier 3 when both Tier 1 and Tier 2 suffer complete network blackout', async () => {
      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.reject(new TypeError('Failed to fetch'))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.reject(new TypeError('Failed to fetch'))
        }
        return Promise.reject(new Error('Blackout'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('ETHUSDT', '1h', 50)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      expect(result).toHaveLength(50)
      // ETH baseline price is 2700
      expect(result[0].close).toBeGreaterThan(2000)
      expect(result[0].close).toBeLessThan(4000)
    })

    it('cascades gracefully when Tier 1 request is aborted via AbortSignal / DOMException', async () => {
      const binanceKlines = [
        [1791569700000, '180.0', '185.0', '178.0', '182.0', '500.0', 1791570599999, '0', 5, '0', '0', '0'],
      ]

      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          const abortError = new Error('The operation was aborted')
          abortError.name = 'AbortError'
          return Promise.reject(abortError)
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(jsonResponse(200, binanceKlines))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('SOLUSDT', '15m', 10)
      expect(result).toHaveLength(1)
      expect(result[0].close).toBe(182.0)
    })

    it('cascades to Tier 3 when both Tier 1 and Tier 2 are aborted', async () => {
      const fetchMock = vi.fn().mockImplementation(() => {
        const abortError = new Error('The user aborted a request')
        abortError.name = 'AbortError'
        return Promise.reject(abortError)
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('SOLUSDT', '15m', 20)
      expect(result).toHaveLength(20)
      expect(result[0].open).toBeGreaterThan(0)
    })
  })

  // =========================================================================
  // 2. HTTP RATE LIMITS (429) & UPSTREAM STATUS ERRORS
  // =========================================================================
  describe('2. HTTP Rate Limits & Status Code Fault Injection', () => {
    it('Tier 1 returns HTTP 429 Too Many Requests -> successfully falls through to Tier 2', async () => {
      const binanceKlines = [
        [1791569700000, '90000', '90500', '89800', '90200', '100', 1791570599999, '0', 2, '0', '0', '0'],
      ]

      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(jsonResponse(429, { detail: 'Rate limit exceeded: 60/minute' }))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(jsonResponse(200, binanceKlines))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('BTCUSDT', '1h', 1)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      expect(result).toHaveLength(1)
      expect(result[0].close).toBe(90200)
    })

    it('Tier 1 returns HTTP 429 AND Tier 2 returns HTTP 429 -> successfully cascades to Tier 3 synthetic', async () => {
      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(jsonResponse(429, { detail: 'Local rate limit exceeded' }))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(
            jsonResponse(429, { code: -1003, msg: 'Too many requests; IP banned until 1791574200000' }),
          )
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('BTCUSDT', '15m', 40)
      expect(fetchMock).toHaveBeenCalledTimes(2)
      expect(result).toHaveLength(40)
      expect(result[0].open).toBeGreaterThan(50000)
    })

    it('Tier 1 returns HTTP 500, Tier 2 returns HTTP 502/503 -> falls back to Tier 3 synthetic', async () => {
      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(jsonResponse(500, { detail: 'Internal Database Failure' }))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(jsonResponse(503, { code: -1001, msg: 'Internal Service Error' }))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('SOLUSDT', '15m', 15)
      expect(result).toHaveLength(15)
    })

    it('Tier 1 returns HTTP 403 Forbidden, Tier 2 returns HTTP 418 I\'m a teapot (WAF Block) -> falls to Tier 3', async () => {
      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(jsonResponse(403, { detail: 'Forbidden' }))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(jsonResponse(418, { msg: 'IP blocked by Cloudflare / WAF' }))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('ETHUSDT', '1h', 25)
      expect(result).toHaveLength(25)
    })
  })

  // =========================================================================
  // 3. MALFORMED, CORRUPTED & UNEXPECTED PAYLOAD SHAPES
  // =========================================================================
  describe('3. Malformed, Corrupted & Unexpected Upstream JSON', () => {
    it('Tier 1 returns HTTP 200 with HTML/corrupted non-JSON -> cascades to Tier 2', async () => {
      const binanceKlines = [
        [1791569700000, '200.0', '205.0', '198.0', '201.0', '50.0', 1791570599999, '0', 1, '0', '0', '0'],
      ]

      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(malformedJsonResponse(200, '<html><head><title>502 Bad Gateway</title></head>'))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(jsonResponse(200, binanceKlines))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('SOLUSDT', '15m', 10)
      expect(result).toHaveLength(1)
      expect(result[0].close).toBe(201.0)
    })

    it('Tier 1 and Tier 2 both return HTTP 200 with corrupted non-JSON -> cascades to Tier 3', async () => {
      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(malformedJsonResponse(200, 'truncated json {"candles": ['))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(malformedJsonResponse(200, 'upstream timeout html'))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('BTCUSDT', '1h', 10)
      expect(result).toHaveLength(10)
      expect(result[0].close).toBeGreaterThan(50000)
    })

    it('Tier 1 returns HTTP 200 with empty candles array `{ candles: [] }` -> cascades to Tier 2', async () => {
      const binanceKlines = [
        [1791569700000, '250.0', '255.0', '248.0', '252.0', '80.0', 1791570599999, '0', 1, '0', '0', '0'],
      ]

      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(jsonResponse(200, { symbol: 'SOLUSDT', candles: [] }))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(jsonResponse(200, binanceKlines))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('SOLUSDT', '15m', 5)
      expect(result).toHaveLength(1)
      expect(result[0].close).toBe(252.0)
    })

    it('Tier 1 returns HTTP 200 with empty direct array `[]` -> cascades to Tier 2', async () => {
      const binanceKlines = [
        [1791569700000, '300.0', '305.0', '298.0', '302.0', '10.0', 1791570599999, '0', 1, '0', '0', '0'],
      ]

      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(jsonResponse(200, []))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(jsonResponse(200, binanceKlines))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('SOLUSDT', '15m', 5)
      expect(result).toHaveLength(1)
      expect(result[0].close).toBe(302.0)
    })

    it('Tier 1 returns HTTP 200 with non-array `{ candles: "not-an-array" }` -> cascades to Tier 2', async () => {
      const binanceKlines = [
        [1791569700000, '400.0', '405.0', '398.0', '402.0', '10.0', 1791570599999, '0', 1, '0', '0', '0'],
      ]

      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(jsonResponse(200, { candles: 'invalid type' }))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(jsonResponse(200, binanceKlines))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('SOLUSDT', '15m', 5)
      expect(result).toHaveLength(1)
      expect(result[0].close).toBe(402.0)
    })

    it('Tier 1 returns empty `{}` AND Tier 2 returns Binance error object `{ code: -1121 }` -> cascades to Tier 3', async () => {
      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(jsonResponse(200, {}))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          // Binance sometimes returns HTTP 200 with error object if proxied incorrectly
          return Promise.resolve(jsonResponse(200, { code: -1121, msg: 'Invalid symbol.' }))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('SOLUSDT', '15m', 10)
      expect(result).toHaveLength(10)
      expect(result[0].open).toBeGreaterThan(0)
    })

    it('Tier 1 returns 500 AND Tier 2 returns empty array `[]` -> cascades to Tier 3', async () => {
      const fetchMock = vi.fn().mockImplementation((url: string) => {
        if (url.startsWith('/api/v1/market/klines')) {
          return Promise.resolve(jsonResponse(500))
        }
        if (url.startsWith('https://fapi.binance.com')) {
          return Promise.resolve(jsonResponse(200, []))
        }
        return Promise.reject(new Error('Unknown'))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchMarketKlines('ETHUSDT', '15m', 8)
      expect(result).toHaveLength(8)
    })
  })

  // =========================================================================
  // 4. SYNTHETIC GENERATOR OHLC GEOMETRIC INVARIANTS & MONOTONICITY
  // =========================================================================
  describe('4. Synthetic Generator Geometric & Monotonicity Invariants', () => {
    const testSymbols = ['SOLUSDT', 'ETHUSDT', 'BTCUSDT', 'DOGEUSDT']
    const testIntervals: Array<'15m' | '1h'> = ['15m', '1h']

    testSymbols.forEach((symbol) => {
      testIntervals.forEach((interval) => {
        it(`enforces geometric and temporal invariants for ${symbol} @ ${interval}`, () => {
          const count = 100
          const klines = generateSyntheticKlines(symbol, interval, count)
          const expectedStep = interval === '1h' ? 3600 : 900

          expect(klines).toHaveLength(count)

          for (let i = 0; i < klines.length; i++) {
            const bar = klines[i]

            // 1. All numbers must be finite and > 0
            expect(Number.isFinite(bar.timestamp)).toBe(true)
            expect(Number.isFinite(bar.open)).toBe(true)
            expect(Number.isFinite(bar.high)).toBe(true)
            expect(Number.isFinite(bar.low)).toBe(true)
            expect(Number.isFinite(bar.close)).toBe(true)
            expect(Number.isFinite(bar.volume)).toBe(true)

            expect(bar.open).toBeGreaterThan(0)
            expect(bar.high).toBeGreaterThan(0)
            expect(bar.low).toBeGreaterThan(0)
            expect(bar.close).toBeGreaterThan(0)
            expect(bar.volume).toBeGreaterThan(0)

            // 2. Strict OHLC geometric invariants:
            // high >= max(open, close)
            expect(bar.high).toBeGreaterThanOrEqual(Math.max(bar.open, bar.close))
            // low <= min(open, close)
            expect(bar.low).toBeLessThanOrEqual(Math.min(bar.open, bar.close))
            // high >= low
            expect(bar.high).toBeGreaterThanOrEqual(bar.low)

            // 3. Strict timestamp monotonicity and interval step
            if (i > 0) {
              const prevBar = klines[i - 1]
              const delta = bar.timestamp - prevBar.timestamp
              expect(delta).toBe(expectedStep)
              expect(bar.timestamp).toBeGreaterThan(prevBar.timestamp)
            }
          }
        })
      })
    })

    it('returns empty array when count is <= 0', () => {
      expect(generateSyntheticKlines('SOLUSDT', '15m', 0)).toEqual([])
      expect(generateSyntheticKlines('SOLUSDT', '15m', -10)).toEqual([])
    })

    it('generates correct single candle when count = 1', () => {
      const klines = generateSyntheticKlines('BTCUSDT', '15m', 1)
      expect(klines).toHaveLength(1)
      expect(klines[0].high).toBeGreaterThanOrEqual(Math.max(klines[0].open, klines[0].close))
      expect(klines[0].low).toBeLessThanOrEqual(Math.min(klines[0].open, klines[0].close))
    })
  })

  // =========================================================================
  // 5. DOWNSTREAM INDICATOR ENGINE PIPELINE UNDER FALLBACK
  // =========================================================================
  describe('5. Downstream Indicator Compatibility Under Fallback Cascade', () => {
    it('synthetic fallback feeds calculateEma, calculateVolumeSeries, and calculateOhlcSummary cleanly', async () => {
      // Simulate complete network failure to force Tier 3 fallback
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation(() => Promise.reject(new Error('Network offline'))),
      )

      const klines = await fetchMarketKlines('SOLUSDT', '15m', 100)
      expect(klines).toHaveLength(100)

      // Test EMA 50
      const ema50 = calculateEma(klines, 50)
      expect(ema50.length).toBe(51)
      for (const pt of ema50) {
        expect(Number.isFinite(pt.time)).toBe(true)
        expect(Number.isFinite(pt.value)).toBe(true)
        expect(pt.value).toBeGreaterThan(100)
        expect(pt.value).toBeLessThan(300)
      }

      // Test EMA 200 in warmup mode
      const ema200 = calculateEma(klines, 200)
      expect(ema200.length).toBe(100)
      for (const pt of ema200) {
        expect(Number.isFinite(pt.time)).toBe(true)
        expect(Number.isFinite(pt.value)).toBe(true)
      }

      // Test Volume Series
      const volumeSeries = calculateVolumeSeries(klines)
      expect(volumeSeries.length).toBe(100)
      for (let i = 0; i < volumeSeries.length; i++) {
        const v = volumeSeries[i]
        const k = klines[i]
        expect(v.time).toBe(k.timestamp)
        expect(v.value).toBe(k.volume)
        if (k.close >= k.open) {
          expect(v.color).toBe('rgba(16, 185, 129, 0.5)')
        } else {
          expect(v.color).toBe('rgba(244, 63, 94, 0.5)')
        }
      }

      // Test OHLC Summary
      const summary = calculateOhlcSummary(klines)
      expect(summary).not.toBeNull()
      expect(summary!.high24h).toBeGreaterThanOrEqual(summary!.low24h)
      expect(summary!.high24h).toBeGreaterThanOrEqual(summary!.high)
      expect(summary!.low24h).toBeLessThanOrEqual(summary!.low)
    })
  })

  // =========================================================================
  // 6. HIGH CONCURRENCY BURST UNDER ARBITRARY FAULTS
  // =========================================================================
  describe('6. High Concurrency Burst Under Arbitrary Network Faults', () => {
    it('resolves 50 concurrent calls under arbitrary failures without unhandled rejections', async () => {
      let callCount = 0
      const fetchMock = vi.fn().mockImplementation((_url: string) => {
        callCount++
        // Simulate random failure patterns across requests
        if (callCount % 3 === 0) {
          return Promise.reject(new TypeError('Network dropped'))
        }
        if (callCount % 3 === 1) {
          return Promise.resolve(jsonResponse(429, { detail: 'Throttled' }))
        }
        // Malformed payload
        return Promise.resolve(jsonResponse(200, { invalid: true }))
      })
      vi.stubGlobal('fetch', fetchMock)

      const promises = Array.from({ length: 50 }, (_, i) => {
        const symbol = i % 2 === 0 ? 'SOLUSDT' : 'ETHUSDT'
        const interval = i % 3 === 0 ? '1h' : '15m'
        return fetchMarketKlines(symbol, interval, 20)
      })

      const results = await Promise.all(promises)

      expect(results).toHaveLength(50)
      for (const res of results) {
        expect(res).toHaveLength(20)
        expect(res[0].open).toBeGreaterThan(0)
        expect(res[19].close).toBeGreaterThan(0)
      }
    })
  })
})
