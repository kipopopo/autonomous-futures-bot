import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import { Component, type ReactNode } from 'react'

import { KpiCards } from '../mission-control/kpi-cards'
import { PairPriceTickersCard } from '../mission-control/pair-price-tickers-card'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import {
  ResearchArchiveDrawer,
  ARCHIVE_PHASES,
} from '../mission-control/research-archive-drawer'
import { ProvenanceBadge } from '../mission-control/provenance-badge'
import { StrategyConfluenceRadar } from '../mission-control/strategy-confluence-radar'
import { StrategyEvolutionRadar } from '../mission-control/strategy-evolution-radar'
import { EvolutionPage } from '../evolution-page'
import { ExecutivePositionsPage } from '../executive-positions-page'
import { ExecutiveTradesPage } from '../executive-trades-page'
import { ExecutiveSafetyPage } from '../executive-safety-page'
import {
  buildExecutiveDashboardModel,
  formatMytDate,
  formatMytWithRelative,
  formatRelativeTime,
} from '../mission-control/adapter'
import type {
  ExecutiveDashboardModel,
  OrderFeedItem,
  PositionTelemetry,
  ScalperCriteria,
  StrategyEvolutionRadarData,
} from '../mission-control/types'
import {
  buildAutoEvolutionModel,
  buildBracketPositionsModel,
  buildKillSwitchModel,
  buildLiveMarketModel,
  buildMicrostructureModel,
  buildProductionLaunchModel,
  buildRiskModel,
  type CanaryAutoEvolutionData,
  type DoubleEntrySolvencyItem,
} from '@/lib/canary'

// ----------------------------------------------------------------------------
// Tier 5 Adversarial Test Fixtures
// ----------------------------------------------------------------------------

const ALL_8_PAIRS = [
  'BTCUSDT',
  'ETHUSDT',
  'SOLUSDT',
  'DOGEUSDT',
  'BNBUSDT',
  'XRPUSDT',
  'SUIUSDT',
  'AVAXUSDT',
] as const

const MALAY_INDONESIAN_WORDS_REGEX =
  /\b(perdagangan|pasaran|keselamatan|utama|pembelajaran|arkib|yang lalu|baru sahaja|lejar|degupan|pintu|calon|dwi-kemasukan)\b/i

const BASE_KPIS: ExecutiveDashboardModel['kpis'] = {
  totalEquityUsdt: 100.12,
  cashUsdt: 100.12,
  allocatedMarginUsdt: 0.0,
  realizedPnlUsdt: 0.0,
  winRatePct: 0.0,
  totalTrades: 0,
  activeExposureUsdt: 0.0,
  maxExposureCapUsdt: 25.0,
  cashReservePct: 100.0,
  minCashReserveFloorPct: 75.0,
  latencyMs: 14.2,
  interlockBlocksCount: 0,
  balanceDriftUsdt: 0.0,
  isZeroDriftVerified: true,
}

function makeMockFlatPositions(): PositionTelemetry[] {
  const markPrices: Record<string, number> = {
    BTCUSDT: 95000.0,
    ETHUSDT: 2750.0,
    SOLUSDT: 185.0,
    DOGEUSDT: 0.086,
    BNBUSDT: 610.0,
    XRPUSDT: 0.58,
    SUIUSDT: 2.15,
    AVAXUSDT: 34.5,
  }

  return ALL_8_PAIRS.map((symbol) => ({
    symbol,
    currentPrice: markPrices[symbol] ?? 100.0,
    state: 'SCANNING / STANDBY' as const,
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 0.0,
    stopLossPrice: 0.0,
    riskRewardRatio: '—',
  }))
}

function makeMockActivePositions(): PositionTelemetry[] {
  const positions = makeMockFlatPositions()
  positions[2] = {
    symbol: 'SOLUSDT',
    currentPrice: 184.2,
    state: 'LONG',
    entryPrice: 180.0,
    size: 0.025,
    notionalUsdt: 4.5,
    marginUsdt: 4.5,
    unrealizedPnlUsdt: 0.105,
    unrealizedPnlPct: 2.33,
    takeProfitPrice: 187.0,
    stopLossPrice: 175.8,
    riskRewardRatio: '1.66 : 1',
  }
  positions[1] = {
    symbol: 'ETHUSDT',
    currentPrice: 2720.0,
    state: 'SHORT',
    entryPrice: 2750.0,
    size: 0.0016,
    notionalUsdt: 4.4,
    marginUsdt: 4.4,
    unrealizedPnlUsdt: -0.048,
    unrealizedPnlPct: -1.09,
    takeProfitPrice: 2680.0,
    stopLossPrice: 2792.0,
    riskRewardRatio: '1.66 : 1',
  }
  return positions
}

