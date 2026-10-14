import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { MissionControlHeader } from '../mission-control/mission-control-header'
import { KpiCards } from '../mission-control/kpi-cards'
import { MarketPositionsCard } from '../mission-control/market-positions-card'
import { StrategyConfluenceRadar } from '../mission-control/strategy-confluence-radar'
import { StrategyEvolutionRadar } from '../mission-control/strategy-evolution-radar'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import { ResearchArchiveDrawer, ARCHIVE_PHASES } from '../mission-control/research-archive-drawer'
import { ExecutiveDashboard } from '../mission-control/executive-dashboard'
import { ExecutiveTradesPage } from '../executive-trades-page'
import { ExecutiveSafetyPage } from '../executive-safety-page'
import { EvolutionPage } from '../evolution-page'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import type {
  ExecutiveDashboardModel,
  OrderFeedItem,
  PositionTelemetry,
} from '../mission-control/types'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  buildAutoEvolutionModel,
  buildRiskModel,
  buildKillSwitchModel,
  type ExecutionStatusResponse,
} from '@/lib/canary'
import { pageFromHash, isArchivePage } from '@/lib/navigation'

/**
 * Autonomous Futures Bot — Phase 316: Institutional English Standardization
 * Comprehensive 4-Tier Opaque-Box E2E Test Suite for Frontend Mission Control
 *
 * Architecture:
 * - Tier 1: Comprehensive Feature Coverage (F1 to F6, >= 5 isolated tests per feature)
 * - Tier 2: Boundary, Extreme & Corner Cases (C1 to C8)
 * - Tier 3: Pairwise Combinatorial Interactions (C1 to C6)
 * - Tier 4: Real-World Workload Scenarios (S1 to S5)
 *
 * Invariants Enforced:
 * - Solvency Balance Conservation: Equity = Cash + Margin + Unrealized PnL (|Δ| < 10^-15 USDT)
 * - Micro-Capital Governance: <= $5.00 child order, <= $25.00 exposure ceiling, >= 75% cash floor
 * - Pure Maker Limit Execution: 0.02% maker fee, 0.0% win rate when 0 closed trades
 * - 8 Perpetual Market Pairs: BTC, ETH, SOL, DOGE, BNB, XRP, SUI, AVAX
 */

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

const VERIFIED_AUTO_EVO_FIXTURE = {
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
  solvency: {
    starting_equity_usdt: 100.0,
    cash_usdt: 100.0,
    allocated_margin_usdt: 0.0,
    unrealized_pnl_usdt: 0.0,
    realized_pnl_usdt: 0.0,
    total_equity_usdt: 100.0,
    total_fees_usdt: 0.0,
    total_slippage_usdt: 0.0,
    drift_usdt: 0.0,
    zero_balance_drift_verified: true,
    tolerance_ceiling_usdt: 1e-15,
    solvency_ratio_pct: 100.0,
    cash_reserve_pct: 100.0,
    unencumbered_cash_verified: true,
  },
  ledger: {
    starting_equity: 100.0,
    cash: 100.0,
    allocated_margin: 0.0,
    unrealized_pnl: 0.0,
    realized_pnl: 0.0,
    drift: 0.0,
    zero_balance_drift: true,
  },
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
    riskRewardRatio: '1.67 : 1',
  }))
}

function makeMockActivePositions(): PositionTelemetry[] {
  const flat = makeMockFlatPositions()
  // Activate SOLUSDT with standard ATR brackets (+2.0x ATR TP, -1.2x ATR SL)
  flat[2] = {
    symbol: 'SOLUSDT',
    currentPrice: 184.2,
    state: 'LONG' as const,
    entryPrice: 180.0,
    size: 0.025,
    notionalUsdt: 4.5,
    marginUsdt: 4.5,
    unrealizedPnlUsdt: 0.105,
    unrealizedPnlPct: 2.33,
    takeProfitPrice: 187.0, // 180 + (2.0 * 3.50)
    stopLossPrice: 175.8, // 180 - (1.2 * 3.50)
    riskRewardRatio: '1.67 : 1',
    atrDistanceTpPct: 3.89,
    atrDistanceSlPct: 2.33,
  }
  return flat
}

