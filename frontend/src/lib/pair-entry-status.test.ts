import { describe, expect, it } from 'vitest'
import { evaluatePairEntry } from './pair-entry-status'
import type {
  PositionTelemetry,
  IctPairSignal,
  ScalperCriteria,
  BtcMacroTrend,
} from '../components/mission-control/types'

describe('evaluatePairEntry utility', () => {
  const basePosition: PositionTelemetry = {
    symbol: 'SOLUSDT',
    currentPrice: 110.2,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 0.0,
    stopLossPrice: 0.0,
    riskRewardRatio: '1.66:1',
  }

  const baseIctSignal: IctPairSignal = {
    symbol: 'SOLUSDT',
    step: 'IDLE',
    step_number: 0,
    steps: {
      step_1_htf_hit: false,
      step_2_m5_cisd: false,
      step_3_twins_fvg: false,
      step_4_ote_retrace: false,
      step_5_m1_cisd: false,
      step_6_ready: false,
    },
    side: 'NEUTRAL',
    active_pda: null,
    cisd: { m5_cisd_price: null, m1_cisd_price: null },
    targets: {
      ote_lower: null,
      ote_sweet_spot: null,
      ote_upper: null,
      stop_loss: null,
      stdv_2_0: null,
      stdv_4_0: null,
      take_profit_partial: null,
      take_profit_final: null,
    },
    candidate: {
      candidate_id: 'cand-solusdt-ict-001',
      health_tier: 'HEALTHY',
      generation: 1,
      ote_bounds: '62%-79%',
      stdv_tp1: 2.0,
      stdv_tp2: 4.0,
      swing_lookback: 50,
      fvg_threshold_pct: '0.15%',
    },
    invalidation_reason: 'NONE',
  }

  const baseScalper: ScalperCriteria = {
    priceBelowEma20Atr: 1.2,
    priceBelowEmaThreshold: 2.5,
    priceTriggered: false,
    relativeVolume: 1.0,
    volumeThreshold: 2.2,
    volumeTriggered: false,
    rsi14: 45.0,
    rsiThreshold: 26.0,
    rsiTriggered: false,
    makerFeePct: 0.02,
  }

  const btcTrend: BtcMacroTrend = {
    regime: 'BULLISH ALIGNED',
    ema50_1h: 83000,
    ema200_1h: 82000,
    ema50_4h: 82500,
    ema200_4h: 81000,
    explanation: 'Bullish macro alignment',
  }

  it('evaluates STANDBY when no entry conditions are met', () => {
    const result = evaluatePairEntry('SOLUSDT', basePosition, baseIctSignal, baseScalper, btcTrend)
    expect(result.type).toBe('STANDBY')
    expect(result.badgeLabel).toBe('STANDBY / SCANNING')
    expect(result.hasIctEntry).toBe(false)
    expect(result.hasScalperEntry).toBe(false)
  })

  it('evaluates ICT ENTRY when Twins Step 6 is ready', () => {
    const readyIctSignal: IctPairSignal = {
      ...baseIctSignal,
      step: 'STEP_6_READY',
      step_number: 6,
      steps: {
        ...baseIctSignal.steps,
        step_6_ready: true,
      },
      side: 'BUY',
    }

    const result = evaluatePairEntry('SOLUSDT', basePosition, readyIctSignal, baseScalper, btcTrend)
    expect(result.type).toBe('ICT')
    expect(result.badgeLabel).toContain('ICT ENTRY')
    expect(result.hasIctEntry).toBe(true)
    expect(result.hasScalperEntry).toBe(false)
  })

  it('evaluates SCALPER ENTRY when 15m scalper conditions are triggered', () => {
    const triggeredScalper: ScalperCriteria = {
      ...baseScalper,
      priceTriggered: true,
      volumeTriggered: true,
      rsiTriggered: true,
    }

    const result = evaluatePairEntry('SOLUSDT', basePosition, baseIctSignal, triggeredScalper, btcTrend)
    expect(result.type).toBe('SCALPER')
    expect(result.badgeLabel).toContain('SCALPER ENTRY')
    expect(result.hasScalperEntry).toBe(true)
    expect(result.hasIctEntry).toBe(false)
  })

  it('evaluates DUAL ENTRY when both ICT and Scalper conditions are active', () => {
    const readyIctSignal: IctPairSignal = {
      ...baseIctSignal,
      step: 'STEP_6_READY',
      step_number: 6,
      steps: { ...baseIctSignal.steps, step_6_ready: true },
      side: 'BUY',
    }

    const triggeredScalper: ScalperCriteria = {
      ...baseScalper,
      priceTriggered: true,
      volumeTriggered: true,
      rsiTriggered: true,
    }

    const result = evaluatePairEntry('SOLUSDT', basePosition, readyIctSignal, triggeredScalper, btcTrend)
    expect(result.type).toBe('DUAL')
    expect(result.badgeLabel).toContain('DUAL ENTRY')
    expect(result.hasIctEntry).toBe(true)
    expect(result.hasScalperEntry).toBe(true)
  })

  it('evaluates FORMING when ICT is at step 4 or 5', () => {
    const formingSignal: IctPairSignal = {
      ...baseIctSignal,
      step: 'STEP_4_OTE_RETRACE',
      step_number: 4,
      steps: { ...baseIctSignal.steps, step_4_ote_retrace: true },
      side: 'BUY',
    }

    const result = evaluatePairEntry('SOLUSDT', basePosition, formingSignal, baseScalper, btcTrend)
    expect(result.type).toBe('FORMING')
    expect(result.badgeLabel).toContain('ICT OTE Fib')
  })
})
