import { describe, expect, it } from 'vitest'

import { buildCreatorModel } from './creator'
import type { DashboardApiData } from './dashboard'

const VERIFIED_DATA: DashboardApiData = {
  health: {
    status: 'ok',
    service: 'autonomous-futures-data-api',
    paper_safe: true,
    execution_authority: false,
  },
  bundle: {
    verified: true,
    registry_hash: 'a'.repeat(64),
    bundle_hash: 'b'.repeat(64),
    component_count: 5,
    bundle: {
      symbols: ['ETHUSDT', 'BTCUSDT'],
      primary_interval: '5m',
      context_interval: '15m',
      context_feature_policy: 'close_time_plus_1ms',
      time_start: '2026-08-07T00:00:00Z',
      time_end: '2026-08-07T00:10:00Z',
    },
  },
  components: {
    verified: true,
    component_count: 5,
    components: [],
  },
}

const VERIFIED_CREATOR_DATA = {
  ...VERIFIED_DATA,
  creatorRegistry: {
    verified: true,
    registry_hash: 'c'.repeat(64),
    candidate_count: 1,
    registry: {
      registry_version: 1,
      venue: 'BINANCE_USDS_M_FUTURES',
      created_at: '2026-08-07T12:00:00Z',
      registry_hash: 'c'.repeat(64),
      entries: [
        {
          candidate_id: 'cand-api-001',
          artifact_hash: 'd'.repeat(64),
          artifact_ref: 'candidates/cand-api-001.json',
          bundle_hash: 'b'.repeat(64),
          dataset_registry_hash: 'a'.repeat(64),
          strategy_id: 'cand-api-001',
          family: 'experimental',
          symbols: ['BTCUSDT'],
          state: 'testing',
          creator_run_id: 'creator-run-api',
          created_at: '2026-08-07T12:00:00Z',
        },
      ],
    },
  },
} as DashboardApiData

describe('buildCreatorModel', () => {
  it('reports verified foundation readiness without inventing creator output', () => {
    const model = buildCreatorModel(VERIFIED_DATA)

    expect(model.foundationState).toBe('verified')
    expect(model.symbols).toEqual(['BTCUSDT', 'ETHUSDT'])
    expect(model.componentCount).toBe(5)
    expect(model.contextPolicy).toBe('close_time_plus_1ms')
    expect(model.candidateAvailability).toBe('unavailable')
    expect(model.candidateCount).toBeNull()
  })

  it('keeps both foundation and creator output explicit when API data is unavailable', () => {
    const model = buildCreatorModel({ health: null, bundle: null, components: null })

    expect(model.foundationState).toBe('unavailable')
    expect(model.candidateAvailability).toBe('unavailable')
    expect(model.componentCount).toBeNull()
    expect(model.candidateCount).toBeNull()
  })

  it('exposes only verified candidate registry metadata when available', () => {
    const model = buildCreatorModel(VERIFIED_CREATOR_DATA)

    expect(model.candidateAvailability).toBe('available')
    expect(model.candidateCount).toBe(1)
    expect(model.candidates[0]).toMatchObject({
      candidateId: 'cand-api-001',
      state: 'testing',
      family: 'experimental',
    })
    expect(model.candidateRegistryHash).toBe('c'.repeat(64))
  })
})
