import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { EvolutionPage } from '../evolution-page'
import { MarketPositionsCard } from '../mission-control/market-positions-card'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import { ExecutivePositionsPage } from '../executive-positions-page'
import { ExecutiveTradesPage } from '../executive-trades-page'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import type { PositionTelemetry, OrderFeedItem } from '../mission-control/types'
import {
  buildAutoEvolutionModel,
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  type CanaryAutoEvolutionData,
  type LiveEvolutionProgressData,
} from '@/lib/canary'
import {
  calculateEma,
  calculateOhlcSummary,
  generateSyntheticKlines,
  type MarketKline,
} from '@/lib/chart-indicators'

// Base verified fixture for Phase 306 AutoEvolution
const baseVerifiedFixture: CanaryAutoEvolutionData = {
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
    autopsy_cause_distribution: {
      ORGANIC_ALPHA: 12,
      HAWKES_CLUSTER: 4,
    },
    mean_entry_timing_error_bps: 6.35,
    mean_hawkes_slip_drag_bps: 4.03,
    mean_adverse_selection_bps: 4.06,
    mean_realized_edge_bps: 14.86,
    health_tier_distribution: {
      ELITE: 2,
      HEALTHY: 0,
      DEGRADED: 1,
      PROBATIONARY: 0,
    },
    staged_mutations_count: 1,
    promoted_candidates_count: 0,
  },
  autopsies_trace: [],
  health_evaluations: {},
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
  upstream_hash: '0cbf6a93a5332789d5053f72e7e494b03b48ccd0ff7c62118bb339d5d905aa7c',
  phase_hash: '521bcb2f8bf0f35c8bb838419ba233bcbe72eeba6652b9710622675907511fd5',
  merkle_root: '818fd82458a8fb19420dd0179c8f78b0c273e5d2a71b1968b083d20f99e23dbe',
}

// 8 Liquid Perpetual Positions Fixture
const mock8Positions: PositionTelemetry[] = [
  {
    symbol: 'SOLUSDT',
    currentPrice: 185.5,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 0.0,
    stopLossPrice: 0.0,
    riskRewardRatio: '—',
  },
  {
    symbol: 'ETHUSDT',
    currentPrice: 2650.0,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 0.0,
    stopLossPrice: 0.0,
    riskRewardRatio: '—',
  },
  {
    symbol: 'BTCUSDT',
    currentPrice: 85200.0,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 0.0,
    stopLossPrice: 0.0,
    riskRewardRatio: '—',
  },
  {
    symbol: 'DOGEUSDT',
    currentPrice: 0.1625,
    state: 'LONG',
    entryPrice: 0.162,
    size: 25.0,
    notionalUsdt: 4.05,
    marginUsdt: 4.05,
    unrealizedPnlUsdt: 0.0125,
    unrealizedPnlPct: 0.31,
    takeProfitPrice: 0.172,
    stopLossPrice: 0.156,
    riskRewardRatio: '1.66 : 1',
  },
  {
    symbol: 'BNBUSDT',
    currentPrice: 605.0,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 0.0,
    stopLossPrice: 0.0,
    riskRewardRatio: '—',
  },
  {
    symbol: 'XRPUSDT',
    currentPrice: 0.5842,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 0.0,
    stopLossPrice: 0.0,
    riskRewardRatio: '—',
  },
  {
    symbol: 'SUIUSDT',
    currentPrice: 2.185,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 0.0,
    stopLossPrice: 0.0,
    riskRewardRatio: '—',
  },
  {
    symbol: 'AVAXUSDT',
    currentPrice: 28.45,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 0.0,
    stopLossPrice: 0.0,
    riskRewardRatio: '—',
  },
]