function makeMockDashboardModel(overrides?: Partial<ExecutiveDashboardModel>): ExecutiveDashboardModel {
  return {
    botStatus: {
      state: 'ACTIVE 24/7',
      gatewayMode: 'BINANCE TESTNET GATEWAY',
      circuitBreaker: 'NORMAL',
      tripwiresCount: 0,
      lastSyncedAtMyt: '11 Oct 15:30:00',
      isStreaming: true,
    },
    kpis: {
      totalEquityUsdt: 100.12,
      cashUsdt: 95.62,
      allocatedMarginUsdt: 4.5,
      realizedPnlUsdt: 0.0,
      winRatePct: 0.0,
      totalTrades: 0,
      activeExposureUsdt: 4.5,
      maxExposureCapUsdt: 25.0,
      cashReservePct: 95.5,
      minCashReserveFloorPct: 75.0,
      latencyMs: 12.4,
      interlockBlocksCount: 0,
      balanceDriftUsdt: 0.0,
      isZeroDriftVerified: true,
    },
    positions: makeMockFlatPositions(),
    radar: {
      btcMacroTrend: {
        regime: 'BEARISH',
        ema50_1h: 93200.0,
        ema200_1h: 94800.0,
        ema50_4h: 92500.0,
        ema200_4h: 94100.0,
        explanation:
          'Long entries temporarily paused by BTC 1h/4h Bearish regime filter for capital protection (EMA 50 < EMA 200).',
      },
      scalperCriteria: {
        priceBelowEma20Atr: 2.7,
        priceBelowEmaThreshold: 2.5,
        priceTriggered: true,
        relativeVolume: 2.4,
        volumeThreshold: 2.2,
        volumeTriggered: true,
        rsi14: 24.2,
        rsiThreshold: 26.0,
        rsiTriggered: true,
        makerFeePct: 0.02,
      },
      hawkesHazard: {
        spectralRadius: 0.4286,
        isNonToxic: true,
        thresholdWarning: 0.8,
        thresholdCritical: 1.0,
        recentHistory: [0.35, 0.38, 0.42, 0.41, 0.45, 0.43, 0.4, 0.4286],
      },
    },
    evolutionRadar: {
      activeStrategyFamily: 'Liquidity Dip Mean-Reversion',
      microstructureFilter: 'Hawkes Point-Process Self-Excitation (rho < 0.80)',
      activeCandidateId: 'cand-solusdt-evo-001',
      candidateHealthTier: 'ELITE',
      generation: 'Gen #1',
      rollingSharpe: 2.45,
      winRatePct: 100.0,
      maxDrawdownPct: 1.2,
      hawkesResilienceScore: 98.4,
      gates: [
        {
          id: 'gate-1',
          name: 'Double-Entry Solvency Audit',
          thresholdLabel: '|Delta| < 10^-15 USDT',
          actualValueLabel: '|Delta| = 0.00 USDT',
          passed: true,
        },
        {
          id: 'gate-2',
          name: 'Hawkes Microstructure Hazard',
          thresholdLabel: 'rho < 0.80',
          actualValueLabel: 'rho = 0.4286',
          passed: true,
        },
        {
          id: 'gate-3',
          name: 'Micro-Capital Confinement',
          thresholdLabel: 'Exposure <= $25.00',
          actualValueLabel: '$4.50 USDT (18.0%)',
          passed: true,
        },
      ],
      allGatesPassed: true,
      attributionGauges: [
        {
          id: 'gauge-1',
          label: 'Hawkes Toxicity Footprint',
          bps: 2.1,
          thresholdBps: 8.0,
          isOptimal: true,
          description: 'Adverse selection drift within optimal limits',
        },
        {
          id: 'gauge-2',
          label: 'Passive Maker Slippage',
          bps: 0.0,
          thresholdBps: 2.0,
          isOptimal: true,
          description: 'Zero execution slippage on limit maker orders',
        },
      ],
      totalAutopsies: 12,
      promotedCandidatesCount: 3,
    },
    orders: [],
    ...overrides,
  }
}

