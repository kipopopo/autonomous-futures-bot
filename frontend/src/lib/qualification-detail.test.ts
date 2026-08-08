import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchCreatorQualification } from './api'
import type { QualificationDetailResponse } from './dashboard'
import { buildQualificationDetailModel } from './qualification'

const DETAIL_RESPONSE = {
  verified: true,
  artifact: {
    qualification_version: 1,
    candidate_id: 'cand-detail',
    candidate_artifact_hash: 'a'.repeat(64),
    bundle_hash: 'b'.repeat(64),
    dataset_registry_hash: 'c'.repeat(64),
    evaluator_run_id: 'run-detail',
    evaluator_version: 'wf-v1',
    decision: 'qualified',
    metrics: [
      { metric_id: 'average_return_pct', value: '1.23000000000000000001' },
    ],
    gates: [
      {
        gate_id: 'minimum_windows',
        passed: true,
        observed: '4',
        threshold: '3',
        comparator: 'gte',
        reason_code: 'gate.passed',
      },
    ],
    windows_evaluated: 4,
    qualification_policy_id: 'strict-oos-v1',
    oos_aggregation_hash: 'd'.repeat(64),
    source: 'walk_forward_oos',
    evaluated_at: '2026-08-08T04:00:00Z',
    promotion_state: 'unpromoted',
    execution_authority: false,
    qualification_hash: 'e'.repeat(64),
  },
} as QualificationDetailResponse

function response(status: number, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

describe('qualification detail boundary', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('fetches one candidate detail through the encoded read-only route', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(200, DETAIL_RESPONSE))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchCreatorQualification('cand-detail')

    expect(result?.artifact.candidate_id).toBe('cand-detail')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/creator/qualifications/cand-detail', {
      headers: { Accept: 'application/json' },
    })
  })

  it('maps a missing detail artifact to null', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(404)))

    await expect(fetchCreatorQualification('cand-missing')).resolves.toBeNull()
  })

  it('rejects tampered detail evidence instead of returning a partial artifact', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(503)))

    await expect(fetchCreatorQualification('cand-detail')).rejects.toThrow(
      'GET /api/v1/creator/qualifications/cand-detail failed with HTTP 503',
    )
  })

  it('preserves exact Decimal strings and maps full provenance and gates', () => {
    const model = buildQualificationDetailModel(DETAIL_RESPONSE)

    expect(model.status).toBe('verified')
    expect(model.metrics).toEqual([
      { metricId: 'average_return_pct', value: '1.23000000000000000001' },
    ])
    expect(model.gates[0]).toMatchObject({
      gateId: 'minimum_windows',
      passed: true,
      observed: '4',
      threshold: '3',
      comparator: 'gte',
      reasonCode: 'gate.passed',
    })
    expect(model.binding).toMatchObject({
      candidateArtifactHash: 'a'.repeat(64),
      bundleHash: 'b'.repeat(64),
      datasetRegistryHash: 'c'.repeat(64),
      oosAggregationHash: 'd'.repeat(64),
      qualificationHash: 'e'.repeat(64),
    })
    expect(model.safety).toEqual({ promotionState: 'unpromoted', executionAuthority: false })
  })

  it('keeps detail integrity failure separate from a missing artifact', () => {
    const model = buildQualificationDetailModel(null, 'Qualification detail could not be verified')

    expect(model.status).toBe('error')
    expect(model.metrics).toEqual([])
    expect(model.gates).toEqual([])
    expect(model.errorMessage).toBe('Qualification detail could not be verified')
  })
})
