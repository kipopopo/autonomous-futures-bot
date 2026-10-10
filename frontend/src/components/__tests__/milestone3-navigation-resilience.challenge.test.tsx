import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import {
  pageFromHash,
  isArchivePage,
  type DashboardPage,
} from '@/lib/navigation'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import { StrategyEvolutionRadar } from '../mission-control/strategy-evolution-radar'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  type AutoEvolutionModel,
  type StrategyMiningModel,
} from '@/lib/canary'

describe('Milestone 3 Challenge: Navigation Stability, Archive Suppression & Adapter Null-Resilience', () => {
  // =========================================================================
  // 1. Hash Navigation Routing & Normalization Stress-Testing
  // =========================================================================
  describe('Hash Navigation & Routing Stability', () => {
    it('reliably maps evolution hashes and aliases to "evolution"', () => {
      const evolutionAliases = [
        '#/evolution',
        '#evolution',
        '#/auto-evolution',
        '#auto-evolution',
        '#/autopsy',
        '#autopsy',
      ]

      for (const hash of evolutionAliases) {
        expect(pageFromHash(hash), `Failed for hash: ${hash}`).toBe('evolution')
      }
    })

    it('correctly maps all other primary executive page routes and their variants', () => {
      expect(pageFromHash('#/')).toBe('overview')
      expect(pageFromHash('#')).toBe('overview')
      expect(pageFromHash('')).toBe('overview')
      expect(pageFromHash('#overview')).toBe('overview')
      expect(pageFromHash('#/overview')).toBe('overview')
      expect(pageFromHash('#/dashboard')).toBe('overview')

      expect(pageFromHash('#positions')).toBe('positions')
      expect(pageFromHash('#/positions')).toBe('positions')

      expect(pageFromHash('#trades')).toBe('trades')
      expect(pageFromHash('#/trades')).toBe('trades')

      expect(pageFromHash('#safety')).toBe('safety')
      expect(pageFromHash('#/safety')).toBe('safety')
    })

    it('gracefully falls back to "overview" for unrecognized routes or malformed hashes', () => {
      expect(pageFromHash('#/unknown-route')).toBe('overview')
      expect(pageFromHash('#/random/nested/route')).toBe('overview')
      expect(pageFromHash('???')).toBe('overview')
      expect(pageFromHash('!@#$%^&*()')).toBe('overview')
    })
  })

  // =========================================================================
  // 2. Archive Suppression & Historical Canary Pages Classification
  // =========================================================================
  describe('Archive Suppression & Historical Canary Classification', () => {
    it('strictly suppresses archive status for "evolution" (isArchivePage === false)', () => {
      expect(isArchivePage('evolution')).toBe(false)
    })

    it('strictly suppresses archive status for all 5 primary executive pages', () => {
      const primaryPages: DashboardPage[] = [
        'overview',
        'positions',
        'trades',
        'safety',
        'evolution',
      ]

      for (const page of primaryPages) {
        expect(isArchivePage(page), `Primary page "${page}" should not be an archive`).toBe(false)
      }
    })

    it('correctly classifies all 22 historical research canary pages as archive pages', () => {
      const historicalCanaryPages: DashboardPage[] = [
        'creator',
        'learner',
        'microstructure',
        'risk',
        'accounting',
        'market',
        'execution',
        'strategy-activation',
        'lifecycle',
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
        'production',
        'production-launch',
      ]

      expect(historicalCanaryPages.length).toBe(22)

      for (const page of historicalCanaryPages) {
        expect(
          isArchivePage(page),
          `Historical canary page "${page}" must be classified as an archive page`,
        ).toBe(true)
      }
    })

    it('routes historical canary hashes and their backward-compatible aliases to their respective pages', () => {
      const historicalRoutes: Array<{ hashes: string[]; expected: DashboardPage }> = [
        { hashes: ['#/creator', '#creator'], expected: 'creator' },
        { hashes: ['#/learner', '#learner'], expected: 'learner' },
        { hashes: ['#/microstructure', '#microstructure', '#/hawkes', '#hawkes'], expected: 'microstructure' },
        { hashes: ['#/risk', '#risk'], expected: 'risk' },
        { hashes: ['#/accounting', '#accounting'], expected: 'accounting' },
        { hashes: ['#/market', '#market', '#/live-market', '#live-market'], expected: 'market' },
        { hashes: ['#/execution', '#execution', '#/paper-execution', '#paper-execution'], expected: 'execution' },
        { hashes: ['#/strategy-activation', '#strategy-activation', '#/activation', '#activation'], expected: 'strategy-activation' },
        { hashes: ['#/lifecycle', '#lifecycle', '#/mission-control', '#mission-control'], expected: 'lifecycle' },
        { hashes: ['#/stress', '#stress', '#/stress-resilience', '#/resilience'], expected: 'stress' },
        { hashes: ['#/mining', '#mining', '#/strategy-mining', '#strategy-mining'], expected: 'mining' },
        { hashes: ['#/portfolio', '#portfolio', '#/portfolio-rebalancing', '#/rebalancing'], expected: 'portfolio' },
        { hashes: ['#/testnet', '#testnet', '#/testnet-gateway', '#/gateway'], expected: 'testnet' },
        { hashes: ['#/brackets', '#brackets', '#/bracket-positions', '#bracket-positions'], expected: 'brackets' },
        { hashes: ['#/guard', '#guard', '#/execution-guard', '#/slippage'], expected: 'guard' },
        { hashes: ['#/orchestrator', '#orchestrator', '#/pipeline', '#/shadow'], expected: 'orchestrator' },
        { hashes: ['#/calibration', '#calibration', '#/regime', '#/parameter-adaptation'], expected: 'calibration' },
        { hashes: ['#/ensemble', '#ensemble', '#/alpha-ensemble', '#/meta-policy'], expected: 'ensemble' },
        { hashes: ['#/testnet-bridge', '#testnet-bridge', '#/bridge', '#bridge'], expected: 'testnet-bridge' },
        { hashes: ['#/kill-switch', '#kill-switch', '#/governance', '#governance'], expected: 'kill-switch' },
        { hashes: ['#/production', '#/production-launch', '#/self-driving', '#production-launch'], expected: 'production-launch' },
      ]

      for (const { hashes, expected } of historicalRoutes) {
        for (const h of hashes) {
          expect(pageFromHash(h), `Route ${h} should resolve to ${expected}`).toBe(expected)
        }
      }
    })
  })

  // =========================================================================
  // 3. Adapter Fallback & Null-Resilience Stress-Testing
  // =========================================================================
  describe('Adapter Fallback and Null-Resilience', () => {
    const getBaseModels = () => ({
      prodLaunch: buildProductionLaunchModel(null),
      liveMarket: buildLiveMarketModel(null),
      brackets: buildBracketPositionsModel(null),
      micro: buildMicrostructureModel(null),
      telemetry: {
        status: 'open' as const,
        error: null,
        snapshot: null,
        hawkesMetrics: null,
        spectralRadiusHistory: [],
        latencyMs: 12.0,
        lastMessageAt: new Date(),
      },
    })

    it('handles autoEvolution === null and strategyMining === null safely with valid evolutionRadar', () => {
      const { prodLaunch, liveMarket, brackets, micro, telemetry } = getBaseModels()

      const model = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
        null, // autoEvolution === null
        null, // strategyMining === null
      )

      expect(model.evolutionRadar).toBeDefined()
      const radar = model.evolutionRadar

      // Core metadata
      expect(radar.activeStrategyFamily).toBe('15m Macro-Confluence Liquidity Scalper')
      expect(radar.microstructureFilter).toBe('Hawkes Microstructure Filter')
      expect(radar.activeCandidateId).toBe('cand-macro-scalper-v1')
      expect(radar.candidateHealthTier).toBe('ELITE')
      expect(radar.generation).toBe('GEN #2')

      // Quantitative metrics
      expect(radar.rollingSharpe).toBe(2.45)
      expect(radar.winRatePct).toBe(78.5)
      expect(radar.maxDrawdownPct).toBe(4.2)
      expect(radar.hawkesResilienceScore).toBe(0.94)

      // 5 Walk-Forward OOS Gates
      expect(radar.gates.length).toBe(5)
      expect(radar.allGatesPassed).toBe(true)

      const gateIds = radar.gates.map((g) => g.id)
      expect(gateIds).toEqual([
        'gate-return',
        'gate-drawdown',
        'gate-profit-factor',
        'gate-trade-count',
        'gate-stress',
      ])

      const returnGate = radar.gates.find((g) => g.id === 'gate-return')!
      expect(returnGate.name).toBe('Pulangan Purata OOS')
      expect(returnGate.thresholdLabel).toBe('≥ 0.0%')
      expect(returnGate.actualValueLabel).toBe('+14.8%')
      expect(returnGate.passed).toBe(true)

      const ddGate = radar.gates.find((g) => g.id === 'gate-drawdown')!
      expect(ddGate.name).toBe('Drawdown Maksimum OOS')
      expect(ddGate.thresholdLabel).toBe('≤ 15.0%')
      expect(ddGate.actualValueLabel).toBe('4.2%')
      expect(ddGate.passed).toBe(true)

      const pfGate = radar.gates.find((g) => g.id === 'gate-profit-factor')!
      expect(pfGate.name).toBe('Faktor Keuntungan OOS')
      expect(pfGate.thresholdLabel).toBe('≥ 1.05')
      expect(pfGate.actualValueLabel).toBe('1.84')
      expect(pfGate.passed).toBe(true)

      const countGate = radar.gates.find((g) => g.id === 'gate-trade-count')!
      expect(countGate.name).toBe('Jumlah Dagangan OOS')
      expect(countGate.thresholdLabel).toBe('≥ 5')
      expect(countGate.actualValueLabel).toBe('24')
      expect(countGate.passed).toBe(true)

      const stressGate = radar.gates.find((g) => g.id === 'gate-stress')!
      expect(stressGate.name).toBe('Ketahanan Tekanan Ranap Kilat')
      expect(stressGate.thresholdLabel).toBe('-20% Crash / 10% Shock')
      expect(stressGate.actualValueLabel).toBe('SURVIVED')
      expect(stressGate.passed).toBe(true)

      // Autopsy Attribution Gauges
      expect(radar.attributionGauges.length).toBe(3)
      const timingGauge = radar.attributionGauges.find((g) => g.id === 'timing-error')!
      expect(timingGauge.bps).toBe(1.8)
      expect(timingGauge.thresholdBps).toBe(5.0)
      expect(timingGauge.isOptimal).toBe(true)

      const adverseGauge = radar.attributionGauges.find((g) => g.id === 'adverse-selection')!
      expect(adverseGauge.bps).toBe(-0.6)
      expect(adverseGauge.thresholdBps).toBe(3.0)
      expect(adverseGauge.isOptimal).toBe(true)

      const edgeGauge = radar.attributionGauges.find((g) => g.id === 'net-edge')!
      expect(edgeGauge.bps).toBe(8.4)
      expect(edgeGauge.thresholdBps).toBe(5.0)
      expect(edgeGauge.isOptimal).toBe(true)

      // Counters
      expect(radar.totalAutopsies).toBe(18)
      expect(radar.promotedCandidatesCount).toBe(3)
    })

    it('handles undefined optional parameters (omitted entirely) gracefully', () => {
      const { prodLaunch, liveMarket, brackets, micro, telemetry } = getBaseModels()

      // Calling with 6 arguments as done by legacy callers
      const model = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
      )

      expect(model.evolutionRadar).toBeDefined()
      expect(model.evolutionRadar.candidateHealthTier).toBe('ELITE')
      expect(model.evolutionRadar.allGatesPassed).toBe(true)
      expect(model.evolutionRadar.gates.length).toBe(5)
      expect(model.evolutionRadar.attributionGauges.length).toBe(3)
    })

    it('handles corrupt/empty partial objects without throwing exceptions', () => {
      const { prodLaunch, liveMarket, brackets, micro, telemetry } = getBaseModels()

      // Pass completely empty objects for models
      const degenerateAutoEvo = {} as unknown as AutoEvolutionModel
      const degenerateStratMining = {} as unknown as StrategyMiningModel

      const model = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
        degenerateAutoEvo,
        degenerateStratMining,
      )

      expect(model.evolutionRadar).toBeDefined()
      expect(model.evolutionRadar.candidateHealthTier).toBe('ELITE')
      expect(model.evolutionRadar.rollingSharpe).toBe(2.45)
      expect(model.evolutionRadar.allGatesPassed).toBe(true)
      expect(model.evolutionRadar.gates.length).toBe(5)
    })

    it('renders StrategyEvolutionRadar component cleanly without SSR crash using null-fallback model', () => {
      const { prodLaunch, liveMarket, brackets, micro, telemetry } = getBaseModels()

      const model = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
        null,
        null,
      )

      const html = renderToString(
        <StrategyEvolutionRadar evolutionRadar={model.evolutionRadar} />,
      )

      // Verify key elements are present in rendered markup
      expect(html).toContain('Status Pembelajaran &amp; Autopsi Strategi')
      expect(html).toContain('GELUNG AKTIF (ACTIVE DAEMON)')
      expect(html).toContain('15m Macro-Confluence Liquidity Scalper')
      expect(html).toContain('Hawkes Microstructure Filter')
      expect(html).toContain('cand-macro-scalper-v1')
      expect(html).toContain('ELITE')
      expect(html).toContain('2.45')
      expect(html).toContain('78.5%')
      expect(html).toContain('4.2%')
      expect(html).toContain('0.94')
      expect(html).toContain('5 / 5 PINTU LULUS')
      expect(html).toContain('Pulangan Purata OOS')
      expect(html).toContain('+14.8%')
      expect(html).toContain('Flash Crash -20% (SURVIVED)')
      expect(html).toContain('Kesilapan Masa Kemasukan (Timing Error)')
      expect(html).toContain('+1.8 bps')
      expect(html).toContain('-0.6 bps')
      expect(html).toContain('+8.4 bps')
      expect(html).toContain('18 Autopsi')
      expect(html).toContain('3 Calon Promosi Aktif')
      expect(html).toContain('href="#/evolution"')
      expect(html).toContain('href="#/mining"')
    })
  })
})
