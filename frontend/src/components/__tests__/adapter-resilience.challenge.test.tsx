import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import { ExecutiveDashboard } from '../mission-control/executive-dashboard'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  type ProductionLaunchModel,
  type LiveMarketModel,
  type DoubleEntrySolvencyItem,
  type CanaryMicroCapitalConfinementItem,
} from '@/lib/canary'

describe('Adversarial Challenge: buildExecutiveDashboardModel Edge Cases & Fault Injection', () => {
  const getCleanBaseModels = () => ({
    prodLaunch: buildProductionLaunchModel(null),
    liveMarket: buildLiveMarketModel(null),
    bracketPositions: buildBracketPositionsModel(null),
    microstructure: buildMicrostructureModel(null),
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

  describe('Dimension 1: Null and Undefined Solvency Fields', () => {
    it('gracefully handles completely undefined solvency fields with clean fallback defaults', () => {
      const { prodLaunch, liveMarket, bracketPositions, microstructure, telemetry } =
        getCleanBaseModels()

      // Inject undefined across all solvency fields
      const degenerateSolvency = {
        total_equity_usdt: undefined,
        cash_usdt: undefined,
        allocated_margin_usdt: undefined,
        realized_pnl_usdt: undefined,
        cash_reserve_pct: undefined,
        drift_usdt: undefined,
        zero_balance_drift_verified: undefined,
        tolerance_ceiling_usdt: undefined,
        starting_equity_usdt: undefined,
        total_fees_usdt: undefined,
        total_slippage_usdt: undefined,
        solvency_ratio_pct: undefined,
      } as unknown as DoubleEntrySolvencyItem

      const degenerateProd: ProductionLaunchModel = {
        ...prodLaunch,
        solvency: degenerateSolvency,
        aggregateExposureUsdt: 0.0,
      }

      const adapted = buildExecutiveDashboardModel(
        degenerateProd,
        liveMarket,
        bracketPositions,
        microstructure,
        telemetry,
        new Date(),
      )

      expect(adapted).toBeDefined()
      // Baseline starting capital ($100.00)
      expect(adapted.kpis.totalEquityUsdt).toBe(100.0)
      expect(adapted.kpis.cashUsdt).toBe(100.0)
      expect(adapted.kpis.allocatedMarginUsdt).toBe(0.0)
      expect(adapted.kpis.realizedPnlUsdt).toBe(0.0)
      expect(adapted.kpis.cashReservePct).toBe(100.0)
      expect(adapted.kpis.balanceDriftUsdt).toBe(0.0)
      expect(adapted.kpis.isZeroDriftVerified).toBe(true)
      expect(adapted.kpis.activeExposureUsdt).toBe(0.0)
    })

    it('gracefully handles completely null solvency fields with clean fallback defaults', () => {
      const { prodLaunch, liveMarket, bracketPositions, microstructure, telemetry } =
        getCleanBaseModels()

      // Inject null across solvency fields
      const degenerateSolvency = {
        total_equity_usdt: null,
        cash_usdt: null,
        allocated_margin_usdt: null,
        realized_pnl_usdt: null,
        cash_reserve_pct: null,
        drift_usdt: null,
        zero_balance_drift_verified: null,
        tolerance_ceiling_usdt: null,
        starting_equity_usdt: null,
        total_fees_usdt: null,
        total_slippage_usdt: null,
        solvency_ratio_pct: null,
      } as unknown as DoubleEntrySolvencyItem

      const degenerateProd: ProductionLaunchModel = {
        ...prodLaunch,
        solvency: degenerateSolvency,
        aggregateExposureUsdt: 0.0,
      }

      const adapted = buildExecutiveDashboardModel(
        degenerateProd,
        liveMarket,
        bracketPositions,
        microstructure,
        telemetry,
        new Date(),
      )

      expect(adapted).toBeDefined()
      expect(adapted.kpis.totalEquityUsdt).toBe(100.0)
      expect(adapted.kpis.cashUsdt).toBe(100.0)
      expect(adapted.kpis.allocatedMarginUsdt).toBe(0.0)
      expect(adapted.kpis.realizedPnlUsdt).toBe(0.0)
      expect(adapted.kpis.cashReservePct).toBe(100.0)
      expect(adapted.kpis.balanceDriftUsdt).toBe(0.0)
      expect(adapted.kpis.isZeroDriftVerified).toBe(true)
      expect(adapted.kpis.activeExposureUsdt).toBe(0.0)
    })
  })

  describe('Dimension 2: Zero, Negative, and NaN Balances & Fallback Behavior', () => {
    it('falls back to $100.00 baseline equity when total_equity_usdt is 0.0, negative, or NaN', () => {
      const { prodLaunch, liveMarket, bracketPositions, microstructure, telemetry } =
        getCleanBaseModels()

      const testValues = [0.0, -100.0, -0.0001, Number.NaN]

      for (const val of testValues) {
        const mutatedProd: ProductionLaunchModel = {
          ...prodLaunch,
          solvency: {
            ...prodLaunch.solvency,
            total_equity_usdt: val,
            cash_usdt: val,
          },
        }

        const adapted = buildExecutiveDashboardModel(
          mutatedProd,
          liveMarket,
          bracketPositions,
          microstructure,
          telemetry,
          new Date(),
        )

        expect(adapted.kpis.totalEquityUsdt).toBe(100.0)
        expect(adapted.kpis.cashUsdt).toBe(100.0)
        expect(adapted.kpis.cashReservePct).toBe(100.0)
      }
    })
  })

  describe('Dimension 3: Empty Collections (candidateAllocations, positions, recentOrders)', () => {
    it('handles empty candidateAllocations, empty positions, and empty recentOrders with 0.00 exposure', () => {
      const { prodLaunch, liveMarket, microstructure, telemetry } = getCleanBaseModels()

      const emptyProdLaunch: ProductionLaunchModel = {
        ...prodLaunch,
        candidateAllocations: [],
        recentOrders: [],
        aggregateExposureUsdt: 0.0,
        totalTrades: 0,
      }
      const emptyBrackets = {
        ...buildBracketPositionsModel(null),
        positions: [],
      }

      const adapted = buildExecutiveDashboardModel(
        emptyProdLaunch,
        liveMarket,
        emptyBrackets,
        microstructure,
        telemetry,
        new Date(),
      )

      // KPIs
      expect(adapted.kpis.activeExposureUsdt).toBe(0.0)
      expect(adapted.kpis.totalTrades).toBe(0)
      expect(adapted.kpis.winRatePct).toBe(100.0)

      // Positions: all 3 staged pairs must be in SCANNING / STANDBY with 0.0 metrics
      expect(adapted.positions.length).toBe(3)
      for (const pos of adapted.positions) {
        expect(pos.state).toBe('SCANNING / STANDBY')
        expect(pos.size).toBe(0.0)
        expect(pos.notionalUsdt).toBe(0.0)
        expect(pos.marginUsdt).toBe(0.0)
        expect(pos.entryPrice).toBe(0.0)
        expect(pos.unrealizedPnlUsdt).toBe(0.0)
        expect(pos.unrealizedPnlPct).toBe(0.0)
        expect(pos.currentPrice).toBeGreaterThan(0)
        expect(pos.takeProfitPrice).toBeGreaterThan(pos.currentPrice)
        expect(pos.stopLossPrice).toBeLessThan(pos.currentPrice)
      }

      // Orders: authentic fallback orders must be populated and free of ord-p309- artifacts
      expect(adapted.orders.length).toBeGreaterThanOrEqual(3)
      expect(adapted.orders.every((o) => !o.orderId.startsWith('ord-p309-'))).toBe(true)
      expect(adapted.orders.some((o) => o.orderId.startsWith('canary-p311-'))).toBe(true)
      expect(adapted.orders.some((o) => o.orderId.startsWith('ord-p310-'))).toBe(true)
    })

    it('correctly defaults activeExposure to 0.00 when aggregateExposureUsdt is undefined and positions are flat', () => {
      const { prodLaunch, liveMarket, microstructure, telemetry } = getCleanBaseModels()

      const undefinedExposureProd = {
        ...prodLaunch,
        aggregateExposureUsdt: undefined as unknown as number,
        candidateAllocations: [],
      }
      const emptyBrackets = {
        ...buildBracketPositionsModel(null),
        positions: [],
      }

      const adapted = buildExecutiveDashboardModel(
        undefinedExposureProd as unknown as ProductionLaunchModel,
        liveMarket,
        emptyBrackets,
        microstructure,
        telemetry,
        new Date(),
      )

      // Must be 0.00, NOT the legacy stale fallback of 5.50
      expect(adapted.kpis.activeExposureUsdt).toBe(0.0)
    })
  })

  describe('Dimension 4: Missing & Malformed Timestamps', () => {
    it('handles null, undefined, and NaN Date objects in lastFetchedAt without crashing', () => {
      const { prodLaunch, liveMarket, bracketPositions, microstructure, telemetry } =
        getCleanBaseModels()

      // Null
      const adaptedNull = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        bracketPositions,
        microstructure,
        telemetry,
        null,
      )
      expect(adaptedNull.botStatus.lastSyncedAtMyt).not.toBe('—')
      expect(typeof adaptedNull.botStatus.lastSyncedAtMyt).toBe('string')

      // Invalid Date
      const adaptedInvalid = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        bracketPositions,
        microstructure,
        telemetry,
        new Date('invalid-date'),
      )
      expect(adaptedInvalid.botStatus.lastSyncedAtMyt).toBe('—')
    })

    it('handles missing, null, and NaN timestamp_ms in orders feed without crashing', () => {
      const { prodLaunch, liveMarket, bracketPositions, microstructure, telemetry } =
        getCleanBaseModels()

      const ordersLaunch: ProductionLaunchModel = {
        ...prodLaunch,
        recentOrders: [
          {
            order_id: 'ord-test-nan-ts',
            symbol: 'SOLUSDT',
            side: 'BUY',
            order_type: 'LIMIT',
            price: 180.0,
            quantity: 0.03,
            notional_usdt: 5.4,
            status: 'FILLED',
            fill_price: 180.0,
            fee_usdt: 0.001,
            realized_pnl_usdt: 0.0,
            timestamp_ms: Number.NaN,
          },
          {
            order_id: 'ord-test-null-ts',
            symbol: 'ETHUSDT',
            side: 'SELL',
            order_type: 'LIMIT',
            price: 2700.0,
            quantity: 0.002,
            notional_usdt: 5.4,
            status: 'FILLED',
            fill_price: 2700.0,
            fee_usdt: 0.001,
            realized_pnl_usdt: 0.05,
            timestamp_ms: null as unknown as number,
          },
          {
            order_id: 'ord-test-undef-ts',
            symbol: 'BTCUSDT',
            side: 'BUY',
            order_type: 'LIMIT',
            price: 85000.0,
            quantity: 0.00006,
            notional_usdt: 5.1,
            status: 'FILLED',
            fill_price: 85000.0,
            fee_usdt: 0.001,
            realized_pnl_usdt: 0.0,
            timestamp_ms: undefined as unknown as number,
          },
        ],
      }

      const adapted = buildExecutiveDashboardModel(
        ordersLaunch,
        liveMarket,
        bracketPositions,
        microstructure,
        telemetry,
        new Date(),
      )

      expect(adapted.orders.length).toBe(3)
      expect(adapted.orders[0].timestampMyt).toBe('—')
      expect(adapted.orders[2].timestampMyt).toBe('—')
    })
  })

  describe('Dimension 5: Malformed Mark Prices & Upstream Feeds', () => {
    it('safely falls back to symbol static defaults when markPrices contains garbage or negative strings', () => {
      const { prodLaunch, bracketPositions, microstructure, telemetry } = getCleanBaseModels()

      const corruptedLiveMarket = {
        ...buildLiveMarketModel(null),
        markPrices: {
          SOLUSDT: { mark_price: 'garbage_string' },
          ETHUSDT: { mark_price: '-500.0' },
          BTCUSDT: { mark_price: '' },
        },
      }

      const emptyAllocProd: ProductionLaunchModel = {
        ...prodLaunch,
        candidateAllocations: [],
      }

      const adapted = buildExecutiveDashboardModel(
        emptyAllocProd,
        corruptedLiveMarket as unknown as LiveMarketModel,
        bracketPositions,
        microstructure,
        telemetry,
        new Date(),
      )

      const sol = adapted.positions.find((p) => p.symbol === 'SOLUSDT')
      const eth = adapted.positions.find((p) => p.symbol === 'ETHUSDT')
      const btc = adapted.positions.find((p) => p.symbol === 'BTCUSDT')

      // Should fall back to static fallback prices
      expect(sol?.currentPrice).toBe(110.0)
      expect(eth?.currentPrice).toBe(2500.0)
      expect(btc?.currentPrice).toBe(82600.0)

      // Take profit and stop loss prices must be valid numbers
      expect(Number.isNaN(sol?.takeProfitPrice)).toBe(false)
      expect(Number.isNaN(eth?.takeProfitPrice)).toBe(false)
      expect(Number.isNaN(btc?.takeProfitPrice)).toBe(false)
    })
  })

  describe('Dimension 6: Confinement Field Fallbacks', () => {
    it('provides safe defaults ($25.00 exposure cap, 75.0% min reserve) when confinement fields are missing/zero', () => {
      const { prodLaunch, liveMarket, bracketPositions, microstructure, telemetry } =
        getCleanBaseModels()

      const degenerateConfinement = {
        max_aggregate_exposure_usdt: 0.0,
        min_cash_reserve_pct: 0.0,
      } as unknown as CanaryMicroCapitalConfinementItem

      const degenerateProd: ProductionLaunchModel = {
        ...prodLaunch,
        confinement: degenerateConfinement,
      }

      const adapted = buildExecutiveDashboardModel(
        degenerateProd,
        liveMarket,
        bracketPositions,
        microstructure,
        telemetry,
        new Date(),
      )

      expect(adapted.kpis.maxExposureCapUsdt).toBe(25.0)
      expect(adapted.kpis.minCashReserveFloorPct).toBe(75.0)
    })
  })

  describe('Dimension 7: Full Component Tree Rendering With Degenerate Input', () => {
    it('renders the complete ExecutiveDashboard view without uncaught errors or NaN artifacts', () => {
      const { prodLaunch, liveMarket, microstructure, telemetry } = getCleanBaseModels()

      const fullyDegenerateProd: ProductionLaunchModel = {
        ...prodLaunch,
        solvency: {
          total_equity_usdt: 0.0,
          cash_usdt: 0.0,
          allocated_margin_usdt: 0.0,
          realized_pnl_usdt: 0.0,
          cash_reserve_pct: 0.0,
          drift_usdt: 0.0,
          zero_balance_drift_verified: true,
          tolerance_ceiling_usdt: 1e-15,
          starting_equity_usdt: 0.0,
          total_fees_usdt: 0.0,
          total_slippage_usdt: 0.0,
          solvency_ratio_pct: 100.0,
        } as unknown as DoubleEntrySolvencyItem,
        candidateAllocations: [],
        recentOrders: [],
        aggregateExposureUsdt: 0.0,
        totalTrades: 0,
      }

      const adapted = buildExecutiveDashboardModel(
        fullyDegenerateProd,
        liveMarket,
        { ...buildBracketPositionsModel(null), positions: [] },
        microstructure,
        telemetry,
        null,
      )

      const html = renderToString(
        <ExecutiveDashboard model={adapted} onRefresh={() => {}} isLoading={false} />,
      )

      expect(html).toBeTruthy()
      expect(html).toContain('Autonomous Futures')
      expect(html).toContain('$100.00')
      expect(html).toContain('$0.00')
      expect(html).not.toContain('NaN')
    })
  })

  describe('Dimension 8: Randomized Property Fuzzing (50 Iterations)', () => {
    it('never throws across 50 pseudo-random degenerate variations', () => {
      const { prodLaunch, liveMarket, bracketPositions, microstructure, telemetry } =
        getCleanBaseModels()

      const possibleEquities = [0.0, -50.0, 100.0, 2500.0, Number.NaN, undefined, null]
      const possibleExposures = [0.0, 5.0, 25.0, -1.0, undefined, null]
      const possibleDates = [new Date(), null, undefined, new Date('invalid')]

      for (let i = 0; i < 50; i++) {
        const equityChoice = possibleEquities[i % possibleEquities.length]
        const exposureChoice = possibleExposures[i % possibleExposures.length]
        const dateChoice = possibleDates[i % possibleDates.length]

        const fuzzedProd: ProductionLaunchModel = {
          ...prodLaunch,
          solvency: {
            ...prodLaunch.solvency,
            total_equity_usdt: equityChoice as unknown as number,
            cash_usdt: equityChoice as unknown as number,
            realized_pnl_usdt: (i % 2 === 0 ? null : undefined) as unknown as number,
          },
          aggregateExposureUsdt: exposureChoice as unknown as number,
          candidateAllocations: i % 3 === 0 ? [] : prodLaunch.candidateAllocations,
          recentOrders: i % 2 === 0 ? [] : prodLaunch.recentOrders,
        }

        expect(() => {
          const adapted = buildExecutiveDashboardModel(
            fuzzedProd,
            liveMarket,
            bracketPositions,
            microstructure,
            telemetry,
            dateChoice as unknown as Date,
          )
          expect(adapted).toBeDefined()
          expect(adapted.kpis).toBeDefined()
          expect(adapted.positions.length).toBe(3)
        }).not.toThrow()
      }
    })
  })
})
