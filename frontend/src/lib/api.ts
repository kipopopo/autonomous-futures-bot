import type {
  BundleResponse,
  ComponentsResponse,
  QualificationDetailResponse,
  CreatorQualificationsResponse,
  CreatorRegistryResponse,
  DashboardApiData,
  HealthResponse,
  LearnerArtifactResponse,
  LearnerMetricQualityQualificationEvidenceResponse,
  LearnerRunResponse,
  LearnerQualityReviewEvidenceResponse,
  LearnerQualificationEvidenceResponse,
  LearnerTrainingEvidenceResponse,
} from './dashboard'
import type {
  CanaryAccountingResponse,
  CanaryDashboardData,
  CanaryHawkesResponse,
  CanaryLiveMarketResponse,
  CanaryPaperExecutionResponse,
  CanaryRiskResponse,
  CanaryStrategyActivationResponse,
  CanarySummaryResponse,
} from './canary'

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

export async function fetchOptionalBundle(): Promise<BundleResponse | null> {
  const path = '/api/v1/dataset/bundle'
  try {
    const response = await fetch(path, { headers: { Accept: 'application/json' } })
    if (response.status === 404 || response.status === 503) return null
    if (!response.ok) return null
    return (await response.json()) as BundleResponse
  } catch {
    return null
  }
}

export async function fetchOptionalComponents(): Promise<ComponentsResponse | null> {
  const path = '/api/v1/dataset/components'
  try {
    const response = await fetch(path, { headers: { Accept: 'application/json' } })
    if (response.status === 404 || response.status === 503) return null
    if (!response.ok) return null
    return (await response.json()) as ComponentsResponse
  } catch {
    return null
  }
}

async function fetchOptionalCreatorRegistry(): Promise<CreatorRegistryResponse | null> {
  const path = '/api/v1/creator/registry'
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as CreatorRegistryResponse
}

async function fetchOptionalLearnerArtifact(): Promise<LearnerArtifactResponse | null> {
  const path = '/api/v1/learner/artifact'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as LearnerArtifactResponse
}

async function fetchOptionalLearnerRun(): Promise<LearnerRunResponse | null> {
  const path = '/api/v1/learner/run'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as LearnerRunResponse
}

async function fetchOptionalLearnerTrainingEvidence(): Promise<LearnerTrainingEvidenceResponse | null> {
  const path = '/api/v1/learner/training-evidence'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as LearnerTrainingEvidenceResponse
}

async function fetchOptionalLearnerQualityReview(): Promise<LearnerQualityReviewEvidenceResponse | null> {
  const path = '/api/v1/learner/quality-review'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as LearnerQualityReviewEvidenceResponse
}

async function fetchOptionalLearnerQualification(): Promise<LearnerQualificationEvidenceResponse | null> {
  const path = '/api/v1/learner/qualification'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as LearnerQualificationEvidenceResponse
}

async function fetchOptionalLearnerMetricQualityQualification(): Promise<
  LearnerMetricQualityQualificationEvidenceResponse | null
> {
  const path = '/api/v1/learner/metric-quality-qualification'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as LearnerMetricQualityQualificationEvidenceResponse
}

export async function fetchCreatorQualifications(): Promise<CreatorQualificationsResponse | null> {
  const path = '/api/v1/creator/qualifications'
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as CreatorQualificationsResponse
}

export async function fetchCreatorQualification(
  candidateId: string,
): Promise<QualificationDetailResponse | null> {
  const path = `/api/v1/creator/qualifications/${encodeURIComponent(candidateId)}`
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as QualificationDetailResponse
}

