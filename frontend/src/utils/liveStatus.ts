import type { FreshnessState } from '../api/types'

export type LiveDataState = 'LIVE' | FreshnessState | 'OFFLINE'

interface LiveStateInput {
  backendReachable: boolean
  isLatest: boolean
  freshness: FreshnessState
}

export function deriveLiveDataState({
  backendReachable,
  isLatest,
  freshness,
}: LiveStateInput): LiveDataState {
  if (!backendReachable) return 'OFFLINE'
  if (isLatest && freshness === 'FRESH') return 'LIVE'
  return freshness
}
