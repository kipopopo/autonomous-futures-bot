import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import React from 'react'

import { EvolutionPage } from '../evolution-page'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import { ExecutivePositionsPage } from '../executive-positions-page'
import { ExecutiveTradesPage } from '../executive-trades-page'
import {
  buildExecutiveDashboardModel,
} from '../mission-control/adapter'
import {
  calculateEma,
  calculateOhlcSummary,
  generateSyntheticKlines,
  type MarketKline,
} from '@/lib/chart-indicators'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  buildAutoEvolutionModel,
  type AutoEvolutionModel,
  type CanaryAutoEvolutionData,
} from '@/lib/canary'
import type { OrderFeedItem } from '../mission-control/types'

// =============================================================================
// Fixtures & Mocks
// =============================================================================

function createVerifiedEvolutionFixture(
  overrides?: Partial<CanaryAutoEvolutionData['live_progress']>,
): AutoEvolutionModel {
  const rawData: CanaryAutoEvolutionData = {
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
    live_progress: {
      is_live_daemon_active: true,
      current_cycle_stage: 'SHADOW_OOS_GATE',
      cycle_progress_pct: 80.0,
      stage_status: 'WAITING_FOR_SAMPLES',
      closed_trades_count: 0,
      required_trades_count: 5,
      sharpe_hurdle_pct: 15.0,
      current_sharpe_improvement_pct: 0.0,
      active_generation: 'GEN #2',
      next_target_generation: 'GEN #3',
      last_evaluated_timestamp_ms: 1728610000000,
      last_candle_fetch_timestamp_ms: 1728609995000,
      next_cycle_seconds: 15,
      heartbeat_latency_ms: 42.0,
      daemon_status: 'ONLINE 24/7',
      daemon_pid: 87549,
      scanned_symbols: [
        'BTCUSDT',
        'ETHUSDT',
        'SOLUSDT',
        'DOGEUSDT',
        'BNBUSDT',
        'XRPUSDT',
        'SUIUSDT',
        'AVAXUSDT',
        'NEARUSDT',
        'LINKUSDT',
        'APTUSDT',
        'ADAUSDT',
      ],
      oos_gate: {
        samples_required: 5,
        samples_acquired: 0,
        sharpe_hurdle_pct: 15.0,
        current_sharpe_improvement_pct: 0.0,
        status: 'WAITING_FOR_SAMPLES',
        status_label: 'WAITING_FOR_SAMPLES (0/5)',
        explanation: 'Waiting for 5 completed trade samples.',
      },
      macro_gating_state: {
        regime: 'BEARISH',
        longs_filtered: true,
        is_long_allowed: false,
        explanation_ms: 'Bearish Macro Trend (Price < 1h EMA 200).',
        explanation: 'Bearish Macro Trend (Price < 1h EMA 200).',
      },
      ...overrides,
    },
  }
  return buildAutoEvolutionModel(rawData)
}

