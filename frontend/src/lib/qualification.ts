import type {
  CreatorQualificationSummary,
  DashboardApiData,
  QualificationDetailResponse,
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

export interface QualificationDetailMetric {
  metricId: string
  value: string
}

export interface QualificationDetailGate {
  gateId: string
  passed: boolean
  observed: string | null
  threshold: string | null
  comparator: string
  reasonCode: string
}

export interface QualificationDetailModel {
  status: QualificationStatus
  candidateId: string | null
  decision: QualificationDecision | null
  source: QualificationSource | null
  evaluatorRunId: string | null
  evaluatorVersion: string | null
  windowsEvaluated: number | null
  qualificationPolicyId: string | null
  evaluatedAt: string | null
  metrics: QualificationDetailMetric[]
  gates: QualificationDetailGate[]
  binding: {
    candidateArtifactHash: string | null
    bundleHash: string | null
    datasetRegistryHash: string | null
    oosAggregationHash: string | null
    qualificationHash: string | null
  }
  safety: {
    promotionState: 'unpromoted' | null
    executionAuthority: false | null
  }
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

export function buildQualificationDetailModel(
  response: QualificationDetailResponse | null,
  errorMessage: string | null = null,
): QualificationDetailModel {
  const empty: QualificationDetailModel = {
    status: errorMessage ? 'error' : 'unavailable',
    candidateId: null,
    decision: null,
    source: null,
    evaluatorRunId: null,
    evaluatorVersion: null,
    windowsEvaluated: null,
    qualificationPolicyId: null,
    evaluatedAt: null,
    metrics: [],
    gates: [],
    binding: {
      candidateArtifactHash: null,
      bundleHash: null,
      datasetRegistryHash: null,
      oosAggregationHash: null,
      qualificationHash: null,
    },
    safety: {
      promotionState: null,
      executionAuthority: null,
    },
    errorMessage,
  }
  if (!response || response.verified !== true) return empty

  const artifact = response.artifact
  return {
    ...empty,
    status: 'verified',
    candidateId: artifact.candidate_id,
    decision: artifact.decision,
    source: artifact.source,
    evaluatorRunId: artifact.evaluator_run_id,
    evaluatorVersion: artifact.evaluator_version,
    windowsEvaluated: artifact.windows_evaluated,
    qualificationPolicyId: artifact.qualification_policy_id,
    evaluatedAt: artifact.evaluated_at,
    metrics: artifact.metrics.map((metric) => ({
      metricId: metric.metric_id,
      value: metric.value,
    })),
    gates: artifact.gates.map((gate) => ({
      gateId: gate.gate_id,
      passed: gate.passed,
      observed: gate.observed,
      threshold: gate.threshold,
      comparator: gate.comparator,
      reasonCode: gate.reason_code,
    })),
    binding: {
      candidateArtifactHash: artifact.candidate_artifact_hash,
      bundleHash: artifact.bundle_hash,
      datasetRegistryHash: artifact.dataset_registry_hash,
      oosAggregationHash: artifact.oos_aggregation_hash,
      qualificationHash: artifact.qualification_hash,
    },
    safety: {
      promotionState: artifact.promotion_state,
      executionAuthority: artifact.execution_authority,
    },
    errorMessage: null,
  }
}
