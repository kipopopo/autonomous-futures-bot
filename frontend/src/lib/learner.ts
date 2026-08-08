import type {
  DashboardApiData,
  LearnerArtifactEvidence,
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
  learnerArtifact: LearnerArtifactModel | null
  learnerRun: LearnerRunModel | null
  trainingEvidence: LearnerTrainingEvidenceModel | null
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
    learnerArtifact,
    learnerRun,
    trainingEvidence,
    paperActivation: false,
    executionAuthority: false,
  }
}