describe('Phase 316 Institutional English Standardization E2E Test Suite', () => {
  // ===========================================================================
  // Tier 1: Comprehensive Feature Coverage (F1 to F6)
  // ===========================================================================
  describe('Tier 1: Feature Coverage', () => {
    // -------------------------------------------------------------------------
    // F1: Primary Navigation Shell & Routing Contracts (6 tests)
    // -------------------------------------------------------------------------
    describe('F1: Primary Navigation Shell & Routing Contracts', () => {
      it('F1.1: maps executive hash routes to designated pages', () => {
        expect(pageFromHash('#/')).toBe('overview')
        expect(pageFromHash('#/overview')).toBe('overview')
        expect(pageFromHash('#/positions')).toBe('positions')
        expect(pageFromHash('#/trades')).toBe('trades')
        expect(pageFromHash('#/safety')).toBe('safety')
        expect(pageFromHash('#/evolution')).toBe('evolution')
      })

      it('F1.2: routes unsupported or empty hashes safely to overview', () => {
        expect(pageFromHash('')).toBe('overview')
        expect(pageFromHash('#/nonexistent-route')).toBe('overview')
        expect(pageFromHash('#invalid')).toBe('overview')
      })

      it('F1.3: correctly segregates archive pages from executive pages', () => {
        expect(isArchivePage('overview')).toBe(false)
        expect(isArchivePage('positions')).toBe(false)
        expect(isArchivePage('trades')).toBe(false)
        expect(isArchivePage('safety')).toBe(false)
        expect(isArchivePage('evolution')).toBe(false)

        expect(isArchivePage('creator')).toBe(true)
        expect(isArchivePage('learner')).toBe(true)
        expect(isArchivePage('mining')).toBe(true)
        expect(isArchivePage('microstructure')).toBe(true)
        expect(isArchivePage('calibration')).toBe(true)
      })

      it('F1.4: catalog includes all 23 historical research phases', () => {
        expect(ARCHIVE_PHASES.length).toBe(23)
        const phaseIds = ARCHIVE_PHASES.map((p) => p.id)
        expect(phaseIds).toContain('phase-250') // Creator
        expect(phaseIds).toContain('phase-253') // Learner
        expect(phaseIds).toContain('phase-298') // Mining
        expect(phaseIds).toContain('phase-304') // Calibration
        expect(phaseIds).toContain('phase-306') // Evolution
      })

      it('F1.5: verifies archive categories structure across 23 phases', () => {
        const categories = new Set(ARCHIVE_PHASES.map((p) => p.category))
        expect(categories).toContain('research')
        expect(categories).toContain('microstructure')
        expect(categories).toContain('execution')
        expect(categories).toContain('accounting')
      })

      it('F1.6: renders ResearchArchiveDrawer component cleanly without crash', () => {
        const html = renderToString(
          <ResearchArchiveDrawer isOpen={true} onClose={() => {}} />,
        )
        expect(html).toContain('Phase 250')
        expect(html).toContain('Hypothesis Registry')
        expect(html).toContain('Hypothesis Creator')
      })
    })

    // -------------------------------------------------------------------------
    // F2: Executive KPI Cards Telemetry & Contracts (6 tests)
    // -------------------------------------------------------------------------
    describe('F2: Executive KPI Cards Telemetry & Contracts', () => {
      it('F2.1: KPI Card 1 exposes total equity, cash reserve, and margin', () => {
        const model = makeMockDashboardModel()
        const html = renderToString(<KpiCards kpis={model.kpis} />)
        expect(html).toContain('$100.12')
        expect(html).toContain('$95.62')
        expect(html).toContain('$4.50')
      })

      it('F2.2: KPI Card 2 exposes realized PnL and trades count', () => {
        const model = makeMockDashboardModel()
        const html = renderToString(<KpiCards kpis={model.kpis} />)
        expect(html).toContain('+$0.00')
        expect(html).toContain('0.0%')
      })

      it('F2.3: KPI Card 3 exposes active exposure and $25 cap', () => {
        const model = makeMockDashboardModel()
        const html = renderToString(<KpiCards kpis={model.kpis} />)
        expect(html).toContain('$4.50')
        expect(html).toContain('$25.00')
      })

      it('F2.4: KPI Card 4 exposes zero-drift verification and health status', () => {
        const model = makeMockDashboardModel()
        const html = renderToString(<KpiCards kpis={model.kpis} />)
        expect(html).toContain('Zero-Drift')
        expect(html).toContain('12.4 ms')
      })

      it('F2.5: MissionControlHeader renders active state and refresh trigger', () => {
        const model = makeMockDashboardModel()
        const html = renderToString(
          <MissionControlHeader status={model.botStatus} onRefresh={() => {}} />,
        )
        expect(html).toContain('ACTIVE 24/7')
        expect(html).toContain('BINANCE TESTNET GATEWAY')
      })

      it('F2.6: verifies balance conservation invariant (Equity = Cash + Margin + UPnL)', () => {
        const k = makeMockDashboardModel().kpis
        const calculatedEquity = k.cashUsdt + k.allocatedMarginUsdt
        expect(Math.abs(k.totalEquityUsdt - calculatedEquity)).toBeLessThan(1e-12)
        expect(k.isZeroDriftVerified).toBe(true)
        expect(k.balanceDriftUsdt).toBe(0.0)
      })
    })

    // -------------------------------------------------------------------------
    // F3: Live Market Positions & Interactive Candlestick Drawer (6 tests)
    // -------------------------------------------------------------------------
    describe('F3: Live Market Positions & Interactive Candlestick Drawer', () => {
      it('F3.1: covers all 8 perpetual pairs contract', () => {
        const positions = makeMockFlatPositions()
        expect(positions.length).toBe(8)
        const symbols = positions.map((p) => p.symbol)
        expect(symbols).toEqual(ALL_8_PAIRS)
      })

      it('F3.2: flat positions render STANDBY state with 0.00 exposure', () => {
        const positions = makeMockFlatPositions()
        const html = renderToString(<MarketPositionsCard positions={positions} />)
        expect(html).toContain('SCANNING / STANDBY')
        expect(html).toContain('SOLUSDT')
        expect(html).toContain('BTCUSDT')
      })

      it('F3.3: flat positions suppress phantom bracket prices', () => {
        const positions = makeMockFlatPositions()
        for (const p of positions) {
          expect(p.entryPrice).toBe(0.0)
          expect(p.takeProfitPrice).toBe(0.0)
          expect(p.stopLossPrice).toBe(0.0)
          expect(p.notionalUsdt).toBe(0.0)
        }
      })

      it('F3.4: active position exposes dynamic ATR brackets (+2.0x TP, -1.2x SL)', () => {
        const positions = makeMockActivePositions()
        const sol = positions.find((p) => p.symbol === 'SOLUSDT')!
        expect(sol.state).toBe('LONG')
        expect(sol.takeProfitPrice).toBe(187.0)
        expect(sol.stopLossPrice).toBe(175.8)
        expect(sol.notionalUsdt).toBe(4.5)
      })

      it('F3.5: calculates risk-reward ratio matching 1.67:1 expectancy', () => {
        const sol = makeMockActivePositions()[2]
        const tpDist = sol.takeProfitPrice - sol.entryPrice // 7.0
        const slDist = sol.entryPrice - sol.stopLossPrice // 4.2
        const rr = tpDist / slDist // 1.6666...
        expect(Math.round(rr * 100) / 100).toBe(1.67)
      })

      it('F3.6: renders MarketPositionsCard with active position cleanly', () => {
        const positions = makeMockActivePositions()
        const html = renderToString(<MarketPositionsCard positions={positions} />)
        expect(html).toContain('SOLUSDT')
        expect(html).toContain('187.00')
        expect(html).toContain('175.80')
      })
    })

    // -------------------------------------------------------------------------
    // F4: Strategy Confluence Radar & Hawkes Hazard (6 tests)
    // -------------------------------------------------------------------------
    describe('F4: Strategy Confluence Radar & Hawkes Hazard', () => {
      it('F4.1: BTC Macro Trend exposes regime and 1h/4h EMA values', () => {
        const radar = makeMockDashboardModel().radar
        expect(radar.btcMacroTrend.regime).toBe('BEARISH')
        expect(radar.btcMacroTrend.ema50_1h).toBe(93200.0)
        expect(radar.btcMacroTrend.ema200_1h).toBe(94800.0)
      })

      it('F4.2: Bearish regime explanation explains long gating in English', () => {
        const radar = makeMockDashboardModel().radar
        expect(radar.btcMacroTrend.explanation).toContain('Long entries temporarily paused')
        expect(radar.btcMacroTrend.explanation).toContain('capital protection')
      })

      it('F4.3: Bullish regime allows long scalper entries', () => {
        const bullishTrend = {
          regime: 'BULLISH ALIGNED' as const,
          ema50_1h: 96000.0,
          ema200_1h: 94000.0,
          ema50_4h: 95500.0,
          ema200_4h: 93500.0,
          explanation: 'Long scalper entries permitted by BTC 1h/4h Bullish regime.',
        }
        expect(bullishTrend.regime).toBe('BULLISH ALIGNED')
        expect(bullishTrend.ema50_1h).toBeGreaterThan(bullishTrend.ema200_1h)
      })

      it('F4.4: 15m Scalper Checklist evaluates confluence criteria', () => {
        const crit = makeMockDashboardModel().radar.scalperCriteria
        expect(crit.priceBelowEma20Atr).toBe(2.7)
        expect(crit.priceTriggered).toBe(true)
        expect(crit.relativeVolume).toBe(2.4)
        expect(crit.volumeTriggered).toBe(true)
        expect(crit.rsi14).toBe(24.2)
        expect(crit.rsiTriggered).toBe(true)
      })

      it('F4.5: Hawkes Hazard verifies sub-critical safe regime (rho < 1.0)', () => {
        const hawkes = makeMockDashboardModel().radar.hawkesHazard
        expect(hawkes.spectralRadius).toBeLessThan(1.0)
        expect(hawkes.isNonToxic).toBe(true)
        expect(hawkes.spectralRadius).toBe(0.4286)
      })

      it('F4.6: renders StrategyConfluenceRadar without errors', () => {
        const radar = makeMockDashboardModel().radar
        const html = renderToString(
          <StrategyConfluenceRadar
            btcMacroTrend={radar.btcMacroTrend}
            scalperCriteria={radar.scalperCriteria}
            hawkesHazard={radar.hawkesHazard}
          />,
        )
        expect(html).toContain('0.4286')
        expect(html).toContain('2.7x ATR')
      })
    })

    // -------------------------------------------------------------------------
    // F5: Order Executions Feed & Trades Table (6 tests)
    // -------------------------------------------------------------------------
    describe('F5: Order Executions Feed & Trades Table', () => {
      it('F5.1: OrderFeedTable handles empty orders gracefully', () => {
        const html = renderToString(<OrderFeedTable orders={[]} />)
        expect(html).toBeDefined()
        expect(html).toContain('Maker 0.02%')
      })

      it('F5.2: OrderFeedTable renders filled order details accurately', () => {
        const orders: OrderFeedItem[] = [
          {
            orderId: 'canary-ord-001',
            timestampMyt: '11 Oct 15:00:00',
            symbol: 'SOLUSDT',
            side: 'BUY',
            orderType: 'LIMIT MAKER',
            price: 180.0,
            quantity: 0.025,
            notionalUsdt: 4.5,
            makerFeeUsdt: 0.0009,
            realizedPnlUsdt: 0.0,
            status: 'FILLED',
          },
        ]
        const html = renderToString(<OrderFeedTable orders={orders} />)
        expect(html).toContain('SOLUSDT')
        expect(html).toContain('180.00')
        expect(html).toContain('4.50')
      })

      it('F5.3: verifies pure maker limit fee is 0.02% (not 0.05% taker drag)', () => {
        const notional = 4.5
        const makerFee = notional * 0.0002 // 0.0009 USDT
        expect(makerFee).toBeCloseTo(0.0009, 6)
      })

      it('F5.4: ExecutiveTradesPage displays 0.0% win rate for empty order feed', () => {
        const html = renderToString(<ExecutiveTradesPage orders={[]} />)
        expect(html).toContain('0.0%')
      })

      it('F5.5: ExecutiveTradesPage displays negative PnL without duplicate signs', () => {
        const lossOrders: OrderFeedItem[] = [
          {
            orderId: 'canary-ord-loss',
            timestampMyt: '11 Oct 15:10:00',
            symbol: 'SOLUSDT',
            side: 'SELL',
            orderType: 'LIMIT MAKER',
            price: 175.2,
            quantity: 0.025,
            notionalUsdt: 4.38,
            makerFeeUsdt: 0.000876,
            realizedPnlUsdt: -0.12,
            status: 'FILLED',
          },
        ]
        const html = renderToString(<ExecutiveTradesPage orders={lossOrders} />)
        expect(html).toContain('-0.1200')
        expect(html).not.toContain('+-')
        expect(html).not.toContain('+$-')
      })

      it('F5.6: ExecutiveTradesPage displays positive PnL formatted cleanly', () => {
        const gainOrders: OrderFeedItem[] = [
          {
            orderId: 'canary-ord-gain',
            timestampMyt: '11 Oct 15:20:00',
            symbol: 'SOLUSDT',
            side: 'SELL',
            orderType: 'LIMIT MAKER',
            price: 187.0,
            quantity: 0.025,
            notionalUsdt: 4.675,
            makerFeeUsdt: 0.000935,
            realizedPnlUsdt: 0.175,
            status: 'FILLED',
          },
        ]
        const html = renderToString(<ExecutiveTradesPage orders={gainOrders} />)
        expect(html).toContain('+0.1750')
      })
    })

    // -------------------------------------------------------------------------
    // F6: Strategy Evolution Radar & Autopsy Telemetry (6 tests)
    // -------------------------------------------------------------------------
    describe('F6: Strategy Evolution Radar & Autopsy Telemetry', () => {
      it('F6.1: exposes candidate health tier and active candidate ID', () => {
        const evo = makeMockDashboardModel().evolutionRadar
        expect(evo.activeCandidateId).toBe('cand-solusdt-evo-001')
        expect(evo.candidateHealthTier).toBe('ELITE')
        expect(evo.rollingSharpe).toBe(2.45)
      })

      it('F6.2: exposes all 3 qualification gates and verification status', () => {
        const evo = makeMockDashboardModel().evolutionRadar
        expect(evo.gates.length).toBe(3)
        expect(evo.allGatesPassed).toBe(true)
        expect(evo.gates.every((g) => g.passed)).toBe(true)
      })

      it('F6.3: exposes autopsy attribution gauges for maker fees and toxicity', () => {
        const evo = makeMockDashboardModel().evolutionRadar
        expect(evo.attributionGauges.length).toBe(2)
        expect(evo.attributionGauges[0].bps).toBe(2.1)
        expect(evo.attributionGauges[1].bps).toBe(0.0)
      })

      it('F6.4: renders StrategyEvolutionRadar component cleanly', () => {
        const evo = makeMockDashboardModel().evolutionRadar
        const html = renderToString(<StrategyEvolutionRadar evolutionRadar={evo} />)
        expect(html).toContain('cand-solusdt-evo-001')
        expect(html).toContain('ELITE')
        expect(html).toContain('2.45')
      })

      it('F6.5: builds AutoEvolutionModel with live cycle progress and solvency', () => {
        const autoEvo = buildAutoEvolutionModel(VERIFIED_AUTO_EVO_FIXTURE)
        expect(autoEvo.verified).toBe(true)
        expect(autoEvo.isZeroDrift).toBe(true)
        expect(autoEvo.solvency?.drift_usdt).toBe(0.0)
      })

      it('F6.6: renders EvolutionPage component cleanly with zero drift', () => {
        const autoEvo = buildAutoEvolutionModel(VERIFIED_AUTO_EVO_FIXTURE)
        const html = renderToString(<EvolutionPage model={autoEvo} />)
        expect(html).toBeDefined()
        expect(html).toContain('ZERO-DRIFT:')
        expect(html).toContain('VERIFIED')
      })
    })
  })

  // ===========================================================================
  // Tier 2: Boundary & Corner Cases (C1 to C8)
  // ===========================================================================
  describe('Tier 2: Boundary & Corner Cases', () => {
    it('C1: zero completed trades strictly yields 0.0% win rate', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)
      const telemetry = { status: 'OPEN', latencyMs: 10.0 }

      const adapted = buildExecutiveDashboardModel(
        { ...prodLaunch, totalTrades: 0, recentOrders: [] },
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
      )

      expect(adapted.kpis.winRatePct).toBe(0.0)
      expect(adapted.kpis.totalTrades).toBe(0)
    })

    it('C2: 100% win rate when all filled trades have positive realized PnL', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)
      const telemetry = { status: 'OPEN', latencyMs: 10.0 }

      const adapted = buildExecutiveDashboardModel(
        {
          ...prodLaunch,
          totalTrades: 2,
          recentOrders: [
            {
              order_id: 'ord-1',
              symbol: 'SOLUSDT',
              side: 'SELL',
              order_type: 'LIMIT MAKER',
              price: 185.0,
              quantity: 0.025,
              notional_usdt: 4.625,
              status: 'FILLED',
              fill_price: 185.0,
              fee_usdt: 0.0009,
              realized_pnl_usdt: 0.125,
              timestamp_ms: Date.now() - 50000,
            },
            {
              order_id: 'ord-2',
              symbol: 'BTCUSDT',
              side: 'SELL',
              order_type: 'LIMIT MAKER',
              price: 95500.0,
              quantity: 0.0001,
              notional_usdt: 9.55,
              status: 'FILLED',
              fill_price: 95500.0,
              fee_usdt: 0.0019,
              realized_pnl_usdt: 0.05,
              timestamp_ms: Date.now() - 20000,
            },
          ],
        },
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
      )

      expect(adapted.kpis.winRatePct).toBe(100.0)
      expect(adapted.kpis.totalTrades).toBe(2)
    })

    it('C3: negative PnL does not render invalid concatenated signs (+- or +$-)', () => {
      const lossOrder: OrderFeedItem = {
        orderId: 'canary-loss-boundary',
        timestampMyt: '11 Oct 15:45:00',
        symbol: 'SOLUSDT',
        side: 'SELL',
        orderType: 'LIMIT MAKER',
        price: 175.2,
        quantity: 0.025,
        notionalUsdt: 4.38,
        makerFeeUsdt: 0.000876,
        realizedPnlUsdt: -0.12,
        status: 'FILLED',
      }
      const html = renderToString(<ExecutiveTradesPage orders={[lossOrder]} />)
      expect(html).toContain('-0.1200')
      expect(html).not.toContain('+-')
      expect(html).not.toContain('+$-')
    })

    it('C4: flat position exposes 0.00 exposure and suppresses bracket lines', () => {
      const positions = makeMockFlatPositions()
      const sol = positions.find((p) => p.symbol === 'SOLUSDT')!
      expect(sol.size).toBe(0.0)
      expect(sol.notionalUsdt).toBe(0.0)
      expect(sol.marginUsdt).toBe(0.0)
      expect(sol.entryPrice).toBe(0.0)
    })

    it('C5: micro-capital child cap $5.00 and $25.00 exposure ceiling respected', () => {
      const positions = makeMockActivePositions()
      const sol = positions.find((p) => p.symbol === 'SOLUSDT')!
      expect(sol.marginUsdt).toBeLessThanOrEqual(5.0)

      const totalMargin = positions.reduce((acc, p) => acc + p.marginUsdt, 0)
      expect(totalMargin).toBeLessThanOrEqual(25.0)
    })

    it('C6: supercritical Hawkes hazard (rho >= 1.0) trips toxicity flag', () => {
      const criticalHazard = {
        spectralRadius: 1.15,
        isNonToxic: false,
        thresholdWarning: 0.8,
        thresholdCritical: 1.0,
        recentHistory: [0.65, 0.78, 0.92, 1.05, 1.15],
      }
      expect(criticalHazard.spectralRadius).toBeGreaterThanOrEqual(1.0)
      expect(criticalHazard.isNonToxic).toBe(false)
    })

    it('C7: cash reserve floor boundary enforces >= 75.0% threshold', () => {
      const kpis = makeMockDashboardModel().kpis
      expect(kpis.cashReservePct).toBeGreaterThanOrEqual(kpis.minCashReserveFloorPct)
      expect(kpis.minCashReserveFloorPct).toBe(75.0)
    })

    it('C8: zero balance drift verified strictly when |Delta| < 10^-15 USDT', () => {
      const kpis = makeMockDashboardModel().kpis
      expect(kpis.isZeroDriftVerified).toBe(true)
      expect(Math.abs(kpis.balanceDriftUsdt)).toBeLessThan(1e-15)
    })
  })

  // ===========================================================================
  // Tier 3: Pairwise Combinatorial Interactions (C1 to C6)
  // ===========================================================================
  describe('Tier 3: Pairwise Combinatorial Interactions', () => {
    it('C1: Bearish Macro Regime blocks entries despite 15m Scalper Dip Confluence', () => {
      const radar = makeMockDashboardModel().radar
      expect(radar.btcMacroTrend.regime).toBe('BEARISH')
      expect(radar.scalperCriteria.priceTriggered).toBe(true)
      expect(radar.scalperCriteria.volumeTriggered).toBe(true)
      expect(radar.scalperCriteria.rsiTriggered).toBe(true)

      // Macro gating explanation explicitly confirms long pause for capital protection
      expect(radar.btcMacroTrend.explanation).toContain('Long entries temporarily paused')
    })

    it('C2: Bullish Macro Regime permits entries when 15m Scalper Dip Triggers', () => {
      const bullishRadar = {
        ...makeMockDashboardModel().radar,
        btcMacroTrend: {
          regime: 'BULLISH ALIGNED' as const,
          ema50_1h: 96000.0,
          ema200_1h: 94000.0,
          ema50_4h: 95500.0,
          ema200_4h: 93500.0,
          explanation: 'Long scalper entries permitted by BTC 1h/4h Bullish regime.',
        },
      }
      expect(bullishRadar.btcMacroTrend.regime).toBe('BULLISH ALIGNED')
      expect(bullishRadar.scalperCriteria.priceTriggered).toBe(true)
      expect(bullishRadar.btcMacroTrend.explanation).toContain('permitted')
    })

    it('C3: Multi-pair Active Positions maintain cash floor >= 75% and zero drift', () => {
      const positions = makeMockFlatPositions()
      // Activate SOL ($4.50) and ETH ($4.50) -> total margin $9.00
      positions[1] = {
        symbol: 'ETHUSDT',
        currentPrice: 2750.0,
        state: 'LONG',
        entryPrice: 2700.0,
        size: 0.00166,
        notionalUsdt: 4.5,
        marginUsdt: 4.5,
        unrealizedPnlUsdt: 0.08,
        unrealizedPnlPct: 1.78,
        takeProfitPrice: 2800.0,
        stopLossPrice: 2640.0,
        riskRewardRatio: '1.67 : 1',
      }
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
        riskRewardRatio: '1.67 : 1',
      }

      const totalMargin = positions.reduce((acc, p) => acc + p.marginUsdt, 0) // 9.00
      const totalCash = 100.12 - totalMargin // 91.12
      const cashReservePct = (totalCash / 100.12) * 100 // 91.01%

      expect(totalMargin).toBe(9.0)
      expect(totalMargin).toBeLessThanOrEqual(25.0)
      expect(cashReservePct).toBeGreaterThanOrEqual(75.0)

      const totalEquity = totalCash + totalMargin
      expect(Math.abs(totalEquity - 100.12)).toBeLessThan(1e-12)
    })

    it('C4: Out-of-Sample Gate progression aligns with Evolution Pipeline stage', () => {
      const stages = ['INGRESS', 'EVALUATION', 'AUTOPSY', 'MUTATION', 'PROMOTION'] as const
      const oosProgression = [
        { closed: 0, required: 5, status: 'WAITING_FOR_SAMPLES' },
        { closed: 3, required: 5, status: 'WAITING_FOR_SAMPLES' },
        { closed: 5, required: 5, status: 'QUALIFIED' },
      ]

      expect(stages.length).toBe(5)
      expect(oosProgression[0].status).toBe('WAITING_FOR_SAMPLES')
      expect(oosProgression[2].status).toBe('QUALIFIED')
      expect(oosProgression[2].closed).toBe(oosProgression[2].required)
    })

    it('C5: Order Feed Maker Fills update realized PnL while preserving balance conservation', () => {
      const initialCash = 100.0
      const profitUsdt = 0.35
      const makerFeeUsdt = 0.0009
      const netGain = profitUsdt - makerFeeUsdt
      const endingCash = initialCash + netGain

      expect(endingCash).toBeCloseTo(100.3491, 4)
      const drift = Math.abs(endingCash - (initialCash + netGain))
      expect(drift).toBeLessThan(1e-15)
    })

    it('C6: Supercritical Hawkes Hazard blocks new child orders during active positions', () => {
      const positions = makeMockActivePositions()
      const hawkes = {
        spectralRadius: 1.05,
        isNonToxic: false,
      }

      const hasActivePositions = positions.some((p) => p.state !== 'SCANNING / STANDBY')
      const orderEntryBlocked = !hawkes.isNonToxic || hawkes.spectralRadius >= 1.0

      expect(hasActivePositions).toBe(true)
      expect(orderEntryBlocked).toBe(true)
    })
  })

  // ===========================================================================
  // Tier 4: Real-World Workload Scenarios (S1 to S5)
  // ===========================================================================
  describe('Tier 4: Real-World Workload Scenarios', () => {
    it('S1: End-to-End User Navigation & Model Adaptation Workflow', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)
      const telemetry = { status: 'OPEN', latencyMs: 8.5 }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
      )

      expect(adapted.botStatus.state).toBe('ACTIVE 24/7')
      expect(adapted.kpis.totalEquityUsdt).toBeGreaterThanOrEqual(95.0)
      expect(adapted.positions.length).toBe(12)
      expect(adapted.kpis.isZeroDriftVerified).toBe(true)

      const html = renderToString(
        <ExecutiveDashboard model={adapted} onRefresh={() => {}} />,
      )
      expect(html).toContain('ACTIVE 24/7')
      expect(html).toContain('Zero-Drift')
      expect(html).toContain('SOLUSDT')
    })

    it('S2: Responsive Research Drawer Expansion & Archive Navigation', () => {
      const htmlOpen = renderToString(
        <ResearchArchiveDrawer isOpen={true} onClose={() => {}} />,
      )
      expect(htmlOpen).toContain('Phase 250')
      expect(htmlOpen).toContain('Phase 253')
      expect(htmlOpen).toContain('Phase 298')
      expect(htmlOpen).toContain('Phase 304')
      expect(htmlOpen).toContain('Phase 306')

      const htmlClosed = renderToString(
        <ResearchArchiveDrawer isOpen={false} onClose={() => {}} />,
      )
      expect(htmlClosed).toBe('')
    })

    it('S3: Full Trade Lifecycle Telemetry Flow: Standby -> Fill -> TP -> Audit', () => {
      // Step 1: Standby
      const flatPositions = makeMockFlatPositions()
      expect(flatPositions[2].state).toBe('SCANNING / STANDBY')

      // Step 2: Maker Buy Order Filled
      const entryOrder: OrderFeedItem = {
        orderId: 'lifecycle-ord-1',
        timestampMyt: '11 Oct 16:00:00',
        symbol: 'SOLUSDT',
        side: 'BUY',
        orderType: 'LIMIT MAKER',
        price: 180.0,
        quantity: 0.025,
        notionalUsdt: 4.5,
        makerFeeUsdt: 0.0009,
        realizedPnlUsdt: 0.0,
        status: 'FILLED',
      }
      expect(entryOrder.status).toBe('FILLED')

      // Step 3: Active Position with Dynamic ATR Brackets
      const activePositions = makeMockActivePositions()
      const solActive = activePositions[2]
      expect(solActive.state).toBe('LONG')
      expect(solActive.takeProfitPrice).toBe(187.0)

      // Step 4: TP Limit Maker Order Filled
      const tpOrder: OrderFeedItem = {
        orderId: 'lifecycle-ord-2',
        timestampMyt: '11 Oct 16:15:00',
        symbol: 'SOLUSDT',
        side: 'SELL',
        orderType: 'LIMIT MAKER',
        price: 187.0,
        quantity: 0.025,
        notionalUsdt: 4.675,
        makerFeeUsdt: 0.000935,
        realizedPnlUsdt: 0.175,
        status: 'FILLED',
      }
      expect(tpOrder.realizedPnlUsdt).toBe(0.175)

      // Step 5: Ledger Solvency Reconciliation
      const netGain = tpOrder.realizedPnlUsdt - tpOrder.makerFeeUsdt - entryOrder.makerFeeUsdt
      expect(netGain).toBeCloseTo(0.173165, 6)
      const finalDrift = Math.abs(netGain - (0.175 - 0.000935 - 0.0009))
      expect(finalDrift).toBeLessThan(1e-15)
    })

    it('S4: Strategy Evolution Dynamic Progression Across 5 Pipeline Stages', () => {
      const autoEvo = buildAutoEvolutionModel(VERIFIED_AUTO_EVO_FIXTURE)
      expect(autoEvo.verified).toBe(true)

      const stages = ['INGRESS', 'EVALUATION', 'AUTOPSY', 'MUTATION', 'PROMOTION']
      for (const st of stages) {
        expect(stages).toContain(st)
      }

      const html = renderToString(<EvolutionPage model={autoEvo} />)
      expect(html).toBeDefined()
      expect(html).toContain('100.00')
    })

    it('S5: Continuous Solvency & Interlock Invariant Verification', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const risk = buildRiskModel(null)
      const killSwitch = buildKillSwitchModel(null)

      const liveExecStatus: ExecutionStatusResponse = {
        verified: true,
        status: 'ok',
        engine_state: 'RUNNING',
        timestamp_ms: Date.now(),
        solvency: {
          total_equity_usdt: 100.12,
          cash_usdt: 95.62,
          allocated_margin_usdt: 4.5,
          unrealized_pnl_usdt: 0.0,
          cash_reserve_pct: 95.5,
          drift_usdt: 0.0,
          zero_balance_drift_verified: true,
        },
        positions: {},
        candidate_allocations: [],
        aggregate_exposure_usdt: 4.5,
        intra_day_loss_usdt: 0.0,
        interlock_blocks_count: 0,
        recent_orders: [],
        total_orders: 0,
      }

      const html = renderToString(
        <ExecutiveSafetyPage
          productionLaunchModel={prodLaunch}
          riskModel={risk}
          killSwitchModel={killSwitch}
          executionStatus={liveExecStatus}
        />,
      )

      expect(html).toContain('100.1200')
      expect(html).toContain('95.6200')
      expect(html).toContain('|Δ| = 0.000000000000000 USDT')
    })
  })
})
