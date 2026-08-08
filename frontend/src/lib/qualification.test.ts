import { describe, expect, it } from 'vitest'

import { buildQualificationModel } from './qualification'
import type { DashboardApiData } from './dashboard'

const VERIFIED_DATA = {
  health: {
    status: 'ok',
    service: 'autonomous-futures-data-api',
    paper_safe: true,
    execution_authority: false,
  },
  creatorQualifications: {
    verified: true,
    candidate_count: 2,
    qualification_count: 1,
    missing_candidate_ids: ['cand-missing'],
    qualifications: [
      {
        candidate_id: 'cand-qualified',
        decision: 'qualified',
        source: 'walk_forward_oos',
        qualification_hash: 'a'.repeat(64),
        evaluator_run_id: 'run-001',
        evaluator_version: 'wf-v1',
        windows_evaluated: 4,
        qualification_policy_id: 'strict-oos-v1',
        evaluated_at: '2026-08-08T04:00:00Z',
        promotion_state: 'unpromoted',
        execution_authority: false,
      },
    ],
  },
} as DashboardApiData

const NO_EVIDENCE_DATA = {
  health: null,
  creatorQualifications: null,
  creatorQualificationError: null,
} as DashboardApiData

describe('buildQualificationModel', () => {
  it('exposes verified evidence without translating qualified into promotion', () => {
    const model = buildQualificationModel(VERIFIED_DATA)

    expect(model.status).toBe('verified')
    expect(model.candidateCount).toBe(2)
    expect(model.qualificationCount).toBe(1)
    expect(model.missingCandidateIds).toEqual(['cand-missing'])
    expect(model.qualifications[0]).toMatchObject({
      candidateId: 'cand-qualified',
      decision: 'qualified',
      promotionState: 'unpromoted',
      executionAuthority: false,
    })
  })

  it('keeps missing evidence explicit instead of inventing zeroes', () => {
    const model = buildQualificationModel(NO_EVIDENCE_DATA)

    expect(model.status).toBe('unavailable')
    expect(model.candidateCount).toBeNull()
    expect(model.qualificationCount).toBeNull()
    expect(model.missingCandidateIds).toEqual([])
    expect(model.qualifications).toEqual([])
  })

  it('keeps integrity failures separate from a verified empty state', () => {
    const model = buildQualificationModel({
      ...NO_EVIDENCE_DATA,
      creatorQualificationError: 'Qualification evidence could not be verified',
    })

    expect(model.status).toBe('error')
    expect(model.errorMessage).toBe('Qualification evidence could not be verified')
    expect(model.qualificationCount).toBeNull()
  })
})
