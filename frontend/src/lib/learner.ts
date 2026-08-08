import type {
  DashboardApiData,
  LearnerArtifactEvidence,
  LearnerMetricQualityQualificationEvidence,
  LearnerMetricQualityQualificationGate,
  LearnerQualityReviewEvidence,
  LearnerQualityReviewWindow,
  LearnerQualificationEvidence,
  LearnerQualificationGate,
  LearnerQualificationMetric,
  LearnerRunEvidence,
  LearnerTrainingEvidence,
} from './dashboard'
import { buildOverviewModel } from './dashboard'

export type LearnerReadinessStatus = 'verified' | 'unavailable'
export type LearnerEvidenceStatus = 'verified' | 'unavailable' | 'integrity_unavailable'

export interface LearnerArtifactModel {
  learnerId: string
  learnerVersion: string
  modelFamily: string
  modelArtifactHash: string
  artifactHash: string
  candidateId: string
  symbols: string[]
  trainingWindowStart: string
  trainingWindowEnd: string
  state: 'testing'
  promotionState: 'unpromoted'
  paperActivation: false
  executionAuthority: false
}

export interface LearnerRunModel {
  runId: string
  runHash: string
  status: 'prepared'
  inputWindowIds: string[]
  inputSymbols: string[]
  trainingWindowStart: string
  trainingWindowEnd: string
  outputArtifactHash: null
  trainingMetrics: null
  promotionState: 'unpromoted'
  paperActivation: false
  executionAuthority: false
}

export interface LearnerTrainingEvidenceModel {
  evidenceId: string
  learnerVersion: string
  modelFamily: string
  outputArtifactHash: string
  evidenceHash: string
  completedAt: string
  status: 'completed'
  trainingMetrics: null
  promotionState: 'unpromoted'
  paperActivation: false
  executionAuthority: false
}

export interface LearnerQualityReviewMetricModel {
  metricId: string
  value: string
}

export interface LearnerQualityReviewWindowModel {
  windowId: string
  symbol: string
  rowsEvaluated: number
  metrics: LearnerQualityReviewMetricModel[]
}

export interface LearnerQualityReviewModel {
  reviewId: string
  reviewRunId: string
  reviewVersion: string
  trainingEvidenceHash: string
  outputArtifactHash: string
  split: 'holdout'
  windows: LearnerQualityReviewWindowModel[]
  status: 'completed'
  reviewConclusion: 'observed_only'
  reviewedAt: string
  reviewHash: string
  promotionState: 'unpromoted'
  paperActivation: false
  executionAuthority: false
}

export interface LearnerQualificationMetricModel {
  windowId: string
  metricId: string
  observed: string | null
}

export interface LearnerQualificationGateModel {
  gateId: string
  windowId: string | null
  metricId: string | null
  passed: boolean
  observed: string | null
  threshold: string
  comparator: 'gte' | 'lte' | 'eq'
  reasonCode: string
}

export interface LearnerQualificationModel {
  qualificationId: string
  decision: 'rejected' | 'qualified'
  policyId: string
  policyHash: string
  metrics: LearnerQualificationMetricModel[]
  gates: LearnerQualificationGateModel[]
  windowsEvaluated: number
  evaluatedAt: string
  qualificationHash: string
  promotionState: 'unpromoted'
  paperActivation: false
  executionAuthority: false
}

export interface LearnerMetricQualityQualificationGateModel {
  gateId: 'metric_quality_decision' | 'minimum_windows'
  passed: boolean
  observedWindows: number | null
  minimumWindows: number | null
  sourceDecision: 'failed' | 'passed' | null
  requiredDecision: 'passed' | null
  reasonCode: string
}

export interface LearnerMetricQualityQualificationModel {
  qualificationId: string
  sourceDecision: 'failed' | 'passed'
  decision: 'rejected' | 'qualified'
  sourcePolicyId: string
  sourcePolicyHash: string
  qualificationPolicyId: string
  qualificationPolicyHash: string
  gates: LearnerMetricQualityQualificationGateModel[]
  windowsEvaluated: number
  evaluatedAt: string
  qualificationHash: string
  promotionState: 'unpromoted'
  paperActivation: false
  executionAuthority: false
}

export interface LearnerModel {
  status: LearnerReadinessStatus
  symbols: string[]
  primaryInterval: string | null
  contextInterval: string | null
  contextFeaturePolicy: string | null
  bundleHash: string | null
  registryHash: string | null
  learnerArtifactStatus: LearnerEvidenceStatus
  learningRunStatus: LearnerEvidenceStatus
  trainingCompletionStatus: LearnerEvidenceStatus
  qualityReviewStatus: LearnerEvidenceStatus
  qualificationStatus: LearnerEvidenceStatus
  metricQualityQualificationStatus: LearnerEvidenceStatus
  learnerArtifact: LearnerArtifactModel | null
  learnerRun: LearnerRunModel | null
  trainingEvidence: LearnerTrainingEvidenceModel | null
  qualityReview: LearnerQualityReviewModel | null
  qualification: LearnerQualificationModel | null
  metricQualityQualification: LearnerMetricQualityQualificationModel | null
  paperActivation: false
  executionAuthority: false
}

