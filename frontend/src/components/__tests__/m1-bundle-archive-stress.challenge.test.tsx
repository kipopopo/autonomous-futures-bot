import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToString } from 'react-dom/server'
import { Suspense } from 'react'

import App from '@/App'
import appSource from '@/App.tsx?raw'
import apiSource from '@/lib/api.ts?raw'

// 21 Archive Page Components
import { LiveMarketPage } from '../live-market-page'
import { CreatorPage } from '../creator-page'
import { LearnerPage } from '../learner-page'
import { MicrostructurePage } from '../microstructure-page'
import { RiskPage } from '../risk-page'
import { AccountingPage } from '../accounting-page'
import { ExecutionPage } from '../execution-page'
import { StrategyActivationPage } from '../strategy-activation-page'
import { LifecyclePage } from '../lifecycle-page'
import { StressPage } from '../stress-page'
import { StrategyMiningPage } from '../strategy-mining-page'
import { PortfolioRebalancingPage } from '../portfolio-rebalancing-page'
import { TestnetGatewayPage } from '../testnet-gateway-page'
import { BracketPositionsPage } from '../bracket-positions-page'
import { ExecutionGuardPage } from '../execution-guard-page'
import { OrchestratorPage } from '../orchestrator-page'
import { CalibrationPage } from '../calibration-page'
import { EnsemblePage } from '../ensemble-page'
import { TestnetBridgePage } from '../testnet-bridge-page'
import { KillSwitchPage } from '../kill-switch-page'
import { ProductionLaunchPage } from '../production-launch-page'

// Model Builders
import {
  buildAccountingModel,
  buildAutonomousLifecycleModel,
  buildBracketPositionsModel,
  buildCalibrationModel,
  buildEnsembleModel,
  buildExecutionGuardModel,
  buildKillSwitchModel,
  buildLiveMarketModel,
  buildMicrostructureModel,
  buildOrchestratorModel,
  buildPaperExecutionModel,
  buildPortfolioRebalancingModel,
  buildProductionLaunchModel,
  buildRiskModel,
  buildStrategyActivationModel,
  buildStrategyMiningModel,
  buildStressFaultInjectionModel,
  buildTestnetBridgeModel,
  buildTestnetGatewayModel,
} from '@/lib/canary'
import { buildCreatorModel } from '@/lib/creator'
import { buildLearnerModel } from '@/lib/learner'
import { buildQualificationModel } from '@/lib/qualification'
import { INITIAL_TELEMETRY_STATE } from '@/lib/websocket'
import { fetchPrimaryTelemetry, fetchArchiveDataForPage } from '@/lib/api'
import { BANNED_MALAY_ROOTS } from './phase316-m2-empirical-adversarial.challenge.test'

