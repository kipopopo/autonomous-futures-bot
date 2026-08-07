export type DashboardPage = 'overview' | 'creator'

export function pageFromHash(hash: string): DashboardPage {
  const normalized = hash.replace(/^#\/?/, '')
  return normalized === 'creator' ? 'creator' : 'overview'
}