function mapArtifact(artifact: LearnerArtifactEvidence): LearnerArtifactModel {
  return {
    learnerId: artifact.learner_id,
    learnerVersion: artifact.learner_version,
    modelFamily: artifact.model_family,
    modelArtifactHash: artifact.model_artifact_hash,
    artifactHash: artifact.artifact_hash,
    candidateId: artifact.candidate_id,
    symbols: [...artifact.symbols],
    trainingWindowStart: artifact.training_window_start,
    trainingWindowEnd: artifact.training_window_end,
    state: artifact.state,
    promotionState: artifact.promotion_state,
    paperActivation: artifact.paper_activation,
    executionAuthority: artifact.execution_authority,
  }
}

function mapRun(run: LearnerRunEvidence): LearnerRunModel {
  return {
    runId: run.run_id,
    runHash: run.run_hash,
    status: run.status,
    inputWindowIds: [...run.input_window_ids],
    inputSymbols: [...run.input_symbols],
    trainingWindowStart: run.training_window_start,
    trainingWindowEnd: run.training_window_end,
    outputArtifactHash: run.output_artifact_hash,
    trainingMetrics: run.training_metrics,
    promotionState: run.promotion_state,
    paperActivation: run.paper_activation,
    executionAuthority: run.execution_authority,
  }
}

function mapTrainingEvidence(evidence: LearnerTrainingEvidence): LearnerTrainingEvidenceModel {
  return {
    evidenceId: evidence.evidence_id,
    learnerVersion: evidence.learner_version,
    modelFamily: evidence.model_family,
    outputArtifactHash: evidence.output_artifact_hash,
    evidenceHash: evidence.evidence_hash,
    completedAt: evidence.created_at,
    status: evidence.status,
    trainingMetrics: evidence.training_metrics,
    promotionState: evidence.promotion_state,
    paperActivation: evidence.paper_activation,
    executionAuthority: evidence.execution_authority,
  }
}

function mapQualityReviewWindow(window: LearnerQualityReviewWindow): LearnerQualityReviewWindowModel {
  return {
    windowId: window.window_id,
    symbol: window.symbol,
    rowsEvaluated: window.rows_evaluated,
    metrics: window.metrics.map((metric) => ({
      metricId: metric.metric_id,
      value: metric.value,
    })),
  }
}

function mapQualityReview(evidence: LearnerQualityReviewEvidence): LearnerQualityReviewModel {
  return {
    reviewId: evidence.review_id,
    reviewRunId: evidence.review_run_id,
    reviewVersion: evidence.review_version_name,
    trainingEvidenceHash: evidence.training_evidence_hash,
    outputArtifactHash: evidence.output_artifact_hash,
    split: evidence.split,
    windows: evidence.windows.map(mapQualityReviewWindow),
    status: evidence.status,
    reviewConclusion: evidence.review_conclusion,
    reviewedAt: evidence.reviewed_at,
    reviewHash: evidence.review_hash,
    promotionState: evidence.promotion_state,
    paperActivation: evidence.paper_activation,
    executionAuthority: evidence.execution_authority,
  }
}

function mapQualificationMetric(metric: LearnerQualificationMetric): LearnerQualificationMetricModel {
  return {
    windowId: metric.window_id,
    metricId: metric.metric_id,
    observed: metric.observed,
  }
}

function mapQualificationGate(gate: LearnerQualificationGate): LearnerQualificationGateModel {
  return {
    gateId: gate.gate_id,
    windowId: gate.window_id,
    metricId: gate.metric_id,
    passed: gate.passed,
    observed: gate.observed,
    threshold: gate.threshold,
    comparator: gate.comparator,
    reasonCode: gate.reason_code,
  }
}

function mapQualification(evidence: LearnerQualificationEvidence): LearnerQualificationModel {
  return {
    qualificationId: evidence.qualification_id,
    decision: evidence.decision,
    policyId: evidence.policy_id,
    policyHash: evidence.policy_hash,
    metrics: evidence.metrics.map(mapQualificationMetric),
    gates: evidence.gates.map(mapQualificationGate),
    windowsEvaluated: evidence.windows_evaluated,
    evaluatedAt: evidence.evaluated_at,
    qualificationHash: evidence.qualification_hash,
    promotionState: evidence.promotion_state,
    paperActivation: evidence.paper_activation,
    executionAuthority: evidence.execution_authority,
  }
}

