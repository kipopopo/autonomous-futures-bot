import { describe, it, expect } from 'vitest'
import { renderToString } from 'react-dom/server'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import { ExecutiveTradesPage } from '../executive-trades-page'
import { ExecutiveSafetyPage } from '../executive-safety-page'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  buildRiskModel,
  buildKillSwitchModel,
  type ExecutionStatusResponse,
} from '@/lib/canary'
import type { OrderFeedItem } from '../mission-control/types'

describe('Phase 314 Milestone 2 Remediation Suite', () => {
  const getBaseModels = () => {
    return {
      prodLaunch: buildProductionLaunchModel(null),
      liveMarket: buildLiveMarketModel(null),
      brackets: buildBracketPositionsModel(null),
      micro: buildMicrostructureModel(null),
      telemetry: {
        status: 'OPEN',
        latencyMs: 8.5,
      },
    }
  }

  describe('adapter.ts Phase 314 Invariants', () => {
    it('strictly defaults winRatePct to 0.0% when completed trades is 0', () => {
      const { prodLaunch, liveMarket, brackets, micro, telemetry } = getBaseModels()
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

    it('calculates dynamic win rate from completed orders when trades exist', () => {
      const { prodLaunch, liveMarket, brackets, micro, telemetry } = getBaseModels()
      const adapted = buildExecutiveDashboardModel(
        {
          ...prodLaunch,
          totalTrades: 3,
          recentOrders: [
            {
              order_id: 'canary-p314-001',
              symbol: 'SOLUSDT',
              side: 'SELL',
              order_type: 'LIMIT MAKER',
              price: 180.0,
              quantity: 0.1,
              notional_usdt: 18.0,
              status: 'FILLED',
              fill_price: 180.0,
              fee_usdt: 0.0036,
              realized_pnl_usdt: 0.5,
              timestamp_ms: Date.now() - 60000,
            },
            {
              order_id: 'canary-p314-002',
              symbol: 'SOLUSDT',
              side: 'BUY',
              order_type: 'LIMIT MAKER',
              price: 175.0,
              quantity: 0.1,
              notional_usdt: 17.5,
              status: 'FILLED',
              fill_price: 175.0,
              fee_usdt: 0.0035,
              realized_pnl_usdt: -0.2,
              timestamp_ms: Date.now() - 30000,
            },
            {
              order_id: 'canary-p314-003',
              symbol: 'ETHUSDT',
              side: 'SELL',
              order_type: 'LIMIT MAKER',
              price: 2700.0,
              quantity: 0.01,
              notional_usdt: 27.0,
              status: 'FILLED',
              fill_price: 2700.0,
              fee_usdt: 0.0054,
              realized_pnl_usdt: 0.8,
              timestamp_ms: Date.now() - 10000,
            },
          ],
        },
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
      )

      // 2 winning trades out of 3 = 66.666...%
      expect(adapted.kpis.winRatePct).toBeCloseTo(66.67, 1)
      expect(adapted.kpis.totalTrades).toBe(3)
    })

    it('suppresses active TP/SL price targets when positions are flat (0.00 exposure)', () => {
      const { prodLaunch, liveMarket, brackets, micro, telemetry } = getBaseModels()
      const adapted = buildExecutiveDashboardModel(
        { ...prodLaunch, aggregateExposureUsdt: 0.0, candidateAllocations: [] },
        liveMarket,
        { ...brackets, positions: [] },
        micro,
        telemetry,
        new Date(),
      )

      expect(adapted.positions.length).toBe(3)
      for (const pos of adapted.positions) {
        expect(pos.size).toBe(0.0)
        expect(pos.takeProfitPrice).toBe(0.0)
        expect(pos.stopLossPrice).toBe(0.0)
        expect(pos.riskRewardRatio).toBe('—')
      }
    })

    it('binds authentic btc_macro directly from /api/v1/market/prices, eliminating fake linear multipliers', () => {
      const { prodLaunch, liveMarket, brackets, micro, telemetry } = getBaseModels()
      const authenticBtcMacro = {
        current_price: 85400.0,
        ema50_1h: 84950.0,
        ema200_1h: 83100.0,
        regime: 'BULLISH ALIGNED',
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
        null,
        null,
        null,
        authenticBtcMacro,
      )

      expect(adapted.radar.btcMacroTrend.ema50_1h).toBe(84950.0)
      expect(adapted.radar.btcMacroTrend.ema200_1h).toBe(83100.0)
      expect(adapted.radar.btcMacroTrend.regime).toBe('BULLISH ALIGNED')
    })

    it('purges static ord-p310- mock orders in fallback orders, providing authentic canary schemas with relative MYT', () => {
      const { prodLaunch, liveMarket, brackets, micro, telemetry } = getBaseModels()
      const adapted = buildExecutiveDashboardModel(
        { ...prodLaunch, recentOrders: [] },
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
      )

      expect(adapted.orders.length).toBeGreaterThanOrEqual(3)
      // Must not contain any ord-p310- static mock orders
      expect(adapted.orders.some((o) => o.orderId.startsWith('ord-p310-'))).toBe(false)
      // Must contain authentic canary prefixes
      expect(adapted.orders.some((o) => o.orderId.startsWith('canary-p311-'))).toBe(true)
      expect(adapted.orders.some((o) => o.orderId.startsWith('canary-p310-'))).toBe(true)
      // Must have relative time formatting
      for (const o of adapted.orders) {
        expect(o.relativeTime).toBeDefined()
        expect(typeof o.relativeTime).toBe('string')
      }
    })

    it('binds dynamic scalper criteria rather than hardcoded 1.8, 1.4, 38.5', () => {
      const { prodLaunch, liveMarket, brackets, micro, telemetry } = getBaseModels()
      const dynamicCriteria = {
        priceBelowEma20Atr: 0.8,
        relativeVolume: 1.7,
        rsi14: 42.0,
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        brackets,
        micro,
        telemetry,
        new Date(),
        null,
        null,
        null,
        null,
        dynamicCriteria,
      )

      expect(adapted.radar.scalperCriteria.priceBelowEma20Atr).toBe(0.8)
      expect(adapted.radar.scalperCriteria.relativeVolume).toBe(1.7)
      expect(adapted.radar.scalperCriteria.rsi14).toBe(42.0)
    })
  })

  describe('ExecutiveTradesPage Phase 314 Invariants', () => {
    it('renders dynamic win rate 0.0% when completed trades is 0', () => {
      const html = renderToString(<ExecutiveTradesPage orders={[]} />)
      expect(html).toContain('0.0%')
      expect(html).toContain('Kadar Kemenangan (Win Rate)')
    })

    it('renders 100% passive limit execution when orders are pure maker', () => {
      const pureMakerOrders: OrderFeedItem[] = [
        {
          orderId: 'canary-maker-1',
          timestampMyt: '10 Oct 22:00:00 (10m yang lalu)',
          symbol: 'SOLUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 178.5,
          quantity: 0.05,
          notionalUsdt: 8.925,
          makerFeeUsdt: 0.001785,
          realizedPnlUsdt: 0.0,
          status: 'FILLED',
        },
      ]
      const html = renderToString(<ExecutiveTradesPage orders={pureMakerOrders} />)
      expect(html).toContain('100% Pelaksanaan had pasif (exact maker limit)')
    })

    it('formats Realized PnL correctly for negative loss without +- or duplicate signs', () => {
      const lossOrder: OrderFeedItem[] = [
        {
          orderId: 'canary-loss-1',
          timestampMyt: '10 Oct 22:15:00',
          symbol: 'BTCUSDT',
          side: 'SELL',
          orderType: 'LIMIT MAKER',
          price: 83000.0,
          quantity: 0.001,
          notionalUsdt: 83.0,
          makerFeeUsdt: 0.0166,
          realizedPnlUsdt: -0.12,
          status: 'FILLED',
        },
      ]
      const html = renderToString(<ExecutiveTradesPage orders={lossOrder} />)
      expect(html).toContain('-0.1200')
      expect(html).not.toContain('+-')
      expect(html).not.toContain('+$-')
    })

    it('formats Realized PnL correctly for positive gain', () => {
      const gainOrder: OrderFeedItem[] = [
        {
          orderId: 'canary-gain-1',
          timestampMyt: '10 Oct 22:20:00',
          symbol: 'SOLUSDT',
          side: 'SELL',
          orderType: 'LIMIT MAKER',
          price: 180.0,
          quantity: 0.1,
          notionalUsdt: 18.0,
          makerFeeUsdt: 0.0036,
          realizedPnlUsdt: 0.45,
          status: 'FILLED',
        },
      ]
      const html = renderToString(<ExecutiveTradesPage orders={gainOrder} />)
      expect(html).toContain('+0.4500')
    })
  })

  describe('ExecutiveSafetyPage Phase 314 Invariants', () => {
    it('binds to live solvency metrics from executionStatus, eliminating Phase 309 fallbacks', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const risk = buildRiskModel(null)
      const killSwitch = buildKillSwitchModel(null)

      const liveExecStatus: ExecutionStatusResponse = {
        verified: true,
        status: 'ok',
        engine_state: 'RUNNING',
        timestamp_ms: Date.now(),
        solvency: {
          total_equity_usdt: 105.5,
          cash_usdt: 105.5,
          allocated_margin_usdt: 0.0,
          unrealized_pnl_usdt: 0.0,
          cash_reserve_pct: 100.0,
          drift_usdt: 0.0,
          zero_balance_drift_verified: true,
        },
        positions: {},
        candidate_allocations: [],
        aggregate_exposure_usdt: 0.0,
        recent_orders: [],
        total_orders: 0,
        interlock_blocks_count: 0,
        intra_day_loss_usdt: 0.0,
      }

      const html = renderToString(
        <ExecutiveSafetyPage
          productionLaunchModel={prodLaunch}
          riskModel={risk}
          killSwitchModel={killSwitch}
          executionStatus={liveExecStatus}
        />,
      )

      expect(html).toContain('105.5000')
      // Ensure stale Phase 309 fallbacks are NOT present
      expect(html).not.toContain('100.2038')
      expect(html).not.toContain('0.2038')
      expect(html).not.toContain('0.0032')
    })

    it('binds live Hawkes hazard and gateway latency, eliminating hardcoded tripwires', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const risk = buildRiskModel(null)
      const killSwitch = buildKillSwitchModel(null)

      const customMicro = {
        ...buildMicrostructureModel(null),
        maxSpectralRadius: 0.185,
        hawkes: {
          spectralRadius: 0.185,
          isExcited: false,
          halfLifeMs: 120,
          hazardLevel: 'LOW' as const,
          intensity: 0.22,
          toxicityScore: 0.05,
        },
      }

      const html = renderToString(
        <ExecutiveSafetyPage
          productionLaunchModel={prodLaunch}
          riskModel={risk}
          killSwitchModel={killSwitch}
          microstructureModel={customMicro}
          latencyMs={7.4}
        />,
      )

      expect(html).toContain('0.185')
      expect(html).toContain('7.4 ms')
      // Ensure hardcoded 0.428 and 12.4 ms are replaced
      expect(html).not.toContain('ρ = 0.428')
      expect(html).not.toContain('12.4 ms')
    })
  })
})