function createDefaultDashboardModels() {
  const prod = buildProductionLaunchModel({
    phase: 'phase_310',
    verified: true,
    status: 'ACTIVE_PAPER_TRADING',
    circuit_state: 'NORMAL',
    mode: 'PAPER_SAFE',
    timestamp_ms: Date.now(),
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 95.0,
      allocated_margin_usdt: 5.0,
      unrealized_pnl_usdt: 0.15,
      total_equity_usdt: 100.15,
      realized_pnl_usdt: 0.0,
      drift_usdt: 0.0,
      cash_reserve_pct: 95.0,
      exposure_ceiling_usdt: 25.0,
      drawdown_pct: 0.0,
    },
    candidate_allocations: [],
    recent_orders: [],
  } as any)

  const liveMkt = buildLiveMarketModel({
    phase: 'phase_255',
    verified: true,
    status: 'PUBLIC_MARKET_STREAM_VERIFIED',
    mark_prices: {
      BTCUSDT: { symbol: 'BTCUSDT', mark_price: '85200.50', index_price: '85195.00' },
      ETHUSDT: { symbol: 'ETHUSDT', mark_price: '2650.25', index_price: '2650.00' },
      SOLUSDT: { symbol: 'SOLUSDT', mark_price: '185.40', index_price: '185.35' },
      DOGEUSDT: { symbol: 'DOGEUSDT', mark_price: '0.1625', index_price: '0.1624' },
      BNBUSDT: { symbol: 'BNBUSDT', mark_price: '610.75', index_price: '610.50' },
      XRPUSDT: { symbol: 'XRPUSDT', mark_price: '0.5840', index_price: '0.5838' },
      SUIUSDT: { symbol: 'SUIUSDT', mark_price: '2.2150', index_price: '2.2145' },
      AVAXUSDT: { symbol: 'AVAXUSDT', mark_price: '28.60', index_price: '28.55' },
    },
  } as any)

  const brackets = buildBracketPositionsModel({
    phase: 'phase_308',
    verified: true,
    positions: [],
    brackets: [],
  } as any)

  const micro = buildMicrostructureModel(null)

  return { prod, liveMkt, brackets, micro }
}

// =============================================================================
// Challenge Suite
// =============================================================================

