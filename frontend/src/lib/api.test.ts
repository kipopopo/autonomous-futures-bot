import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchCreatorQualifications, fetchMarketKlines, fetchOverviewData } from './api'

function response(status: number, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

describe('fetchCreatorQualifications', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('calls the verified read-only list route and returns its payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(200, {
      verified: true,
      candidate_count: 1,
      qualification_count: 1,
      missing_candidate_ids: [],
      qualifications: [],
    }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchCreatorQualifications()

    expect(result?.verified).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/creator/qualifications', {
      headers: { Accept: 'application/json' },
    })
  })

  it('maps missing evidence to null', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(404)))

    await expect(fetchCreatorQualifications()).resolves.toBeNull()
  })

  it('rejects integrity failures instead of returning an empty success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(503)))

    await expect(fetchCreatorQualifications()).rejects.toThrow(
      'GET /api/v1/creator/qualifications failed with HTTP 503',
    )
  })
})

describe('fetchOverviewData metric-quality qualification evidence', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('preserves a 503 from the dedicated read-only route as an integrity error', async () => {
    const fetchMock = vi.fn().mockImplementation((path: string) => {
      if (path === '/api/v1/learner/metric-quality-qualification') return response(503)
      if (path === '/health') return response(200, {})
      if (path === '/api/v1/dataset/bundle') return response(200, {})
      if (path === '/api/v1/dataset/components') return response(200, {})
      return response(404)
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchOverviewData()

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/learner/metric-quality-qualification', {
      headers: { Accept: 'application/json' },
    })
    expect(result.learnerMetricQualityQualification).toBeNull()
    expect(result.learnerMetricQualityQualificationError).toBe(
      'GET /api/v1/learner/metric-quality-qualification failed with HTTP 503',
    )
  })

  it('tolerates 503 or 404 for optional dataset bundle and components without failing overview', async () => {
    const fetchMock = vi.fn().mockImplementation((path: string) => {
      if (path === '/health') return response(200, { status: 'ok', paper_safe: true, execution_authority: false })
      if (path === '/api/v1/dataset/bundle') return response(503)
      if (path === '/api/v1/dataset/components') return response(503)
      return response(404)
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchOverviewData()

    expect(result.health?.status).toBe('ok')
    expect(result.bundle).toBeNull()
    expect(result.components).toBeNull()
  })
})

describe('fetchMarketKlines', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('Tier 1: returns normalized candles from local FastAPI endpoint', async () => {
    const mockCandles = [
      {
        timestamp: 1791569700,
        open: 109.72,
        high: 109.79,
        low: 109.52,
        close: 109.53,
        volume: 65965.9,
      },
    ]

    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/market/klines')) {
        return Promise.resolve(
          response(200, {
            symbol: 'SOLUSDT',
            interval: '15m',
            source: 'binance_futures_live',
            timestamp_ms: 1791570599000,
            count: 1,
            candles: mockCandles,
          }),
        )
      }
      return Promise.resolve(response(404))
    })
    vi.stubGlobal('fetch', fetchMock)

    const klines = await fetchMarketKlines('SOLUSDT', '15m', 50)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=50',
      { headers: { Accept: 'application/json' } },
    )
    expect(klines).toHaveLength(1)
    expect(klines[0]).toEqual({
      timestamp: 1791569700,
      open: 109.72,
      high: 109.79,
      low: 109.52,
      close: 109.53,
      volume: 65965.9,
    })
  })

  it('Tier 1: supports direct array or klines property in response', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/market/klines')) {
        return Promise.resolve(
          response(200, {
            klines: [
              { time: 1700000000, open: '100', high: '105', low: '95', close: '102', volume: '500' },
            ],
          }),
        )
      }
      return Promise.resolve(response(404))
    })
    vi.stubGlobal('fetch', fetchMock)

    const klines = await fetchMarketKlines('ETHUSDT', '1h', 10)
    expect(klines).toHaveLength(1)
    expect(klines[0]).toEqual({
      timestamp: 1700000000,
      open: 100,
      high: 105,
      low: 95,
      close: 102,
      volume: 500,
    })
  })

  it('Tier 2: falls back to direct Binance public REST if local API fails', async () => {
    const binanceRawKlines = [
      [
        1791569700000, // open time ms
        '109.7200',
        '109.7900',
        '109.5200',
        '109.5300',
        '65965.90',
        1791570599999,
        '7232057.77',
        9641,
        '32690.33',
        '3583844.60',
        '0',
      ],
    ]

    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/market/klines')) {
        return Promise.resolve(response(500))
      }
      if (url.startsWith('https://fapi.binance.com/fapi/v1/klines')) {
        return Promise.resolve(response(200, binanceRawKlines))
      }
      return Promise.resolve(response(404))
    })
    vi.stubGlobal('fetch', fetchMock)

    const klines = await fetchMarketKlines('SOLUSDT', '15m', 100)

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(klines).toHaveLength(1)
    expect(klines[0]).toEqual({
      timestamp: 1791569700, // converted from ms to seconds
      open: 109.72,
      high: 109.79,
      low: 109.52,
      close: 109.53,
      volume: 65965.9,
    })
  })

  it('Tier 3: falls back to synthetic klines when both local and Binance REST fail', async () => {
    const fetchMock = vi.fn().mockImplementation(() => {
      return Promise.reject(new Error('Network offline'))
    })
    vi.stubGlobal('fetch', fetchMock)

    const klines = await fetchMarketKlines('BTCUSDT', '1h', 30)

    expect(klines).toHaveLength(30)
    expect(klines[0].close).toBeGreaterThan(50000)
    for (const bar of klines) {
      expect(bar.high).toBeGreaterThanOrEqual(bar.low)
      expect(bar.volume).toBeGreaterThan(0)
    }
  })

  it('uses default parameters (SOLUSDT, 15m, 100) when omitted', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/market/klines')) {
        return Promise.resolve(
          response(200, {
            candles: [
              { timestamp: 1000, open: 150, high: 155, low: 145, close: 152, volume: 1000 },
            ],
          }),
        )
      }
      return Promise.resolve(response(404))
    })
    vi.stubGlobal('fetch', fetchMock)

    await fetchMarketKlines()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=100',
      { headers: { Accept: 'application/json' } },
    )
  })
})

