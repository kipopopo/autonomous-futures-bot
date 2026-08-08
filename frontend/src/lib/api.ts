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

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as T
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
  const [health, bundle, components, creatorRegistry] = await Promise.all([
    fetchJson<HealthResponse>('/health'),
    fetchJson<BundleResponse>('/api/v1/dataset/bundle'),
    fetchJson<ComponentsResponse>('/api/v1/dataset/components'),
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
