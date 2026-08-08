export interface HealthResponse {
  status: 'ok'
  service: string
  paper_safe: boolean
  execution_authority: boolean
}

export interface BundleMetadata {
  symbols: string[]
  primary_interval: string
  context_interval: string
  context_feature_policy: string
  time_start: string
  time_end: string
}

export interface BundleResponse {
  verified: boolean
  registry_hash: string
  bundle_hash: string
  component_count: number
  bundle: BundleMetadata
}

export interface ComponentInspection {
  kind: string
  symbols: string[]
  interval: string | null
  artifact_ref: string
  data_ref: string | null
  manifest_hash: string
  artifact_sha256?: string | null
  rows?: number | null
  schema_version: string
}

export interface ComponentsResponse {
  verified: boolean
  component_count: number
  components: ComponentInspection[]
}

export interface CreatorCandidateRegistryEntry {
  candidate_id: string
  artifact_hash: string
  artifact_ref: string
  bundle_hash: string
  dataset_registry_hash: string
  strategy_id: string
  family: string
  symbols: string[]
  state: 'testing'
  creator_run_id: string
  created_at: string
}

export interface CreatorRegistryResponse {
  verified: boolean
  registry_hash: string
  candidate_count: number
  registry: {
    registry_version: 1
    venue: string
    created_at: string
    registry_hash: string
    entries: CreatorCandidateRegistryEntry[]
  }
}

export type QualificationDecision = 'rejected' | 'qualified'
export type QualificationSource = 'creator_evaluator' | 'walk_forward_oos'

export interface CreatorQualificationSummary {
  candidate_id: string
  decision: QualificationDecision
  source: QualificationSource
  qualification_hash: string
  evaluator_run_id: string
  evaluator_version: string
  windows_evaluated: number
  qualification_policy_id: string | null
  evaluated_at: string
  promotion_state: 'unpromoted'
  execution_authority: false
}

export interface CreatorQualificationsResponse {
  verified: boolean
  candidate_count: number
  qualification_count: number
  missing_candidate_ids: string[]
  qualifications: CreatorQualificationSummary[]
}

export type QualificationComparator = 'gte' | 'lte' | 'eq' | 'present' | 'bool'

export interface CreatorQualificationMetric {
  metric_id: string
  value: string
}

export interface CreatorQualificationGate {
  gate_id: string
  passed: boolean
  observed: string | null
  threshold: string | null
  comparator: QualificationComparator
  reason_code: string
}

export interface CreatorQualificationArtifact {
  qualification_version: 1
  candidate_id: string
  candidate_artifact_hash: string
  bundle_hash: string
  dataset_registry_hash: string
  evaluator_run_id: string
  evaluator_version: string
  decision: QualificationDecision
  metrics: CreatorQualificationMetric[]
  gates: CreatorQualificationGate[]
  windows_evaluated: number
  qualification_policy_id: string | null
  oos_aggregation_hash: string | null
  source: QualificationSource
  evaluated_at: string
  promotion_state: 'unpromoted'
  execution_authority: false
  qualification_hash: string
}

export interface QualificationDetailResponse {
  verified: boolean
  artifact: CreatorQualificationArtifact
}

export interface LearnerArtifactEvidence {
  artifact_version: 1
  learner_id: string
  candidate_id: string
  candidate_artifact_hash: string
  bundle_hash: string
  dataset_registry_hash: string
  symbols: string[]
  primary_interval: string
  context_interval: string
  learner_run_id: string
  learner_version: string
  model_family: string
  feature_ids: string[]
  training_window_start: string
  training_window_end: string
  model_artifact_ref: string
  model_artifact_hash: string
  state: 'testing'
  source: 'learner_research'
  data_source: 'cached_only'
  exchange_access: false
  promotion_state: 'unpromoted'
  paper_activation: false
  execution_authority: false
  created_at: string
  artifact_hash: string
}

export interface LearnerArtifactResponse {
  verified: boolean
  artifact: LearnerArtifactEvidence
}