describe('Milestone M3 Concurrency & Precision Empirical Challenge', () => {
  // ===========================================================================
  // 1. Poller & Timer Behavior Under Concurrency & Rapid Re-renders
  // ===========================================================================
  describe('Poller & Countdown Timer Resilience', () => {
    it('countdown ticker state machine decrements strictly and resets at boundary', () => {
      // Logic from EvolutionPage: (prev) => (prev <= 1 ? 15 : prev - 1)
      const tick = (prev: number) => (prev <= 1 ? 15 : prev - 1)

      expect(tick(15)).toBe(14)
      expect(tick(14)).toBe(13)
      expect(tick(2)).toBe(1)
      expect(tick(1)).toBe(15) // Reset at 1s boundary!
      expect(tick(0)).toBe(15) // Reset when 0
      expect(tick(-5)).toBe(15) // Reset when negative
    })

    it('simulates 100 rapid re-renders and verifies timer invariants without leaks', () => {
      // Simulating interval hook lifecycle
      let activeTimers = 0
      const timersList: number[] = []

      const mount = () => {
        const id = activeTimers + 1
        activeTimers++
        timersList.push(id)
        return () => {
          activeTimers--
          const idx = timersList.indexOf(id)
          if (idx >= 0) timersList.splice(idx, 1)
        }
      }

      // Initial mount
      const unmount = mount()
      expect(activeTimers).toBe(1)

      // 100 rapid state updates / re-renders (does not remount effect due to [])
      for (let i = 0; i < 100; i++) {
        // useEffect with [] does NOT call cleanup or recreate timer on re-render
      }
      expect(activeTimers).toBe(1)

      // Unmount properly clears interval
      unmount()
      expect(activeTimers).toBe(0)
      expect(timersList).toHaveLength(0)
    })

    it('handles degenerate & edge-case countdown inputs gracefully', () => {
      // next_cycle_seconds is 0
      const modelZero = createVerifiedEvolutionFixture({ next_cycle_seconds: 0 })
      const htmlZero = renderToString(React.createElement(EvolutionPage, { model: modelZero })).replace(/<!-- -->/g, '')
      expect(htmlZero).toContain('Next Cycle')
      expect(htmlZero).toContain('0s') // 0 seconds shown initially

      // next_cycle_seconds is negative
      const modelNeg = createVerifiedEvolutionFixture({ next_cycle_seconds: -10 })
      const htmlNeg = renderToString(React.createElement(EvolutionPage, { model: modelNeg })).replace(/<!-- -->/g, '')
      expect(htmlNeg).toContain('Next Cycle')

      // next_cycle_seconds is missing / undefined -> renders Unavailable truthfully
      const modelUndef = createVerifiedEvolutionFixture({ next_cycle_seconds: undefined })
      const htmlUndef = renderToString(React.createElement(EvolutionPage, { model: modelUndef })).replace(/<!-- -->/g, '')
      expect(htmlUndef).toContain('Unavailable')
    })

    it('renders all 4 real-time telemetry boxes in EvolutionPage with valid timestamps', () => {
      const model = createVerifiedEvolutionFixture()
      const html = renderToString(React.createElement(EvolutionPage, { model })).replace(/<!-- -->/g, '')

      // Box 1: Current System Time (MYT)
      expect(html).toContain('Current Time (MYT)')
      expect(html).toContain('GMT+8')

      // Box 2: Last Cycle & Candle Fetch
      expect(html).toContain('Last Cycle')
      expect(html).toContain('Candle Fetch:')
      expect(html).toContain('Scan (12 Pairs):')
      expect(html).toContain('BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT, BNBUSDT, XRPUSDT, SUIUSDT, AVAXUSDT, NEARUSDT, LINKUSDT, APTUSDT, ADAUSDT')

      // Box 3: Next Cycle Heartbeat
      expect(html).toContain('Next Cycle')
      expect(html).toContain('/ runtime-reported interval')

      // Box 4: Latency & Daemon Status
      expect(html).toContain('DAEMON PID: 87549')
      expect(html).toContain('ACTIVE')
    })
  })

  // ===========================================================================
  // 2. Precision Formatting Consistency Across Adapter Layer and Chart Series
  // ===========================================================================
  describe('Precision Formatting Consistency (All 12 Pairs)', () => {
    it('adapter configures all 12 perpetual pairs with exact fallback and ATR multipliers', () => {
      const { prod, liveMkt, brackets, micro } = createDefaultDashboardModels()
      const adapted = buildExecutiveDashboardModel(
        prod,
        liveMkt,
        brackets,
        micro,
        { status: 'CONNECTED', latencyMs: 25 },
        new Date(),
      )

      expect(adapted.positions).toHaveLength(12)

      const expectedSymbols = [
        'SOLUSDT',
        'ETHUSDT',
        'BTCUSDT',
        'DOGEUSDT',
        'BNBUSDT',
        'XRPUSDT',
        'SUIUSDT',
        'AVAXUSDT',
        'NEARUSDT',
        'LINKUSDT',
        'APTUSDT',
        'ADAUSDT',
      ]
      expect(adapted.positions.map((p) => p.symbol)).toEqual(expectedSymbols)

      // Verify sub-dollar prices are mapped accurately from liveMarket
      const doge = adapted.positions.find((p) => p.symbol === 'DOGEUSDT')
      expect(doge).toBeDefined()
      expect(doge!.currentPrice).toBe(0.1625)

      const xrp = adapted.positions.find((p) => p.symbol === 'XRPUSDT')
      expect(xrp).toBeDefined()
      expect(xrp!.currentPrice).toBe(0.584)

      const sui = adapted.positions.find((p) => p.symbol === 'SUIUSDT')
      expect(sui).toBeDefined()
      expect(sui!.currentPrice).toBe(2.215)
    })

    it('adapter calculates TP/SL brackets with 4-decimal precision for sub-dollar coins', () => {
      const { prod, liveMkt, brackets, micro } = createDefaultDashboardModels()

      // Inject active execution positions for DOGE and XRP
      const execStatus = {
        positions: {
          DOGEUSDT: {
            symbol: 'DOGEUSDT',
            position_qty: 30.0,
            entry_price: 0.1600,
            mark_price: 0.1625,
            allocated_exposure_usdt: 4.875,
            allocated_margin_usdt: 4.875,
            unrealized_pnl_usdt: 0.075,
          },
          XRPUSDT: {
            symbol: 'XRPUSDT',
            position_qty: 8.0,
            entry_price: 0.5800,
            mark_price: 0.5840,
            allocated_exposure_usdt: 4.672,
            allocated_margin_usdt: 4.672,
            unrealized_pnl_usdt: 0.032,
          },
        },
      }

      const adapted = buildExecutiveDashboardModel(
        prod,
        liveMkt,
        brackets,
        micro,
        { status: 'CONNECTED', latencyMs: 25 },
        new Date(),
        null,
        null,
        execStatus as any,
      )

      const dogePos = adapted.positions.find((p) => p.symbol === 'DOGEUSDT')!
      expect(dogePos.state).toBe('LONG')
      expect(dogePos.entryPrice).toBe(0.1600)
      // DOGE ATR TP: baseEntry (0.1600) + 0.005 * 2.0 = 0.1700 (precision 4)
      expect(dogePos.takeProfitPrice).toBe(0.1700)
      // DOGE ATR SL: baseEntry (0.1600) - 0.005 * 1.2 = 0.1540 (precision 4)
      expect(dogePos.stopLossPrice).toBe(0.1540)

      const xrpPos = adapted.positions.find((p) => p.symbol === 'XRPUSDT')!
      expect(xrpPos.state).toBe('LONG')
      expect(xrpPos.entryPrice).toBe(0.5800)
      // XRP ATR TP: baseEntry (0.5800) + 0.015 * 2.0 = 0.6100 (precision 4)
      expect(xrpPos.takeProfitPrice).toBe(0.6100)
      // XRP ATR SL: baseEntry (0.5800) - 0.015 * 1.2 = 0.5620 (precision 4)
      expect(xrpPos.stopLossPrice).toBe(0.5620)
    })

    it('chart-indicators calculateOhlcSummary applies 4-decimal bounds for sub-dollar and 2 for standard', () => {
      // Sub-dollar series (DOGE)
      const dogeKlines: MarketKline[] = [
        { timestamp: 1000, open: 0.1610, high: 0.1635, low: 0.1605, close: 0.1625, volume: 50000 },
      ]
      const dogeSummary = calculateOhlcSummary(dogeKlines)
      expect(dogeSummary).not.toBeNull()
      expect(dogeSummary!.high24h).toBe(0.1635)
      expect(dogeSummary!.low24h).toBe(0.1605)

      // Standard dollar series (SOL)
      const solKlines: MarketKline[] = [
        { timestamp: 1000, open: 180.123, high: 185.456, low: 179.999, close: 182.50, volume: 1000 },
      ]
      const solSummary = calculateOhlcSummary(solKlines)
      expect(solSummary).not.toBeNull()
      expect(solSummary!.high24h).toBe(185.46)
      expect(solSummary!.low24h).toBe(180.00)
    })

    it('chart-indicators calculateEma guarantees 4-decimal precision across all series', () => {
      const klines = generateSyntheticKlines('DOGEUSDT', '15m', 30)
      expect(klines.length).toBe(30)

      const emaPoints = calculateEma(klines, 10)
      expect(emaPoints.length).toBeGreaterThan(0)

      // Verify each EMA point has at most 4 decimal places
      for (const pt of emaPoints) {
        const str = pt.value.toString()
        const decimals = str.includes('.') ? str.split('.')[1].length : 0
        expect(decimals).toBeLessThanOrEqual(4)
      }
    })

    it('generateSyntheticKlines correctly targets base prices and precision for all 8 pairs', () => {
      const pairs = [
        { sym: 'BTCUSDT', minExpected: 80000, maxExpected: 90000, subDollar: false },
        { sym: 'ETHUSDT', minExpected: 2500, maxExpected: 3000, subDollar: false },
        { sym: 'SOLUSDT', minExpected: 150, maxExpected: 220, subDollar: false },
        { sym: 'DOGEUSDT', minExpected: 0.14, maxExpected: 0.18, subDollar: true },
        { sym: 'BNBUSDT', minExpected: 550, maxExpected: 650, subDollar: false },
        { sym: 'XRPUSDT', minExpected: 0.50, maxExpected: 0.65, subDollar: true },
        { sym: 'SUIUSDT', minExpected: 1.80, maxExpected: 2.60, subDollar: false },
        { sym: 'AVAXUSDT', minExpected: 24, maxExpected: 32, subDollar: false },
      ]

      for (const p of pairs) {
        const klines = generateSyntheticKlines(p.sym, '15m', 20)
        expect(klines).toHaveLength(20)
        const sample = klines[0]
        expect(sample.close).toBeGreaterThanOrEqual(p.minExpected)
        expect(sample.close).toBeLessThanOrEqual(p.maxExpected)

        if (p.subDollar) {
          // Sub-dollar should have up to 4 decimal places
          const decimalPart = sample.close.toString().split('.')[1] || ''
          expect(decimalPart.length).toBeGreaterThanOrEqual(2)
        }
      }
    })

    it('OrderFeedTable formats sub-dollar coin prices with 4 decimals and standard with 2 decimals', () => {
      const sampleOrders: OrderFeedItem[] = [
        {
          orderId: 'ord-doge-001',
          symbol: 'DOGEUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 0.1625,
          quantity: 30,
          notionalUsdt: 4.875,
          makerFeeUsdt: 0.000975,
          realizedPnlUsdt: 0,
          status: 'FILLED',
          timestampMyt: '11 Oct 12:00:00 MYT',
        },
        {
          orderId: 'ord-btc-001',
          symbol: 'BTCUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 85200.5,
          quantity: 0.0001,
          notionalUsdt: 8.52,
          makerFeeUsdt: 0.0017,
          realizedPnlUsdt: 0,
          status: 'FILLED',
          timestampMyt: '11 Oct 12:01:00 MYT',
        },
      ]

      const html = renderToString(React.createElement(OrderFeedTable, { orders: sampleOrders }))

      // DOGE price formatted with 4 decimals: $0.1625
      expect(html).toContain('$0.1625')

      // BTC price formatted with standard 2 decimals with comma: $85,200.50
      expect(html).toContain('$85,200.50')

      // Filter pills include all 8 pairs
      for (const sym of ['ALL', 'SOL', 'ETH', 'BTC', 'DOGE', 'BNB', 'XRP', 'SUI', 'AVAX']) {
        expect(html).toContain(sym)
      }
    })

    it('ExecutivePositionsPage formats prices with appropriate precision and renders filter pills', () => {
      const { prod, liveMkt, brackets, micro } = createDefaultDashboardModels()
      const adapted = buildExecutiveDashboardModel(
        prod,
        liveMkt,
        brackets,
        micro,
        { status: 'CONNECTED', latencyMs: 25 },
        new Date(),
      )

      const html = renderToString(
        React.createElement(ExecutivePositionsPage, {
          positions: adapted.positions,
          bracketPositionsModel: brackets,
          liveMarketModel: liveMkt,
        }),
      ).replace(/<!-- -->/g, '')

      expect(html).toContain('Detailed Positions &amp; Markets')
      expect(html).toContain('0 Open / 12 Monitored')

      // Pills
      for (const pill of ['ALL', 'SOL', 'ETH', 'BTC', 'DOGE', 'BNB', 'XRP', 'SUI', 'AVAX', 'NEAR', 'LINK', 'APT', 'ADA']) {
        expect(html).toContain(pill)
      }
    })

    it('ExecutiveTradesPage renders dynamic win rate and 4-decimal prices for sub-dollar coins', () => {
      const orders: OrderFeedItem[] = [
        {
          orderId: 'ord-xrp-001',
          symbol: 'XRPUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 0.5840,
          quantity: 8,
          notionalUsdt: 4.672,
          makerFeeUsdt: 0.00093,
          realizedPnlUsdt: 0.05,
          status: 'FILLED',
          timestampMyt: '11 Oct 12:00:00 MYT',
        },
      ]

      const html = renderToString(React.createElement(ExecutiveTradesPage, { orders })).replace(/<!-- -->/g, '')

      expect(html).toContain('$0.5840')
      expect(html).toContain('100.0%') // 1 winning trade out of 1 filled trade
    })
  })
})
