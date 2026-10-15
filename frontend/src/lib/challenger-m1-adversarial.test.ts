import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchPrimaryTelemetry } from './api'
import appSource from '../App.tsx?raw'
import apiSource from './api.ts?raw'

const LEGACY_CANARY_ENDPOINTS = [
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
] as const

const LEGACY_DATASET_CREATOR_LEARNER_ENDPOINTS = [
  '/api/v1/dataset/bundle',
  '/api/v1/dataset/components',
  '/api/v1/creator/registry',
  '/api/v1/creator/qualifications',
  '/api/v1/learner/artifact',
  '/api/v1/learner/run',
  '/api/v1/learner/training-evidence',
  '/api/v1/learner/quality-review',
  '/api/v1/learner/qualification',
  '/api/v1/learner/metric-quality-qualification',
] as const

const ALL_BANNED_ENDPOINTS = [
  ...LEGACY_CANARY_ENDPOINTS,
  ...LEGACY_DATASET_CREATOR_LEARNER_ENDPOINTS,
]

function makeMockResponse(status: number, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

describe('Challenger M1 Adversarial Verification Suite', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  describe('Adversarial Verification 1: fetchPrimaryTelemetry() NEVER calls legacy canary or dataset endpoints', () => {
    it('under normal conditions, never calls any of the 20 canary or 10 dataset/creator/learner endpoints', async () => {
      const interceptedUrls: string[] = []
      const fetchMock = vi.fn().mockImplementation((url: unknown) => {
        const u = String(url)
        interceptedUrls.push(u)
        if (u === '/api/v1/execution/status') {
          return Promise.resolve(
            makeMockResponse(200, {
              verified: true,
              status: 'HEALTHY',
              engine_state: 'ACTIVE',
            })
          )
        }
        if (u === '/api/v1/market/prices') {
          return Promise.resolve(
            makeMockResponse(200, {
              timestamp_ms: Date.now(),
              prices: { BTCUSDT: 68500, ETHUSDT: 3600, SOLUSDT: 165 },
            })
          )
        }
        if (u === '/api/v1/canary/evolution') {
          return Promise.resolve(
            makeMockResponse(200, {
              verified: true,
              phase: 'evolution',
              active_stage: 'STAGE_5',
            })
          )
        }
        return Promise.resolve(makeMockResponse(404, {}))
      })

      vi.stubGlobal('fetch', fetchMock)

      const telemetry = await fetchPrimaryTelemetry()

      expect(telemetry.executionStatus?.verified).toBe(true)
      expect(telemetry.liveMarketPrices?.prices['BTCUSDT']).toBe(68500)
      expect(telemetry.evolution?.verified).toBe(true)

      // Strict check: zero banned endpoints requested
      for (const banned of ALL_BANNED_ENDPOINTS) {
        expect(interceptedUrls).not.toContain(banned)
      }

      // Check regex patterns: no other canary endpoints, no dataset, no creator, no learner
      for (const url of interceptedUrls) {
        expect(url).not.toMatch(/\/api\/v1\/canary\/(?!evolution)/)
        expect(url).not.toMatch(/\/api\/v1\/dataset\//)
        expect(url).not.toMatch(/\/api\/v1\/creator\//)
        expect(url).not.toMatch(/\/api\/v1\/learner\//)
      }

      expect(interceptedUrls).toEqual([
        '/api/v1/execution/status',
        '/api/v1/market/prices',
        '/api/v1/canary/evolution',
      ])
    })

    it('when local market prices fails and triggers external Binance fallback, never calls legacy canary/dataset endpoints', async () => {
      const interceptedUrls: string[] = []
      const fetchMock = vi.fn().mockImplementation((url: unknown) => {
        const u = String(url)
        interceptedUrls.push(u)

        if (u === '/api/v1/execution/status') {
          return Promise.resolve(makeMockResponse(200, { verified: true }))
        }
        if (u === '/api/v1/market/prices') {
          return Promise.resolve(makeMockResponse(500, { error: 'Internal server error' }))
        }
        if (u === '/api/v1/canary/evolution') {
          return Promise.resolve(makeMockResponse(200, { verified: true }))
        }
        if (u.includes('fapi.binance.com/fapi/v1/ticker/price')) {
          return Promise.resolve(
            makeMockResponse(200, [
              { symbol: 'BTCUSDT', price: '68000.00' },
              { symbol: 'ETHUSDT', price: '3500.00' },
              { symbol: 'SOLUSDT', price: '160.00' },
            ])
          )
        }
        if (u.includes('fapi.binance.com/fapi/v1/premiumIndex')) {
          return Promise.resolve(
            makeMockResponse(200, [
              { symbol: 'BTCUSDT', markPrice: '68000.00', lastFundingRate: '0.000100' },
            ])
          )
        }
        return Promise.resolve(makeMockResponse(404, {}))
      })

      vi.stubGlobal('fetch', fetchMock)

      const telemetry = await fetchPrimaryTelemetry()

      expect(telemetry.executionStatus?.verified).toBe(true)
      expect(telemetry.evolution?.verified).toBe(true)
      expect(telemetry.liveMarketPrices?.source).toBe('binance_direct')

      for (const banned of ALL_BANNED_ENDPOINTS) {
        expect(interceptedUrls).not.toContain(banned)
      }
      for (const url of interceptedUrls) {
        expect(url).not.toMatch(/\/api\/v1\/canary\/(?!evolution)/)
        expect(url).not.toMatch(/\/api\/v1\/dataset\//)
        expect(url).not.toMatch(/\/api\/v1\/creator\//)
        expect(url).not.toMatch(/\/api\/v1\/learner\//)
      }
    })

    it('under catastrophic network rejection, never calls legacy canary or dataset endpoints', async () => {
      const interceptedUrls: string[] = []
      const fetchMock = vi.fn().mockImplementation((url: unknown) => {
        interceptedUrls.push(String(url))
        return Promise.reject(new Error('Network socket disconnected'))
      })

      vi.stubGlobal('fetch', fetchMock)

      const telemetry = await fetchPrimaryTelemetry()

      expect(telemetry.executionStatus).toBeNull()
      expect(telemetry.evolution).toBeNull()

      for (const banned of ALL_BANNED_ENDPOINTS) {
        expect(interceptedUrls).not.toContain(banned)
      }
    })
  })

  describe('Adversarial Verification 2: Edge cases with mock fetch', () => {
    it('gracefully handles all 3 primary endpoints failing without throwing unhandled exceptions', async () => {
      const fetchMock = vi.fn().mockRejectedValue(new Error('Connection reset by peer'))
      vi.stubGlobal('fetch', fetchMock)

      let result: Awaited<ReturnType<typeof fetchPrimaryTelemetry>> | null = null
      let caughtError: unknown = null

      try {
        result = await fetchPrimaryTelemetry()
      } catch (err) {
        caughtError = err
      }

      // Assert that fetchPrimaryTelemetry never throws on network failure
      expect(caughtError).toBeNull()
      expect(result).not.toBeNull()
      expect(result?.executionStatus).toBeNull()
      expect(result?.evolution).toBeNull()
      // When both local and binance market endpoints fail to connect,
      // liveMarketPrices provides safe fallback ticker data so downstream UI models do not crash
      expect(result?.liveMarketPrices).toBeDefined()
      expect(result?.liveMarketPrices?.source).toBe('binance_direct')
    })

    it('gracefully handles all 3 primary endpoints returning HTTP 500 server errors', async () => {
      const fetchMock = vi.fn().mockImplementation(() =>
        Promise.resolve(makeMockResponse(500, { detail: 'Fatal gateway error' }))
      )
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchPrimaryTelemetry()

      expect(result.executionStatus).toBeNull()
      expect(result.evolution).toBeNull()
      expect(result.liveMarketPrices).toBeDefined()
    })

    it('gracefully handles only executionStatus failing while marketPrices and evolution succeed', async () => {
      const fetchMock = vi.fn().mockImplementation((url: unknown) => {
        const u = String(url)
        if (u === '/api/v1/execution/status') {
          return Promise.reject(new Error('PostgreSQL deadlock / timeout'))
        }
        if (u === '/api/v1/market/prices') {
          return Promise.resolve(
            makeMockResponse(200, {
              timestamp_ms: Date.now(),
              prices: { BTCUSDT: 67000 },
            })
          )
        }
        if (u === '/api/v1/canary/evolution') {
          return Promise.resolve(
            makeMockResponse(200, {
              verified: true,
              phase: 'evolution',
            })
          )
        }
        return Promise.resolve(makeMockResponse(404, {}))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchPrimaryTelemetry()

      expect(result.executionStatus).toBeNull()
      expect(result.liveMarketPrices?.prices['BTCUSDT']).toBe(67000)
      expect(result.evolution?.verified).toBe(true)
    })

    it('gracefully handles only marketPrices failing while executionStatus and evolution succeed', async () => {
      const fetchMock = vi.fn().mockImplementation((url: unknown) => {
        const u = String(url)
        if (u === '/api/v1/execution/status') {
          return Promise.resolve(makeMockResponse(200, { verified: true, status: 'HEALTHY' }))
        }
        if (u === '/api/v1/market/prices') {
          return Promise.reject(new Error('Feed timeout'))
        }
        if (u.includes('fapi.binance.com')) {
          return Promise.reject(new Error('Binance rate limit 429'))
        }
        if (u === '/api/v1/canary/evolution') {
          return Promise.resolve(makeMockResponse(200, { verified: true, active_stage: 'STAGE_1' }))
        }
        return Promise.resolve(makeMockResponse(404, {}))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchPrimaryTelemetry()

      expect(result.executionStatus?.verified).toBe(true)
      expect(result.evolution?.verified).toBe(true)
      // Prices safe fallback structure is available
      expect(result.liveMarketPrices).toBeDefined()
    })

    it('gracefully handles only evolution failing while executionStatus and marketPrices succeed', async () => {
      const fetchMock = vi.fn().mockImplementation((url: unknown) => {
        const u = String(url)
        if (u === '/api/v1/execution/status') {
          return Promise.resolve(makeMockResponse(200, { verified: true, status: 'HEALTHY' }))
        }
        if (u === '/api/v1/market/prices') {
          return Promise.resolve(
            makeMockResponse(200, {
              timestamp_ms: Date.now(),
              prices: { BTCUSDT: 67200 },
            })
          )
        }
        if (u === '/api/v1/canary/evolution') {
          return Promise.reject(new Error('Evolution engine restarting'))
        }
        return Promise.resolve(makeMockResponse(404, {}))
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchPrimaryTelemetry()

      expect(result.executionStatus?.verified).toBe(true)
      expect(result.liveMarketPrices?.prices['BTCUSDT']).toBe(67200)
      expect(result.evolution).toBeNull()
    })

    it('gracefully handles corrupted non-JSON responses from all endpoints', async () => {
      const fetchMock = vi.fn().mockImplementation(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: async () => {
            throw new SyntaxError('Unexpected token < in JSON at position 0')
          },
        })
      )
      vi.stubGlobal('fetch', fetchMock)

      const result = await fetchPrimaryTelemetry()

      expect(result.executionStatus).toBeNull()
      expect(result.evolution).toBeNull()
      expect(result.liveMarketPrices).toBeDefined()
    })

    it('supports rapid concurrent polling invocations without state collision', async () => {
      let callCount = 0
      const fetchMock = vi.fn().mockImplementation((url: unknown) => {
        callCount++
        const u = String(url)
        return Promise.resolve(
          makeMockResponse(200, {
            verified: true,
            url: u,
            callId: callCount,
          })
        )
      })
      vi.stubGlobal('fetch', fetchMock)

      const batch = await Promise.all([
        fetchPrimaryTelemetry(),
        fetchPrimaryTelemetry(),
        fetchPrimaryTelemetry(),
        fetchPrimaryTelemetry(),
      ])

      expect(batch).toHaveLength(4)
      for (const item of batch) {
        expect(item.executionStatus?.verified).toBe(true)
        expect(item.evolution?.verified).toBe(true)
      }
    })
  })

  describe('Adversarial Verification 3: Source code contracts & architecture audit', () => {
    it('verifies that App.tsx 10-second polling interval ONLY calls fetchPrimaryTelemetry', () => {
      expect(appSource).toContain('fetchPrimaryTelemetry()')
      expect(appSource).not.toContain('fetchCanaryDashboardData()')
      expect(appSource).not.toContain('fetchOverviewData()')

      const timerBlockMatch = appSource.match(/setInterval\(\(\)\s*=>\s*\{([\s\S]*?)\},\s*10000\)/)
      expect(timerBlockMatch).not.toBeNull()
      const timerBody = timerBlockMatch![1]

      expect(timerBody).toContain('fetchPrimaryTelemetry()')
      expect(timerBody).not.toContain('fetchCanary')
      expect(timerBody).not.toContain('fetchOptional')
      expect(timerBody).not.toContain('fetchCreator')
      expect(timerBody).not.toContain('fetchLearner')
    })

    it('verifies that App.tsx code-splits all 21 historical archive pages with React.lazy', () => {
      const archivePages = [
        'AccountingPage',
        'CreatorPage',
        'ExecutionPage',
        'LearnerPage',
        'LifecyclePage',
        'LiveMarketPage',
        'MicrostructurePage',
        'RiskPage',
        'StrategyActivationPage',
        'StressPage',
        'StrategyMiningPage',
        'PortfolioRebalancingPage',
        'TestnetGatewayPage',
        'BracketPositionsPage',
        'ExecutionGuardPage',
        'OrchestratorPage',
        'CalibrationPage',
        'EnsemblePage',
        'TestnetBridgePage',
        'KillSwitchPage',
        'ProductionLaunchPage',
      ]

      for (const pageName of archivePages) {
        const lazyRegex = new RegExp(`const\\s+${pageName}\\s*=\\s*React\\.lazy`)
        expect(appSource).toMatch(lazyRegex)
      }

      // EvolutionPage must NOT be lazy loaded because it is a primary navigation tab
      expect(appSource).not.toMatch(/const\s+EvolutionPage\s*=\s*React\.lazy/)
      expect(appSource).toMatch(/import\s*\{\s*EvolutionPage\s*\}\s*from\s*['"]@\/components\/evolution-page['"]/)
    })

    it('verifies that fetchPrimaryTelemetry in api.ts does not reference any legacy canary or dataset endpoints', () => {
      const fnMatch = apiSource.match(/export\s+async\s+function\s+fetchPrimaryTelemetry\(\)[\s\S]*?\n\}/)
      expect(fnMatch).not.toBeNull()
      const fnBody = fnMatch![0]

      for (const banned of ALL_BANNED_ENDPOINTS) {
        expect(fnBody).not.toContain(banned)
      }

      expect(fnBody).toContain('fetchExecutionStatus()')
      expect(fnBody).toContain('fetchLiveMarketPrices()')
      expect(fnBody).toContain('fetchCanaryAutoEvolution()')
    })
  })
})