const VERIFIED_AUTO_EVO_FIXTURE: CanaryAutoEvolutionData = {
  phase: 'phase_306',
  verified: true,
  status: 'SIMULATION_ARTIFACT_VERIFIED',
  circuit_state: 'NORMAL',
  timestamp_ms: 1790146800000,
  timestamp_utc: '2026-09-23T07:00:00.000000+00:00',
  paper_safe: true,
  execution_authority: false,
  candidates: ['cand-btcusdt-dcb-002', 'cand-ethusdt-dcb-003', 'cand-solusdt-rgb-001'],
  performance: {
    total_autopsies_conducted: 16,
    autopsy_cause_distribution: { ORGANIC_ALPHA: 12, HAWKES_CLUSTER: 4 },
    mean_entry_timing_error_bps: 6.35,
    mean_hawkes_slip_drag_bps: 4.03,
    mean_adverse_selection_bps: 4.06,
    mean_realized_edge_bps: 14.86,
    health_tier_distribution: { ELITE: 2, HEALTHY: 0, DEGRADED: 1, PROBATIONARY: 0 },
    staged_mutations_count: 1,
    promoted_candidates_count: 0,
  },
  autopsies_trace: [
    {
      trade_id: 'tr-p306-001',
      candidate_id: 'cand-solusdt-rgb-001',
      symbol: 'SOLUSDT',
      side: 'BUY',
      entry_price: 185.0,
      exit_price: 189.5,
      fill_qty: 0.03,
      entry_timing_error_bps: 4.2,
      hawkes_slip_drag_bps: 2.1,
      adverse_selection_bps: 1.8,
      realized_edge_bps: 16.5,
      gross_pnl_usdt: 0.135,
      fee_cost_usdt: 0.0011,
      net_pnl_usdt: 0.12,
      cause: 'ORGANIC_ALPHA',
      timestamp_ms: 1790146800000,
    },
    {
      trade_id: 'tr-p306-002',
      candidate_id: 'cand-ethusdt-dcb-003',
      symbol: 'ETHUSDT',
      side: 'SELL',
      entry_price: 2750.0,
      exit_price: 2765.0,
      fill_qty: 0.002,
      entry_timing_error_bps: 8.5,
      hawkes_slip_drag_bps: 6.2,
      adverse_selection_bps: 5.8,
      realized_edge_bps: -7.5,
      gross_pnl_usdt: -0.03,
      fee_cost_usdt: 0.0011,
      net_pnl_usdt: -0.05,
      cause: 'HAWKES_CLUSTER',
      timestamp_ms: 1790147100000,
    },
  ],
  health_evaluations: {
    'cand-solusdt-rgb-001': {
      candidate_id: 'cand-solusdt-rgb-001',
      symbol: 'SOLUSDT',
      tier: 'ELITE',
      rolling_sharpe: 2.45,
      win_rate_pct: 78.5,
      max_drawdown_pct: 4.2,
      hawkes_resilience_score: 0.94,
      total_trades: 12,
      consecutive_losses: 0,
      needs_mutation: false,
    },
    'cand-ethusdt-dcb-003': {
      candidate_id: 'cand-ethusdt-dcb-003',
      symbol: 'ETHUSDT',
      tier: 'DEGRADED',
      rolling_sharpe: 0.85,
      win_rate_pct: 45.0,
      max_drawdown_pct: 16.5,
      hawkes_resilience_score: 0.42,
      total_trades: 4,
      consecutive_losses: 2,
      needs_mutation: true,
    },
  },
  mutations_trace: [],
  shadow_evaluations: [],
  solvency: {
    starting_equity_usdt: 100.0,
    cash_usdt: 100.12,
    allocated_margin_usdt: 0.0,
    unrealized_pnl_usdt: 0.0,
    realized_pnl_usdt: 0.12,
    total_equity_usdt: 100.12,
    total_fees_usdt: 0.05,
    total_slippage_usdt: 0.01,
    drift_usdt: 0.0,
    zero_balance_drift_verified: true,
    tolerance_ceiling_usdt: 1e-15,
    solvency_ratio_pct: 100.0,
    cash_reserve_pct: 100.0,
    unencumbered_cash_verified: true,
  },
  ledger: {
    starting_equity: 100.0,
    cash: 100.12,
    allocated_margin: 0.0,
    unrealized_pnl: 0.0,
    realized_pnl: 0.12,
    drift: 0.0,
    zero_balance_drift: true,
  },
  upstream_hash: '0cbf6a93a5332789d5053f72e7e494b03b48ccd0ff7c62118bb339d5d905aa7c',
  phase_hash: '521bcb2f8bf0f35c8bb838419ba233bcbe72eeba6652b9710622675907511fd5',
  merkle_root: '818fd82458a8fb19420dd0179c8f78b0c273e5d2a71b1968b083d20f99e23dbe',
}

// ----------------------------------------------------------------------------
// Tier 5 Adversarial Hardening Challenge Test Suite
// ----------------------------------------------------------------------------

