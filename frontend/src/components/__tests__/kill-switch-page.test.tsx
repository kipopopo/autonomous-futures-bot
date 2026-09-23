import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { KillSwitchPage } from '../kill-switch-page'
import {
  buildKillSwitchModel,
  type CanaryKillSwitchData,
} from '../../lib/canary'

describe('KillSwitchPage component', () => {
  const verifiedFixture: CanaryKillSwitchData = {
    phase: 'phase_308',
    verified: true,
    status: 'KILL_SWITCH_VERIFIED',
    circuit_state: 'NORMAL',
    timestamp_ms: 1790150000000,
    timestamp_utc: '2026-09-23T07:45:00.000000+00:00',
    paper_safe: true,
    execution_authority: false,
    kill_switch_state: 'LEVEL_3_HARDWARE_PANIC',
    memory_wiped: true,
    active_signers_count: 3,
    required_quorum: 2,
    proposals_evaluated: 1,
    proposals_executed: 1,
    total_kill_events: 3,
    emergency_flattened_positions: 2,
    cancelled_orders_count: 3,
    signers: [
      {
        signer_id: 'signer-cro-alice',
        public_key: 'pubkey-secp256k1-cro-alice-7f89b',
        role: 'CHIEF_RISK_OFFICER',
        is_active: true,
        last_nonce: 2,
      },
      {
        signer_id: 'signer-sec-bob',
        public_key: 'pubkey-secp256k1-sec-bob-4e12c',
        role: 'SECURITY_LEAD',
        is_active: true,
        last_nonce: 0,
      },
      {
        signer_id: 'signer-dev-charlie',
        public_key: 'pubkey-secp256k1-dev-charlie-9a34d',
        role: 'LEAD_DEV_DEVOPS',
        is_active: true,
        last_nonce: 1,
      },
    ],
    proposals: [
      {
        proposal_id: 'prop-gov-001',
        action_type: 'RESET_LOCKOUT',
        target: 'kill_switch',
        parameters: { target_state: 'ARMED_NORMAL' },
        required_quorum: 2,
        votes_cast: 2,
        is_executed: true,
        execution_result: 'RESET_OK',
      },
    ],
    events_trace: [
      {
        event_id: 'ks-evt-0001',
        tier: 'LEVEL_1_SOFT',
        previous_state: 'ARMED_NORMAL',
        new_state: 'LEVEL_1_SOFT_PAUSE',
        reason: 'Hawkes jump intensity supercritical spike',
        trigger_source: 'HAWKES_BREACH',
        positions_flattened_count: 0,
        orders_cancelled_count: 0,
        memory_wiped: false,
        timestamp_ms: 1790150000000,
      },
      {
        event_id: 'ks-evt-0002',
        tier: 'LEVEL_2_LOCKOUT',
        previous_state: 'LEVEL_1_SOFT_PAUSE',
        new_state: 'LEVEL_2_LOCKOUT',
        reason: 'Testnet gateway heartbeat latency surge (> 500 ms)',
        trigger_source: 'LATENCY_SPIKE',
        positions_flattened_count: 0,
        orders_cancelled_count: 3,
        memory_wiped: false,
        timestamp_ms: 1790150001000,
      },
      {
        event_id: 'ks-evt-0003',
        tier: 'LEVEL_3_PANIC',
        previous_state: 'ARMED_NORMAL',
        new_state: 'LEVEL_3_HARDWARE_PANIC',
        reason: 'OS signal SIGINT/SIGUSR1 intercepted or emergency tripwire token file detected',
        trigger_source: 'OS_SIGNAL_SIGINT',
        positions_flattened_count: 2,
        orders_cancelled_count: 3,
        memory_wiped: true,
        timestamp_ms: 1790150003000,
      },
    ],
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 100.12,
      allocated_margin_usdt: 0.0,
      unrealized_pnl_usdt: 0.0,
      realized_pnl_usdt: 0.12,
      total_equity_usdt: 100.12,
      total_fees_usdt: 0.01,
      total_slippage_usdt: 0.0,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.0,
      cash_reserve_pct: 100.0,
      unencumbered_cash_verified: true,
    },
    ledger: {
      starting_equity: 100.0,
      cash: 100.12,
      allocated_margin: 0.0,
      unrealized_pnl: 0.0,
      realized_pnl: 0.12,
      drift: 0.0,
      zero_balance_drift: true,
    },
    upstream_hash: '4eb405de6cdc48e26fddaa4a2ed8bd91ef9e0843a4b71cfd0cb643a15e7ceb16',
    phase_hash: 'phase308-local-payload-hash',
    merkle_root: '65c2e7d2b3dc5d0f63773ef531c700a0fa2f6e73bdc094c7fad1105fc675e31e',
  }

  it('renders verified kill-switch dashboard with all key sections', () => {
    const model = buildKillSwitchModel(verifiedFixture)
    const html = renderToString(<KillSwitchPage model={model} />)

    // Header & phase badges
    expect(html).toContain('PHASE 308')
    expect(html).toContain('KILL_SWITCH_VERIFIED')
    expect(html).toContain('PAPER-SAFE:')
    expect(html).toContain('TRUE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
    expect(html).toContain('ZERO-DRIFT:')
    expect(html).toContain('VERIFIED')

    // KPI cards
    expect(html).toContain('LEVEL_3_HARDWARE_PANIC')
    expect(html).toContain('ZEROIZATION_VERIFIED')
    expect(html).toContain('2 / 3')
    expect(html).toContain('M-of-N QUORUM')
    expect(html).toContain('100.12')

    // Containment metrics
    expect(html).toContain('Positions Flattened')
    expect(html).toContain('Orders Mass-Cancelled')

    // Multi-sig and event content
    expect(html).toContain('ks-evt-0001')
    expect(html).toContain('LEVEL_1_SOFT')
    expect(html).toContain('LEVEL_2_LOCKOUT')
    expect(html).toContain('LEVEL_3_PANIC')

    // 3-Tier escalation model section
    expect(html).toContain('Fail-Closed 3-Tier Escalation Containment Model')
    expect(html).toContain('LEVEL_1_SOFT_PAUSE')
    expect(html).toContain('LEVEL_2_LOCKOUT')
    expect(html).toContain('LEVEL_3_HARDWARE_PANIC')

    // Merkle provenance
    expect(html).toContain('4eb405de6cdc48e26fddaa4a2ed8bd91ef9e0843a4b71cfd0cb643a15e7ceb16')
    expect(html).toContain('65c2e7d2b3dc5d0f63773ef531c700a0fa2f6e73bdc094c7fad1105fc675e31e')
  })

  it('renders fallback model gracefully without throwing when data is null', () => {
    const model = buildKillSwitchModel(null)
    const html = renderToString(<KillSwitchPage model={model} />)

    expect(html).toContain('PHASE 308')
    expect(html).toContain('UNAVAILABLE')
    expect(html).toContain('PAPER-SAFE:')
    expect(html).toContain('TRUE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
  })
})