export interface LearnerRunEvidence {
  run_version: 1
  run_id: string
  learner_id: string
  learner_run_id: string
  learner_version: string
  learner_artifact_hash: string
  candidate_id: string
  candidate_artifact_hash: string
  bundle_hash: string
  dataset_registry_hash: string
  input_window_ids: string[]
  input_symbols: string[]
  feature_ids: string[]
  training_window_start: string
  training_window_end: string
  status: 'prepared'
  output_artifact_hash: null
  training_metrics: null
  data_source: 'cached_only'
  exchange_access: false
  promotion_state: 'unpromoted'
  paper_activation: false
  execution_authority: false
  prepared_at: string
  run_hash: string
}

export interface LearnerRunResponse {
  verified: boolean
  run: LearnerRunEvidence
}

export interface LearnerTrainingEvidence {
  evidence_version: 1
  evidence_id: string
  prepared_run_id: string
  prepared_run_ref: string
  prepared_run_hash: string
  source_learner_artifact_ref: string
  source_learner_artifact_hash: string
  output_artifact_ref: string
  output_artifact_hash: string
  learner_id: string
  learner_run_id: string
  candidate_id: string
  candidate_artifact_hash: string
  bundle_hash: string
  dataset_registry_hash: string
  input_window_ids: string[]
  input_symbols: string[]
  feature_ids: string[]
  training_window_start: string
  training_window_end: string
  learner_version: string
  model_family: string
  status: 'completed'
  training_metrics: null
  data_source: 'cached_only'
  exchange_access: false
  promotion_state: 'unpromoted'
  paper_activation: false
  execution_authority: false
  created_at: string
  evidence_hash: string
}

export interface LearnerTrainingEvidenceResponse {
  verified: boolean
  evidence: LearnerTrainingEvidence
}

export interface LearnerQualityReviewMetric {
  metric_id: string
  value: string
}

export interface LearnerQualityReviewWindow {
  window_id: string
  symbol: string
  rows_evaluated: number
  metrics: LearnerQualityReviewMetric[]
}

export interface LearnerQualityReviewEvidence {
  review_version: 1
  review_id: string
  training_evidence_id: string
  training_evidence_hash: string
  output_artifact_hash: string
  learner_id: string
  learner_run_id: string
  candidate_id: string
  candidate_artifact_hash: string
  bundle_hash: string
  dataset_registry_hash: string
  review_run_id: string
  review_version_name: string
  split: 'holdout'
  windows: LearnerQualityReviewWindow[]
  status: 'completed'
  review_conclusion: 'observed_only'
  data_source: 'cached_only'
  exchange_access: false
  promotion_state: 'unpromoted'
  paper_activation: false
  execution_authority: false
  reviewed_at: string
  review_hash: string
}

export interface LearnerQualityReviewEvidenceResponse {
  verified: boolean
  evidence: LearnerQualityReviewEvidence
}

export type LearnerQualificationDecision = 'rejected' | 'qualified'
export type LearnerQualificationComparator = 'gte' | 'lte' | 'eq'

export interface LearnerQualificationMetric {
  window_id: string
  metric_id: string
  observed: string | null
}

export interface LearnerQualificationGate {
  gate_id: string
  window_id: string | null
  metric_id: string | null
  passed: boolean
  observed: string | null
  threshold: string
  comparator: LearnerQualificationComparator
  reason_code: string
}

export interface LearnerQualificationEvidence {
  qualification_version: 1
  qualification_id: string
  training_evidence_id: string
  training_evidence_hash: string
  quality_review_id: string
  quality_review_hash: string
  output_artifact_hash: string
  learner_id: string
  learner_run_id: string
  candidate_id: string
  candidate_artifact_hash: string
  bundle_hash: string
  dataset_registry_hash: string
  policy_id: string
  policy_hash: string
  decision: LearnerQualificationDecision
  metrics: LearnerQualificationMetric[]
  gates: LearnerQualificationGate[]
  windows_evaluated: number
  status: 'evaluated'
  data_source: 'cached_only'
  exchange_access: false
  promotion_state: 'unpromoted'
  paper_activation: false
  execution_authority: false
  evaluated_at: string
  qualification_hash: string
}

export interface LearnerQualificationEvidenceResponse {
  verified: boolean
  evidence: LearnerQualificationEvidence
}

