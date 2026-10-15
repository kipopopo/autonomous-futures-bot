import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fetchPrimaryTelemetry,
  fetchArchiveDataForPage,
} from './api'
import type { DashboardPage } from './navigation'

function createMockResponse(status: number, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

describe('fetchPrimaryTelemetry', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('queries only the three primary live endpoints using Promise.allSettled', async () => {
    const calledPaths: string[] = []

    const fetchMock = vi.fn().mockImplementation((url: string) => {
      const path = typeof url === 'string' ? url : ''
      calledPaths.push(path)

      if (path === '/api/v1/execution/status') {
        return Promise.resolve(
          createMockResponse(200, {
            verified: true,
            status: 'ok',
            engine_state: 'ACTIVE',
            timestamp_ms: Date.now(),
            solvency: { verified: true, is_solvent: true, drift_usdt: 0 },
            positions: {},
            candidate_allocations: [],
            aggregate_exposure_usdt: 0,
            recent_orders: [],
            total_orders: 0,
            interlock_blocks_count: 0,
          })
        )
      }
      if (path === '/api/v1/market/prices') {
        return Promise.resolve(
          createMockResponse(200, {
            timestamp_ms: Date.now(),
            prices: { BTCUSDT: 65000, ETHUSDT: 3500, SOLUSDT: 150 },
          })
        )
      }
      if (path === '/api/v1/canary/evolution') {
        return Promise.resolve(
          createMockResponse(200, {
            verified: true,
            phase: 'evolution',
            active_stage: 'STAGE_5',
          })
        )
      }

      return Promise.resolve(createMockResponse(404, {}))
    })

    vi.stubGlobal('fetch', fetchMock)

    const telemetry = await fetchPrimaryTelemetry()

    expect(telemetry.executionStatus?.verified).toBe(true)
    expect(telemetry.liveMarketPrices?.prices['BTCUSDT']).toBe(65000)
    expect(telemetry.evolution?.verified).toBe(true)

    // Verify exactly 3 endpoints called
    expect(calledPaths).toHaveLength(3)
    expect(calledPaths).toContain('/api/v1/execution/status')
    expect(calledPaths).toContain('/api/v1/market/prices')
    expect(calledPaths).toContain('/api/v1/canary/evolution')

    // Verify archive endpoints were NEVER called
    const archiveEndpoints = [
      '/api/v1/canary/summary',
      '/api/v1/canary/hawkes',
      '/api/v1/canary/risk',
      '/api/v1/canary/accounting',
      '/api/v1/canary/live-market',
      '/api/v1/canary/paper-execution',
      '/api/v1/canary/strategy-activation',
      '/api/v1/canary/autonomous-lifecycle',
      '/api/v1/canary/stress-fault-injection',
      '/api/v1/canary/strategy-mining',
      '/api/v1/canary/portfolio-rebalancing',
      '/api/v1/canary/testnet-gateway',
      '/api/v1/canary/bracket-positions',
      '/api/v1/canary/execution-guard',
      '/api/v1/canary/orchestrator',
      '/api/v1/canary/calibration',
      '/api/v1/canary/ensemble',
      '/api/v1/canary/testnet-bridge',
      '/api/v1/canary/kill-switch',
      '/api/v1/canary/production-launch',
      '/api/v1/dataset/bundle',
      '/api/v1/dataset/components',
      '/api/v1/creator/registry',
      '/api/v1/creator/qualifications',
      '/api/v1/learner/artifact',
    ]

    for (const archiveEndpoint of archiveEndpoints) {
      expect(calledPaths).not.toContain(archiveEndpoint)
    }
  })

  it('handles partial failures gracefully without throwing', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      const path = typeof url === 'string' ? url : ''
      if (path === '/api/v1/execution/status') {
        return Promise.reject(new Error('Network offline'))
      }
      if (path === '/api/v1/market/prices') {
        return Promise.resolve(createMockResponse(500, {}))
      }
      if (path === '/api/v1/canary/evolution') {
        return Promise.resolve(
          createMockResponse(200, {
            verified: true,
            phase: 'evolution',
          })
        )
      }
      return Promise.resolve(createMockResponse(404, {}))
    })

    vi.stubGlobal('fetch', fetchMock)

    const telemetry = await fetchPrimaryTelemetry()

    expect(telemetry.executionStatus).toBeNull()
    expect(telemetry.evolution?.verified).toBe(true)
  })
})