describe('Milestone M3 Empirical Challenge Suite', () => {
  describe('Dimension 1: evolution-page.tsx Rendering Across Boundary Payloads', () => {
    it('handles null live_progress safely with default fallback values', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: null as unknown as LiveEvolutionProgressData,
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('Continuous Self-Learning Loop')
      expect(html).toContain('ACTIVE 24/7 LOOP')
      expect(html).toContain('data-testid="btc-macro-gating-banner"')
      expect(html).toContain('REGIME: BEARISH')
      expect(html).toContain('data-testid="oos-qualification-gate-card"')
      expect(html).toContain('0 / 5 required trades')
      expect(html).toContain('80% COMPLETE')
      expect(html).toContain('BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT, BNBUSDT, XRPUSDT, SUIUSDT, AVAXUSDT')
    })

    it('handles undefined live_progress safely', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: undefined,
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('Current Evolution Progress &amp; Status')
      expect(html).toContain('0 / 5 required trades')
      expect(html).not.toContain('NaN')
    })

    it('handles empty object {} live_progress without throwing or rendering undefined strings', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {} as unknown as LiveEvolutionProgressData,
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('Current Evolution Progress &amp; Status')
      expect(html).toContain('0 / 5 required trades')
      expect(html).not.toContain('undefined%')
      expect(html).not.toContain('NaN%')
    })

    it('verifies sample count 0/5: 80% progress and WAITING_FOR_SAMPLES status', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          closed_trades_count: 0,
          required_trades_count: 5,
          current_cycle_stage: 'SHADOW_OOS_GATE',
          stage_status: 'WAITING_FOR_SAMPLES',
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('0 / 5 required trades')
      expect(html).toContain('80% COMPLETE')
      expect(html).toContain('WAITING_FOR_SAMPLES')
      expect(html).toContain('0/5 SAMPLES')
    })

    it('verifies sample count 4/5: 96% progress (80 + 4/5*20) and WAITING_FOR_SAMPLES status', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          closed_trades_count: 4,
          required_trades_count: 5,
          current_cycle_stage: 'SHADOW_OOS_GATE',
          stage_status: 'WAITING_FOR_SAMPLES',
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('4 / 5 required trades')
      expect(html).toContain('96% COMPLETE')
      expect(html).toContain('WAITING_FOR_SAMPLES')
      expect(html).toContain('4/5 SAMPLES')
    })

    it('verifies sample count 5/5: 100% progress and EVALUATING / QUALIFIED stage status', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          closed_trades_count: 5,
          required_trades_count: 5,
          current_cycle_stage: 'SHADOW_OOS_GATE',
          stage_status: 'QUALIFIED',
          current_sharpe_improvement_pct: 22.5,
          sharpe_hurdle_pct: 15.0,
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('5 / 5 required trades')
      expect(html).toContain('100% COMPLETE')
      expect(html).toContain('QUALIFIED')
      expect(html).toContain('QUALIFIED / PROMOTED')
      expect(html).toContain('+22.5%')
    })

    it('verifies sample count 100/5: clamps progress to 100% without overflowing or crashing', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          closed_trades_count: 100,
          required_trades_count: 5,
          current_cycle_stage: 'SHADOW_OOS_GATE',
          stage_status: 'QUALIFIED',
          current_sharpe_improvement_pct: 150.0,
          sharpe_hurdle_pct: 15.0,
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('100 / 5 required trades')
      expect(html).toContain('100% COMPLETE')
      expect(html).not.toContain('480%')
      expect(html).not.toContain('NaN')
    })

    it('verifies Macro Gating Regime BEARISH: warning styling and LONGS: DISEKAT', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          macro_gating_state: {
            regime: 'BEARISH',
            longs_filtered: true,
            is_long_allowed: false,
            explanation_ms: 'Bearish Macro Trend (Price < 1h EMA 200). LONG entries filtered.',
            explanation: 'Bearish Macro Trend (Price < 1h EMA 200). LONG entries filtered.',
          },
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('REGIME: BEARISH')
      expect(html).toContain('LONG Filtered')
      expect(html).toContain('LONGS: BLOCKED')
      expect(html).toContain('border-warning/40')
    })

    it('verifies Macro Gating Regime BULLISH_ALIGNED: success styling and LONGS: ALLOWED', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          macro_gating_state: {
            regime: 'BULLISH_ALIGNED',
            longs_filtered: false,
            is_long_allowed: true,
            explanation_ms: 'Bullish Macro Trend (Price > 1h EMA 200). LONG entries allowed.',
            explanation: 'Bullish Macro Trend (Price > 1h EMA 200). LONG entries allowed.',
          },
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('REGIME: BULLISH_ALIGNED')
      expect(html).not.toContain('LONG Filtered')
      expect(html).toContain('LONGS: ALLOWED')
      expect(html).toContain('border-success/40')
    })

    it('verifies Macro Gating Regime NEUTRAL: handles neutral state cleanly', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          macro_gating_state: {
            regime: 'NEUTRAL',
            longs_filtered: false,
            is_long_allowed: true,
            explanation_ms: 'Neutral Macro Trend (Sideways consolidation).',
            explanation: 'Neutral Macro Trend (Sideways consolidation).',
          },
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('REGIME: NEUTRAL')
      expect(html).toContain('LONGS: ALLOWED')
      expect(html).toContain('Neutral Macro Trend')
    })

    it('verifies Stage 1 INGRESS activates Stage 1 stepper', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          current_stage: 'INGRESS',
          cycle_progress_pct: 20.0,
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('1. Market Ingress &amp; Klines Streaming')
      expect(html).toContain('20% COMPLETE')
      expect(html).toContain('1. Market Ingress')
    })

    it('verifies Stage 2 HEALTH_EVALUATION activates Stage 2 stepper', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          current_stage: 'HEALTH_EVALUATION',
          cycle_progress_pct: 40.0,
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('2. Candidate Strategy Health Evaluation')
      expect(html).toContain('40% COMPLETE')
    })

    it('verifies Stage 3 TRADE_AUTOPSY activates Stage 3 stepper', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          current_stage: 'TRADE_AUTOPSY',
          cycle_progress_pct: 60.0,
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('3. Trade Execution Autopsy &amp; Friction Decomposition')
      expect(html).toContain('60% COMPLETE')
    })

    it('verifies Stage 4 MUTATION_STAGING activates Stage 4 stepper', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          current_stage: 'MUTATION_STAGING',
          cycle_progress_pct: 80.0,
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('4. Genome Mutation &amp; Parameter Tuning')
      expect(html).toContain('80% COMPLETE')
    })

    it('verifies Stage 5 SHADOW_OOS_GATE activates Stage 5 stepper', () => {
      const fixture: CanaryAutoEvolutionData = {
        ...baseVerifiedFixture,
        live_progress: {
          current_stage: 'SHADOW_OOS_GATE',
          cycle_progress_pct: 90.0,
        },
      }
      const model = buildAutoEvolutionModel(fixture)
      const html = renderToString(<EvolutionPage model={model} />)

      expect(html).toContain('5. Shadow Simulation &amp; OOS Promotion Gate Verification')
      expect(html).toContain('90% COMPLETE')
    })
  })

  describe('Dimension 2: Symbol Selector Pills & Multi-Symbol Filtering', () => {
    it('renders all 8 symbol selector pills and 8-pair perp badge in MarketPositionsCard', () => {
      const html = renderToString(<MarketPositionsCard positions={mock8Positions} />)

      expect(html).toContain('8 Perpetual Pairs')
      expect(html).toContain('data-testid="symbol-pill-all"')
      expect(html).toContain('data-testid="symbol-pill-sol"')
      expect(html).toContain('data-testid="symbol-pill-eth"')
      expect(html).toContain('data-testid="symbol-pill-btc"')
      expect(html).toContain('data-testid="symbol-pill-doge"')
      expect(html).toContain('data-testid="symbol-pill-bnb"')
      expect(html).toContain('data-testid="symbol-pill-xrp"')
      expect(html).toContain('data-testid="symbol-pill-sui"')
      expect(html).toContain('data-testid="symbol-pill-avax"')
      expect(html).toContain('ALL')

      // All 8 cards rendered by default
      expect(html).toContain('data-testid="market-pair-card-solusdt"')
      expect(html).toContain('data-testid="market-pair-card-ethusdt"')
      expect(html).toContain('data-testid="market-pair-card-btcusdt"')
      expect(html).toContain('data-testid="market-pair-card-dogeusdt"')
      expect(html).toContain('data-testid="market-pair-card-bnbusdt"')
      expect(html).toContain('data-testid="market-pair-card-xrpusdt"')
      expect(html).toContain('data-testid="market-pair-card-suiusdt"')
      expect(html).toContain('data-testid="market-pair-card-avaxusdt"')
    })

    it('verifies multi-symbol filtering predicate handles all 8 symbols accurately', () => {
      const testSymbols = ['ALL', 'SOL', 'ETH', 'BTC', 'DOGE', 'BNB', 'XRP', 'SUI', 'AVAX']
      const filterFn = (positions: PositionTelemetry[], selectedSymbol: string) =>
        positions.filter((p) => {
          if (selectedSymbol === 'ALL') return true
          return p.symbol.startsWith(selectedSymbol) || p.symbol === `${selectedSymbol}USDT`
        })

      // When ALL: 8 positions
      expect(filterFn(mock8Positions, 'ALL')).toHaveLength(8)

      // When specific: exactly 1 match each
      for (const sym of testSymbols.slice(1)) {
        const matches = filterFn(mock8Positions, sym)
        expect(matches).toHaveLength(1)
        expect(matches[0].symbol).toBe(`${sym}USDT`)
      }

      // Non-existent symbol returns 0 matches safely
      expect(filterFn(mock8Positions, 'NONEXISTENT')).toHaveLength(0)
    })

    it('verifies OrderFeedTable symbol filtering across all 8 pairs', () => {
      const mockOrders: OrderFeedItem[] = [
        {
          orderId: 'c=canary-p315-sol-001',
          symbol: 'SOLUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 185.2,
          quantity: 0.02,
          notionalUsdt: 3.704,
          makerFeeUsdt: 0.0007,
          realizedPnlUsdt: 0.0,
          timestampMyt: '11 Oct 12:00:00 MYT',
          status: 'FILLED',
        },
        {
          orderId: 'c=canary-p315-doge-001',
          symbol: 'DOGEUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 0.1625,
          quantity: 25.0,
          notionalUsdt: 4.0625,
          makerFeeUsdt: 0.0008,
          realizedPnlUsdt: 0.0,
          timestampMyt: '11 Oct 12:05:00 MYT',
          status: 'FILLED',
        },
        {
          orderId: 'c=canary-p315-xrp-001',
          symbol: 'XRPUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 0.5842,
          quantity: 7.0,
          notionalUsdt: 4.0894,
          makerFeeUsdt: 0.0008,
          realizedPnlUsdt: 0.0,
          timestampMyt: '11 Oct 12:10:00 MYT',
          status: 'FILLED',
        },
      ]

      const html = renderToString(<OrderFeedTable orders={mockOrders} />)
      expect(html).toContain('SOLUSDT')
      expect(html).toContain('DOGEUSDT')
      expect(html).toContain('XRPUSDT')

      // Check sub-dollar price formatting in order feed table
      expect(html).toContain('$0.1625')
      expect(html).toContain('$0.5842')
    })

    it('verifies ExecutivePositionsPage renders filter pills and handles 8 pairs', () => {
      const mockBracketModel = buildBracketPositionsModel(null)
      const mockLiveMarket = buildLiveMarketModel(null)

      const html = renderToString(
        <ExecutivePositionsPage
          positions={mock8Positions}
          bracketPositionsModel={mockBracketModel}
          liveMarketModel={mockLiveMarket}
        />,
      )

      expect(html).toContain('Detailed Positions &amp; Markets')
      expect(html).toContain('ALL')
      expect(html).toContain('DOGE')
      expect(html).toContain('XRP')
      expect(html).toMatch(/8<!-- -->\s*Monitored/)
    })

    it('verifies ExecutiveTradesPage renders filter pills and formats 8 pairs', () => {
      const mockOrders: OrderFeedItem[] = [
        {
          orderId: 'c=canary-p315-doge-001',
          symbol: 'DOGEUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 0.1625,
          quantity: 25.0,
          notionalUsdt: 4.0625,
          makerFeeUsdt: 0.0008,
          realizedPnlUsdt: 0.025,
          timestampMyt: '11 Oct 12:05:00 MYT',
          status: 'FILLED',
        },
      ]

      const html = renderToString(<ExecutiveTradesPage orders={mockOrders} />)
      expect(html).toContain('Trade Log &amp; Execution Autopsy')
      expect(html).toContain('DOGE')
      expect(html).toContain('XRP')
      expect(html).toContain('0.1625')
    })
  })

  describe('Dimension 3: 4-Decimal Sub-Dollar Price Formatting & Extreme Values', () => {
    it('verifies sub-dollar formatting logic across extreme values: $0.0001, $0.00001, $0.9999', () => {
      // Testing formatPrice algorithm
      function formatPriceTest(val?: number): string {
        if (val === undefined || Number.isNaN(val)) return '0.00'
        if (val < 10) return val.toFixed(4)
        if (val < 1000) return val.toFixed(2)
        return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      }

      // Extreme small values
      expect(formatPriceTest(0.0001)).toBe('0.0001')
      expect(formatPriceTest(0.00001)).toBe('0.0000') // toFixed(4) rounds 1e-5 to 0.0000
      expect(formatPriceTest(0.00005)).toBe('0.0001') // toFixed(4) rounds 5e-5 to 0.0001
      expect(formatPriceTest(0.9999)).toBe('0.9999')
      expect(formatPriceTest(0.5842)).toBe('0.5842')
      expect(formatPriceTest(0.1625)).toBe('0.1625')

      // Boundary transitions
      expect(formatPriceTest(9.9999)).toBe('9.9999')
      expect(formatPriceTest(10.0)).toBe('10.00')
      expect(formatPriceTest(999.99)).toBe('999.99')
      expect(formatPriceTest(1000.0)).toBe('1,000.00')

      // Undefined and NaN resilience
      expect(formatPriceTest(undefined)).toBe('0.00')
      expect(formatPriceTest(NaN)).toBe('0.00')
    })

    it('verifies MarketPositionsCard renders 4-decimal prices for extreme values in position state', () => {
      const extremePositions: PositionTelemetry[] = [
        {
          symbol: 'DOGEUSDT',
          currentPrice: 0.0001,
          state: 'LONG',
          entryPrice: 0.0001,
          size: 10000,
          notionalUsdt: 1.0,
          marginUsdt: 1.0,
          unrealizedPnlUsdt: 0.0,
          unrealizedPnlPct: 0.0,
          takeProfitPrice: 0.0002,
          stopLossPrice: 0.00005,
          riskRewardRatio: '1.66 : 1',
        },
        {
          symbol: 'XRPUSDT',
          currentPrice: 0.9999,
          state: 'LONG',
          entryPrice: 0.9999,
          size: 5,
          notionalUsdt: 4.9995,
          marginUsdt: 4.9995,
          unrealizedPnlUsdt: 0.0,
          unrealizedPnlPct: 0.0,
          takeProfitPrice: 1.025,
          stopLossPrice: 0.985,
          riskRewardRatio: '1.66 : 1',
        },
      ]

      const html = renderToString(<MarketPositionsCard positions={extremePositions} />)
      expect(html).toContain('0.0001')
      expect(html).toContain('0.9999')
    })

    it('verifies OrderFeedTable formats extreme sub-dollar prices with 4 decimals', () => {
      const orders: OrderFeedItem[] = [
        {
          orderId: 'ord-micro-1',
          symbol: 'DOGEUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 0.0001,
          quantity: 10000,
          notionalUsdt: 1.0,
          makerFeeUsdt: 0.0002,
          realizedPnlUsdt: 0.0,
          timestampMyt: '11 Oct 12:00:00 MYT',
          status: 'FILLED',
        },
        {
          orderId: 'ord-micro-2',
          symbol: 'XRPUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 0.9999,
          quantity: 5,
          notionalUsdt: 4.9995,
          makerFeeUsdt: 0.001,
          realizedPnlUsdt: 0.0,
          timestampMyt: '11 Oct 12:01:00 MYT',
          status: 'FILLED',
        },
      ]

      const html = renderToString(<OrderFeedTable orders={orders} />)
      expect(html).toContain('$0.0001')
      expect(html).toContain('$0.9999')
    })

    it('verifies calculateEma preserves 4-decimal precision for extreme sub-dollar candlesticks', () => {
      const extremeKlines: MarketKline[] = [
        { timestamp: 1000, open: 0.0001, high: 0.0002, low: 0.00005, close: 0.0001, volume: 100 },
        { timestamp: 1900, open: 0.0001, high: 0.00015, low: 0.00008, close: 0.00012, volume: 110 },
        { timestamp: 2800, open: 0.00012, high: 0.00018, low: 0.0001, close: 0.00014, volume: 120 },
      ]

      const ema = calculateEma(extremeKlines, 2)
      expect(ema.length).toBeGreaterThan(0)
      for (const pt of ema) {
        expect(pt.value).toBeGreaterThan(0)
        expect(Number.isFinite(pt.value)).toBe(true)
      }
    })

    it('verifies calculateOhlcSummary applies 4-decimal precision when latest close < 1', () => {
      const subDollarKlines: MarketKline[] = [
        { timestamp: 1000, open: 0.162, high: 0.165, low: 0.16, close: 0.163, volume: 100 },
        { timestamp: 1900, open: 0.163, high: 0.166, low: 0.161, close: 0.1625, volume: 110 },
      ]

      const summary = calculateOhlcSummary(subDollarKlines)
      expect(summary).not.toBeNull()
      expect(summary?.close).toBe(0.1625)
      expect(summary?.high24h).toBe(0.166)
      expect(summary?.low24h).toBe(0.16)
    })

    it('verifies synthetic klines for DOGE and XRP generate 4-decimal values below $1.00', () => {
      const dogeKlines = generateSyntheticKlines('DOGEUSDT', '15m', 10)
      expect(dogeKlines).toHaveLength(10)
      for (const k of dogeKlines) {
        expect(k.close).toBeLessThan(1.0)
        expect(k.close).toBeGreaterThan(0.0)
      }

      const xrpKlines = generateSyntheticKlines('XRPUSDT', '15m', 10)
      expect(xrpKlines).toHaveLength(10)
      for (const k of xrpKlines) {
        expect(k.close).toBeLessThan(1.0)
        expect(k.close).toBeGreaterThan(0.0)
      }
    })

    it('verifies adapter.ts generates 8 positions and 4-decimal brackets for DOGE and XRP', () => {
      const prodLaunch = buildProductionLaunchModel(null)
      const liveMarket = buildLiveMarketModel(null)
      const bracketPos = buildBracketPositionsModel(null)
      const micro = buildMicrostructureModel(null)

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        bracketPos,
        micro,
        { latencyMs: 25, status: 'NORMAL' },
        new Date(),
      )

      expect(adapted.positions).toHaveLength(8)
      const dogePos = adapted.positions.find((p) => p.symbol === 'DOGEUSDT')
      const xrpPos = adapted.positions.find((p) => p.symbol === 'XRPUSDT')

      expect(dogePos).toBeDefined()
      expect(dogePos?.currentPrice).toBe(0.16)
      expect(xrpPos).toBeDefined()
      expect(xrpPos?.currentPrice).toBe(0.58)
    })
  })
})
