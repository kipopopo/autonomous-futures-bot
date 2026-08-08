import type { DashboardApiData } from './dashboard'
import { buildOverviewModel } from './dashboard'

export type LearnerReadinessStatus = 'verified' | 'unavailable'

export interface LearnerModel {
  status: LearnerReadinessStatus
  symbols: string[]
  primaryInterval: string | null
  contextInterval: string | null
  contextFeaturePolicy: string | null
  bundleHash: string | null
  registryHash: string | null
  learnerArtifactStatus: 'unavailable'
  learningRunStatus: 'unavailable'
  paperActivation: false
  executionAuthority: false
}

export function buildLearnerModel(data: DashboardApiData): LearnerModel {
  const foundation = buildOverviewModel(data)
  const verified = foundation.verification === 'verified'

  return {
    status: verified ? 'verified' : 'unavailable',
    symbols: verified ? [...foundation.symbols] : [],
    primaryInterval: verified ? foundation.primaryInterval : null,
    contextInterval: verified ? foundation.contextInterval : null,
    contextFeaturePolicy: verified ? foundation.contextFeaturePolicy : null,
    bundleHash: verified ? foundation.bundleHash : null,
    registryHash: verified ? foundation.registryHash : null,
    learnerArtifactStatus: 'unavailable',
    learningRunStatus: 'unavailable',
    paperActivation: false,
    executionAuthority: false,
  }
}