describe('fetchArchiveDataForPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fetches only the accounting endpoint when navigating to accounting archive', async () => {
    const calledPaths: string[] = []
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      calledPaths.push(typeof url === 'string' ? url : '')
      return Promise.resolve(createMockResponse(200, { verified: true, accounts: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchArchiveDataForPage('accounting')

    expect(result.canary?.accounting?.verified).toBe(true)
    expect(calledPaths).toEqual(['/api/v1/canary/accounting'])
  })

  it('fetches creator and dataset endpoints when navigating to creator archive', async () => {
    const calledPaths: string[] = []
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      calledPaths.push(typeof url === 'string' ? url : '')
      return Promise.resolve(createMockResponse(200, { verified: true }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchArchiveDataForPage('creator')

    expect(result.apiData).toBeDefined()
    expect(calledPaths).toContain('/api/v1/creator/registry')
    expect(calledPaths).toContain('/api/v1/creator/qualifications')
    expect(calledPaths).toContain('/api/v1/dataset/bundle')
    expect(calledPaths).toContain('/api/v1/dataset/components')
    expect(calledPaths).not.toContain('/api/v1/canary/accounting')
  })

  it('fetches paper execution endpoint when navigating to execution archive', async () => {
    const calledPaths: string[] = []
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      calledPaths.push(typeof url === 'string' ? url : '')
      return Promise.resolve(createMockResponse(200, { verified: true }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchArchiveDataForPage('execution')

    expect(result.canary?.paperExecution?.verified).toBe(true)
    expect(calledPaths).toEqual(['/api/v1/canary/paper-execution'])
  })

  it('fetches learner endpoints when navigating to learner archive', async () => {
    const calledPaths: string[] = []
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      calledPaths.push(typeof url === 'string' ? url : '')
      return Promise.resolve(createMockResponse(200, { verified: true }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchArchiveDataForPage('learner')

    expect(result.apiData).toBeDefined()
    expect(calledPaths).toContain('/api/v1/learner/artifact')
    expect(calledPaths).toContain('/api/v1/learner/run')
    expect(calledPaths).toContain('/api/v1/learner/training-evidence')
  })

  it('fetches Hawkes microstructure when navigating to microstructure archive', async () => {
    const calledPaths: string[] = []
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      calledPaths.push(typeof url === 'string' ? url : '')
      return Promise.resolve(createMockResponse(200, { verified: true }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchArchiveDataForPage('microstructure')

    expect(result.canary?.hawkes?.verified).toBe(true)
    expect(calledPaths).toEqual(['/api/v1/canary/hawkes'])
  })

  it('fetches risk endpoint when navigating to risk archive', async () => {
    const calledPaths: string[] = []
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      calledPaths.push(typeof url === 'string' ? url : '')
      return Promise.resolve(createMockResponse(200, { verified: true }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchArchiveDataForPage('risk')

    expect(result.canary?.risk?.verified).toBe(true)
    expect(calledPaths).toEqual(['/api/v1/canary/risk'])
  })

  it('fetches safety-relevant endpoints when navigating to safety page', async () => {
    const calledPaths: string[] = []
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      calledPaths.push(typeof url === 'string' ? url : '')
      return Promise.resolve(createMockResponse(200, { verified: true }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchArchiveDataForPage('safety')

    expect(result.canary?.productionLaunch).toBeDefined()
    expect(result.canary?.risk).toBeDefined()
    expect(result.canary?.killSwitch).toBeDefined()
    expect(calledPaths).toContain('/api/v1/canary/production-launch')
    expect(calledPaths).toContain('/api/v1/canary/risk')
    expect(calledPaths).toContain('/api/v1/canary/kill-switch')
    expect(calledPaths).toContain('/api/v1/canary/hawkes')
    expect(calledPaths).toContain('/api/v1/canary/live-market')
  })

  it('returns empty object and calls no endpoints for primary pages', async () => {
    const calledPaths: string[] = []
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      calledPaths.push(typeof url === 'string' ? url : '')
      return Promise.resolve(createMockResponse(200, {}))
    })
    vi.stubGlobal('fetch', fetchMock)

    const primaryPages: DashboardPage[] = ['overview', 'positions', 'trades', 'evolution', 'pair']
    for (const page of primaryPages) {
      const result = await fetchArchiveDataForPage(page)
      expect(result).toEqual({})
    }

    expect(calledPaths).toHaveLength(0)
  })
})