export type LearnerMetricQualityDecision = 'failed' | 'passed'
export type LearnerMetricQualityQualificationDecision = 'rejected' | 'qualified'

export interface LearnerMetricQualityQualificationGate {
  gate_id: 'metric_quality_decision' | 'minimum_windows'
  passed: boolean
  observed_windows: number | null
  minimum_windows: number | null
  source_decision: LearnerMetricQualityDecision | null
  required_decision: 'passed' | null
  reason_code: string
}

export interface LearnerMetricQualityQualificationEvidence {
  qualification_version: 1
  qualification_id: string
  qualification_input_id: string
  qualification_input_hash: string
  decision_id: string
  decision_hash: string
  review_id: string
  review_hash: string
  metric_evaluation_run_id: string
  metric_evaluation_hash: string
  learner_id: string
  learner_artifact_hash: string
  candidate_id: string
  candidate_artifact_hash: string
  bundle_hash: string
  dataset_registry_hash: string
  source_policy_id: string
  source_policy_hash: string
  qualification_policy_id: string
  qualification_policy_hash: string
  source_decision: LearnerMetricQualityDecision
  decision: LearnerMetricQualityQualificationDecision
  gates: LearnerMetricQualityQualificationGate[]
  windows_evaluated: number
  status: 'evaluated'
  data_source: 'cached_only'
  exchange_access: false
  promotion_state: 'unpromoted'
  paper_activation: false
  execution_authority: false
  evaluated_at: string
  qualification_hash: string
}

export interface LearnerMetricQualityQualificationEvidenceResponse {
  verified: boolean
  evidence: LearnerMetricQualityQualificationEvidence
}

export interface DashboardApiData {
  health: HealthResponse | null
  bundle: BundleResponse | null
  components: ComponentsResponse | null
  creatorRegistry?: CreatorRegistryResponse | null
  creatorQualifications?: CreatorQualificationsResponse | null
  creatorQualificationError?: string | null
  learnerArtifact?: LearnerArtifactResponse | null
  learnerArtifactError?: string | null
  learnerRun?: LearnerRunResponse | null
  learnerRunError?: string | null
  learnerTrainingEvidence?: LearnerTrainingEvidenceResponse | null
  learnerTrainingEvidenceError?: string | null
  learnerQualityReview?: LearnerQualityReviewEvidenceResponse | null
  learnerQualityReviewError?: string | null
  learnerQualification?: LearnerQualificationEvidenceResponse | null
  learnerQualificationError?: string | null
  learnerMetricQualityQualification?: LearnerMetricQualityQualificationEvidenceResponse | null
  learnerMetricQualityQualificationError?: string | null
}

export type VerificationState = 'verified' | 'error'

export interface OverviewModel {
  verification: VerificationState
  paperSafe: boolean | null
  executionAuthority: boolean | null
  componentCount: number | null
  symbols: string[]
  bundleHash: string | null
  registryHash: string | null
  primaryInterval: string | null
  contextInterval: string | null
  contextFeaturePolicy: string | null
  timeStart: string | null
  timeEnd: string | null
  components: ComponentInspection[]
}

export function buildOverviewModel(data: DashboardApiData): OverviewModel {
  const verified =
    data.health?.status === 'ok' &&
    data.health.paper_safe === true &&
    data.health.execution_authority === false &&
    data.bundle?.verified === true &&
    data.components?.verified === true
  const bundle = data.bundle?.bundle

  return {
    verification: verified ? 'verified' : 'error',
    paperSafe: data.health?.paper_safe ?? null,
    executionAuthority: data.health?.execution_authority ?? null,
    componentCount: data.components?.component_count ?? data.bundle?.component_count ?? null,
    symbols: [...(bundle?.symbols ?? [])].sort(),
    bundleHash: data.bundle?.bundle_hash ?? null,
    registryHash: data.bundle?.registry_hash ?? null,
    primaryInterval: bundle?.primary_interval ?? null,
    contextInterval: bundle?.context_interval ?? null,
    contextFeaturePolicy: bundle?.context_feature_policy ?? null,
    timeStart: bundle?.time_start ?? null,
    timeEnd: bundle?.time_end ?? null,
    components: data.components?.components ?? [],
  }
}