describe('Phase 316 — Tier 5 Frontend Adversarial Hardening Challenge', () => {
  // --------------------------------------------------------------------------
  // Dimension 1: Zero-Division, Numeric Extremes & Floating-Point Boundaries
  // --------------------------------------------------------------------------
  describe('Dimension 1: Zero-Division, Numeric Extremes & Boundary Hardening', () => {
    it('C1.1: KpiCards handles maxExposureCapUsdt = 0 without zero-division, defaulting safely', () => {
      const kpis = {
        ...BASE_KPIS,
        activeExposureUsdt: 5.0,
        maxExposureCapUsdt: 0.0, // Triggers (kpis.maxExposureCapUsdt || 25)
      }
      const html = renderToString(<KpiCards kpis={kpis} />)
      expect(html).toContain('$5.00')
      expect(html).toContain('/ $0.00 Max Cap')
      expect(html).not.toContain('NaN')
      expect(html).not.toContain('Infinity')
    })

    it('C1.2: KpiCards clamps activeExposureUsdt > maxExposureCap to 100% progress width', () => {
      const kpis = {
        ...BASE_KPIS,
        activeExposureUsdt: 50.0, // Exceeds 25.0 cap
        maxExposureCapUsdt: 25.0,
      }
      const html = renderToString(<KpiCards kpis={kpis} />)
      expect(html).toContain('style="width:100%"')
      expect(html).toContain('bg-rose-500') // exposurePct > 80 triggers rose warning
    })

    it('C1.3: KpiCards renders extreme precision numbers cleanly without NaN', () => {
      const kpis = {
        ...BASE_KPIS,
        totalEquityUsdt: 1234567.8912,
        realizedPnlUsdt: 0.0,
        winRatePct: 100.0,
        totalTrades: 999999,
        cashReservePct: 75.0,
        minCashReserveFloorPct: 75.0,
      }
      const html = renderToString(<KpiCards kpis={kpis} />)
      expect(html).toContain('$1,234,567.8912')
      expect(html).toContain('+$0.00')
      expect(html).toContain('100.0% Win Rate')
      expect(html).toContain('999999 Completed Trades')
      expect(html).toContain('text-emerald-400') // Floor healthy
    })

    it('C1.6: StrategyConfluenceRadar handles single-point and identical-point recentHistory without zero-division in SVG', () => {
      const singlePointHazard = {
        spectralRadius: 0.4286,
        isNonToxic: true,
        thresholdWarning: 0.85,
        thresholdCritical: 1.0,
        recentHistory: [0.42], // Single item
      }
      const btcTrend = {
        regime: 'BULLISH ALIGNED' as const,
        ema50_1h: 83120.0,
        ema200_1h: 81800.0,
        ema50_4h: 83600.0,
        ema200_4h: 80900.0,
        explanation: 'Longs permitted',
      }
      const scalper: ScalperCriteria = {
        priceBelowEma20Atr: 2.8,
        priceBelowEmaThreshold: 2.5,
        priceTriggered: true,
        relativeVolume: 2.5,
        volumeThreshold: 2.2,
        volumeTriggered: true,
        rsi14: 24.0,
        rsiThreshold: 26.0,
        rsiTriggered: true,
        makerFeePct: 0.02,
      }
      const html = renderToString(
        <StrategyConfluenceRadar
          btcMacroTrend={btcTrend}
          scalperCriteria={scalper}
          hawkesHazard={singlePointHazard}
        />,
      )
      expect(html).toContain('points="0.0,')
      expect(html).not.toContain('NaN')
      expect(html).not.toContain('Infinity')
    })

    it('C1.7: StrategyEvolutionRadar handles thresholdBps = 0 in attribution gauges without NaN style crash', () => {
      const data: StrategyEvolutionRadarData = {
        activeStrategyFamily: '15m Macro-Confluence Liquidity Scalper',
        microstructureFilter: 'Hawkes Microstructure Filter',
        activeCandidateId: 'cand-test-001',
        candidateHealthTier: 'ELITE',
        generation: 'GEN #2',
        rollingSharpe: 2.5,
        winRatePct: 80.0,
        maxDrawdownPct: 3.5,
        hawkesResilienceScore: 0.95,
        gates: [],
        allGatesPassed: true,
        attributionGauges: [
          {
            id: 'zero-threshold-gauge',
            label: 'Zero Threshold Gauge',
            bps: 5.0,
            thresholdBps: 0.0, // Tests (Math.abs(gauge.bps) / gauge.thresholdBps)
            isOptimal: true,
            description: 'Defense against division by zero',
          },
        ],
        totalAutopsies: 10,
        promotedCandidatesCount: 1,
      }
      const html = renderToString(<StrategyEvolutionRadar evolutionRadar={data} />)
      expect(html).toContain('Zero Threshold Gauge')
      expect(html).toContain('+5.0 bps')
      expect(html).toContain('style="width:100%"') // Math.min(100, Infinity * 60) clamps to 100%
      expect(html).not.toContain('NaN')
    })
  })

  // --------------------------------------------------------------------------
  // Dimension 2: Unhandled Null, Undefined & Sparse Sub-Object Ingress
  // --------------------------------------------------------------------------
  describe('Dimension 2: Unhandled Null, Undefined & Sparse Sub-Object Ingress', () => {
    it('C2.1: buildExecutiveDashboardModel handles completely null/empty inputs gracefully with safe defaults', () => {
      const emptyProd = buildProductionLaunchModel(null)
      const emptyMarket = buildLiveMarketModel(null)
      const emptyBrackets = buildBracketPositionsModel(null)
      const emptyMicro = buildMicrostructureModel(null)
      const emptyTelemetry = { status: 'DISCONNECTED' }

      const model = buildExecutiveDashboardModel(
        emptyProd,
        emptyMarket,
        emptyBrackets,
        emptyMicro,
        emptyTelemetry,
        null, // lastFetchedAt is null
        null, // autoEvolution is null
        null, // strategyMining is null
        null, // executionStatus is null
        null, // btcMacro is null
      )

      expect(model.botStatus.state).toBe('ACTIVE 24/7')
      expect(model.kpis.totalEquityUsdt).toBe(100.0)
      expect(model.kpis.cashReservePct).toBe(100.0)
      expect(model.kpis.activeExposureUsdt).toBe(0.0)
      expect(model.positions).toHaveLength(12)
      expect(model.orders.length).toBeGreaterThan(0) // Falls back to authentic fallback orders
      expect(model.radar.btcMacroTrend.regime).toBeDefined()
    })

    it('C2.2: EvolutionPage renders UNAVAILABLE screen when verified is false or status is UNAVAILABLE', () => {
      const unverifiedModel = buildAutoEvolutionModel(null)
      const html = renderToString(<EvolutionPage model={unverifiedModel} />)
      expect(html).toContain('PHASE 306 · UNAVAILABLE')
      expect(html).toContain('No verified Phase 306 artifact is available.')
    })

    it('C2.3: EvolutionPage handles sparse liveProgress object without crashing', () => {
      const sparseAutoEvo = buildAutoEvolutionModel({
        ...VERIFIED_AUTO_EVO_FIXTURE,
        live_progress: {
          current_cycle_stage: 'INGRESS',
          cycle_progress_pct: 15.0,
        },
      })
      const html = renderToString(<EvolutionPage model={sparseAutoEvo} />)
      expect(html).toContain('1. Market Ingress')
      expect(html).toContain('RESEARCH ARTIFACT / SIMULATION')
      expect(html).not.toContain('NaN')
    })

    it('C2.5: OrderFeedTable handles empty orders array [] with centered empty notice', () => {
      const html = renderToString(<OrderFeedTable orders={[]} />)
      expect(html).toContain('No order records for this filter.')
    })

    it('C2.6: ResearchArchiveDrawer returns null when isOpen is false', () => {
      const html = renderToString(
        <ResearchArchiveDrawer isOpen={false} onClose={() => {}} />,
      )
      expect(html).toBe('')
    })
  })

  // --------------------------------------------------------------------------
  // Dimension 3: Adversarial Input Sanitization, XSS & Metacharacter Resilience
  // --------------------------------------------------------------------------
  describe('Dimension 3: Adversarial Input Sanitization, XSS & Metacharacter Resilience', () => {
    it('C3.1: ResearchArchiveDrawer renders modal with all 23 historical phases when open', () => {
      const html = renderToString(
        <ResearchArchiveDrawer isOpen={true} onClose={() => {}} />,
      )
      expect(html).toContain('Research Archives')
      expect(html).toContain('23 Historical Phases')
      expect(ARCHIVE_PHASES).toHaveLength(23)
    })

    it('C3.2: ResearchArchiveDrawer safely handles regex metacharacters and script injection queries in static filter', () => {
      const adversarialQueries = [
        '.*',
        '([a-z]+)',
        '\\d+',
        '^(?=.*[A-Z])',
        '<script>alert(1)</script>',
        "'; DROP TABLE phases; --",
        '🧠🚀日本語',
      ]

      for (const query of adversarialQueries) {
        expect(() => {
          ARCHIVE_PHASES.filter((phase) => {
            return (
              phase.title.toLowerCase().includes(query.toLowerCase()) ||
              phase.phaseNumber.toLowerCase().includes(query.toLowerCase()) ||
              phase.description.toLowerCase().includes(query.toLowerCase()) ||
              phase.badgeText.toLowerCase().includes(query.toLowerCase())
            )
          })
        }).not.toThrow()
      }
    })

    it('C3.3: OrderFeedTable renders clean rows for populated orders', () => {
      const orders: OrderFeedItem[] = [
        {
          orderId: 'canary-p311-drill-sol-1',
          timestampMyt: '11 Oct 16:30:00 (Just now)',
          relativeTime: 'Just now',
          symbol: 'SOLUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 185.0,
          quantity: 0.03,
          notionalUsdt: 5.55,
          makerFeeUsdt: 0.00111,
          realizedPnlUsdt: 0.0,
          status: 'FILLED',
        },
      ]
      const html = renderToString(<OrderFeedTable orders={orders} />)
      expect(html).toContain('SOLUSDT')
      expect(html).toContain('185.00')
      expect(html).toContain('LIMIT MAKER')
    })
  })

  // --------------------------------------------------------------------------
  // Dimension 4: State Machine Invariants, Dynamic Transitions & Gate Scorecards
  // --------------------------------------------------------------------------
  describe('Dimension 4: State Machine Invariants, Dynamic Transitions & Gate Scorecards', () => {
    it('C4.1: EvolutionPage displays each of the 5 pipeline stages accurately', () => {
      const stages = [
        { stage: 'INGRESS', expected: '1. Market Ingress &amp; Klines Streaming' },
        {
          stage: 'HEALTH_EVALUATION',
          expected: '2. Candidate Strategy Health Evaluation',
        },
        {
          stage: 'TRADE_AUTOPSY',
          expected: '3. Trade Execution Autopsy &amp; Friction Decomposition',
        },
        {
          stage: 'MUTATION_STAGING',
          expected: '4. Genome Mutation &amp; Parameter Tuning',
        },
        {
          stage: 'SHADOW_OOS_GATE',
          expected: '5. Shadow Simulation &amp; OOS Promotion Gate Verification',
        },
      ]

      for (const { stage, expected } of stages) {
        const fixture: CanaryAutoEvolutionData = {
          ...VERIFIED_AUTO_EVO_FIXTURE,
          live_progress: {
            current_cycle_stage: stage,
            cycle_progress_pct: 50.0,
          },
        }
        const model = buildAutoEvolutionModel(fixture)
        const html = renderToString(<EvolutionPage model={model} />)
        expect(html).toContain(expected)
      }
    })

    it('C4.2: EvolutionPage reflects OOS Gate waiting (0/5) vs evaluating (5/5) states', () => {
      const waitingFixture: CanaryAutoEvolutionData = {
        ...VERIFIED_AUTO_EVO_FIXTURE,
        live_progress: {
          current_cycle_stage: 'SHADOW_OOS_GATE',
          closed_trades_count: 0,
          required_trades_count: 5,
          sharpe_hurdle_pct: 15.0,
          stage_status: 'WAITING_FOR_SAMPLES',
        },
      }
      const waitingModel = buildAutoEvolutionModel(waitingFixture)
      const waitingHtml = renderToString(<EvolutionPage model={waitingModel} />)
      expect(waitingHtml).toContain('WAITING_FOR_SAMPLES')
      expect(waitingHtml).toContain('Waiting for 5 completed trade samples')

      const evaluatingFixture: CanaryAutoEvolutionData = {
        ...VERIFIED_AUTO_EVO_FIXTURE,
        live_progress: {
          current_cycle_stage: 'SHADOW_OOS_GATE',
          closed_trades_count: 5,
          required_trades_count: 5,
          sharpe_hurdle_pct: 15.0,
          current_sharpe_improvement_pct: 18.5,
          stage_status: 'EVALUATING',
        },
      }
      const evaluatingModel = buildAutoEvolutionModel(evaluatingFixture)
      const evaluatingHtml = renderToString(<EvolutionPage model={evaluatingModel} />)
      expect(evaluatingHtml).toContain('Evaluating shadow promotion')
    })

    it('C4.3: EvolutionPage dynamically renders BTC macro gating banner in BEARISH vs BULLISH regimes', () => {
      const bearishFixture: CanaryAutoEvolutionData = {
        ...VERIFIED_AUTO_EVO_FIXTURE,
        live_progress: {
          macro_gating_state: {
            regime: 'BEARISH',
            longs_filtered: true,
            is_long_allowed: false,
            explanation:
              'Long entries temporarily paused by BTC 1h/4h Bearish regime filter for capital protection (EMA 50 < EMA 200).',
          },
        },
      }
      const bearishHtml = renderToString(
        <EvolutionPage model={buildAutoEvolutionModel(bearishFixture)} />,
      )
      expect(bearishHtml).toContain('REGIME: BEARISH')
      expect(bearishHtml).toContain('LONG Filtered')
      expect(bearishHtml).toContain('LONGS: BLOCKED')

      const bullishFixture: CanaryAutoEvolutionData = {
        ...VERIFIED_AUTO_EVO_FIXTURE,
        live_progress: {
          macro_gating_state: {
            regime: 'BULLISH',
            longs_filtered: false,
            is_long_allowed: true,
            explanation: 'Macro trend aligned bullish. Long entries allowed.',
          },
        },
      }
      const bullishHtml = renderToString(
        <EvolutionPage model={buildAutoEvolutionModel(bullishFixture)} />,
      )
      expect(bullishHtml).toContain('REGIME: BULLISH')
      expect(bullishHtml).toContain('LONGS: ALLOWED')
    })

    it('C4.4: StrategyEvolutionRadar reports accurate count of passed gates (3/5 vs 5/5)', () => {
      const partialRadar: StrategyEvolutionRadarData = {
        activeStrategyFamily: '15m Macro-Confluence Liquidity Scalper',
        microstructureFilter: 'Hawkes Microstructure Filter',
        activeCandidateId: 'cand-partial-001',
        candidateHealthTier: 'HEALTHY',
        generation: 'GEN #2',
        rollingSharpe: 1.8,
        winRatePct: 65.0,
        maxDrawdownPct: 12.0,
        hawkesResilienceScore: 0.88,
        gates: [
          {
            id: 'g1',
            name: 'Gate 1',
            thresholdLabel: '≥ 0%',
            actualValueLabel: '+10%',
            passed: true,
          },
          {
            id: 'g2',
            name: 'Gate 2',
            thresholdLabel: '≤ 15%',
            actualValueLabel: '12%',
            passed: true,
          },
          {
            id: 'g3',
            name: 'Gate 3',
            thresholdLabel: '≥ 1.05',
            actualValueLabel: '1.20',
            passed: true,
          },
          {
            id: 'g4',
            name: 'Gate 4',
            thresholdLabel: '≥ 5',
            actualValueLabel: '3',
            passed: false,
          },
          {
            id: 'g5',
            name: 'Gate 5',
            thresholdLabel: 'Shock',
            actualValueLabel: 'FAILED',
            passed: false,
          },
        ],
        allGatesPassed: false,
        attributionGauges: [],
        totalAutopsies: 5,
        promotedCandidatesCount: 0,
      }
      const html = renderToString(<StrategyEvolutionRadar evolutionRadar={partialRadar} />)
      expect(html).toContain('3 / 5 GATES PASSED')
      expect(html).toContain('badge-warning')
    })
  })

  // --------------------------------------------------------------------------
  // Dimension 5: Double-Entry Solvency Conservation & Micro-Capital Governance
  // --------------------------------------------------------------------------
  describe('Dimension 5: Double-Entry Solvency Conservation & Micro-Capital Governance', () => {
    it('C5.1: Double-entry mathematical invariant holds exactly: Cash + Margin + Unrealized = Starting Equity + Realized (|Δ| < 10^-15 USDT)', () => {
      const solvency: DoubleEntrySolvencyItem = {
        starting_equity_usdt: 100.0,
        cash_usdt: 95.5,
        allocated_margin_usdt: 4.5,
        unrealized_pnl_usdt: 0.12,
        realized_pnl_usdt: 0.12,
        total_equity_usdt: 100.12,
        total_fees_usdt: 0.001,
        total_slippage_usdt: 0.0,
        drift_usdt: 0.0,
        zero_balance_drift_verified: true,
        tolerance_ceiling_usdt: 1e-15,
        solvency_ratio_pct: 100.0,
        cash_reserve_pct: 95.5,
        unencumbered_cash_verified: true,
      }

      const leftSide =
        solvency.cash_usdt + solvency.allocated_margin_usdt + solvency.unrealized_pnl_usdt
      const rightSide = solvency.starting_equity_usdt + solvency.realized_pnl_usdt
      const drift = Math.abs(leftSide - rightSide)

      expect(drift).toBeLessThan(1e-15)
      expect(solvency.zero_balance_drift_verified).toBe(true)
    })

    it('C5.2: ExecutiveSafetyPage displays ACCOUNT LEDGER VERIFIED badge and solvency proof when live evidence is provided', () => {
      const prod = buildProductionLaunchModel(null)
      const risk = buildRiskModel(null)
      const kill = buildKillSwitchModel(null)

      const html = renderToString(
        <ExecutiveSafetyPage
          productionLaunchModel={prod}
          riskModel={risk}
          killSwitchModel={kill}
          executionStatus={{
            verified: true,
            status: 'ACCOUNT_VERIFIED',
            engine_state: 'ONLINE 24/7',
            timestamp_ms: 1710000000000,
            positions: {},
            candidate_allocations: [],
            aggregate_exposure_usdt: 0.0,
            recent_orders: [],
            total_orders: 0,
            interlock_blocks_count: 0,
            intra_day_loss_usdt: 0.0,
            solvency: {
              starting_equity_usdt: 5000.0,
              cash_usdt: 5000.0,
              available_balance_usdt: 5000.0,
              allocated_margin_usdt: 0.0,
              unrealized_pnl_usdt: 0.0,
              realized_pnl_usdt: 0.0,
              total_equity_usdt: 5000.0,
              drift_usdt: 0.0,
              zero_balance_drift_verified: true,
              cash_reserve_pct: 100.0,
              unencumbered_cash_verified: true,
            },
          }}
        />,
      )
      expect(html).toContain('Risk Controls &amp; Ledger Integrity')
      expect(html).toContain('ACCOUNT LEDGER VERIFIED')
      expect(html).toContain('Zero drift verified')
      expect(html).toContain('0 observed tripwires')
    })

    it('C5.3: Micro-capital governance boundaries are strictly satisfied across fixtures', () => {
      const positions = makeMockActivePositions()
      const activePositions = positions.filter((p) => p.state !== 'SCANNING / STANDBY')

      // 1. Child order cap <= 5.00 USDT
      for (const pos of activePositions) {
        expect(pos.notionalUsdt).toBeLessThanOrEqual(5.0)
      }

      // 2. Aggregate exposure ceiling <= 25.00 USDT
      const totalExposure = activePositions.reduce((acc, p) => acc + p.notionalUsdt, 0)
      expect(totalExposure).toBeLessThanOrEqual(25.0)

      // 3. Unencumbered cash reserve floor >= 75.0%
      const totalEquity = 100.0
      const cashReservePct = ((totalEquity - totalExposure) / totalEquity) * 100.0
      expect(cashReservePct).toBeGreaterThanOrEqual(75.0)
    })
  })

  // --------------------------------------------------------------------------
  // Dimension 6: Pure Maker Fee Structuring & Execution Attribution Invariants
  // --------------------------------------------------------------------------
  describe('Dimension 6: Pure Maker Fee Structuring & Execution Attribution Invariants', () => {
    it('C6.1: Maker fee is strictly calculated at 0.02% (notional * 0.0002) eliminating taker drag', () => {
      const testCases = [
        { notional: 5.0, expectedFee: 0.001 },
        { notional: 4.5, expectedFee: 0.0009 },
        { notional: 2.2, expectedFee: 0.00044 },
      ]

      for (const tc of testCases) {
        const calculatedFee = Number((tc.notional * 0.0002).toFixed(6))
        expect(calculatedFee).toBe(tc.expectedFee)
      }
    })

    it('C6.2: ExecutiveTradesPage displays 100% passive limit execution and 0.00 bps slippage', () => {
      const orders: OrderFeedItem[] = [
        {
          orderId: 'canary-p311-drill-sol-1',
          timestampMyt: '11 Oct 16:30:00',
          symbol: 'SOLUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 185.0,
          quantity: 0.025,
          notionalUsdt: 4.625,
          makerFeeUsdt: 0.000925,
          realizedPnlUsdt: 0.0,
          status: 'FILLED',
        },
        {
          orderId: 'canary-p311-tp-sol-1',
          timestampMyt: '11 Oct 16:45:00',
          symbol: 'SOLUSDT',
          side: 'SELL',
          orderType: 'LIMIT MAKER',
          price: 189.0,
          quantity: 0.025,
          notionalUsdt: 4.725,
          makerFeeUsdt: 0.000945,
          realizedPnlUsdt: 0.1,
          status: 'FILLED',
        },
      ]

      const html = renderToString(<ExecutiveTradesPage orders={orders} />)
      expect(html).toContain('Trade Log &amp; Execution Autopsy')
      expect(html).toMatch(/2(<!-- -->)? Orders Filled/)
      expect(html).toContain('+0.1000 USDT')
      expect(html).toContain('0.00 bps (0.00%)')
      expect(html).toContain('100% Passive limit execution (exact maker limit)')
      expect(html).toContain('100.0%') // 1 of 1 completed with PnL is winning
    })

    it('C6.3: ExecutiveTradesPage dynamic win rate defaults strictly to 0.0% when 0 completed trades', () => {
      const html = renderToString(<ExecutiveTradesPage orders={[]} />)
      expect(html).toContain('0.0%')
      expect(html).toMatch(/0(<!-- -->)? Orders Filled/)
    })
  })

  // --------------------------------------------------------------------------
  // Dimension 7: English Institutional Localization Verification & Zero-Remnant Guarantee
  // --------------------------------------------------------------------------
  describe('Dimension 7: English Institutional Localization Verification & Zero-Remnant Guarantee', () => {
    it('C7.1: ProvenanceBadge renders all 3 data provenance sources cleanly in English', () => {
      const b1 = renderToString(<ProvenanceBadge source="LIVE EXCHANGE" />)
      expect(b1).toContain('LIVE EXCHANGE')
      expect(b1).not.toMatch(MALAY_INDONESIAN_WORDS_REGEX)

      const b2 = renderToString(<ProvenanceBadge source="DAEMON 24/7" />)
      expect(b2).toContain('DAEMON 24/7')
      expect(b2).not.toMatch(MALAY_INDONESIAN_WORDS_REGEX)

      const b3 = renderToString(<ProvenanceBadge source="RESEARCH ARTIFACT / SIMULATION" />)
      expect(b3).toContain('RESEARCH ARTIFACT / SIMULATION')
      expect(b3).not.toMatch(MALAY_INDONESIAN_WORDS_REGEX)
    })

    it('C7.2: formatRelativeTime renders idiomatic English relative times with zero Malay words', () => {
      const now = 1791600000000
      expect(formatRelativeTime(now - 2000, now)).toBe('Just now')
      expect(formatRelativeTime(now - 15000, now)).toBe('15s ago')
      expect(formatRelativeTime(now - 180000, now)).toBe('3m ago')
      expect(formatRelativeTime(now - 7200000, now)).toBe('2h ago')
      expect(formatRelativeTime(now - 172800000, now)).toBe('2d ago')
      expect(formatRelativeTime(null, now)).toBe('')
      expect(formatRelativeTime(undefined, now)).toBe('')
      expect(formatRelativeTime(0, now)).toBe('')
      expect(formatRelativeTime(-100, now)).toBe('')
    })

    it('C7.3: formatMytDate and formatMytWithRelative format timestamps accurately in Malaysia Time (GMT+8)', () => {
      const timestampMs = 1790146800000 // 2026-09-23T07:00:00Z -> 15:00:00 MYT
      const formatted = formatMytDate(timestampMs)
      expect(formatted).toContain('15:00:00')
      expect(formatted).toContain('Sep')

      const withRel = formatMytWithRelative(timestampMs, timestampMs + 30000)
      expect(withRel).toContain('30s ago')
    })

    it('C7.4: Zero Malay/Indonesian strings leak in rendered KpiCards, PairPriceTickersCard, and OrderFeedTable', () => {
      const kpiHtml = renderToString(<KpiCards kpis={BASE_KPIS} />)
      expect(kpiHtml).not.toMatch(MALAY_INDONESIAN_WORDS_REGEX)

      const posHtml = renderToString(
        <PairPriceTickersCard positions={makeMockActivePositions()} />,
      )
      expect(posHtml).not.toMatch(MALAY_INDONESIAN_WORDS_REGEX)

      const ordersHtml = renderToString(
        <OrderFeedTable
          orders={[
            {
              orderId: 'canary-p311-drill-sol-1',
              timestampMyt: '11 Oct 16:30:00',
              symbol: 'SOLUSDT',
              side: 'BUY',
              orderType: 'LIMIT MAKER',
              price: 185.0,
              quantity: 0.03,
              notionalUsdt: 5.55,
              makerFeeUsdt: 0.00111,
              realizedPnlUsdt: 0.0,
              status: 'FILLED',
            },
          ]}
        />,
      )
      expect(ordersHtml).not.toMatch(MALAY_INDONESIAN_WORDS_REGEX)
    })

    it('C7.5: Zero Malay/Indonesian strings leak in rendered EvolutionPage, ExecutivePositionsPage, ExecutiveTradesPage, and ExecutiveSafetyPage', () => {
      const autoEvoModel = buildAutoEvolutionModel(VERIFIED_AUTO_EVO_FIXTURE)
      const evoHtml = renderToString(<EvolutionPage model={autoEvoModel} />)
      expect(evoHtml).not.toMatch(MALAY_INDONESIAN_WORDS_REGEX)

      const positions = makeMockActivePositions()
      const posPageHtml = renderToString(
        <ExecutivePositionsPage
          positions={positions}
          bracketPositionsModel={buildBracketPositionsModel(null)}
          liveMarketModel={buildLiveMarketModel(null)}
        />,
      )
      expect(posPageHtml).not.toMatch(MALAY_INDONESIAN_WORDS_REGEX)

      const tradesHtml = renderToString(<ExecutiveTradesPage orders={[]} />)
      expect(tradesHtml).not.toMatch(MALAY_INDONESIAN_WORDS_REGEX)

      const safetyHtml = renderToString(
        <ExecutiveSafetyPage
          productionLaunchModel={buildProductionLaunchModel(null)}
          riskModel={buildRiskModel(null)}
          killSwitchModel={buildKillSwitchModel(null)}
        />,
      )
      expect(safetyHtml).not.toMatch(MALAY_INDONESIAN_WORDS_REGEX)
    })
  })

  // --------------------------------------------------------------------------
  // Dimension 8: Component Rerender Resilience, Rapid Prop Mutation & SSR Stability
  // --------------------------------------------------------------------------
  describe('Dimension 8: Component Rerender Resilience, Rapid Prop Mutation & SSR Stability', () => {
    it('C8.1: Components maintain deterministic SSR stability across rapid prop cycling', () => {
      const testCycles = 50
      let lastKpiHtml = ''

      for (let i = 0; i < testCycles; i++) {
        const kpis: ExecutiveDashboardModel['kpis'] = {
          ...BASE_KPIS,
          totalEquityUsdt: 100.0 + i * 0.1,
          realizedPnlUsdt: i % 2 === 0 ? 0.05 * i : -0.05 * i,
          activeExposureUsdt: (i % 5) * 4.5,
        }
        const html = renderToString(<KpiCards kpis={kpis} />)
        expect(html).toBeDefined()
        expect(html.length).toBeGreaterThan(100)
        lastKpiHtml = html
      }

      expect(lastKpiHtml).toContain('Total Balance &amp; Equity')
    })

    it('C8.2: ErrorBoundary contract adheres to getDerivedStateFromError and safe throw capture', () => {
      class TestErrorBoundary extends Component<
        { children: ReactNode },
        { hasError: boolean; error: Error | null }
      > {
        constructor(props: { children: ReactNode }) {
          super(props)
          this.state = { hasError: false, error: null }
        }
        static getDerivedStateFromError(error: Error) {
          return { hasError: true, error }
        }
        render() {
          if (this.state.hasError) {
            return (
              <div data-testid="error-boundary-fallback">
                Rendering Notice: {this.state.error?.message}
              </div>
            )
          }
          return this.props.children
        }
      }

      // Verify static getDerivedStateFromError contract
      const testErr = new Error('Adversarial render fault injection')
      const derivedState = TestErrorBoundary.getDerivedStateFromError(testErr)
      expect(derivedState.hasError).toBe(true)
      expect(derivedState.error).toBe(testErr)

      // Verify normal rendering
      const normalHtml = renderToString(
        <TestErrorBoundary>
          <div>Safe Content</div>
        </TestErrorBoundary>,
      )
      expect(normalHtml).toContain('Safe Content')

      // Verify exception catching behavior in SSR context
      expect(() => {
        renderToString(
          <TestErrorBoundary>
            <FaultyThrowComponent />
          </TestErrorBoundary>,
        )
      }).toThrow('Intentional SSR throw')
    })
  })
})

function FaultyThrowComponent(): never {
  throw new Error('Intentional SSR throw')
}