export async function fetchOverviewData(): Promise<DashboardApiData> {
  let health: HealthResponse | null = null
  try {
    health = await fetchJson<HealthResponse>('/health')
  } catch {
    health = null
  }

  const [bundle, components, creatorRegistry] = await Promise.all([
    fetchOptionalBundle(),
    fetchOptionalComponents(),
    fetchOptionalCreatorRegistry(),
  ])

  let creatorQualifications: CreatorQualificationsResponse | null = null
  let creatorQualificationError: string | null = null
  try {
    creatorQualifications = await fetchCreatorQualifications()
  } catch (error) {
    creatorQualificationError = error instanceof Error
      ? error.message
      : 'Qualification evidence could not be verified'
  }

  let learnerArtifact: LearnerArtifactResponse | null = null
  let learnerArtifactError: string | null = null
  try {
    learnerArtifact = await fetchOptionalLearnerArtifact()
  } catch (error) {
    learnerArtifactError = error instanceof Error
      ? error.message
      : 'Learner artifact evidence could not be verified'
  }

  let learnerRun: LearnerRunResponse | null = null
  let learnerRunError: string | null = null
  try {
    learnerRun = await fetchOptionalLearnerRun()
  } catch (error) {
    learnerRunError = error instanceof Error
      ? error.message
      : 'Learner run evidence could not be verified'
  }

  let learnerTrainingEvidence: LearnerTrainingEvidenceResponse | null = null
  let learnerTrainingEvidenceError: string | null = null
  try {
    learnerTrainingEvidence = await fetchOptionalLearnerTrainingEvidence()
  } catch (error) {
    learnerTrainingEvidenceError = error instanceof Error
      ? error.message
      : 'Training completion proof could not be verified'
  }

  let learnerQualityReview: LearnerQualityReviewEvidenceResponse | null = null
  let learnerQualityReviewError: string | null = null
  try {
    learnerQualityReview = await fetchOptionalLearnerQualityReview()
  } catch (error) {
    learnerQualityReviewError = error instanceof Error
      ? error.message
      : 'Learner quality review evidence could not be verified'
  }

  let learnerQualification: LearnerQualificationEvidenceResponse | null = null
  let learnerQualificationError: string | null = null
  try {
    learnerQualification = await fetchOptionalLearnerQualification()
  } catch (error) {
    learnerQualificationError = error instanceof Error
      ? error.message
      : 'Learner qualification evidence could not be verified'
  }

  let learnerMetricQualityQualification: LearnerMetricQualityQualificationEvidenceResponse | null = null
  let learnerMetricQualityQualificationError: string | null = null
  try {
    learnerMetricQualityQualification = await fetchOptionalLearnerMetricQualityQualification()
  } catch (error) {
    learnerMetricQualityQualificationError = error instanceof Error
      ? error.message
      : 'Metric-quality qualification evidence could not be verified'
  }

  return {
    health,
    bundle,
    components,
    creatorRegistry,
    creatorQualifications,
    creatorQualificationError,
    learnerArtifact,
    learnerArtifactError,
    learnerRun,
    learnerRunError,
    learnerTrainingEvidence,
    learnerTrainingEvidenceError,
    learnerQualityReview,
    learnerQualityReviewError,
    learnerQualification,
    learnerQualificationError,
    learnerMetricQualityQualification,
    learnerMetricQualityQualificationError,
  }
}

export async function fetchCanarySummary(): Promise<CanarySummaryResponse | null> {
  const path = '/api/v1/canary/summary'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as CanarySummaryResponse
}

export async function fetchCanaryHawkes(): Promise<CanaryHawkesResponse | null> {
  const path = '/api/v1/canary/hawkes'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as CanaryHawkesResponse
}

export async function fetchCanaryRisk(): Promise<CanaryRiskResponse | null> {
  const path = '/api/v1/canary/risk'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as CanaryRiskResponse
}

export async function fetchCanaryAccounting(): Promise<CanaryAccountingResponse | null> {
  const path = '/api/v1/canary/accounting'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as CanaryAccountingResponse
}

export async function fetchCanaryLiveMarket(): Promise<CanaryLiveMarketResponse | null> {
  const path = '/api/v1/canary/live-market'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as CanaryLiveMarketResponse
}

export async function fetchCanaryPaperExecution(): Promise<CanaryPaperExecutionResponse | null> {
  const path = '/api/v1/canary/paper-execution'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as CanaryPaperExecutionResponse
}

export async function fetchCanaryStrategyActivation(): Promise<CanaryStrategyActivationResponse | null> {
  const path = '/api/v1/canary/strategy-activation'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as CanaryStrategyActivationResponse
}

export async function fetchCanaryDashboardData(): Promise<CanaryDashboardData> {
  let summary: CanarySummaryResponse | null = null
  let hawkes: CanaryHawkesResponse | null = null
  let risk: CanaryRiskResponse | null = null
  let accounting: CanaryAccountingResponse | null = null
  let liveMarket: CanaryLiveMarketResponse | null = null
  let paperExecution: CanaryPaperExecutionResponse | null = null
  let strategyActivation: CanaryStrategyActivationResponse | null = null
  let error: string | null = null

  try {
    const results = await Promise.allSettled([
      fetchCanarySummary(),
      fetchCanaryHawkes(),
      fetchCanaryRisk(),
      fetchCanaryAccounting(),
      fetchCanaryLiveMarket(),
      fetchCanaryPaperExecution(),
      fetchCanaryStrategyActivation(),
    ])

    if (results[0].status === 'fulfilled') summary = results[0].value
    if (results[1].status === 'fulfilled') hawkes = results[1].value
    if (results[2].status === 'fulfilled') risk = results[2].value
    if (results[3].status === 'fulfilled') accounting = results[3].value
    if (results[4].status === 'fulfilled') liveMarket = results[4].value
    if (results[5].status === 'fulfilled') paperExecution = results[5].value
    if (results[6].status === 'fulfilled') strategyActivation = results[6].value

    for (const res of results) {
      if (res.status === 'rejected') {
        error = res.reason instanceof Error ? res.reason.message : 'Telemetry request failed'
        break
      }
    }
  } catch (err) {
    error = err instanceof Error ? err.message : 'Telemetry fetch failed'
  }

  return { summary, hawkes, risk, accounting, liveMarket, paperExecution, strategyActivation, error }
}
