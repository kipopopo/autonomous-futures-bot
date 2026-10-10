import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import { KpiCards } from '../mission-control/kpi-cards'
import { MarketPositionsCard } from '../mission-control/market-positions-card'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import { ExecutiveDashboard } from '../mission-control/executive-dashboard'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  type ProductionLaunchModel,
  type BracketPositionsModel,
} from '@/lib/canary'

describe('Empirical Adversarial Challenge Suite: Milestone 2 Deliverables', () => {
  // Common baseline models
  const liveMarket = buildLiveMarketModel(null)
  const emptyBrackets: BracketPositionsModel = {
    ...buildBracketPositionsModel(null),
    positions: [],
  }
  const micro = buildMicrostructureModel(null)
  const emptyTelemetry = {}
  const testDate = new Date('2026-10-10T07:15:00Z')

  describe('Challenge 1: Strict Zero Exposure Invariant (aggregateExposureUsdt === 0)', () => {
    it('asserts activeExposureUsdt is strictly 0 and formats to 0.00 when aggregateExposureUsdt === 0', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        aggregateExposureUsdt: 0,
        candidateAllocations: [],
        solvency: {
          ...buildProductionLaunchModel(null).solvency,
          total_equity_usdt: 100.0,
          cash_usdt: 100.0,
          allocated_margin_usdt: 0.0,
          unrealized_pnl_usdt: 0.0,
          cash_reserve_pct: 100.0,
        },
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      // Strict numeric checks
      expect(adapted.kpis.activeExposureUsdt).toBe(0)
      expect(adapted.kpis.activeExposureUsdt.toFixed(2)).toBe('0.00')

      // Assert cash reserve is 100.0% when flat
      expect(adapted.kpis.cashReservePct).toBe(100.0)
    })

    it('asserts activeExposureUsdt is strictly 0.00 when aggregateExposureUsdt is 0.0 (float zero)', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        aggregateExposureUsdt: 0.0,
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      expect(adapted.kpis.activeExposureUsdt).toBe(0.0)
      expect(adapted.kpis.activeExposureUsdt.toFixed(2)).toBe('0.00')
    })

    it('asserts activeExposureUsdt remains 0.00 even if legacy candidateAllocations had non-zero quantities when aggregateExposureUsdt === 0', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        aggregateExposureUsdt: 0.0,
        // Dirty candidateAllocations attempting to inject phantom exposure
        candidateAllocations: [
          {
            symbol: 'SOLUSDT',
            current_price: 185.0,
            position_qty: 0.03,
            entry_price: 185.0,
            allocated_exposure_usdt: 5.55,
            unrealized_pnl_usdt: 0.0,
            realized_pnl_usdt: 0.0,
            total_fees_usdt: 0.001,
            trades_count: 1,
          },
        ],
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      // aggregateExposureUsdt strictly takes precedence when specified >= 0
      expect(adapted.kpis.activeExposureUsdt).toBe(0.0)
      expect(adapted.kpis.activeExposureUsdt.toFixed(2)).toBe('0.00')
    })

    it('asserts positions.reduce fallback strictly yields 0.00 when aggregateExposureUsdt is undefined and positions are flat', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      // Delete aggregateExposureUsdt to test the fallback branch
      const undefinedExposureLaunch: ProductionLaunchModel = {
        ...prodLaunch,
        aggregateExposureUsdt: undefined as unknown as number,
        candidateAllocations: [],
      }

      const adapted = buildExecutiveDashboardModel(
        undefinedExposureLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      expect(adapted.kpis.activeExposureUsdt).toBe(0.0)
      expect(adapted.kpis.activeExposureUsdt.toFixed(2)).toBe('0.00')
    })

    it('asserts KpiCards renders strictly $0.00 for active exposure and NOT $5.50', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        aggregateExposureUsdt: 0.0,
        solvency: {
          ...buildProductionLaunchModel(null).solvency,
          total_equity_usdt: 100.0,
          cash_usdt: 100.0,
          cash_reserve_pct: 100.0,
        },
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      const html = renderToString(<KpiCards kpis={adapted.kpis} />)

      // Must display $0.00
      expect(html).toContain('$0.00')
      expect(html).toContain('/ $25.00 Had Maksimum')
      expect(html).toContain('100.0% (Lantai ≥ 75%)')

      // Adversarial check: Must NOT contain the purged $5.50 stale fallback
      expect(html).not.toContain('$5.50')
      expect(html).not.toContain('100.2038')
    })
  })

  describe('Challenge 2: Phase 309 Isolation & Phantom Position Prevention', () => {
    it('asserts passing phase: "phase_309" with fake allocations NEVER causes ANY pair to show LONG or SHORT when flat', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        phase: 'phase_309',
        aggregateExposureUsdt: 0.0,
        candidateAllocations: [
          {
            symbol: 'ETHUSDT',
            current_price: 2750.0,
            position_qty: -0.002, // Fake ETH short from Phase 309
            entry_price: 2750.0,
            allocated_exposure_usdt: 5.5,
            unrealized_pnl_usdt: 0.02,
            realized_pnl_usdt: 0.0,
            total_fees_usdt: 0.0011,
            trades_count: 1,
          },
          {
            symbol: 'SOLUSDT',
            current_price: 185.0,
            position_qty: 0.03, // Fake SOL long from Phase 309
            entry_price: 185.0,
            allocated_exposure_usdt: 5.55,
            unrealized_pnl_usdt: 0.0,
            realized_pnl_usdt: 0.0,
            total_fees_usdt: 0.00111,
            trades_count: 1,
          },
          {
            symbol: 'BTCUSDT',
            current_price: 95000.0,
            position_qty: -0.05, // Adversarial BTC short injection
            entry_price: 95500.0,
            allocated_exposure_usdt: 4750.0,
            unrealized_pnl_usdt: 25.0,
            realized_pnl_usdt: 0.0,
            total_fees_usdt: 0.95,
            trades_count: 5,
          },
        ],
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      // Verify each candidate pair explicitly
      const sol = adapted.positions.find((p) => p.symbol === 'SOLUSDT')
      const eth = adapted.positions.find((p) => p.symbol === 'ETHUSDT')
      const btc = adapted.positions.find((p) => p.symbol === 'BTCUSDT')

      expect(sol).toBeDefined()
      expect(eth).toBeDefined()
      expect(btc).toBeDefined()

      // Absolute invariant: NO pair may show LONG or SHORT
      expect(sol?.state).toBe('SCANNING / STANDBY')
      expect(eth?.state).toBe('SCANNING / STANDBY')
      expect(btc?.state).toBe('SCANNING / STANDBY')

      expect(adapted.positions.some((p) => p.state === 'LONG')).toBe(false)
      expect(adapted.positions.some((p) => p.state === 'SHORT')).toBe(false)

      // All metrics must be zeroed for inactive positions
      for (const pos of adapted.positions) {
        expect(pos.size).toBe(0.0)
        expect(pos.notionalUsdt).toBe(0.0)
        expect(pos.marginUsdt).toBe(0.0)
        expect(pos.unrealizedPnlUsdt).toBe(0.0)
        expect(pos.unrealizedPnlPct).toBe(0.0)
        expect(pos.entryPrice).toBe(0.0)
      }
    })

    it('asserts MarketPositionsCard renders clean SCANNING / STANDBY badges with zero phantom position details', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        phase: 'phase_309',
        aggregateExposureUsdt: 0.0,
        candidateAllocations: [
          {
            symbol: 'ETHUSDT',
            current_price: 2750.0,
            position_qty: -0.002,
            entry_price: 2750.0,
            allocated_exposure_usdt: 5.5,
            unrealized_pnl_usdt: 0.0,
            realized_pnl_usdt: 0.0,
            total_fees_usdt: 0.001,
            trades_count: 1,
          },
          {
            symbol: 'SOLUSDT',
            current_price: 185.0,
            position_qty: 0.03,
            entry_price: 185.0,
            allocated_exposure_usdt: 5.55,
            unrealized_pnl_usdt: 0.0,
            realized_pnl_usdt: 0.0,
            total_fees_usdt: 0.001,
            trades_count: 1,
          },
        ],
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      const html = renderToString(<MarketPositionsCard positions={adapted.positions} />)

      // All pairs rendered in SCANNING / STANDBY
      expect(html).toContain('SCANNING / STANDBY')
      expect(html).toContain('SOLUSDT')
      expect(html).toContain('ETHUSDT')
      expect(html).toContain('BTCUSDT')

      // Adversarial check: Must NOT contain LONG or SHORT state badges
      expect(html).not.toMatch(/>\s*LONG\s*</)
      expect(html).not.toMatch(/>\s*SHORT\s*</)

      // Active position telemetry fields must NOT be displayed
      expect(html).not.toContain('Harga Masuk:')
      expect(html).not.toContain('PnL Belum Direalisasi:')
    })

    it('asserts genuine active positions are preserved when phase is NOT phase_309 (control test)', () => {
      const genuineBrackets: BracketPositionsModel = {
        ...buildBracketPositionsModel(null),
        positions: [
          {
            symbol: 'SOLUSDT',
            side: 'BUY',
            size: 0.03,
            entry_price: 185.0,
            mark_price: 187.0,
            notional_usdt: 5.61,
            margin_allocated_usdt: 5.61,
            unrealized_pnl_usdt: 0.06,
            realized_pnl_usdt: 0.0,
            liquidation_price_usdt: 0.0,
            margin_ratio_pct: 10.0,
            risk_state: 'HEALTHY',
            brackets_count: 0,
            last_updated_utc: '2026-10-10T07:15:00Z',
          },
        ],
      }

      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        phase: 'phase_311',
        aggregateExposureUsdt: 5.61,
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        genuineBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      const sol = adapted.positions.find((p) => p.symbol === 'SOLUSDT')
      expect(sol?.state).toBe('LONG')
      expect(sol?.size).toBe(0.03)
      expect(sol?.entryPrice).toBe(185.0)
      expect(sol?.notionalUsdt).toBe(5.61)
      expect(sol?.unrealizedPnlUsdt).toBe(0.06)
    })
  })

  describe('Challenge 3: Order Feed Sanitization of ord-p309- Artifacts', () => {
    it('asserts passing recentOrders containing only ord-p309- IDs results in ZERO ord-p309- orders in output', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        recentOrders: [
          {
            order_id: 'ord-p309-btcusdt-0001',
            symbol: 'BTCUSDT',
            side: 'BUY',
            order_type: 'LIMIT',
            price: 95000.0,
            quantity: 0.00006,
            notional_usdt: 5.7,
            status: 'FILLED',
            fill_price: 95000.0,
            fee_usdt: 0.00114,
            realized_pnl_usdt: 0.0,
            timestamp_ms: 1790160000000,
          },
          {
            order_id: 'ord-p309-ethusdt-0002',
            symbol: 'ETHUSDT',
            side: 'SELL',
            order_type: 'LIMIT',
            price: 2750.0,
            quantity: 0.002,
            notional_usdt: 5.5,
            status: 'FILLED',
            fill_price: 2750.0,
            fee_usdt: 0.0011,
            realized_pnl_usdt: 0.0,
            timestamp_ms: 1790160100000,
          },
          {
            order_id: 'ord-p309-solusdt-0003',
            symbol: 'SOLUSDT',
            side: 'BUY',
            order_type: 'LIMIT',
            price: 185.0,
            quantity: 0.03,
            notional_usdt: 5.55,
            status: 'FILLED',
            fill_price: 185.0,
            fee_usdt: 0.00111,
            realized_pnl_usdt: 0.0,
            timestamp_ms: 1790160200000,
          },
          {
            order_id: 'ord-p309-btcusdt-0004',
            symbol: 'BTCUSDT',
            side: 'SELL',
            order_type: 'LIMIT',
            price: 95500.0,
            quantity: 0.00006,
            notional_usdt: 5.73,
            status: 'FILLED',
            fill_price: 95500.0,
            fee_usdt: 0.001146,
            realized_pnl_usdt: 0.03,
            timestamp_ms: 1790160300000,
          },
        ],
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      // Invariant: ZERO ord-p309- orders exist in adapted.orders
      const staleOrders = adapted.orders.filter((o) => o.orderId.startsWith('ord-p309-'))
      expect(staleOrders.length).toBe(0)
      expect(adapted.orders.some((o) => o.orderId.startsWith('ord-p309-'))).toBe(false)

      // Fallback activates: Authentic Phase 310/311 orders must be rendered
      expect(adapted.orders.length).toBe(5)
      expect(adapted.orders[0].orderId).toBe('canary-p311-drill-sol-1791554786355')
    })

    it('asserts passing mixed recentOrders preserves authentic orders while purging ALL ord-p309- orders', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        recentOrders: [
          {
            order_id: 'ord-p309-btcusdt-0001', // Stale
            symbol: 'BTCUSDT',
            side: 'BUY',
            order_type: 'LIMIT',
            price: 95000.0,
            quantity: 0.00006,
            notional_usdt: 5.7,
            status: 'FILLED',
            fill_price: 95000.0,
            fee_usdt: 0.00114,
            realized_pnl_usdt: 0.0,
            timestamp_ms: 1790160000000,
          },
          {
            order_id: 'canary-p311-drill-sol-1791554786355', // Authentic
            symbol: 'SOLUSDT',
            side: 'BUY',
            order_type: 'LIMIT MAKER',
            price: 185.0,
            quantity: 0.03,
            notional_usdt: 5.55,
            status: 'FILLED',
            fill_price: 185.0,
            fee_usdt: 0.00111,
            realized_pnl_usdt: 0.0,
            timestamp_ms: 1791554786355,
          },
          {
            order_id: 'ord-p309-ethusdt-0002', // Stale
            symbol: 'ETHUSDT',
            side: 'SELL',
            order_type: 'LIMIT',
            price: 2750.0,
            quantity: 0.002,
            notional_usdt: 5.5,
            status: 'FILLED',
            fill_price: 2750.0,
            fee_usdt: 0.0011,
            realized_pnl_usdt: 0.0,
            timestamp_ms: 1790160100000,
          },
          {
            order_id: 'ord-p310-sol-0002', // Authentic
            symbol: 'SOLUSDT',
            side: 'SELL',
            order_type: 'LIMIT MAKER',
            price: 177.9,
            quantity: 0.03,
            notional_usdt: 5.337,
            status: 'FILLED',
            fill_price: 177.9,
            fee_usdt: 0.0010674,
            realized_pnl_usdt: 0.207,
            timestamp_ms: 1790250900000,
          },
          {
            order_id: 'ord-p310-eth-0003', // Authentic
            symbol: 'ETHUSDT',
            side: 'BUY',
            order_type: 'LIMIT MAKER',
            price: 2750.0,
            quantity: 0.002,
            notional_usdt: 5.5,
            status: 'FILLED',
            fill_price: 2750.0,
            fee_usdt: 0.0011,
            realized_pnl_usdt: 0.0,
            timestamp_ms: 1790251800000,
          },
        ],
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      // Invariant: Exactly 3 authentic orders preserved
      expect(adapted.orders.length).toBe(3)

      // Invariant: ZERO ord-p309- orders survive
      expect(adapted.orders.filter((o) => o.orderId.startsWith('ord-p309-')).length).toBe(0)
      expect(adapted.orders.some((o) => o.orderId.includes('p309'))).toBe(false)

      // Verify authentic orders are in the output
      const ids = adapted.orders.map((o) => o.orderId)
      expect(ids).toEqual([
        'canary-p311-drill-sol-1791554786355',
        'ord-p310-sol-0002',
        'ord-p310-eth-0003',
      ])
    })

    it('asserts OrderFeedTable HTML rendering is strictly free of ord-p309- strings', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        recentOrders: [
          {
            order_id: 'ord-p309-btcusdt-0001',
            symbol: 'BTCUSDT',
            side: 'BUY',
            order_type: 'LIMIT',
            price: 95000.0,
            quantity: 0.00006,
            notional_usdt: 5.7,
            status: 'FILLED',
            fill_price: 95000.0,
            fee_usdt: 0.00114,
            realized_pnl_usdt: 0.0,
            timestamp_ms: 1790160000000,
          },
        ],
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      const html = renderToString(<OrderFeedTable orders={adapted.orders} />)

      // Invariant: HTML does NOT contain ord-p309-
      expect(html).not.toContain('ord-p309-')

      // Contains authentic testnet drill order
      expect(html).toContain('SOLUSDT')
      expect(html).toContain('LIMIT MAKER')
    })
  })

  describe('Challenge 4: Authentic Phase 310/311 Orders Preservation & Metric Integrity', () => {
    it('asserts authentic Phase 311 and Phase 310 order properties are accurately mapped', () => {
      const authenticRecentOrders = [
        {
          order_id: 'canary-p311-drill-sol-1791554786355',
          symbol: 'SOLUSDT',
          side: 'BUY' as const,
          order_type: 'LIMIT MAKER',
          price: 185.0,
          quantity: 0.03,
          notional_usdt: 5.55,
          status: 'FILLED' as const,
          fill_price: 185.0,
          fee_usdt: 0.00111,
          realized_pnl_usdt: 0.0,
          timestamp_ms: 1791554786355,
        },
        {
          order_id: 'canary-p311-tp-sol-1791554786355',
          symbol: 'SOLUSDT',
          side: 'SELL' as const,
          order_type: 'LIMIT MAKER',
          price: 189.0,
          quantity: 0.03,
          notional_usdt: 5.67,
          status: 'FILLED' as const,
          fill_price: 189.0,
          fee_usdt: 0.001134,
          realized_pnl_usdt: 0.12,
          timestamp_ms: 1791554786365,
        },
        {
          order_id: 'ord-p310-sol-0002',
          symbol: 'SOLUSDT',
          side: 'SELL' as const,
          order_type: 'LIMIT MAKER',
          price: 177.9,
          quantity: 0.03,
          notional_usdt: 5.337,
          status: 'FILLED' as const,
          fill_price: 177.9,
          fee_usdt: 0.0010674,
          realized_pnl_usdt: 0.207,
          timestamp_ms: 1790250900000,
        },
      ]

      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        recentOrders: authenticRecentOrders,
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      expect(adapted.orders.length).toBe(3)

      // Test drill order mapping
      const drill = adapted.orders.find((o) => o.orderId === 'canary-p311-drill-sol-1791554786355')
      expect(drill).toBeDefined()
      expect(drill?.symbol).toBe('SOLUSDT')
      expect(drill?.side).toBe('BUY')
      expect(drill?.price).toBe(185.0)
      expect(drill?.quantity).toBe(0.03)
      expect(drill?.notionalUsdt).toBe(5.55)
      expect(drill?.makerFeeUsdt).toBe(0.00111)
      expect(drill?.realizedPnlUsdt).toBe(0.0)

      // Test TP order mapping
      const tp = adapted.orders.find((o) => o.orderId === 'canary-p311-tp-sol-1791554786355')
      expect(tp).toBeDefined()
      expect(tp?.symbol).toBe('SOLUSDT')
      expect(tp?.side).toBe('SELL')
      expect(tp?.price).toBe(189.0)
      expect(tp?.realizedPnlUsdt).toBe(0.12)

      // Test Phase 310 order mapping
      const p310 = adapted.orders.find((o) => o.orderId === 'ord-p310-sol-0002')
      expect(p310).toBeDefined()
      expect(p310?.side).toBe('SELL')
      expect(p310?.price).toBe(177.9)
      expect(p310?.realizedPnlUsdt).toBe(0.207)

      // Win rate: All 3 orders have realized_pnl >= 0, so 100% win rate
      expect(adapted.kpis.winRatePct).toBe(100.0)
      expect(adapted.kpis.totalTrades).toBe(3)
    })

    it('asserts winRatePct and totalTrades exclude purged ord-p309- simulation orders from metric calculations', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        totalTrades: 0,
        recentOrders: [
          // 2 Stale ord-p309- orders with fake losses
          {
            order_id: 'ord-p309-fake-01',
            symbol: 'ETHUSDT',
            side: 'SELL',
            order_type: 'LIMIT',
            price: 2700.0,
            quantity: 0.002,
            notional_usdt: 5.4,
            status: 'FILLED',
            fill_price: 2700.0,
            fee_usdt: 0.001,
            realized_pnl_usdt: -1.0, // Loss in stale record
            timestamp_ms: 1790160000000,
          },
          {
            order_id: 'ord-p309-fake-02',
            symbol: 'ETHUSDT',
            side: 'SELL',
            order_type: 'LIMIT',
            price: 2700.0,
            quantity: 0.002,
            notional_usdt: 5.4,
            status: 'FILLED',
            fill_price: 2700.0,
            fee_usdt: 0.001,
            realized_pnl_usdt: -1.0, // Loss in stale record
            timestamp_ms: 1790160000000,
          },
          // 1 Authentic order with profit
          {
            order_id: 'ord-p310-sol-0002',
            symbol: 'SOLUSDT',
            side: 'SELL',
            order_type: 'LIMIT MAKER',
            price: 177.9,
            quantity: 0.03,
            notional_usdt: 5.337,
            status: 'FILLED',
            fill_price: 177.9,
            fee_usdt: 0.0010674,
            realized_pnl_usdt: 0.207,
            timestamp_ms: 1790250900000,
          },
        ],
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      // Total trades must be 1 (only the authentic order), not 3
      expect(adapted.kpis.totalTrades).toBe(1)
      // Win rate must be 100% (1/1 winning), NOT 33.3% (1/3)
      expect(adapted.kpis.winRatePct).toBe(100.0)
    })
  })

  describe('Challenge 5: Full Executive Dashboard Component Integration', () => {
    it('assembles and renders ExecutiveDashboard end-to-end under adversarial flat & purged inputs', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        phase: 'phase_309',
        aggregateExposureUsdt: 0.0,
        candidateAllocations: [
          {
            symbol: 'ETHUSDT',
            current_price: 2750.0,
            position_qty: -0.002,
            entry_price: 2750.0,
            allocated_exposure_usdt: 5.5,
            unrealized_pnl_usdt: 0.0,
            realized_pnl_usdt: 0.0,
            total_fees_usdt: 0.001,
            trades_count: 1,
          },
        ],
        recentOrders: [
          {
            order_id: 'ord-p309-btcusdt-0001',
            symbol: 'BTCUSDT',
            side: 'BUY',
            order_type: 'LIMIT',
            price: 95000.0,
            quantity: 0.00006,
            notional_usdt: 5.7,
            status: 'FILLED',
            fill_price: 95000.0,
            fee_usdt: 0.00114,
            realized_pnl_usdt: 0.0,
            timestamp_ms: 1790160000000,
          },
        ],
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      const html = renderToString(
        <ExecutiveDashboard model={adapted} onRefresh={() => {}} isLoading={false} />,
      )

      // Check full page elements
      expect(html).toContain('Autonomous Futures')
      expect(html).toContain('ACTIVE 24/7')
      expect(html).toContain('$0.00') // Active exposure
      expect(html).toContain('SCANNING / STANDBY')
      expect(html).not.toContain('ord-p309-')
      expect(html).not.toMatch(/>\s*LONG\s*</)
      expect(html).not.toMatch(/>\s*SHORT\s*</)
    })
  })
})