function mapMetricQualityQualificationGate(
  gate: LearnerMetricQualityQualificationGate,
): LearnerMetricQualityQualificationGateModel {
  return {
    gateId: gate.gate_id,
    passed: gate.passed,
    observedWindows: gate.observed_windows,
    minimumWindows: gate.minimum_windows,
    sourceDecision: gate.source_decision,
    requiredDecision: gate.required_decision,
    reasonCode: gate.reason_code,
  }
}

function mapMetricQualityQualification(
  evidence: LearnerMetricQualityQualificationEvidence,
): LearnerMetricQualityQualificationModel {
  return {
    qualificationId: evidence.qualification_id,
    sourceDecision: evidence.source_decision,
    decision: evidence.decision,
    sourcePolicyId: evidence.source_policy_id,
    sourcePolicyHash: evidence.source_policy_hash,
    qualificationPolicyId: evidence.qualification_policy_id,
    qualificationPolicyHash: evidence.qualification_policy_hash,
    gates: evidence.gates.map(mapMetricQualityQualificationGate),
    windowsEvaluated: evidence.windows_evaluated,
    evaluatedAt: evidence.evaluated_at,
    qualificationHash: evidence.qualification_hash,
    promotionState: evidence.promotion_state,
    paperActivation: evidence.paper_activation,
    executionAuthority: evidence.execution_authority,
  }
}

export function buildLearnerModel(data: DashboardApiData): LearnerModel {
  const foundation = buildOverviewModel(data)
  const verified = foundation.verification === 'verified'
  const learnerArtifact = verified && data.learnerArtifact?.verified
    ? mapArtifact(data.learnerArtifact.artifact)
    : null
  const learnerRun = verified && data.learnerRun?.verified ? mapRun(data.learnerRun.run) : null
  const trainingEvidence = verified && data.learnerTrainingEvidence?.verified
    ? mapTrainingEvidence(data.learnerTrainingEvidence.evidence)
    : null
  const qualityReview = verified && data.learnerQualityReview?.verified
    ? mapQualityReview(data.learnerQualityReview.evidence)
    : null
  const qualification = verified && data.learnerQualification?.verified
    ? mapQualification(data.learnerQualification.evidence)
    : null
  const metricQualityQualification = verified && data.learnerMetricQualityQualification?.verified
    ? mapMetricQualityQualification(data.learnerMetricQualityQualification.evidence)
    : null
  const learnerArtifactStatus: LearnerEvidenceStatus = !verified
    ? 'unavailable'
    : learnerArtifact
      ? 'verified'
      : data.learnerArtifactError || data.learnerArtifact?.verified === false
        ? 'integrity_unavailable'
        : 'unavailable'
  const learningRunStatus: LearnerEvidenceStatus = !verified
    ? 'unavailable'
    : learnerRun
      ? 'verified'
      : data.learnerRunError || data.learnerRun?.verified === false
        ? 'integrity_unavailable'
        : 'unavailable'
  const trainingCompletionStatus: LearnerEvidenceStatus = !verified
    ? 'unavailable'
    : trainingEvidence
      ? 'verified'
      : data.learnerTrainingEvidenceError || data.learnerTrainingEvidence?.verified === false
        ? 'integrity_unavailable'
        : 'unavailable'
  const qualityReviewStatus: LearnerEvidenceStatus = !verified
    ? 'unavailable'
    : qualityReview
      ? 'verified'
      : data.learnerQualityReviewError || data.learnerQualityReview?.verified === false
        ? 'integrity_unavailable'
        : 'unavailable'
  const qualificationStatus: LearnerEvidenceStatus = !verified
    ? 'unavailable'
    : qualification
      ? 'verified'
      : data.learnerQualificationError || data.learnerQualification?.verified === false
        ? 'integrity_unavailable'
        : 'unavailable'
  const metricQualityQualificationStatus: LearnerEvidenceStatus = !verified
    ? 'unavailable'
    : metricQualityQualification
      ? 'verified'
      : data.learnerMetricQualityQualificationError
          || data.learnerMetricQualityQualification?.verified === false
        ? 'integrity_unavailable'
        : 'unavailable'

  return {
    status: verified ? 'verified' : 'unavailable',
    symbols: verified ? [...foundation.symbols] : [],
    primaryInterval: verified ? foundation.primaryInterval : null,
    contextInterval: verified ? foundation.contextInterval : null,
    contextFeaturePolicy: verified ? foundation.contextFeaturePolicy : null,
    bundleHash: verified ? foundation.bundleHash : null,
    registryHash: verified ? foundation.registryHash : null,
    learnerArtifactStatus,
    learningRunStatus,
    trainingCompletionStatus,
    qualityReviewStatus,
    qualificationStatus,
    metricQualityQualificationStatus,
    learnerArtifact,
    learnerRun,
    trainingEvidence,
    qualityReview,
    qualification,
    metricQualityQualification,
    paperActivation: false,
    executionAuthority: false,
  }
}
