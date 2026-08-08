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

export type QualificationMatrixOutcome = 'qualified' | 'rejected' | 'missing'
export type QualificationMatrixOutcomeFilter = 'all' | QualificationMatrixOutcome
export type QualificationMatrixSourceFilter = 'all' | QualificationSource
export type QualificationMatrixSort = 'candidate' | 'outcome' | 'windows' | 'evaluated'

export interface QualificationMatrixFilters {
  outcome: QualificationMatrixOutcomeFilter
  source: QualificationMatrixSourceFilter
  sort: QualificationMatrixSort
}

export interface QualificationMatrixRow {
  candidateId: string
  outcome: QualificationMatrixOutcome
  source: QualificationSource | null
  qualificationHash: string | null
  evaluatorVersion: string | null
  windowsEvaluated: number | null
  qualificationPolicyId: string | null
  evaluatedAt: string | null
  promotionState: 'unpromoted' | null
  executionAuthority: false | null
}

export interface QualificationMatrixModel {
  status: QualificationStatus
  totalRows: number
  visibleCount: number
  visibleRows: QualificationMatrixRow[]
}

function compareCandidate(left: QualificationMatrixRow, right: QualificationMatrixRow): number {
  return left.candidateId.localeCompare(right.candidateId)
}

function compareRows(left: QualificationMatrixRow, right: QualificationMatrixRow, sort: QualificationMatrixSort): number {
  if (sort === 'windows') {
    if (left.windowsEvaluated !== right.windowsEvaluated) {
      if (left.windowsEvaluated === null) return 1
      if (right.windowsEvaluated === null) return -1
      return right.windowsEvaluated - left.windowsEvaluated
    }
  }
  if (sort === 'evaluated') {
    const leftTime = left.evaluatedAt ? Date.parse(left.evaluatedAt) : Number.NaN
    const rightTime = right.evaluatedAt ? Date.parse(right.evaluatedAt) : Number.NaN
    if (!Number.isNaN(leftTime) || !Number.isNaN(rightTime)) {
      if (Number.isNaN(leftTime)) return 1
      if (Number.isNaN(rightTime)) return -1
      if (leftTime !== rightTime) return rightTime - leftTime
    }
  }
  if (sort === 'outcome') {
    const order: Record<QualificationMatrixOutcome, number> = {
      qualified: 0,
      rejected: 1,
      missing: 2,
    }
    if (order[left.outcome] !== order[right.outcome]) {
      return order[left.outcome] - order[right.outcome]
    }
  }
  return compareCandidate(left, right)
}

export function buildQualificationMatrix(
  model: QualificationModel,
  filters: QualificationMatrixFilters,
): QualificationMatrixModel {
  if (model.status !== 'verified') {
    return {
      status: model.status,
      totalRows: 0,
      visibleCount: 0,
      visibleRows: [],
    }
  }

  const missingIds = [...new Set(model.missingCandidateIds)]
  const rows: QualificationMatrixRow[] = [
    ...model.qualifications.map((summary) => ({
      candidateId: summary.candidateId,
      outcome: summary.decision,
      source: summary.source,
      qualificationHash: summary.qualificationHash,
      evaluatorVersion: summary.evaluatorVersion,
      windowsEvaluated: summary.windowsEvaluated,
      qualificationPolicyId: summary.qualificationPolicyId,
      evaluatedAt: summary.evaluatedAt,
      promotionState: summary.promotionState,
      executionAuthority: summary.executionAuthority,
    })),
    ...missingIds.map((candidateId) => ({
      candidateId,
      outcome: 'missing' as const,
      source: null,
      qualificationHash: null,
      evaluatorVersion: null,
      windowsEvaluated: null,
      qualificationPolicyId: null,
      evaluatedAt: null,
      promotionState: null,
      executionAuthority: null,
    })),
  ]

  const visibleRows = rows
    .filter((row) => filters.outcome === 'all' || row.outcome === filters.outcome)
    .filter((row) => filters.source === 'all' || row.source === filters.source)
    .sort((left, right) => compareRows(left, right, filters.sort))

  return {
    status: 'verified',
    totalRows: rows.length,
    visibleCount: visibleRows.length,
    visibleRows,
  }
}
