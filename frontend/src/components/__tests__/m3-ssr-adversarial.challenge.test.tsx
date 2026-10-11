import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { StrategyConfluenceRadar } from '../mission-control/strategy-confluence-radar'
import { StrategyEvolutionRadar } from '../mission-control/strategy-evolution-radar'
import { EvolutionPage } from '../evolution-page'
import { ExecutivePositionsPage } from '../executive-positions-page'
import { ExecutiveTradesPage } from '../executive-trades-page'
import { ExecutiveSafetyPage } from '../executive-safety-page'

import type {
  BtcMacroTrend,
  HawkesHazard,
  ScalperCriteria,
  StrategyEvolutionRadarData,
  PositionTelemetry,
  OrderFeedItem,
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
  type AutoEvolutionModel,
} from '@/lib/canary'

const BANNED_MALAY_ROOTS = [
  'fasa', 'konfluens', 'skalper', 'penapis', 'makro', 'lepasserang',
  'isipadu', 'lonjakan', 'terlebih', 'jual', 'yuran', 'pembuat',
  'kurungan', 'sasaran', 'bahaya', 'jejari', 'spektrum', 'selamat',
  'toksik', 'amaran', 'kritikal', 'kelulusan', 'ditahan', 'autorisasi',
  'belian', 'pembelajaran', 'pintu', 'kelayakan', 'lulus', 'purata',
  'pulangan', 'keuntungan', 'bilangan', 'dagangan', 'ketahanan',
  'kemalangan', 'kilat', 'ralat', 'pemasaan', 'pemilihan', 'merugikan',
  'kelebihan', 'bersih', 'posisi', 'terperinci', 'pasaran', 'terbuka',
  'dipantau', 'nisbah', 'pesanan', 'diisi', 'kawalan', 'integriti',
  'lejar', 'sifar', 'semakan', 'berterusan', 'lantai', 'rizab',
  'hadkan', 'sekat', 'dibenarkan', 'ditapis', 'kitaran', 'semasa',
  'lilin', 'imbasan', 'sampel', 'selesai', 'layak', 'utama', 'semua',
]

function cleanSsrText(html: string): string {
  return html.replace(/<!-- -->/g, '')
}

function assertZeroMalay(html: string, context: string) {
  for (const root of BANNED_MALAY_ROOTS) {
    const regex = new RegExp(`\\b${root}\\b`, 'i')
    expect(
      regex.test(html),
      `Residual Malay root "${root}" detected in SSR output for ${context}: ${html.slice(0, 300)}...`,
    ).toBe(false)
  }
}

