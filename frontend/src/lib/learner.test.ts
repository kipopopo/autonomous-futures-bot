import { describe, expect, it } from 'vitest'

import { buildLearnerModel, type LearnerModel } from './learner'
import type { DashboardApiData } from './dashboard'
import { pageFromHash } from './navigation'

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
    component_count: 2,
    bundle: {
      symbols: ['ETHUSDT', 'BTCUSDT'],
      primary_interval: '5m',
      context_interval: '15m',
      context_feature_policy: 'close_time_plus_1ms',
      time_start: '2026-08-08T00:00:00Z',
      time_end: '2026-08-08T01:00:00Z',
    },
  },
  components: {
    verified: true,
    component_count: 2,
    components: [],
  },
}

describe('buildLearnerModel', () => {
  it('exposes verified foundation facts while keeping learner artifacts unavailable', () => {
    const model = buildLearnerModel(VERIFIED_DATA)

    expect(model).toMatchObject({
      status: 'verified',
      symbols: ['BTCUSDT', 'ETHUSDT'],
      primaryInterval: '5m',
      contextInterval: '15m',
      contextFeaturePolicy: 'close_time_plus_1ms',
      learnerArtifactStatus: 'unavailable',
      learningRunStatus: 'unavailable',
      paperActivation: false,
      executionAuthority: false,
    })
    expect(model.bundleHash).toBe('b'.repeat(64))
    expect(model.registryHash).toBe('a'.repeat(64))
  })

  it('fails closed without verified foundation and invents no learner facts', () => {
    const model: LearnerModel = buildLearnerModel({
      health: null,
      bundle: null,
      components: null,
    })

    expect(model).toMatchObject({
      status: 'unavailable',
      symbols: [],
      primaryInterval: null,
      contextInterval: null,
      contextFeaturePolicy: null,
      learnerArtifactStatus: 'unavailable',
      learningRunStatus: 'unavailable',
      paperActivation: false,
      executionAuthority: false,
    })
    expect(model.bundleHash).toBeNull()
    expect(model.registryHash).toBeNull()
  })
})

describe('learner route', () => {
  it('recognizes the learner hash and keeps unsupported routes on overview', () => {
    expect(pageFromHash('#/learner')).toBe('learner')
    expect(pageFromHash('#learner')).toBe('learner')
    expect(pageFromHash('#/signals')).toBe('overview')
  })
})
