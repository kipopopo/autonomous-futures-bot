import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { StressPage } from '../stress-page'
import {
  buildStressFaultInjectionModel,
  type CanaryStressFaultInjectionResponse,
} from '../../lib/canary'

describe('StressPage component', () => {
  const verifiedFixture: CanaryStressFaultInjectionResponse = {
    verified: true,
    phase: 'phase_297',
    status: 'STRESS_RESILIENCE_VERIFIED',
    timestamp_ms: 1789452000000,
    timestamp_utc: '2026-09-21T16:00:00.000Z',
    paper_safe: true,
    execution_authority: false,
    circuit_state: 'HALTED',
    shock_vectors: [
      {
        vector_id: 'SHOCK_01_FLASH_CRASH',
        name: 'Flash Crash Simulation',
        intensity: '-8.5% price drop in 300ms',
        status: 'TRIGGERED',
        action_taken: 'CIRCUIT_TRIPPED_AUTO_FLATTEN',
        timestamp_utc: '2026-09-21T16:00:00.000Z',
      },
      {
        vector_id: 'SHOCK_02_LIQUIDITY_EVAPORATION',
        name: 'Liquidity Evaporation Drill',
        intensity: '92% depth removal on bid side',
        status: 'TRIGGERED',
        action_taken: 'ORDER_PURGE_SPREAD_WIDENED',
        timestamp_utc: '2026-09-21T16:00:00.000Z',
      },
      {
        vector_id: 'SHOCK_03_PHANTOM_DEPTH',
        name: 'Phantom Depth / Spoofing Burst',
        intensity: 'Rapid quote cancellation (1200 cancels/s)',
        status: 'TRIGGERED',
        action_taken: 'SPOOF_FILTER_REJECTED',
        timestamp_utc: '2026-09-21T16:00:00.000Z',
      },
      {
        vector_id: 'SHOCK_04_TELEMETRY_DEGRADATION',
        name: 'Telemetry Degradation & Heartbeat Loss',
        intensity: 'Simulated 1200ms gateway stall',
        status: 'TRIGGERED',
        action_taken: 'HEARTBEAT_GATE_FAIL_CLOSED',
        timestamp_utc: '2026-09-21T16:00:00.000Z',
      },
    ],
    circuit_breaker_latencies: [
      {
        breaker_id: 'hawkes_runaway_cutoff',
        vector_id: 'SHOCK_01_FLASH_CRASH',
        detection_latency_us: 120.0,
        trigger_latency_us: 150.0,
        action: 'ORDER_REJECTION_ENGAGED',
        tripped: true,
        sub_millisecond: true,
      },
      {
        breaker_id: 'depth_collapse_interlock',
        vector_id: 'SHOCK_02_LIQUIDITY_EVAPORATION',
        detection_latency_us: 280.0,
        trigger_latency_us: 310.0,
        action: 'SPREAD_PROTECTION_HALT',
        tripped: true,
        sub_millisecond: true,
      },
      {
        breaker_id: 'emergency_auto_flattening',
        vector_id: 'SHOCK_01_FLASH_CRASH',
        detection_latency_us: 650.0,
        trigger_latency_us: 720.0,
        action: 'CANCEL_AND_FLATTEN',
        tripped: true,
        sub_millisecond: true,
      },
      {
        breaker_id: 'gateway_heartbeat_staleness',
        vector_id: 'SHOCK_04_TELEMETRY_DEGRADATION',
        detection_latency_us: 90.0,
        trigger_latency_us: 110.0,
        action: 'FAIL_CLOSED_GATE_ENGAGED',
        tripped: true,
        sub_millisecond: true,
      },
    ],
    auto_flattening_audits: [
      {
        flattening_id: 'FLAT_297_001',
        symbol: 'BTCUSDT',
        trigger_reason: 'Loss ceiling threshold proximity (drawdown >= 4.5%)',
        positions_closed_count: 2,
        orders_cancelled_count: 4,
        pre_flatten_equity_usdt: 99.85,
        post_flatten_cash_usdt: 99.42,
        capital_preserved_pct: 99.57,
        execution_authority: false,
        timestamp_utc: '2026-09-21T16:00:00.000Z',
      },
      {
        flattening_id: 'FLAT_297_002',
        symbol: 'ETHUSDT',
        trigger_reason: 'Liquidity collapse bid vacuum detection',
        positions_closed_count: 1,
        orders_cancelled_count: 2,
        pre_flatten_equity_usdt: 99.42,
        post_flatten_cash_usdt: 99.18,
        capital_preserved_pct: 99.76,
        execution_authority: false,
        timestamp_utc: '2026-09-21T16:00:00.000Z',
      },
    ],
    capital_preservation_stats: {
      pre_flatten_equity_usdt: 100.0,
      post_flatten_cash_usdt: 99.18,
      capital_preserved_pct: 99.18,
      max_loss_budget_usdt: 7.0,
      actual_loss_usdt: 0.82,
      loss_ceiling_breached: false,
      circuit_state: 'HALTED',
    },
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 99.18,
      allocated_margin_usdt: 0.0,
      unrealized_pnl_usdt: 0.0,
      realized_pnl_usdt: -0.82,
      total_equity_usdt: 99.18,
      total_fees_usdt: 0.0,
      total_slippage_usdt: 0.0,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.0,
      cash_reserve_pct: 99.18,
      unencumbered_cash_verified: true,
    },
    ledger: {
      starting_equity: 100.0,
      cash: 99.18,
      allocated_margin: 0.0,
      unrealized_pnl: 0.0,
      realized_pnl: -0.82,
      drift: 0.0,
      zero_balance_drift: true,
    },
    upstream_hash: 'aadff07fae3505f6f2b7f57519dc4d322a1d9d913d697be02354dea3b0c5c718',
    phase_hash: 'c8d4e2f1a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2',
    merkle_root: '9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d9c8b7a6f5e4d3c2b1a0f9e8d',
  }

  it('renders all safety and confinement badges', () => {
    const model = buildStressFaultInjectionModel(verifiedFixture)
    const html = renderToString(<StressPage model={model} />)

    expect(html).toContain('STRESS RESILIENCE VERIFIED')
    expect(html).toContain('PAPER-SAFE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
    expect(html).toContain('SUB-MS LATENCY (&lt; 1 ms)')
    expect(html).toContain('ZERO-DRIFT VERIFIED')
  })

  it('renders real-time shock vector status matrix with all 4 calibrated vectors', () => {
    const model = buildStressFaultInjectionModel(verifiedFixture)
    const html = renderToString(<StressPage model={model} />)

    expect(html).toContain('Real-time Shock Vector Status Matrix')
    expect(html).toContain('SHOCK_01_FLASH_CRASH')
    expect(html).toContain('Flash Crash Simulation')
    expect(html).toContain('-8.5% price drop in 300ms')
    expect(html).toContain('CIRCUIT_TRIPPED_AUTO_FLATTEN')

    expect(html).toContain('SHOCK_02_LIQUIDITY_EVAPORATION')
    expect(html).toContain('Liquidity Evaporation Drill')

    expect(html).toContain('SHOCK_03_PHANTOM_DEPTH')
    expect(html).toContain('Phantom Depth / Spoofing Burst')

    expect(html).toContain('SHOCK_04_TELEMETRY_DEGRADATION')
    expect(html).toContain('Telemetry Degradation &amp; Heartbeat Loss')
  })

  it('renders circuit breaker reaction latencies table with sub-millisecond badge', () => {
    const model = buildStressFaultInjectionModel(verifiedFixture)
    const html = renderToString(<StressPage model={model} />)

    expect(html).toContain('Circuit Breaker Reaction Latencies (&lt; 1 ms Trigger Time)')
    expect(html).toContain('hawkes_runaway_cutoff')
    expect(html).toContain('120.0 μs')
    expect(html).toContain('emergency_auto_flattening')
    expect(html).toContain('CANCEL_AND_FLATTEN')
    expect(html).toContain('SUB-MILLISECOND (&lt; 1 ms)')
  })

  it('renders auto-flattening and capital preservation audit scorecards and event rows', () => {
    const model = buildStressFaultInjectionModel(verifiedFixture)
    const html = renderToString(<StressPage model={model} />)

    expect(html).toContain('Auto-Flattening &amp; Capital Preservation Audit')
    expect(html).toContain('99.18%')
    expect(html).toContain('0.8200 USDT')
    expect(html).toContain('FLAT_297_001')
    expect(html).toContain('FLAT_297_002')
    expect(html).toContain('Loss ceiling threshold proximity')
    expect(html).toContain('Liquidity collapse bid vacuum detection')
  })

  it('renders double-entry solvency meter and continuous zero-drift verification', () => {
    const model = buildStressFaultInjectionModel(verifiedFixture)
    const html = renderToString(<StressPage model={model} />)

    expect(html).toContain('Double-Entry Solvency Meter (|drift| &lt; 10⁻¹⁵ USDT)')
    expect(html).toContain('100.00 USDT')
    expect(html).toContain('99.18 USDT')
    expect(html).toContain('|drift| &lt; 10⁻¹⁵ USDT')
    expect(html).toContain('Continuous mathematical accounting conservation')
    expect(html).toContain('RESERVE BUFFER VERIFIED')
  })

  it('renders cryptographic SHA-256 Merkle DAG provenance linking Phase 296 parent hash', () => {
    const model = buildStressFaultInjectionModel(verifiedFixture)
    const html = renderToString(<StressPage model={model} />)

    expect(html).toContain('Cryptographic SHA-256 Merkle DAG Provenance')
    expect(html).toContain('Phase 297 Merkle Root:')
    expect(html).toContain('9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d9c8b7a6f5e4d3c2b1a0f9e8d')
    expect(html).toContain('Upstream Phase 296 Parent Hash:')
    expect(html).toContain('aadff07fae3505f6f2b7f57519dc4d322a1d9d913d697be02354dea3b0c5c718')
    expect(html).toContain('MERKLE ROOT VERIFIED')
  })

  it('handles default/null model safely without throwing', () => {
    const defaultModel = buildStressFaultInjectionModel(null)
    const html = renderToString(<StressPage model={defaultModel} />)

    expect(html).toBeDefined()
    expect(html).toContain('Phase 297 / Stress Resilience Plane')
    expect(html).toContain('Real-time Shock Vector Status Matrix')
    expect(html).toContain('Circuit Breaker Reaction Latencies (&lt; 1 ms Trigger Time)')
    expect(html).toContain('Double-Entry Solvency Meter (|drift| &lt; 10⁻¹⁵ USDT)')
  })
})
