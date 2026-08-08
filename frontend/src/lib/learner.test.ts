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

  it('exposes only verified persisted learner artifact and prepared-run evidence', () => {
    const model = buildLearnerModel({
      ...VERIFIED_DATA,
      learnerArtifact: {
        verified: true,
        artifact: {
          learner_id: 'learner-api-001',
          learner_version: 'v1',
          model_family: 'explicit-test',
          model_artifact_hash: 'c'.repeat(64),
          artifact_hash: 'd'.repeat(64),
          candidate_id: 'cand-learner-api',
          symbols: ['BTCUSDT'],
          training_window_start: '2026-08-08T00:00:00Z',
          training_window_end: '2026-08-08T01:00:00Z',
          state: 'testing',
          promotion_state: 'unpromoted',
          paper_activation: false,
          execution_authority: false,
        },
      },
      learnerRun: {
        verified: true,
        run: {
          run_id: 'run-learner-api',
          run_hash: 'e'.repeat(64),
          status: 'prepared',
          input_window_ids: ['input-api-001'],
          input_symbols: ['BTCUSDT'],
          output_artifact_hash: null,
          training_metrics: null,
          training_window_start: '2026-08-08T00:00:00Z',
          training_window_end: '2026-08-08T01:00:00Z',
          promotion_state: 'unpromoted',
          paper_activation: false,
          execution_authority: false,
        },
      },
    } as DashboardApiData)

    expect(model).toMatchObject({
      learnerArtifactStatus: 'verified',
      learningRunStatus: 'verified',
      learnerArtifact: {
        learnerId: 'learner-api-001',
        modelArtifactHash: 'c'.repeat(64),
        artifactHash: 'd'.repeat(64),
      },
      learnerRun: {
        runId: 'run-learner-api',
        status: 'prepared',
        outputArtifactHash: null,
      },
    })
  })

  it('distinguishes integrity-unavailable evidence from a missing artifact', () => {
    const model = buildLearnerModel({
      ...VERIFIED_DATA,
      learnerArtifactError: 'GET /api/v1/learner/artifact failed with HTTP 503',
      learnerRunError: null,
    } as DashboardApiData)

    expect(model).toMatchObject({
      learnerArtifactStatus: 'integrity_unavailable',
      learningRunStatus: 'unavailable',
    })
  })

  it('shows completed training as provenance only, never as model quality', () => {
    const model = buildLearnerModel({
      ...VERIFIED_DATA,
      learnerTrainingEvidence: {
        verified: true,
        evidence: {
          evidence_version: 1,
          evidence_id: 'training-evidence-learner-api',
          prepared_run_id: 'run-learner-api',
          prepared_run_ref: 'learner-run.json',
          prepared_run_hash: 'a'.repeat(64),
          source_learner_artifact_ref: 'learner-artifact.json',
          source_learner_artifact_hash: 'b'.repeat(64),
          output_artifact_ref: 'trained/learner.json',
          output_artifact_hash: 'c'.repeat(64),
          learner_id: 'learner-api-001',
          learner_run_id: 'run-learner-api',
          candidate_id: 'cand-learner-api',
          candidate_artifact_hash: 'd'.repeat(64),
          bundle_hash: 'e'.repeat(64),
          dataset_registry_hash: 'f'.repeat(64),
          input_window_ids: ['input-api-001'],
          input_symbols: ['BTCUSDT'],
          feature_ids: ['returns'],
          training_window_start: '2026-08-08T00:00:00Z',
          training_window_end: '2026-08-08T01:00:00Z',
          learner_version: 'output-v1',
          model_family: 'explicit-test-output',
          status: 'completed',
          training_metrics: null,
          data_source: 'cached_only',
          exchange_access: false,
          promotion_state: 'unpromoted',
          paper_activation: false,
          execution_authority: false,
          created_at: '2026-08-08T02:00:00Z',
          evidence_hash: '1'.repeat(64),
        },
      },
    } as DashboardApiData)

    expect(model).toMatchObject({
      trainingCompletionStatus: 'verified',
      trainingEvidence: {
        status: 'completed',
        learnerVersion: 'output-v1',
        modelFamily: 'explicit-test-output',
        outputArtifactHash: 'c'.repeat(64),
        trainingMetrics: null,
        promotionState: 'unpromoted',
        paperActivation: false,
        executionAuthority: false,
      },
    })
  })
})

describe('learner route', () => {
  it('recognizes the learner hash and keeps unsupported routes on overview', () => {
    expect(pageFromHash('#/learner')).toBe('learner')
    expect(pageFromHash('#learner')).toBe('learner')
    expect(pageFromHash('#/signals')).toBe('overview')
  })
})
