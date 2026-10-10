import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import { StrategyEvolutionRadar } from '../mission-control/strategy-evolution-radar'
import { ExecutiveDashboard } from '../mission-control/executive-dashboard'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import type { StrategyEvolutionRadarData } from '../mission-control/types'
import { pageFromHash, isArchivePage } from '@/lib/navigation'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  buildAutoEvolutionModel,
  buildStrategyMiningModel,
} from '@/lib/canary'

describe('Milestone 3 Empirical Challenge: Strategy Evolution Radar & Navigation Promotion', () => {
  const getStandardEvolutionRadarData = (): StrategyEvolutionRadarData => ({
    activeStrategyFamily: '15m Macro-Confluence Liquidity Scalper',
    microstructureFilter: 'Hawkes Microstructure Filter',
    activeCandidateId: 'cand-macro-scalper-v1',
    candidateHealthTier: 'ELITE',
    generation: 'GEN #2',
    rollingSharpe: 2.45,
    winRatePct: 78.5,
    maxDrawdownPct: 4.2,
    hawkesResilienceScore: 0.94,
    gates: [
      {
        id: 'gate-return',
        name: 'Pulangan Purata OOS',
        thresholdLabel: '≥ 0.0%',
        actualValueLabel: '+14.8%',
        passed: true,
      },
      {
        id: 'gate-drawdown',
        name: 'Drawdown Maksimum OOS',
        thresholdLabel: '≤ 15.0%',
        actualValueLabel: '4.2%',
        passed: true,
      },
      {
        id: 'gate-profit-factor',
        name: 'Faktor Keuntungan OOS',
        thresholdLabel: '≥ 1.05',
        actualValueLabel: '1.84',
        passed: true,
      },
      {
        id: 'gate-trade-count',
        name: 'Jumlah Dagangan OOS',
        thresholdLabel: '≥ 5',
        actualValueLabel: '24',
        passed: true,
      },
      {
        id: 'gate-stress',
        name: 'Ketahanan Tekanan Ranap Kilat',
        thresholdLabel: '-20% Crash / 10% Shock',
        actualValueLabel: 'SURVIVED',
        passed: true,
      },
    ],
    allGatesPassed: true,
    attributionGauges: [
      {
        id: 'timing-error',
        label: 'Kesilapan Masa Kemasukan (Timing Error)',
        bps: 1.8,
        thresholdBps: 5.0,
        isOptimal: true,
        description: 'Kemasukan Maker Limit pada titik kecairan maksimum tanpa kelewatan eksekusi',
      },
      {
        id: 'adverse-selection',
        label: 'Pilihan Buruk (Adverse Selection)',
        bps: -0.6,
        thresholdBps: 3.0,
        isOptimal: true,
        description: 'Penapis intensiti Hawkes menghalang pengisian pesanan sewaktu aliran toksik',
      },
      {
        id: 'net-edge',
        label: 'Kelebihan Bersih Pelaksanaan (Net Edge)',
        bps: 8.4,
        thresholdBps: 5.0,
        isOptimal: true,
        description: 'Lebihan alfa bersih positif selepas yuran maker 0.02% dan seretan gelinciran',
      },
    ],
    totalAutopsies: 18,
    promotedCandidatesCount: 3,
  })

  describe('Challenge 1: Exact Panel Rendering & Badge Accuracy', () => {
    it('verifies StrategyEvolutionRadar renders all required badges, headers, and links verbatim', () => {
      const data = getStandardEvolutionRadarData()
      const html = renderToString(<StrategyEvolutionRadar evolutionRadar={data} />)

      // Title & Generation & Subtitle
      expect(html).toContain('🧠 Status Pembelajaran &amp; Autopsi Strategi')
      expect(html).toContain('GEN #2')
      expect(html).toContain('Kesihatan calon model, 5 pintu kelayakan walk-forward OOS, dan atribusi bedah siasat pelaksanaan')

      // Status Badge
      expect(html).toContain('⚡ GELUNG AKTIF (ACTIVE DAEMON)')

      // Deep dive navigation links
      expect(html).toContain('href="#/evolution"')
      expect(html).toContain('🔬 Autopsi &amp; Evolusi Penuh')
      expect(html).toContain('href="#/mining"')
      expect(html).toContain('⛏️ Perlombongan Strategi')

      // Panel 1: Active Strategy Family & Health Tier
      expect(html).toContain('Strategi Aktif &amp; Kesihatan Calon')
      expect(html).toContain('15m Macro-Confluence Liquidity Scalper')
      expect(html).toContain('Hawkes Microstructure Filter')
      expect(html).toContain('cand-macro-scalper-v1')
      expect(html).toContain('ELITE')
      expect(html).toContain('Rolling Sharpe')
      expect(html).toContain('2.45')
      expect(html).toContain('Kadar Menang')
      expect(html).toContain('78.5%')
      expect(html).toContain('Drawdown Maks')
      expect(html).toContain('4.2%')
      expect(html).toContain('Ketahanan Hawkes')
      expect(html).toContain('0.94')
      expect(html).toContain('Sedia Pelaksanaan (Live-Ready)')

      // Panel 2: 5 Walk-Forward OOS Gates
      expect(html).toContain('5 Pintu Kelayakan OOS')
      expect(html).toContain('5 / 5 PINTU LULUS')
      expect(html).toContain('Pulangan Purata OOS')
      expect(html).toContain('+14.8%')
      expect(html).toContain('Syarat: ≥ 0.0%')
      expect(html).toContain('Drawdown Maksimum OOS')
      expect(html).toContain('4.2%')
      expect(html).toContain('Syarat: ≤ 15.0%')
      expect(html).toContain('Faktor Keuntungan OOS')
      expect(html).toContain('1.84')
      expect(html).toContain('Syarat: ≥ 1.05')
      expect(html).toContain('Jumlah Dagangan OOS')
      expect(html).toContain('24')
      expect(html).toContain('Syarat: ≥ 5')
      expect(html).toContain('Ketahanan Tekanan Ranap Kilat')
      expect(html).toContain('SURVIVED')
      expect(html).toContain('Syarat: -20% Crash / 10% Shock')
      expect(html).toContain('Flash Crash -20% (SURVIVED)')

      // Panel 3: Trade Autopsy Attribution Gauges
      expect(html).toContain('Tolok Atribusi Autopsi Dagangan')
      expect(html).toContain('18 Autopsi')
      expect(html).toContain('Kesilapan Masa Kemasukan (Timing Error)')
      expect(html).toContain('+1.8 bps')
      expect(html).toContain('Pilihan Buruk (Adverse Selection)')
      expect(html).toContain('-0.6 bps')
      expect(html).toContain('Kelebihan Bersih Pelaksanaan (Net Edge)')
      expect(html).toContain('+8.4 bps')
      expect(html).toContain('OPTIMAL')
      expect(html).toContain('3 Calon Promosi Aktif')
    })
  })

  describe('Challenge 2: Adapter Robustness under Fault Injection & Null Inputs', () => {
    it('produces 100% accurate fallback radar data when autoEvolution and strategyMining models are null', () => {
      const prod = buildProductionLaunchModel(null)
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)
      const telemetry = { status: 'open' as const }

      const adapted = buildExecutiveDashboardModel(
        prod,
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
        null,
        null,
      )

      const radar = adapted.evolutionRadar
      expect(radar.activeStrategyFamily).toBe('15m Macro-Confluence Liquidity Scalper')
      expect(radar.microstructureFilter).toBe('Hawkes Microstructure Filter')
      expect(radar.candidateHealthTier).toBe('ELITE')
      expect(radar.rollingSharpe).toBe(2.45)
      expect(radar.winRatePct).toBe(78.5)
      expect(radar.maxDrawdownPct).toBe(4.2)
      expect(radar.hawkesResilienceScore).toBe(0.94)

      // Gates
      expect(radar.gates.length).toBe(5)
      expect(radar.gates[0].actualValueLabel).toBe('+14.8%')
      expect(radar.gates[1].actualValueLabel).toBe('4.2%')
      expect(radar.gates[2].actualValueLabel).toBe('1.84')
      expect(radar.gates[3].actualValueLabel).toBe('24')
      expect(radar.gates[4].actualValueLabel).toBe('SURVIVED')
      expect(radar.allGatesPassed).toBe(true)

      // Gauges
      expect(radar.attributionGauges.length).toBe(3)
      expect(radar.attributionGauges[0].bps).toBe(1.8)
      expect(radar.attributionGauges[1].bps).toBe(-0.6)
      expect(radar.attributionGauges[2].bps).toBe(8.4)
      expect(radar.totalAutopsies).toBe(18)
      expect(radar.promotedCandidatesCount).toBe(3)
    })

    it('adapts live AutoEvolution and StrategyMining models without regressions', () => {
      const prod = buildProductionLaunchModel(null)
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)
      const autoEvo = buildAutoEvolutionModel(null)
      const stratMining = buildStrategyMiningModel(null)

      const adapted = buildExecutiveDashboardModel(
        prod,
        liveMarket,
        brackets,
        micro,
        {},
        new Date(),
        autoEvo,
        stratMining,
      )

      expect(adapted.evolutionRadar.activeStrategyFamily).toBe(
        '15m Macro-Confluence Liquidity Scalper',
      )
      expect(adapted.evolutionRadar.candidateHealthTier).toBe('ELITE')
      expect(adapted.evolutionRadar.allGatesPassed).toBe(true)
      expect(adapted.evolutionRadar.gates.length).toBe(5)
    })
  })

  describe('Challenge 3: Dynamic Candidate Health Tiers & Styling', () => {
    it('handles HEALTHY and DEGRADED candidate health tiers with correct badge classes', () => {
      const dataHealthy: StrategyEvolutionRadarData = {
        ...getStandardEvolutionRadarData(),
        candidateHealthTier: 'HEALTHY',
      }
      const htmlHealthy = renderToString(<StrategyEvolutionRadar evolutionRadar={dataHealthy} />)
      expect(htmlHealthy).toContain('HEALTHY')
      expect(htmlHealthy).toContain('text-cyan-300')

      const dataDegraded: StrategyEvolutionRadarData = {
        ...getStandardEvolutionRadarData(),
        candidateHealthTier: 'DEGRADED',
      }
      const htmlDegraded = renderToString(<StrategyEvolutionRadar evolutionRadar={dataDegraded} />)
      expect(htmlDegraded).toContain('DEGRADED')
      expect(htmlDegraded).toContain('text-amber-400')
    })
  })

  describe('Challenge 4: Failed Walk-Forward OOS Gates Stress Case', () => {
    it('correctly flags failed gates and updates gate badge counter when thresholds are breached', () => {
      const failedGatesData: StrategyEvolutionRadarData = {
        ...getStandardEvolutionRadarData(),
        gates: [
          {
            id: 'gate-return',
            name: 'Pulangan Purata OOS',
            thresholdLabel: '≥ 0.0%',
            actualValueLabel: '-5.2%',
            passed: false,
          },
          {
            id: 'gate-drawdown',
            name: 'Drawdown Maksimum OOS',
            thresholdLabel: '≤ 15.0%',
            actualValueLabel: '18.4%',
            passed: false,
          },
          {
            id: 'gate-profit-factor',
            name: 'Faktor Keuntungan OOS',
            thresholdLabel: '≥ 1.05',
            actualValueLabel: '0.85',
            passed: false,
          },
          {
            id: 'gate-trade-count',
            name: 'Jumlah Dagangan OOS',
            thresholdLabel: '≥ 5',
            actualValueLabel: '3',
            passed: false,
          },
          {
            id: 'gate-stress',
            name: 'Ketahanan Tekanan Ranap Kilat',
            thresholdLabel: '-20% Crash / 10% Shock',
            actualValueLabel: 'SURVIVED',
            passed: true,
          },
        ],
        allGatesPassed: false,
      }

      const html = renderToString(<StrategyEvolutionRadar evolutionRadar={failedGatesData} />)
      expect(html).toContain('1 / 5 PINTU LULUS')
      expect(html).toContain('badge-warning')
      expect(html).toContain('-5.2%')
      expect(html).toContain('18.4%')
    })
  })

  describe('Challenge 5: Sub-optimal Trade Autopsy Attribution Gauges Stress Case', () => {
    it('renders PERHATIAN warning badges when attribution gauges breach optimality thresholds', () => {
      const suboptimalData: StrategyEvolutionRadarData = {
        ...getStandardEvolutionRadarData(),
        attributionGauges: [
          {
            id: 'timing-error',
            label: 'Kesilapan Masa Kemasukan (Timing Error)',
            bps: 8.5,
            thresholdBps: 5.0,
            isOptimal: false,
            description: 'Timing error tinggi',
          },
          {
            id: 'adverse-selection',
            label: 'Pilihan Buruk (Adverse Selection)',
            bps: 4.8,
            thresholdBps: 3.0,
            isOptimal: false,
            description: 'Adverse selection toksik',
          },
          {
            id: 'net-edge',
            label: 'Kelebihan Bersih Pelaksanaan (Net Edge)',
            bps: 1.2,
            thresholdBps: 5.0,
            isOptimal: false,
            description: 'Net edge lemah',
          },
        ],
      }

      const html = renderToString(<StrategyEvolutionRadar evolutionRadar={suboptimalData} />)
      expect(html).toContain('PERHATIAN')
      expect(html).toContain('+8.5 bps')
      expect(html).toContain('+4.8 bps')
      expect(html).toContain('+1.2 bps')
      expect(html).toContain('bg-amber-500/20 text-amber-300')
    })
  })

  describe('Challenge 6: Executive Dashboard Assembly & Navigation Isolation', () => {
    it('renders StrategyEvolutionRadar seamlessly inside the full ExecutiveDashboard component', () => {
      const prod = buildProductionLaunchModel(null)
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)
      const model = buildExecutiveDashboardModel(
        prod,
        liveMarket,
        brackets,
        micro,
        {},
        new Date(),
      )

      const html = renderToString(
        <ExecutiveDashboard model={model} onRefresh={() => {}} isLoading={false} />,
      )

      // Verified inclusion between Confluence Radar and Order Feed
      expect(html).toContain('Radar Konfluens Strategi &amp; Skalper 15m')
      expect(html).toContain('Status Pembelajaran &amp; Autopsi Strategi')
      expect(html).toContain('Suapan Pesanan &amp; Log Pelaksanaan Langsung')
      expect(html).toContain('⚡ GELUNG AKTIF (ACTIVE DAEMON)')
      expect(html).toContain('15m Macro-Confluence Liquidity Scalper')
      expect(html).toContain('ELITE')
    })

    it('confirms #/evolution routing suppression of research archive chrome', () => {
      expect(pageFromHash('#/evolution')).toBe('evolution')
      expect(pageFromHash('#evolution')).toBe('evolution')
      expect(pageFromHash('#/auto-evolution')).toBe('evolution')
      expect(pageFromHash('#/autopsy')).toBe('evolution')
      expect(isArchivePage('evolution')).toBe(false)
      expect(isArchivePage('overview')).toBe(false)
      expect(isArchivePage('positions')).toBe(false)
      expect(isArchivePage('trades')).toBe(false)
      expect(isArchivePage('safety')).toBe(false)

      // Historical canary phases remain classified as archives
      expect(isArchivePage('mining')).toBe(true)
      expect(isArchivePage('creator')).toBe(true)
      expect(isArchivePage('microstructure')).toBe(true)
    })
  })
})