function createMockResponse(status: number, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

describe('Empirical Adversarial Challenge Suite: Milestone M1 Archive Stress & SSR', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  // --------------------------------------------------------------------------
  // Challenge 1: Verify all 21 Archive Page Components Mount & Render Cleanly
  // --------------------------------------------------------------------------
  describe('Challenge 1: Mount and Render all 21 Archive Page Components', () => {
    it('1. LiveMarketPage mounts and renders with default model', () => {
      const model = buildLiveMarketModel(null)
      const html = renderToString(<LiveMarketPage model={model} />)
      expect(html).toContain('Live Public Market Ingress')
    })

    it('2. CreatorPage mounts and renders with default models', () => {
      const emptyApi = { health: null, bundle: null, components: null }
      const model = buildCreatorModel(emptyApi)
      const qualification = buildQualificationModel(emptyApi)
      const html = renderToString(<CreatorPage model={model} qualification={qualification} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('3. LearnerPage mounts and renders with default model', () => {
      const emptyApi = { health: null, bundle: null, components: null }
      const model = buildLearnerModel(emptyApi)
      const html = renderToString(<LearnerPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('4. MicrostructurePage mounts and renders with default model & telemetry', () => {
      const model = buildMicrostructureModel(null)
      const html = renderToString(<MicrostructurePage model={model} telemetry={INITIAL_TELEMETRY_STATE} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('5. RiskPage mounts and renders with default model', () => {
      const model = buildRiskModel(null)
      const html = renderToString(<RiskPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('6. AccountingPage mounts and renders with default model', () => {
      const model = buildAccountingModel(null)
      const html = renderToString(<AccountingPage model={model} />)
      expect(html).toContain('Accounting')
    })

    it('7. ExecutionPage mounts and renders with default model', () => {
      const model = buildPaperExecutionModel(null)
      const html = renderToString(<ExecutionPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('8. StrategyActivationPage mounts and renders with default model', () => {
      const model = buildStrategyActivationModel(null)
      const html = renderToString(<StrategyActivationPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('9. LifecyclePage mounts and renders with default model', () => {
      const model = buildAutonomousLifecycleModel(null)
      const html = renderToString(<LifecyclePage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('10. StressPage mounts and renders with default model', () => {
      const model = buildStressFaultInjectionModel(null)
      const html = renderToString(<StressPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('11. StrategyMiningPage mounts and renders with default model', () => {
      const model = buildStrategyMiningModel(null)
      const html = renderToString(<StrategyMiningPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('12. PortfolioRebalancingPage mounts and renders with default model', () => {
      const model = buildPortfolioRebalancingModel(null)
      const html = renderToString(<PortfolioRebalancingPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('13. TestnetGatewayPage mounts and renders with default model', () => {
      const model = buildTestnetGatewayModel(null)
      const html = renderToString(<TestnetGatewayPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('14. BracketPositionsPage mounts and renders with default model', () => {
      const model = buildBracketPositionsModel(null)
      const html = renderToString(<BracketPositionsPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('15. ExecutionGuardPage mounts and renders with default model', () => {
      const model = buildExecutionGuardModel(null)
      const html = renderToString(<ExecutionGuardPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('16. OrchestratorPage mounts and renders with default model', () => {
      const model = buildOrchestratorModel(null)
      const html = renderToString(<OrchestratorPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('17. CalibrationPage mounts and renders with default model', () => {
      const model = buildCalibrationModel(null)
      const html = renderToString(<CalibrationPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('18. EnsemblePage mounts and renders with default model', () => {
      const model = buildEnsembleModel(null)
      const html = renderToString(<EnsemblePage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('19. TestnetBridgePage mounts and renders with default model', () => {
      const model = buildTestnetBridgeModel(null)
      const html = renderToString(<TestnetBridgePage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('20. KillSwitchPage mounts and renders with default model', () => {
      const model = buildKillSwitchModel(null)
      const html = renderToString(<KillSwitchPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })

    it('21. ProductionLaunchPage mounts and renders with default model', () => {
      const model = buildProductionLaunchModel(null)
      const html = renderToString(<ProductionLaunchPage model={model} />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(50)
    })
  })

  // --------------------------------------------------------------------------
  // Challenge 2: SSR Compatibility — renderToString(<App />)
  // --------------------------------------------------------------------------
  describe('Challenge 2: SSR Compatibility (renderToString(<App />))', () => {
    it('executes renderToString(<App />) successfully without runtime errors', () => {
      const html = renderToString(<App />)
      expect(html).toBeDefined()
      expect(html.length).toBeGreaterThan(100)
      expect(html).toContain('Autonomous')
      expect(html).toContain('Futures')
      expect(html).toContain('Trading Mission Control')
    })

    it('renders Suspense fallback component cleanly under SSR without crashing', () => {
      const fallbackHtml = renderToString(
        <Suspense
          fallback={
            <section className="card bg-base-200" aria-live="polite">
              <h2>Loading Historical Research Archive</h2>
            </section>
          }
        >
          <div>Archive Content</div>
        </Suspense>,
      )
      expect(fallbackHtml).toContain('Archive Content')
    })

    it('SSR output contains expected English accessibility landmarks', () => {
      const html = renderToString(<App />)
      expect(html).toContain('aria-label="Mobile Navigation"')
      expect(html).toContain('page-footer')
      expect(html).toContain('PAPER-SAFE')
    })
  })

  // --------------------------------------------------------------------------
  // Challenge 3: Dictionary Check Against src/App.tsx (Zero Non-English Words)
  // --------------------------------------------------------------------------
  describe('Challenge 3: Zero Non-English Words in src/App.tsx', () => {
    it('verifies 70+ banned dictionary contains extensive forbidden roots', () => {
      expect(BANNED_MALAY_ROOTS.length).toBeGreaterThanOrEqual(70)
    })

    it('scans src/App.tsx for banned non-English roots and asserts exactly zero violations', () => {
      const violations: Array<{ root: string; line: number; text: string }> = []
      const lines = appSource.split('\n')

      lines.forEach((lineText: string, lineIdx: number) => {
        for (const root of BANNED_MALAY_ROOTS) {
          const pattern = new RegExp(`\\b${root.replace('-', '\\-')}\\b`, 'i')
          if (pattern.test(lineText)) {
            violations.push({
              root,
              line: lineIdx + 1,
              text: lineText.trim(),
            })
          }
        }
      })

      expect(violations).toEqual([])
    })

    it('scans src/lib/api.ts for banned non-English roots and asserts zero violations', () => {
      const violations: Array<{ root: string; line: number; text: string }> = []
      const lines = apiSource.split('\n')

      lines.forEach((lineText: string, lineIdx: number) => {
        for (const root of BANNED_MALAY_ROOTS) {
          const pattern = new RegExp(`\\b${root.replace('-', '\\-')}\\b`, 'i')
          if (pattern.test(lineText)) {
            violations.push({
              root,
              line: lineIdx + 1,
              text: lineText.trim(),
            })
          }
        }
      })

      expect(violations).toEqual([])
    })
  })

  // --------------------------------------------------------------------------
  // Challenge 4: Lazy Loading Dynamic Import Resolution
  // --------------------------------------------------------------------------
  describe('Challenge 4: Dynamic Import Resolution for Code-Split Archive Pages', () => {
    const archiveComponentModules = [
      { name: 'AccountingPage', path: '../accounting-page' },
      { name: 'CreatorPage', path: '../creator-page' },
      { name: 'ExecutionPage', path: '../execution-page' },
      { name: 'LearnerPage', path: '../learner-page' },
      { name: 'LifecyclePage', path: '../lifecycle-page' },
      { name: 'LiveMarketPage', path: '../live-market-page' },
      { name: 'MicrostructurePage', path: '../microstructure-page' },
      { name: 'RiskPage', path: '../risk-page' },
      { name: 'StrategyActivationPage', path: '../strategy-activation-page' },
      { name: 'StressPage', path: '../stress-page' },
      { name: 'StrategyMiningPage', path: '../strategy-mining-page' },
      { name: 'PortfolioRebalancingPage', path: '../portfolio-rebalancing-page' },
      { name: 'TestnetGatewayPage', path: '../testnet-gateway-page' },
      { name: 'BracketPositionsPage', path: '../bracket-positions-page' },
      { name: 'ExecutionGuardPage', path: '../execution-guard-page' },
      { name: 'OrchestratorPage', path: '../orchestrator-page' },
      { name: 'CalibrationPage', path: '../calibration-page' },
      { name: 'EnsemblePage', path: '../ensemble-page' },
      { name: 'TestnetBridgePage', path: '../testnet-bridge-page' },
      { name: 'KillSwitchPage', path: '../kill-switch-page' },
      { name: 'ProductionLaunchPage', path: '../production-launch-page' },
    ]

    it('verifies that exactly 21 archive pages are defined for code-splitting', () => {
      expect(archiveComponentModules.length).toBe(21)
    })

    archiveComponentModules.forEach(({ name, path }) => {
      it(`resolves dynamic import for ${name} from ${path}`, async () => {
        const mod = await import(/* @vite-ignore */ path)
        expect(mod[name]).toBeDefined()
        expect(typeof mod[name]).toBe('function')
      })
    })
  })

  // --------------------------------------------------------------------------
  // Challenge 5: Network API Polling Selective Isolation
  // --------------------------------------------------------------------------
  describe('Challenge 5: Selective Primary Telemetry Polling Isolation', () => {
    it('primary telemetry fetch only requests 3 live endpoints and isolates archive data', async () => {
      const fetchMock = vi.fn().mockImplementation((url: string) => {
        const path = typeof url === 'string' ? url : ''
        if (path === '/api/v1/execution/status') {
          return Promise.resolve(createMockResponse(200, { verified: true }))
        }
        if (path === '/api/v1/market/prices') {
          return Promise.resolve(createMockResponse(200, { timestamp_ms: Date.now(), prices: {} }))
        }
        if (path === '/api/v1/canary/evolution') {
          return Promise.resolve(createMockResponse(200, { verified: true }))
        }
        return Promise.resolve(createMockResponse(404, {}))
      })
      vi.stubGlobal('fetch', fetchMock)

      const telemetry = await fetchPrimaryTelemetry()
      expect(telemetry).toHaveProperty('executionStatus')
      expect(telemetry).toHaveProperty('liveMarketPrices')
      expect(telemetry).toHaveProperty('evolution')
      // Ensure no archive keys exist on primary telemetry response
      const telemetryObj = telemetry as unknown as Record<string, unknown>
      expect(telemetryObj.accounting).toBeUndefined()
      expect(telemetryObj.stressFaultInjection).toBeUndefined()
    })

    it('fetchArchiveDataForPage correctly handles all valid archive pages', async () => {
      const fetchMock = vi.fn().mockImplementation(() =>
        Promise.resolve(createMockResponse(200, { verified: true }))
      )
      vi.stubGlobal('fetch', fetchMock)

      const pages = [
        'accounting',
        'creator',
        'execution',
        'learner',
        'lifecycle',
        'market',
        'microstructure',
        'risk',
        'strategy-activation',
        'stress',
        'mining',
        'portfolio',
        'testnet',
        'brackets',
        'guard',
        'orchestrator',
        'calibration',
        'ensemble',
        'testnet-bridge',
        'kill-switch',
        'production-launch',
        'safety',
      ] as const

      for (const p of pages) {
        const res = await fetchArchiveDataForPage(p)
        expect(res).toBeDefined()
      }
    })
  })
})
