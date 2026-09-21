import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { LifecyclePage } from '../lifecycle-page'
import {
  buildAutonomousLifecycleModel,
  type CanaryAutonomousLifecycleResponse,
} from '../../lib/canary'

describe('LifecyclePage component', () => {
  const verifiedFixture: CanaryAutonomousLifecycleResponse = {
    verified: true,
    phase: 'phase_296',
    status: 'AUTONOMOUS_LIFECYCLE_VERIFIED',
    timestamp_ms: 1789447964946,
    paper_safe: true,
    execution_authority: false,
    daemon_status: 'ACTIVE',
    circuit_state: 'NORMAL',
    longevity: {
      total_sessions: 3,
      total_ticks_processed: 2702,
      uptime_seconds: 60.0,
      throughput_tps: 45.03,
      disconnect_count: 1,
      reconnect_count: 1,
      sequence_gap_count: 12,
      duplicate_packets_count: 2,
      memory_bounded: true,
      ring_buffer_capacity: 1000,
    },
    components: [
      {
        name: 'Public Ingress Gateway',
        status: 'HEALTHY',
        details: 'Ingested 2,702 ticks across BTC, ETH, SOL feeds',
        updated_at: '2026-09-21T12:50:10.831607+00:00',
      },
      {
        name: 'Hawkes Microstructure Streamer',
        status: 'HEALTHY',
        details: 'Spectral radius rho < 1.0 (subcritical normal regime)',
        updated_at: '2026-09-21T12:50:10.831607+00:00',
      },
      {
        name: 'Strategy Activation Engine',
        status: 'HEALTHY',
        details: 'Walk-forward OOS promotion active, 3/3 candidates qualified',
        updated_at: '2026-09-21T12:50:10.831607+00:00',
      },
      {
        name: 'Passive Matching Simulator',
        status: 'HEALTHY',
        details: 'Micro child order slicing <= 5.00 USDT with ROUND_DOWN',
        updated_at: '2026-09-21T12:50:10.831607+00:00',
      },
      {
        name: 'Zero-Drift Ledger',
        status: 'HEALTHY',
        details: 'Continuous double-entry balance verified (|drift| < 1e-15)',
        updated_at: '2026-09-21T12:50:10.831607+00:00',
      },
    ],
    sessions: [
      {
        session_id: 'track4_session_001',
        session_index: 0,
        start_time_utc: '2026-09-21T12:50:00+00:00',
        end_time_utc: '2026-09-21T12:50:20+00:00',
        duration_seconds: 20.0,
        ticks_processed: 900,
        orders_placed: 3,
        fills_count: 3,
        starting_equity_usdt: 100.0,
        ending_cash_usdt: 85.0,
        ending_equity_usdt: 99.998,
        realized_pnl_usdt: -0.002,
        drift_usdt: 0.0,
        zero_balance_drift: true,
        disconnect_count: 0,
        reconnect_count: 0,
        status: 'COMPLETED',
      },
      {
        session_id: 'track4_session_002',
        session_index: 1,
        start_time_utc: '2026-09-21T12:50:20+00:00',
        end_time_utc: '2026-09-21T12:50:40+00:00',
        duration_seconds: 20.0,
        ticks_processed: 900,
        orders_placed: 3,
        fills_count: 3,
        starting_equity_usdt: 99.998,
        ending_cash_usdt: 78.24,
        ending_equity_usdt: 99.997,
        realized_pnl_usdt: -0.002,
        drift_usdt: 0.0,
        zero_balance_drift: true,
        disconnect_count: 1,
        reconnect_count: 1,
        status: 'COMPLETED',
      },
    ],
    risk_circuits: {
      circuit_state: 'NORMAL',
      spectral_radius_rho: 0.082,
      hawkes_cutoff_threshold: 1.0,
      hawkes_supercritical: false,
      heartbeat_age_ms: 0.0,
      heartbeat_threshold_ms: 500.0,
      gateway_heartbeat_stale: false,
      aggregate_exposure_usdt: 21.756,
      aggregate_exposure_cap_usdt: 60.0,
      margin_headroom_breach: false,
      intra_phase_loss_usdt: 0.004,
      intra_phase_loss_ceiling_usdt: 7.0,
      loss_ceiling_breached: false,
      cash_reserve_pct: 78.24,
      min_cash_reserve_floor_pct: 40.0,
      cash_reserve_depleted: false,
    },
    operational_switches: [
      {
        name: 'paper_safe',
        label: 'Paper-Safe Mode',
        enabled: true,
        fail_closed: true,
        value_display: 'ENABLED',
        description: 'Strict offline sandbox isolation',
      },
      {
        name: 'execution_authority',
        label: 'Live Execution Authority',
        enabled: false,
        fail_closed: true,
        value_display: 'DISABLED',
        description: 'Hard fail-closed block',
      },
      {
        name: 'hawkes_cutoff',
        label: 'Hawkes Runaway Cutoff',
        enabled: true,
        fail_closed: true,
        value_display: 'rho < 1.0000',
        description: 'Automatic order suppression',
      },
      {
        name: 'heartbeat_freshness',
        label: 'Heartbeat Freshness Gate',
        enabled: true,
        fail_closed: true,
        value_display: '<= 500 ms',
        description: 'Latency freshness gate',
      },
      {
        name: 'aggregate_margin_cap',
        label: 'Aggregate Exposure Ceiling',
        enabled: true,
        fail_closed: true,
        value_display: '<= 60.00 USDT',
        description: 'Maximum margin limit',
      },
      {
        name: 'loss_budget',
        label: 'Intra-Phase Loss Ceiling',
        enabled: true,
        fail_closed: true,
        value_display: '<= 7.00 USDT',
        description: 'Emergency flattening trigger',
      },
      {
        name: 'reserve_buffer',
        label: 'Unencumbered Reserve Buffer',
        enabled: true,
        fail_closed: true,
        value_display: '>= 40.0%',
        description: 'Guaranteed cash reserve buffer',
      },
    ],
    ledger: {
      starting_equity: 100.0,
      cash: 78.2396,
      allocated_margin: 21.756,
      unrealized_pnl: 0.002,
      realized_pnl: -0.004,
      drift: 0.0,
      zero_balance_drift: true,
    },
    upstream_hash: '1d6e6412f9c2a19dce2625fd3236ebdb9bd6c527959bb33875889a18ee51f005',
    phase_hash: '56e9eeec1bd06f9dea2df3a38e74138ecc942b345bce861f6ca579d216477338',
    merkle_root: 'a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890',
  }

  it('renders all safety and confinement badges', () => {
    const model = buildAutonomousLifecycleModel(verifiedFixture)
    const html = renderToString(<LifecyclePage model={model} />)

    expect(html).toContain('LIFECYCLE VERIFIED')
    expect(html).toContain('PAPER-SAFE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
    expect(html).toContain('ZERO-DRIFT VERIFIED')
  })

  it('renders 5 subsystem health scorecards', () => {
    const model = buildAutonomousLifecycleModel(verifiedFixture)
    const html = renderToString(<LifecyclePage model={model} />)

    expect(html).toContain('Public Ingress Gateway')
    expect(html).toContain('Hawkes Microstructure Streamer')
    expect(html).toContain('Strategy Activation Engine')
    expect(html).toContain('Passive Matching Simulator')
    expect(html).toContain('Zero-Drift Ledger')
    expect(html).toContain('HEALTHY')
  })

  it('renders longevity and uptime telemetry grid', () => {
    const model = buildAutonomousLifecycleModel(verifiedFixture)
    const html = renderToString(<LifecyclePage model={model} />)

    expect(html).toContain('Total Sessions')
    expect(html).toContain('3')
    expect(html).toContain('Cumulative Uptime')
    expect(html).toContain('60.0s')
    expect(html).toContain('Throughput')
    expect(html).toContain('45.0')
    expect(html).toContain('Memory Bounded')
    expect(html).toContain('O(1) Ring')
    expect(html).toContain('Dedup Suppressed')
    expect(html).toContain('Reconnection Drills')
  })

  it('renders endurance session timeline table', () => {
    const model = buildAutonomousLifecycleModel(verifiedFixture)
    const html = renderToString(<LifecyclePage model={model} />)

    expect(html).toContain('Endurance Session Timeline Table')
    expect(html).toContain('track4_session_001')
    expect(html).toContain('track4_session_002')
    expect(html).toContain('20.00s')
    expect(html).toContain('COMPLETED')
  })

  it('renders live operational switches matrix with fail-closed boundaries', () => {
    const model = buildAutonomousLifecycleModel(verifiedFixture)
    const html = renderToString(<LifecyclePage model={model} />)

    expect(html).toContain('Live Operational Switches &amp; Risk Interlocks Matrix')
    expect(html).toContain('Paper-Safe Mode')
    expect(html).toContain('Live Execution Authority')
    expect(html).toContain('Hawkes Runaway Cutoff')
    expect(html).toContain('Heartbeat Freshness Gate')
    expect(html).toContain('Aggregate Exposure Ceiling')
    expect(html).toContain('Intra-Phase Loss Ceiling')
    expect(html).toContain('Unencumbered Reserve Buffer')
    expect(html).toContain('INTERLOCKED')
  })

  it('renders double-entry solvency and accounting ledger', () => {
    const model = buildAutonomousLifecycleModel(verifiedFixture)
    const html = renderToString(<LifecyclePage model={model} />)

    expect(html).toContain('Double-Entry Solvency &amp; Accounting Ledger')
    expect(html).toContain('Starting Equity:')
    expect(html).toContain('100.00 USDT')
    expect(html).toContain('Final Cash:')
    expect(html).toContain('78.2396 USDT')
    expect(html).toContain('Allocated Margin:')
    expect(html).toContain('21.7560 USDT')
    expect(html).toContain('Mathematical Drift:')
    expect(html).toContain('|drift| &lt; 10⁻¹⁵ USDT')
  })

  it('renders cryptographic SHA-256 Merkle DAG provenance linking Phase 295', () => {
    const model = buildAutonomousLifecycleModel(verifiedFixture)
    const html = renderToString(<LifecyclePage model={model} />)

    expect(html).toContain('Cryptographic SHA-256 Merkle DAG Provenance')
    expect(html).toContain('Phase 296 Merkle Root:')
    expect(html).toContain('Upstream Phase 295 Root Summary Hash:')
    expect(html).toContain('1d6e6412f9c2a19dce2625fd3236ebdb9bd6c527959bb33875889a18ee51f005')
    expect(html).toContain('MERKLE ROOT VERIFIED')
  })

  it('handles default/null model safely without throwing', () => {
    const defaultModel = buildAutonomousLifecycleModel(null)
    const html = renderToString(<LifecyclePage model={defaultModel} />)

    expect(html).toBeDefined()
    expect(html).toContain('Phase 296 / Autonomous Lifecycle Plane')
    expect(html).toContain('Public Ingress Gateway')
    expect(html).toContain('Double-Entry Solvency &amp; Accounting Ledger')
    expect(html).toContain('No sessions recorded in current view.')
  })
})
