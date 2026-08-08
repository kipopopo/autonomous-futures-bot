export type DashboardPage = 'overview' | 'creator' | 'learner'

export function pageFromHash(hash: string): DashboardPage {
  const normalized = hash.replace(/^#\/?/, '')
  if (normalized === 'creator') return 'creator'
  if (normalized === 'learner') return 'learner'
  return 'overview'
}
