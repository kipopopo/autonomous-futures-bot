import { describe, expect, it } from 'vitest'

import {
  buildQualificationComparison,
  toggleQualificationComparisonSelection,
  type QualificationModel,
} from './qualification'

const MODEL: QualificationModel = {
  status: 'verified',
  candidateCount: 3,
  qualificationCount: 2,
  missingCandidateIds: ['cand-missing'],
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
  errorMessage: null,
}

describe('qualification cohort comparison', () => {
  it('returns selected rows in selection order with missing fields explicit', () => {
    const comparison = buildQualificationComparison(MODEL, [
      'cand-rejected',
      'cand-missing',
    ])

    expect(comparison.status).toBe('verified')
    expect(comparison.selectedRows.map((row) => row.candidateId)).toEqual([
      'cand-rejected',
      'cand-missing',
    ])
    expect(comparison.selectedRows[1]).toMatchObject({
      outcome: 'missing',
      source: null,
      evaluatorVersion: null,
      windowsEvaluated: null,
      evaluatedAt: null,
      qualificationHash: null,
      promotionState: null,
      executionAuthority: null,
    })
  })

  it('removes unknown IDs, deduplicates, and enforces a maximum of three selections', () => {
    const selected = ['cand-qualified', 'cand-rejected', 'cand-missing', 'unknown', 'cand-qualified']
    const comparison = buildQualificationComparison(MODEL, selected)
    const blocked = toggleQualificationComparisonSelection(
      ['one', 'two', 'three'],
      'four',
    )
    const removed = toggleQualificationComparisonSelection(['one', 'two'], 'one')

    expect(comparison.selectedRows.map((row) => row.candidateId)).toEqual([
      'cand-qualified',
      'cand-rejected',
      'cand-missing',
    ])
    expect(blocked).toEqual(['one', 'two', 'three'])
    expect(removed).toEqual(['two'])
  })

  it('fails closed to an empty comparison when qualification evidence is unavailable', () => {
    const comparison = buildQualificationComparison({
      status: 'error',
      candidateCount: null,
      qualificationCount: null,
      missingCandidateIds: [],
      qualifications: [],
      errorMessage: 'integrity unavailable',
    }, ['cand-qualified'])

    expect(comparison.status).toBe('error')
    expect(comparison.selectedRows).toEqual([])
  })
})
