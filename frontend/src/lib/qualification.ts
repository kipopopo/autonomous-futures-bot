import type {
  CreatorQualificationSummary,
  DashboardApiData,
  QualificationDecision,
  QualificationSource,
} from './dashboard'

export type QualificationStatus = 'verified' | 'unavailable' | 'error'

export interface QualificationSummary {
  candidateId: string
  decision: QualificationDecision
  source: QualificationSource
  qualificationHash: string
  evaluatorRunId: string
  evaluatorVersion: string
  windowsEvaluated: number
  qualificationPolicyId: string | null
  evaluatedAt: string
  promotionState: 'unpromoted'
  executionAuthority: false
}

export interface QualificationModel {
  status: QualificationStatus
  candidateCount: number | null
  qualificationCount: number | null
  missingCandidateIds: string[]
  qualifications: QualificationSummary[]
  errorMessage: string | null
}

function toSummary(summary: CreatorQualificationSummary): QualificationSummary {
  return {
    candidateId: summary.candidate_id,
    decision: summary.decision,
    source: summary.source,
    qualificationHash: summary.qualification_hash,
    evaluatorRunId: summary.evaluator_run_id,
    evaluatorVersion: summary.evaluator_version,
    windowsEvaluated: summary.windows_evaluated,
    qualificationPolicyId: summary.qualification_policy_id,
    evaluatedAt: summary.evaluated_at,
    promotionState: summary.promotion_state,
    executionAuthority: summary.execution_authority,
  }
}

export function buildQualificationModel(data: DashboardApiData): QualificationModel {
  if (data.creatorQualificationError) {
    return {
      status: 'error',
      candidateCount: null,
      qualificationCount: null,
      missingCandidateIds: [],
      qualifications: [],
      errorMessage: data.creatorQualificationError,
    }
  }

  const response = data.creatorQualifications?.verified ? data.creatorQualifications : null
  if (!response) {
    return {
      status: 'unavailable',
      candidateCount: null,
      qualificationCount: null,
      missingCandidateIds: [],
      qualifications: [],
      errorMessage: null,
    }
  }

  return {
    status: 'verified',
    candidateCount: response.candidate_count,
    qualificationCount: response.qualification_count,
    missingCandidateIds: [...response.missing_candidate_ids],
    qualifications: response.qualifications.map(toSummary),
    errorMessage: null,
  }
}
