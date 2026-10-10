import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import { MissionControlHeader } from '../mission-control/mission-control-header'
import { KpiCards } from '../mission-control/kpi-cards'
import { MarketPositionsCard } from '../mission-control/market-positions-card'
import { StrategyConfluenceRadar } from '../mission-control/strategy-confluence-radar'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import { ExecutiveDashboard } from '../mission-control/executive-dashboard'
import { ExecutivePositionsPage } from '../executive-positions-page'
import { ExecutiveTradesPage } from '../executive-trades-page'
import { ExecutiveSafetyPage } from '../executive-safety-page'
import type {
  ExecutiveDashboardModel,
  PositionTelemetry,
  OrderFeedItem,
} from '../mission-control/types'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  buildRiskModel,
  buildKillSwitchModel,
  type ProductionLaunchModel,
  type MicrostructureModel,
} from '@/lib/canary'

describe('Adversarial Test Suite: Executive Mission Control Robustness & Edge Cases', () => {
  describe('Dimension 1: Missing & Defaulted Canary Data', () => {
    it('handles null raw canary responses gracefully through model builders and adapter', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)
      const telemetry = {
        status: 'disconnected' as const,
        error: null,
        snapshot: null,
        hawkesMetrics: null,
        spectralRadiusHistory: [],
        latencyMs: 0,
        lastMessageAt: null,
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        brackets,
        micro,
        telemetry,
        null,
      )

      expect(adapted).toBeDefined()
      expect(adapted.botStatus.state).toBe('ACTIVE 24/7')
      expect(adapted.botStatus.isStreaming).toBe(false)
      expect(adapted.botStatus.lastSyncedAtMyt).not.toBe('—')
      expect(adapted.kpis.totalEquityUsdt).toBeGreaterThanOrEqual(100.0)
      expect(adapted.positions.length).toBe(3)
      expect(adapted.orders.length).toBeGreaterThan(0)

      // Ensure the assembled dashboard renders without any exceptions
      const html = renderToString(
        <ExecutiveDashboard model={adapted} onRefresh={() => {}} isLoading={false} />,
      )
      expect(html).toContain('Autonomous Futures')
      expect(html).toContain('CONNECTING')
    })

    it('handles null lastFetchedAt and invalid dates in formatMytDate without crashing', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)
      const telemetry = {
        status: 'open' as const,
        error: null,
        snapshot: null,
        hawkesMetrics: null,
        spectralRadiusHistory: [],
        latencyMs: 10,
        lastMessageAt: null,
      }

      const adaptedNullDate = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        brackets,
        micro,
        telemetry,
        null,
      )
      expect(adaptedNullDate.botStatus.lastSyncedAtMyt).toBeTruthy()

      // Order with NaN / invalid date
      const mutatedProdLaunch: ProductionLaunchModel = {
        ...prodLaunch,
        recentOrders: [
          {
            order_id: 'ord-bad-date',
            symbol: 'SOLUSDT',
            side: 'BUY',
            order_type: 'LIMIT',
            price: 180.0,
            quantity: 0.01,
            notional_usdt: 1.8,
            status: 'FILLED',
            fill_price: 180.0,
            fee_usdt: 0.00036,
            realized_pnl_usdt: 0.0,
            timestamp_ms: Number.NaN,
          },
        ],
      }

      const adaptedBadOrderDate = buildExecutiveDashboardModel(
        mutatedProdLaunch,
        liveMarket,
        brackets,
        micro,
        telemetry,
        null,
      )
      expect(adaptedBadOrderDate.orders[0].timestampMyt).toBe('—')
    })
  })

  describe('Dimension 2: Zero Balances & Fallback Behavior Analysis', () => {
    it('analyzes adapter behavior when total_equity_usdt and cash_usdt are zero', () => {
      const baseProd = buildProductionLaunchModel(null)
      const zeroBalanceProd: ProductionLaunchModel = {
        ...baseProd,
        solvency: {
          ...baseProd.solvency,
          total_equity_usdt: 0.0,
          cash_usdt: 0.0,
          allocated_margin_usdt: 0.0,
          cash_reserve_pct: 0.0,
          realized_pnl_usdt: 0.0,
        },
        aggregateExposureUsdt: 0.0,
        totalTrades: 0,
      }
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)

      const adapted = buildExecutiveDashboardModel(
        zeroBalanceProd,
        liveMarket,
        brackets,
        micro,
        {},
        new Date(),
      )

      // Note: adapter lines 65-66 use `total_equity_usdt > 0 ? solvency.total_equity_usdt : 100.0`
      // which acts as a fallback default when balance is 0
      expect(adapted.kpis.totalEquityUsdt).toBe(100.0)
      expect(adapted.kpis.cashUsdt).toBe(100.0)
    })

    it('renders KpiCards cleanly when fed absolute zero values without NaN or divide-by-zero', () => {
      const zeroKpis: ExecutiveDashboardModel['kpis'] = {
        totalEquityUsdt: 0.0,
        cashUsdt: 0.0,
        allocatedMarginUsdt: 0.0,
        realizedPnlUsdt: 0.0,
        winRatePct: 0.0,
        totalTrades: 0,
        activeExposureUsdt: 0.0,
        maxExposureCapUsdt: 0.0,
        cashReservePct: 0.0,
        minCashReserveFloorPct: 75.0,
        latencyMs: 0.0,
        interlockBlocksCount: 0,
        balanceDriftUsdt: 0.0,
        isZeroDriftVerified: true,
      }

      const html = renderToString(<KpiCards kpis={zeroKpis} />)
      expect(html).not.toContain('NaN')
      expect(html).not.toContain('Infinity')
      expect(html).toContain('$0.00')
      expect(html).toContain('0.0% Win Rate')
      expect(html).toContain('0 Dagangan Selesai')
      expect(html).toContain('0.0% (Lantai ≥ 75%)')
      expect(html).toContain('text-amber-400') // unhealthy reserve floor < 75%
    })
  })

  describe('Dimension 3: Negative PnL & Underwater Drawdown', () => {
    it('adapts and passes negative realized PnL correctly', () => {
      const baseProd = buildProductionLaunchModel(null)
      const underwaterProd: ProductionLaunchModel = {
        ...baseProd,
        solvency: {
          ...baseProd.solvency,
          realized_pnl_usdt: -15.42,
          total_equity_usdt: 84.58,
          cash_usdt: 84.58,
        },
      }
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)

      const adapted = buildExecutiveDashboardModel(
        underwaterProd,
        liveMarket,
        brackets,
        micro,
        {},
        new Date(),
      )

      expect(adapted.kpis.realizedPnlUsdt).toBe(-15.42)
    })

    it('renders negative realized PnL in KpiCards with proper negative formatting and red styling', () => {
      const underwaterKpis: ExecutiveDashboardModel['kpis'] = {
        totalEquityUsdt: 84.58,
        cashUsdt: 84.58,
        allocatedMarginUsdt: 0.0,
        realizedPnlUsdt: -15.42,
        winRatePct: 40.0,
        totalTrades: 10,
        activeExposureUsdt: 0.0,
        maxExposureCapUsdt: 25.0,
        cashReservePct: 100.0,
        minCashReserveFloorPct: 75.0,
        latencyMs: 14.2,
        interlockBlocksCount: 0,
        balanceDriftUsdt: 0.0,
        isZeroDriftVerified: true,
      }

      const html = renderToString(<KpiCards kpis={underwaterKpis} />)
      expect(html).toContain('text-rose-400')
      expect(html).toContain('bg-rose-500/10')
      expect(html).toContain('$-15.42')
      expect(html).not.toContain('+$')
    })

    it('renders negative unrealized PnL in MarketPositionsCard with red styling and down arrow', () => {
      const negativePositions: PositionTelemetry[] = [
        {
          symbol: 'ETHUSDT',
          currentPrice: 2650.0,
          state: 'LONG',
          entryPrice: 2750.0,
          size: 0.002,
          notionalUsdt: 5.3,
          marginUsdt: 5.3,
          unrealizedPnlUsdt: -0.2,
          unrealizedPnlPct: -3.77,
          takeProfitPrice: 2820.0,
          stopLossPrice: 2600.0,
          riskRewardRatio: '1.66 : 1',
        },
      ]

      const html = renderToString(<MarketPositionsCard positions={negativePositions} />)
      expect(html).toContain('text-rose-400')
      expect(html).toContain('-0.200')
      expect(html).toContain('-3.77')
    })

    it('renders negative realized PnL in OrderFeedTable with red styling and down arrow', () => {
      const lossOrders: OrderFeedItem[] = [
        {
          orderId: 'ord-loss-001',
          timestampMyt: '09 Oct 15:00:00',
          symbol: 'SOLUSDT',
          side: 'SELL',
          orderType: 'LIMIT MAKER',
          price: 170.0,
          quantity: 0.03,
          notionalUsdt: 5.1,
          makerFeeUsdt: 0.00102,
          realizedPnlUsdt: -0.21,
          status: 'FILLED',
        },
      ]

      const html = renderToString(<OrderFeedTable orders={lossOrders} />)
      expect(html).toContain('text-rose-400')
      expect(html).toContain('-0.2100')
      expect(html).not.toContain('+$')
    })
  })

  describe('Dimension 4: Supercritical Hawkes Hazard (rho >= 1.0)', () => {
    it('detects supercritical Hawkes hazard and updates isNonToxic to false', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const baseMicro = buildMicrostructureModel(null)
      const supercriticalMicro: MicrostructureModel = {
        ...baseMicro,
        maxSpectralRadius: 1.345,
        isSupercritical: true,
      }
      const telemetry = {
        spectralRadiusHistory: [0.85, 0.98, 1.15, 1.345],
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        brackets,
        supercriticalMicro,
        telemetry,
        new Date(),
      )

      expect(adapted.radar.hawkesHazard.spectralRadius).toBe(1.345)
      expect(adapted.radar.hawkesHazard.isNonToxic).toBe(false)
      expect(adapted.radar.hawkesHazard.recentHistory).toEqual([0.85, 0.98, 1.15, 1.345])
    })

    it('renders BAHAYA TOKSIK and KELULUSAN DITAHAN when rho >= 1.0', () => {
      const html = renderToString(
        <StrategyConfluenceRadar
          btcMacroTrend={{
            regime: 'BULLISH ALIGNED',
            ema50_1h: 95400,
            ema200_1h: 93800,
            ema50_4h: 94800,
            ema200_4h: 91200,
            explanation: 'Macro bullish',
          }}
          scalperCriteria={{
            priceBelowEma20Atr: 1.8,
            priceBelowEmaThreshold: 2.5,
            priceTriggered: false,
            relativeVolume: 1.4,
            volumeThreshold: 2.2,
            volumeTriggered: false,
            rsi14: 38.5,
            rsiThreshold: 26.0,
            rsiTriggered: false,
            makerFeePct: 0.02,
          }}
          hawkesHazard={{
            spectralRadius: 1.25,
            isNonToxic: false,
            thresholdWarning: 0.85,
            thresholdCritical: 1.0,
            recentHistory: [0.8, 0.95, 1.1, 1.25],
          }}
        />,
      )

      expect(html).toContain('BAHAYA TOKSIK')
      expect(html).toContain('badge-error')
      expect(html).toContain('⚠️ KELULUSAN DITAHAN')
      expect(html).toContain('badge-warning')
      expect(html).not.toContain('✅ AUTORISASI BELIAN AKTIF')
      expect(html).not.toContain('NaN')
    })

    it('renders sparkline SVG safely with single-element or extreme histories', () => {
      const singlePointHazard = {
        spectralRadius: 1.5,
        isNonToxic: false,
        thresholdWarning: 0.85,
        thresholdCritical: 1.0,
        recentHistory: [1.5],
      }

      const html = renderToString(
        <StrategyConfluenceRadar
          btcMacroTrend={{
            regime: 'BULLISH ALIGNED',
            ema50_1h: 95400,
            ema200_1h: 93800,
            ema50_4h: 94800,
            ema200_4h: 91200,
            explanation: 'Macro bullish',
          }}
          scalperCriteria={{
            priceBelowEma20Atr: 1.8,
            priceBelowEmaThreshold: 2.5,
            priceTriggered: false,
            relativeVolume: 1.4,
            volumeThreshold: 2.2,
            volumeTriggered: false,
            rsi14: 38.5,
            rsiThreshold: 26.0,
            rsiTriggered: false,
            makerFeePct: 0.02,
          }}
          hawkesHazard={singlePointHazard}
        />,
      )

      expect(html).not.toContain('NaN')
      expect(html).toContain('<polyline')
    })
  })

  describe('Dimension 5: Empty Order Feeds & Table Empty State', () => {
    it('analyzes adapter behavior when recentOrders is empty array', () => {
      const baseProd = buildProductionLaunchModel(null)
      const emptyOrdersProd: ProductionLaunchModel = {
        ...baseProd,
        recentOrders: [],
      }
      const liveMarket = buildLiveMarketModel(null)
      const brackets = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)

      const adapted = buildExecutiveDashboardModel(
        emptyOrdersProd,
        liveMarket,
        brackets,
        micro,
        {},
        new Date(),
      )

      // Note: adapter falls back to 5 authentic Phase 310/311 testnet orders if recentOrders.length === 0
      // Verifying empirical behavior:
      expect(adapted.orders.length).toBe(5)
      expect(adapted.orders[0].symbol).toBe('SOLUSDT')
    })

    it('renders empty table banner when OrderFeedTable is passed empty array directly', () => {
      const html = renderToString(<OrderFeedTable orders={[]} />)
      expect(html).toContain('Tiada rekod pesanan bagi tapisan ini.')
      expect(html).not.toContain('<tbody')
    })
  })

  describe('Dimension 6: Secondary Pages Resilience Under Edge Cases', () => {
    it('renders ExecutivePositionsPage with empty positions array without error', () => {
      const brackets = buildBracketPositionsModel(null)
      const liveMarket = buildLiveMarketModel(null)

      const html = renderToString(
        <ExecutivePositionsPage
          positions={[]}
          bracketPositionsModel={brackets}
          liveMarketModel={liveMarket}
        />,
      )
      expect(html).toContain('Terbuka')
      expect(html).toContain('Dipantau')
      expect(html).not.toContain('NaN')
    })

    it('renders ExecutiveTradesPage with empty orders list and negative PnL', () => {
      const emptyHtml = renderToString(<ExecutiveTradesPage orders={[]} />)
      expect(emptyHtml).toContain('Pesanan Diisi')
      expect(emptyHtml).toContain('0.0000')

      const lossOrders: OrderFeedItem[] = [
        {
          orderId: 'ord-loss-1',
          timestampMyt: '09 Oct 15:30:00',
          symbol: 'BTCUSDT',
          side: 'SELL',
          orderType: 'LIMIT MAKER',
          price: 94000.0,
          quantity: 0.00005,
          notionalUsdt: 4.7,
          makerFeeUsdt: 0.00094,
          realizedPnlUsdt: -1.25,
          status: 'FILLED',
        },
      ]

      const lossHtml = renderToString(<ExecutiveTradesPage orders={lossOrders} />)
      expect(lossHtml).toContain('Pesanan Diisi')
      expect(lossHtml).toContain('-1.2500')
    })

    it('renders ExecutiveSafetyPage with zero-drift verified and unverified models', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const risk = buildRiskModel(null)
      const killSwitch = buildKillSwitchModel(null)

      const verifiedHtml = renderToString(
        <ExecutiveSafetyPage
          productionLaunchModel={prodLaunch}
          riskModel={risk}
          killSwitchModel={killSwitch}
        />,
      )
      expect(verifiedHtml).toContain('Disahkan Sifar-Drift')

      const driftedProd: ProductionLaunchModel = {
        ...prodLaunch,
        solvency: {
          ...prodLaunch.solvency,
          zero_balance_drift_verified: false,
          drift_usdt: 0.005,
        },
      }

      const driftedHtml = renderToString(
        <ExecutiveSafetyPage
          productionLaunchModel={driftedProd}
          riskModel={risk}
          killSwitchModel={killSwitch}
        />,
      )
      expect(driftedHtml).toContain('Semakan Berterusan')
    })
  })

  describe('Dimension 7: Header & Status Edge Cases', () => {
    it('renders PAUSED, DEGRADED, and TRIPPED states accurately', () => {
      const pausedHtml = renderToString(
        <MissionControlHeader
          status={{
            state: 'PAUSED',
            gatewayMode: 'BINANCE TESTNET GATEWAY',
            circuitBreaker: 'TRIPPED',
            tripwiresCount: 2,
            lastSyncedAtMyt: '09 Oct 14:00:00',
            isStreaming: false,
          }}
          onRefresh={() => {}}
          isLoading={false}
        />,
      )
      expect(pausedHtml).toContain('PAUSED')
      expect(pausedHtml).toContain('text-rose-400')
      expect(pausedHtml).toContain('CIRCUIT: TRIPPED')
      expect(pausedHtml).toContain('CONNECTING')

      const degradedHtml = renderToString(
        <MissionControlHeader
          status={{
            state: 'DEGRADED',
            gatewayMode: 'BINANCE TESTNET GATEWAY',
            circuitBreaker: 'NORMAL',
            tripwiresCount: 0,
            lastSyncedAtMyt: '09 Oct 14:00:00',
            isStreaming: true,
          }}
          onRefresh={() => {}}
          isLoading={true}
        />,
      )
      expect(degradedHtml).toContain('DEGRADED')
      expect(degradedHtml).toContain('text-amber-400')
      expect(degradedHtml).toContain('CIRCUIT: NORMAL')
      expect(degradedHtml).toContain('STREAMING')
    })
  })
})
