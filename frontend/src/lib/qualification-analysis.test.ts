import { describe, expect, it } from 'vitest'

import type { QualificationModel } from './qualification'
import {
  buildQualificationMatrix,
  type QualificationMatrixFilters,
} from './qualification'

const MODEL: QualificationModel = {
  status: 'verified',
  candidateCount: 3,
  qualificationCount: 2,
  missingCandidateIds: ['cand-missing'],
  errorMessage: null,
  qualifications: [
    {
      candidateId: 'cand-qualified',
      decision: 'qualified',
      source: 'walk_forward_oos',
      qualificationHash: 'a'.repeat(64),
      evaluatorRunId: 'run-qualified',
      evaluatorVersion: 'wf-v1',
      windowsEvaluated: 4,
      qualificationPolicyId: 'strict-oos-v1',
      evaluatedAt: '2026-08-08T04:00:00Z',
      promotionState: 'unpromoted',
      executionAuthority: false,
    },
    {
      candidateId: 'cand-rejected',
      decision: 'rejected',
      source: 'creator_evaluator',
      qualificationHash: 'b'.repeat(64),
      evaluatorRunId: 'run-rejected',
      evaluatorVersion: 'creator-v1',
      windowsEvaluated: 2,
      qualificationPolicyId: null,
      evaluatedAt: '2026-08-08T05:00:00Z',
      promotionState: 'unpromoted',
      executionAuthority: false,
    },
  ],
}

const FILTERS: QualificationMatrixFilters = {
  outcome: 'all',
  source: 'all',
  sort: 'candidate',
}

describe('buildQualificationMatrix', () => {
  it('keeps verified rows and missing evidence explicit with deterministic candidate ordering', () => {
    const matrix = buildQualificationMatrix(MODEL, FILTERS)

    expect(matrix.status).toBe('verified')
    expect(matrix.totalRows).toBe(3)
    expect(matrix.visibleRows.map((row) => row.candidateId)).toEqual([
      'cand-missing',
      'cand-qualified',
      'cand-rejected',
    ])
    expect(matrix.visibleRows[0]).toMatchObject({
      outcome: 'missing',
      source: null,
      windowsEvaluated: null,
      promotionState: null,
      executionAuthority: null,
    })
  })

  it('filters outcome and source without changing persisted summaries', () => {
    const matrix = buildQualificationMatrix(MODEL, {
      outcome: 'rejected',
      source: 'creator_evaluator',
      sort: 'candidate',
    })

    expect(matrix.visibleRows.map((row) => row.candidateId)).toEqual(['cand-rejected'])
    expect(matrix.visibleRows[0]).toMatchObject({
      evaluatorVersion: 'creator-v1',
      qualificationPolicyId: null,
      promotionState: 'unpromoted',
      executionAuthority: false,
    })
    expect(MODEL.qualifications[1].qualificationHash).toBe('b'.repeat(64))
  })

  it('sorts windows descending and uses candidate ID as a stable tie-break', () => {
    const matrix = buildQualificationMatrix(MODEL, {
      outcome: 'all',
      source: 'all',
      sort: 'windows',
    })

    expect(matrix.visibleRows.map((row) => row.candidateId)).toEqual([
      'cand-qualified',
      'cand-rejected',
      'cand-missing',
    ])
  })

  it('sorts evaluated timestamps newest first and keeps unavailable state empty', () => {
    const sorted = buildQualificationMatrix(MODEL, {
      outcome: 'all',
      source: 'all',
      sort: 'evaluated',
    })
    const unavailable = buildQualificationMatrix({
      status: 'unavailable',
      candidateCount: null,
      qualificationCount: null,
      missingCandidateIds: [],
      qualifications: [],
      errorMessage: null,
    }, FILTERS)

    expect(sorted.visibleRows.map((row) => row.candidateId)).toEqual([
      'cand-rejected',
      'cand-qualified',
      'cand-missing',
    ])
    expect(unavailable.status).toBe('unavailable')
    expect(unavailable.totalRows).toBe(0)
    expect(unavailable.visibleRows).toEqual([])
  })
})