describe('Adversarial SSR Stress Tests — Milestone M3 Components', () => {
  describe('1. StrategyConfluenceRadar SSR Adversarial Resilience', () => {
    it('handles extreme supercritical Hawkes spectral radius (ρ > 1.00 and ρ = 999.0)', () => {
      const btcTrend: BtcMacroTrend = {
        regime: 'BULLISH ALIGNED',
        ema50_1h: 94000.0,
        ema200_1h: 91000.0,
        ema50_4h: 93000.0,
        ema200_4h: 90000.0,
        explanation: 'Bitcoin 1h & 4h macro trend bullish.',
      }
      const scalper: ScalperCriteria = {
        priceBelowEma20Atr: 2.8,
        priceBelowEmaThreshold: 2.5,
        priceTriggered: true,
        relativeVolume: 2.5,
        volumeThreshold: 2.2,
        volumeTriggered: true,
        rsi14: 22.0,
        rsiThreshold: 26.0,
        rsiTriggered: true,
        makerFeePct: 0.02,
      }
      const extremeHawkes: HawkesHazard = {
        spectralRadius: 1.85,
        isNonToxic: false,
        thresholdWarning: 0.85,
        thresholdCritical: 1.0,
        recentHistory: [0.8, 0.95, 1.2, 1.5, 1.85],
      }

      const html = renderToString(
        <StrategyConfluenceRadar
          btcMacroTrend={btcTrend}
          scalperCriteria={scalper}
          hawkesHazard={extremeHawkes}
        />,
      )

      const text = cleanSsrText(html)
      expect(text).toContain('⚠️ APPROVAL WITHHELD')
      expect(text).toContain('TOXIC HAZARD')
      expect(text).toContain('ρ = 1.8500')
      expect(text).toContain('Warning: ρ ≥ 0.85')
      expect(text).toContain('Critical: ρ ≥ 1.00')
      assertZeroMalay(html, 'StrategyConfluenceRadar with ρ > 1.00')
    })

    it('handles empty, single-element, and flat Hawkes history without NaN or division by zero', () => {
      const btcTrend: BtcMacroTrend = {
        regime: 'BEARISH',
        ema50_1h: 88000.0,
        ema200_1h: 92000.0,
        ema50_4h: 87000.0,
        ema200_4h: 91000.0,
        explanation: 'Bearish regime.',
      }
      const scalper: ScalperCriteria = {
        priceBelowEma20Atr: 0.0,
        priceBelowEmaThreshold: 2.5,
        priceTriggered: false,
        relativeVolume: 0.0,
        volumeThreshold: 2.2,
        volumeTriggered: false,
        rsi14: 50.0,
        rsiThreshold: 26.0,
        rsiTriggered: false,
        makerFeePct: 0.02,
      }

      // Empty history array (should use default fallback)
      const hawkesEmpty: HawkesHazard = {
        spectralRadius: 0.4286,
        isNonToxic: true,
        thresholdWarning: 0.85,
        thresholdCritical: 1.0,
        recentHistory: [],
      }
      const htmlEmpty = renderToString(
        <StrategyConfluenceRadar
          btcMacroTrend={btcTrend}
          scalperCriteria={scalper}
          hawkesHazard={hawkesEmpty}
        />,
      )
      expect(htmlEmpty).not.toContain('NaN')
      expect(htmlEmpty).toContain('points=')

      // Single-element history array
      const hawkesSingle: HawkesHazard = {
        ...hawkesEmpty,
        recentHistory: [0.4286],
      }
      const htmlSingle = renderToString(
        <StrategyConfluenceRadar
          btcMacroTrend={btcTrend}
          scalperCriteria={scalper}
          hawkesHazard={hawkesSingle}
        />,
      )
      expect(htmlSingle).not.toContain('NaN')

      // Flat identical values (maxVal === minVal)
      const hawkesFlat: HawkesHazard = {
        ...hawkesEmpty,
        recentHistory: [0.5, 0.5, 0.5],
      }
      const htmlFlat = renderToString(
        <StrategyConfluenceRadar
          btcMacroTrend={btcTrend}
          scalperCriteria={scalper}
          hawkesHazard={hawkesFlat}
        />,
      )
      expect(htmlFlat).not.toContain('NaN')
      assertZeroMalay(htmlFlat, 'StrategyConfluenceRadar flat history')
    })
  })

  describe('2. StrategyEvolutionRadar SSR Adversarial Resilience', () => {
    it('handles empty OOS qualification gates array and empty attribution gauges', () => {
      const emptyData: StrategyEvolutionRadarData = {
        activeStrategyFamily: 'Liquidity Dip Mean-Reversion',
        microstructureFilter: 'Hawkes Self-Excitation',
        activeCandidateId: 'cand-sol-001',
        candidateHealthTier: 'DEGRADED',
        generation: 'GEN #1',
        rollingSharpe: -1.25,
        winRatePct: 0.0,
        maxDrawdownPct: 100.0,
        hawkesResilienceScore: 0.0,
        gates: [],
        allGatesPassed: false,
        attributionGauges: [],
        totalAutopsies: 0,
        promotedCandidatesCount: 0,
      }

      const html = renderToString(<StrategyEvolutionRadar evolutionRadar={emptyData} />)
      const text = cleanSsrText(html)

      expect(text).toContain('0 / 0 GATES PASSED')
      expect(text).toContain('0 Autopsies')
      expect(text).toContain('0 Active Promoted Candidates')
      expect(text).toContain('DEGRADED')
      expect(text).toContain('-1.25')
      expect(text).toContain('0.0%')
      assertZeroMalay(html, 'StrategyEvolutionRadar empty gates/gauges')
    })

    it('handles extreme negative and positive attribution gauge bps values with capping', () => {
      const data: StrategyEvolutionRadarData = {
        activeStrategyFamily: 'Liquidity Dip Mean-Reversion',
        microstructureFilter: 'Hawkes Self-Excitation',
        activeCandidateId: 'cand-sol-001',
        candidateHealthTier: 'ELITE',
        generation: 'GEN #2',
        rollingSharpe: 2.85,
        winRatePct: 85.0,
        maxDrawdownPct: 4.5,
        hawkesResilienceScore: 0.95,
        gates: [
          {
            id: 'gate-1',
            name: 'Double-Entry Solvency Audit',
            thresholdLabel: '|Δ| < 10^-15 USDT',
            actualValueLabel: '|Δ| = 0.00 USDT',
            passed: true,
          },
        ],
        allGatesPassed: true,
        attributionGauges: [
          {
            id: 'g-1',
            label: 'Extreme Timing Delay',
            bps: -125.4,
            thresholdBps: 15.0,
            isOptimal: false,
            description: 'Severe execution lag beyond boundary.',
          },
          {
            id: 'g-2',
            label: 'Massive Net Edge',
            bps: 540.8,
            thresholdBps: 20.0,
            isOptimal: true,
            description: 'Outlier alpha surge.',
          },
        ],
        totalAutopsies: 42,
        promotedCandidatesCount: 3,
      }

      const html = renderToString(<StrategyEvolutionRadar evolutionRadar={data} />)
      const text = cleanSsrText(html)

      expect(text).toContain('-125.4 bps')
      expect(text).toContain('+540.8 bps')
      expect(text).toContain('width:100%')
      expect(text).toContain('1 / 1 GATES PASSED')
      assertZeroMalay(html, 'StrategyEvolutionRadar extreme bps')
    })
  })

  describe('3. EvolutionPage SSR Adversarial Resilience', () => {
    it('renders clean fallback state when unverified or UNAVAILABLE', () => {
      const unverifiedModel: AutoEvolutionModel = {
        ...buildAutoEvolutionModel(null),
        verified: false,
        status: 'UNAVAILABLE',
      }

      const html = renderToString(<EvolutionPage model={unverifiedModel} />)
      const text = cleanSsrText(html)

      expect(text).toContain('PHASE 306 · UNAVAILABLE')
      expect(text).toContain('No verified Phase 306 artifact is available.')
      assertZeroMalay(html, 'EvolutionPage unavailable fallback')
    })

    it('handles zero sample OOS gates (0/5 trades) and negative Sharpe improvement', () => {
      const base = buildAutoEvolutionModel(null)
      const zeroSampleModel: AutoEvolutionModel = {
        ...base,
        verified: true,
        status: 'SIMULATION_ARTIFACT_VERIFIED',
        liveProgress: {
          is_live_daemon_active: true,
          current_cycle_stage: 'SHADOW_OOS_GATE',
          cycle_progress_pct: 80.0,
          stage_status: 'WAITING_FOR_SAMPLES',
          stage_status_label: 'WAITING_FOR_SAMPLES (0/5)',
          closed_trades_count: 0,
          required_trades_count: 5,
          sharpe_hurdle_pct: 15.0,
          current_sharpe_improvement_pct: -8.5,
          active_generation: 'GEN #2',
          next_target_generation: 'GEN #3',
          last_evaluated_timestamp_ms: 1710000000000,
          last_candle_fetch_timestamp_ms: 1710000000000,
          next_cycle_seconds: 15,
          heartbeat_latency_ms: 38.0,
          daemon_status: 'ONLINE 24/7',
          daemon_pid: 87549,
          scanned_symbols: ['BTCUSDT', 'ETHUSDT'],
          oos_gate: {
            samples_required: 5,
            samples_acquired: 0,
            sharpe_hurdle_pct: 15.0,
            current_sharpe_improvement_pct: -8.5,
            status: 'WAITING_FOR_SAMPLES',
            status_label: 'WAITING_FOR_SAMPLES (0/5)',
            explanation:
              'Waiting for 5 completed trade samples to evaluate out-of-sample Sharpe (current: 0/5, hurdle >= 15.0%).',
          },
          macro_gating_state: {
            regime: 'BEARISH',
            longs_filtered: true,
            is_long_allowed: false,
            explanation_ms: 'Active BTC Macro Trend Filter.',
            explanation: 'Long entries temporarily paused by BTC 1h/4h Bearish regime filter for capital protection (EMA 50 < EMA 200).',
          },
          recent_events: [],
        },
      }

      const html = renderToString(<EvolutionPage model={zeroSampleModel} />)
      const text = cleanSsrText(html)

      expect(text).toContain('0 / 5 required trades')
      expect(text).toContain('Sharpe hurdle &gt;= 15.0%')
      expect(text).toContain('LONGS: BLOCKED')
      expect(text).toContain('BEARISH')
      expect(text).toContain('80% COMPLETE')
      assertZeroMalay(html, 'EvolutionPage zero sample OOS gate')
    })

    it('handles degenerate required trades (0 required) without crashing or NaN', () => {
      const base = buildAutoEvolutionModel(null)
      const degenerateModel: AutoEvolutionModel = {
        ...base,
        verified: true,
        status: 'SIMULATION_ARTIFACT_VERIFIED',
        liveProgress: {
          is_live_daemon_active: true,
          current_cycle_stage: 'SHADOW_OOS_GATE',
          closed_trades_count: 0,
          required_trades_count: 0,
          sharpe_hurdle_pct: 15.0,
          current_sharpe_improvement_pct: 0.0,
          oos_gate: {
            samples_required: 0,
            samples_acquired: 0,
            sharpe_hurdle_pct: 15.0,
            current_sharpe_improvement_pct: 0.0,
            status: 'WAITING_FOR_SAMPLES',
            explanation: 'Zero required trade test.',
          },
          macro_gating_state: {
            regime: 'SIDEWAYS',
            longs_filtered: false,
            is_long_allowed: true,
            explanation_ms: 'Sideways regime.',
            explanation: 'Sideways regime.',
          },
          recent_events: [],
        },
      }

      const html = renderToString(<EvolutionPage model={degenerateModel} />)

      expect(html).toBeDefined()
      assertZeroMalay(html, 'EvolutionPage 0 required trades')
    })
  })

  describe('4. ExecutivePositionsPage SSR Adversarial Resilience', () => {
    it('handles empty positions array and empty brackets table', () => {
      const liveMarket = buildLiveMarketModel(null)
      const bracketModel = buildBracketPositionsModel(null)
      bracketModel.brackets = []

      const html = renderToString(
        <ExecutivePositionsPage
          positions={[]}
          bracketPositionsModel={bracketModel}
          liveMarketModel={liveMarket}
        />,
      )
      const text = cleanSsrText(html)

      expect(text).toContain('0 Open / 0 Monitored')
      expect(text).toContain('No active brackets currently.')
      assertZeroMalay(html, 'ExecutivePositionsPage empty state')
    })

    it('handles extreme negative unrealized PnL and sub-dollar prices without double minus', () => {
      const liveMarket = buildLiveMarketModel(null)
      const bracketModel = buildBracketPositionsModel(null)

      const positions: PositionTelemetry[] = [
        {
          symbol: 'DOGEUSDT',
          currentPrice: 0.0825,
          state: 'LONG',
          entryPrice: 0.095,
          size: 50.0,
          notionalUsdt: 4.125,
          marginUsdt: 4.125,
          unrealizedPnlUsdt: -0.625,
          unrealizedPnlPct: -15.15,
          takeProfitPrice: 0.105,
          stopLossPrice: 0.088,
          riskRewardRatio: '1.66:1',
        },
        {
          symbol: 'SOLUSDT',
          currentPrice: 150.0,
          state: 'LONG',
          entryPrice: 180.0,
          size: 0.025,
          notionalUsdt: 3.75,
          marginUsdt: 3.75,
          unrealizedPnlUsdt: -0.75,
          unrealizedPnlPct: -16.67,
          takeProfitPrice: 195.0,
          stopLossPrice: 172.0,
          riskRewardRatio: '1.66:1',
        },
      ]

      const html = renderToString(
        <ExecutivePositionsPage
          positions={positions}
          bracketPositionsModel={bracketModel}
          liveMarketModel={liveMarket}
        />,
      )
      const text = cleanSsrText(html)

      expect(text).toContain('$0.0825')
      expect(text).toContain('$-0.625')
      expect(text).not.toContain('--')
      expect(text).toContain('$-0.750')
      assertZeroMalay(html, 'ExecutivePositionsPage negative PnL')
    })
  })

  describe('5. ExecutiveTradesPage SSR Adversarial Resilience', () => {
    it('handles empty orders feed with clean zero defaults', () => {
      const html = renderToString(<ExecutiveTradesPage orders={[]} />)
      const text = cleanSsrText(html)

      expect(text).toContain('0 Orders Filled')
      expect(text).toContain('+0.0000 USDT')
      expect(text).toContain('$0.0000 USDT')
      expect(text).toContain('0.0%')
      expect(text).toContain('Exact limit execution')
      assertZeroMalay(html, 'ExecutiveTradesPage empty orders')
    })

    it('handles negative realized PnL with negative or zero fees', () => {
      const losingOrders: OrderFeedItem[] = [
        {
          orderId: 'canary-p311-drill-sol-loss-1',
          timestampMyt: '11 Oct 16:00:00',
          symbol: 'SOLUSDT',
          side: 'SELL',
          orderType: 'LIMIT MAKER',
          price: 175.5,
          quantity: 0.025,
          notionalUsdt: 4.3875,
          makerFeeUsdt: 0.0008,
          realizedPnlUsdt: -0.1125,
          status: 'FILLED',
        },
        {
          orderId: 'canary-p311-drill-eth-loss-2',
          timestampMyt: '11 Oct 16:05:00',
          symbol: 'ETHUSDT',
          side: 'SELL',
          orderType: 'LIMIT MAKER',
          price: 2700.0,
          quantity: 0.0015,
          notionalUsdt: 4.05,
          makerFeeUsdt: 0.0008,
          realizedPnlUsdt: -0.075,
          status: 'FILLED',
        },
      ]

      const html = renderToString(<ExecutiveTradesPage orders={losingOrders} />)
      const text = cleanSsrText(html)

      expect(text).toContain('2 Orders Filled')
      expect(text).toContain('-0.1875 USDT')
      expect(text).toContain('0.0%')
      expect(text).toContain('0 of 2 winning trades')
      expect(text).toContain('100% Passive limit execution (exact maker limit)')
      expect(text).toContain('-0.1125')
      expect(text).toContain('-0.0750')
      assertZeroMalay(html, 'ExecutiveTradesPage negative realized PnL')
    })
  })

  describe('6. ExecutiveSafetyPage SSR Adversarial Resilience', () => {
    it('handles null optional parameters and renders all 4 pillars safely', () => {
      const prod = buildProductionLaunchModel(null)
      const risk = buildRiskModel(null)
      const kill = buildKillSwitchModel(null)

      const html = renderToString(
        <ExecutiveSafetyPage
          productionLaunchModel={prod}
          riskModel={risk}
          killSwitchModel={kill}
          executionStatus={null}
          microstructureModel={null}
          liveMarketModel={null}
          latencyMs={undefined}
        />,
      )
      const text = cleanSsrText(html)

      expect(text).toContain('Risk Controls &amp; Ledger Integrity')
      expect(text).toContain('Double-Entry Invariant')
      expect(text).toContain('Micro-Exposure Limits')
      expect(text).toContain('Cash Floor Reserve')
      expect(text).toContain('Daily Loss Ceiling')
      expect(text).toContain('Mathematical Double-Entry Ledger Invariant Proof')
      expect(text).toContain('Circuit Breaker Conditions &amp; Emergency Kill Switch')
      assertZeroMalay(html, 'ExecutiveSafetyPage null optional params')
    })

    it('triggers tripwires under supercritical Hawkes (ρ = 1.450) and latency breach (> 500ms)', () => {
      const prod = buildProductionLaunchModel(null)
      const risk = buildRiskModel(null)
      const kill = buildKillSwitchModel(null)
      const micro = buildMicrostructureModel(null)
      micro.maxSpectralRadius = 1.45

      const execStatus: ExecutionStatusResponse = {
        verified: true,
        status: 'ok',
        engine_state: 'ONLINE 24/7',
        timestamp_ms: 1710000000000,
        candidate_allocations: [],
        aggregate_exposure_usdt: 24.5,
        total_orders: 0,
        interlock_blocks_count: 0,
        intra_day_loss_usdt: 3.25,
        solvency: {
          starting_equity_usdt: 100.0,
          cash_usdt: 68.0,
          allocated_margin_usdt: 24.5,
          unrealized_pnl_usdt: -1.25,
          realized_pnl_usdt: -3.25,
          total_equity_usdt: 91.25,
          drift_usdt: 0.0,
          zero_balance_drift_verified: true,
          cash_reserve_pct: 74.5, // below 75%
        },
        positions: {},
        recent_orders: [],
      }

      const html = renderToString(
        <ExecutiveSafetyPage
          productionLaunchModel={prod}
          riskModel={risk}
          killSwitchModel={kill}
          executionStatus={execStatus}
          microstructureModel={micro}
          liveMarketModel={null}
          latencyMs={625.4}
        />,
      )
      const text = cleanSsrText(html)

      expect(text).toContain('Status: ELEVATED / CRITICAL (ρ = 1.450)')
      expect(text).toContain('Status: HIGH LATENCY (625.4 ms)')
      expect(text).toContain('$3.25 / $3.00 USDT')
      expect(text).toContain('Floor Warning')
      assertZeroMalay(html, 'ExecutiveSafetyPage tripwires triggered')
    })

    it('handles Kill Switch armed state and zero cash boundary safely', () => {
      const prod = buildProductionLaunchModel(null)
      const risk = buildRiskModel(null)
      const kill = buildKillSwitchModel(null)
      kill.killSwitchState = 'ARMED'

      const execStatus: ExecutionStatusResponse = {
        verified: true,
        status: 'ok',
        engine_state: 'ONLINE 24/7',
        timestamp_ms: 1710000000000,
        candidate_allocations: [],
        aggregate_exposure_usdt: 0.0,
        total_orders: 0,
        interlock_blocks_count: 0,
        intra_day_loss_usdt: 0.0,
        solvency: {
          starting_equity_usdt: 100.0,
          cash_usdt: 0.0,
          allocated_margin_usdt: 0.0,
          unrealized_pnl_usdt: 0.0,
          realized_pnl_usdt: 0.0,
          total_equity_usdt: 0.0,
          drift_usdt: 0.0,
          zero_balance_drift_verified: true,
          cash_reserve_pct: 0.0,
        },
        positions: {},
        recent_orders: [],
      }

      const html = renderToString(
        <ExecutiveSafetyPage
          productionLaunchModel={prod}
          riskModel={risk}
          killSwitchModel={kill}
          executionStatus={execStatus}
          microstructureModel={null}
          liveMarketModel={null}
        />,
      )
      const text = cleanSsrText(html)

      expect(text).toContain('Status: ARMED')
      expect(text).toContain('0.0% Cash')
      expect(text).toContain('Floor Warning')
      assertZeroMalay(html, 'ExecutiveSafetyPage armed kill switch')
    })
  })

  describe('7. EvolutionPage Deep Edge Cases: Null Macro State & Missing LiveProgress', () => {
    it('handles model with undefined liveProgress without SSR error', () => {
      const base = buildAutoEvolutionModel(null)
      const modelWithoutLiveProgress: AutoEvolutionModel = {
        ...base,
        verified: true,
        status: 'SIMULATION_ARTIFACT_VERIFIED',
        liveProgress: undefined,
      }

      const html = renderToString(<EvolutionPage model={modelWithoutLiveProgress} />)
      const text = cleanSsrText(html)

      expect(text).toContain('Continuous Self-Learning Loop, Strategy Autopsy &amp; Auto-Evolution Daemon')
      expect(text).toContain('ACTIVE 24/7 LOOP')
      expect(text).toContain('BTC Macro Trend Gating (1-Hour Regime)')
      expect(text).toContain('BEARISH')
      expect(text).toContain('LONGS: BLOCKED')
      assertZeroMalay(html, 'EvolutionPage with undefined liveProgress')
    })

    it('handles null macro_gating_state safely via fallback', () => {
      const base = buildAutoEvolutionModel(null)
      const modelWithNullMacro: AutoEvolutionModel = {
        ...base,
        verified: true,
        status: 'SIMULATION_ARTIFACT_VERIFIED',
        liveProgress: {
          is_live_daemon_active: true,
          current_cycle_stage: 'INGRESS',
          macro_gating_state: null as any,
          macro_gating: undefined as any,
          recent_events: [],
        },
      }

      const html = renderToString(<EvolutionPage model={modelWithNullMacro} />)
      const text = cleanSsrText(html)

      expect(text).toContain('BTC Macro Trend Gating (1-Hour Regime)')
      expect(text).toContain('BEARISH')
      assertZeroMalay(html, 'EvolutionPage with null macro_gating_state')
    })
  })

  describe('8. StrategyConfluenceRadar Boundary: ρ = 0.0000 & Safe Conditions', () => {
    it('handles absolute zero hazard and active buy authorization', () => {
      const btcTrend: BtcMacroTrend = {
        regime: 'BULLISH ALIGNED',
        ema50_1h: 96000.0,
        ema200_1h: 91000.0,
        ema50_4h: 95000.0,
        ema200_4h: 90000.0,
        explanation: 'Bitcoin strong bull market.',
      }
      const scalper: ScalperCriteria = {
        priceBelowEma20Atr: 3.1,
        priceBelowEmaThreshold: 2.5,
        priceTriggered: true,
        relativeVolume: 3.0,
        volumeThreshold: 2.2,
        volumeTriggered: true,
        rsi14: 18.5,
        rsiThreshold: 26.0,
        rsiTriggered: true,
        makerFeePct: 0.02,
      }
      const zeroHawkes: HawkesHazard = {
        spectralRadius: 0.0,
        isNonToxic: true,
        thresholdWarning: 0.85,
        thresholdCritical: 1.0,
        recentHistory: [0.0, 0.0, 0.0],
      }

      const html = renderToString(
        <StrategyConfluenceRadar
          btcMacroTrend={btcTrend}
          scalperCriteria={scalper}
          hawkesHazard={zeroHawkes}
        />,
      )
      const text = cleanSsrText(html)

      expect(text).toContain('✅ BUY AUTHORIZATION ACTIVE')
      expect(text).toContain('SAFE / NON-TOXIC')
      expect(text).toContain('ρ = 0.0000')
      assertZeroMalay(html, 'StrategyConfluenceRadar zero hazard')
    })
  })
})


