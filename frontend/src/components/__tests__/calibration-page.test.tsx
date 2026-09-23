import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { CalibrationPage } from '../calibration-page'
import {
  buildCalibrationModel,
  type CanaryCalibrationData,
} from '../../lib/canary'

describe('CalibrationPage component', () => {
  const verifiedFixture: CanaryCalibrationData = {
    phase: 'phase_304',
    verified: true,
    status: 'CALIBRATION_VERIFIED',
    circuit_state: 'NORMAL',
    timestamp_ms: 1790132000000,
    timestamp_utc: '2026-09-23T03:00:00.000000+00:00',
    paper_safe: true,
    execution_authority: false,
    candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
    performance: {
      total_calibrations: 18,
      dominant_regime: 'CALM_BALANCED',
      average_stability_index: 98.4,
      mean_adaptation_latency_ms: 12.4,
      adaptation_sla_met: true,
      regime_distribution: {
        CALM_BALANCED: 0.65,
        VOLATILITY_EXPANSION: 0.15,
        TRENDING_MOMENTUM: 0.1,
        MEAN_REVERTING: 0.08,
        TOXIC_TURBULENCE: 0.02,
      },
      defense_lockouts_triggered: 1,
      parameter_clamp_events: 2,
      realized_sharpe_ratio: 1045.0,
      calmar_ratio: 6940.0,
      max_drawdown_pct: 0.0035,
      win_rate_pct: 100.0,
      profit_factor: 1.5,
    },
    shadow_states: {
      BTCUSDT: {
        symbol: 'BTCUSDT',
        active_regime: 'CALM_BALANCED',
        regime_confidence: 0.92,
        stability_index: 99.1,
        total_calibrations: 6,
        calibrated_params: {
          risk_aversion_gamma: 0.1,
          hawkes_decay_beta: 5.0,
          reservation_cushion_bps: 4.0,
          temporary_impact_eta: 0.005,
          micro_chunk_usdt: 5.0,
          tp_atr_multiplier: 1.5,
          sl_atr_multiplier: 1.2,
        },
        allocated_margin_usdt: 0.0,
        unrealized_pnl_usdt: 0.035,
        adaptation_latency_ms: 0.11,
      },
      ETHUSDT: {
        symbol: 'ETHUSDT',
        active_regime: 'VOLATILITY_EXPANSION',
        regime_confidence: 0.88,
        stability_index: 97.5,
        total_calibrations: 6,
        calibrated_params: {
          risk_aversion_gamma: 0.35,
          hawkes_decay_beta: 4.2,
          reservation_cushion_bps: 18.0,
          temporary_impact_eta: 0.012,
          micro_chunk_usdt: 2.5,
          tp_atr_multiplier: 2.0,
          sl_atr_multiplier: 1.0,
        },
        allocated_margin_usdt: 0.0,
        unrealized_pnl_usdt: 0.0,
        adaptation_latency_ms: 0.13,
      },
      SOLUSDT: {
        symbol: 'SOLUSDT',
        active_regime: 'CALM_BALANCED',
        regime_confidence: 0.94,
        stability_index: 98.8,
        total_calibrations: 6,
        calibrated_params: {
          risk_aversion_gamma: 0.1,
          hawkes_decay_beta: 5.0,
          reservation_cushion_bps: 4.0,
          temporary_impact_eta: 0.005,
          micro_chunk_usdt: 5.0,
          tp_atr_multiplier: 1.5,
          sl_atr_multiplier: 1.2,
        },
        allocated_margin_usdt: 1.0,
        unrealized_pnl_usdt: 0.035,
        adaptation_latency_ms: 0.12,
      },
    },
    evolution_trace: [
      {
        event: 'CALIB_INIT',
        timestamp_ms: 1790132000000,
        symbol: 'BTCUSDT',
        regime: 'CALM_BALANCED',
        confidence: 0.95,
        probabilities: { CALM_BALANCED: 0.95 },
        damped_params: {
          risk_aversion_gamma: 0.1,
          hawkes_decay_beta: 5.0,
          reservation_cushion_bps: 4.0,
          temporary_impact_eta: 0.005,
          micro_chunk_usdt: 5.0,
          tp_atr_multiplier: 1.5,
          sl_atr_multiplier: 1.2,
        },
        raw_target: {
          risk_aversion_gamma: 0.1,
          hawkes_decay_beta: 5.0,
          reservation_cushion_bps: 4.0,
          temporary_impact_eta: 0.005,
          micro_chunk_usdt: 5.0,
          tp_atr_multiplier: 1.5,
          sl_atr_multiplier: 1.2,
        },
        stability_index: 100.0,
        is_clamped: false,
        solvency_drift: 0.0,
      },
    ],
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 98.9965,
      allocated_margin_usdt: 1.0,
      unrealized_pnl_usdt: 0.035,
      realized_pnl_usdt: 0.0,
      total_equity_usdt: 100.0315,
      total_fees_usdt: 0.0015,
      total_slippage_usdt: 0.002,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.0315,
      cash_reserve_pct: 98.9965,
      unencumbered_cash_verified: true,
    },
    ledger: {
      starting_equity: 100.0,
      cash: 98.9965,
      allocated_margin: 1.0,
      unrealized_pnl: 0.035,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    upstream_hash: '8ec3824da1946a3fc6fb70f2302a3b139f046385e76bf6050bf00fc58ae31f70',
    phase_hash: '3d8a436df9521fa4b7b25055b85a3c631481b0f58064a390eb1793740263f35a',
    merkle_root: '07ffc13325eeffaadd0fb2e2cc60fe15269943f0bfca55fd613289c02a4fb80b',
  }

  it('renders verified calibration model with all indicators, regimes, and DAG chain', () => {
    const model = buildCalibrationModel(verifiedFixture)
    const html = renderToString(<CalibrationPage model={model} />)

    expect(html).toContain('Autonomous Self-Calibrating Parameter Adaptation')
    expect(html).toContain('PHASE 304')
    expect(html).toContain('CALIBRATION_VERIFIED')
    expect(html).toContain('PAPER SAFE: CONFINED')
    expect(html).toContain('AUTHORITY: OFF')
    expect(html).toContain('ZERO DRIFT')
    expect(html).toContain('BTCUSDT')
    expect(html).toContain('ETHUSDT')
    expect(html).toContain('SOLUSDT')
    expect(html).toContain('Online Market Regime State Machine')
    expect(html).toContain('Calm Balanced')
    expect(html).toContain('Volatility Expansion')
    expect(html).toContain('Toxic Turbulence')
    expect(html).toContain('Centralized Double-Entry Solvency Ledger')
    expect(html).toContain('Cryptographic Merkle DAG Governance')
    expect(html).toContain('8ec3824da1946a3fc6fb70f2302a3b139f046385e76bf6050bf00fc58ae31f70')
    expect(html).toContain('07ffc13325eeffaadd0fb2e2cc60fe15269943f0bfca55fd613289c02a4fb80b')
  })

  it('renders fallback model gracefully without throwing when data is null', () => {
    const fallbackModel = buildCalibrationModel(null)
    const html = renderToString(<CalibrationPage model={fallbackModel} />)

    expect(html).toContain('Autonomous Self-Calibrating Parameter Adaptation')
    expect(html).toContain('PHASE 304')
    expect(html).toContain('CALIBRATION_VERIFIED')
    expect(html).toContain('PAPER SAFE: CONFINED')
    expect(html).toContain('AUTHORITY: OFF')
    expect(html).toContain('BTCUSDT')
  })
})
