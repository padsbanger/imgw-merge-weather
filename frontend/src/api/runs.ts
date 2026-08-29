import { getJson, postJson } from './client'
import type {
  ForecastRunDetail,
  ForecastRunListResponse,
  RefreshAcceptedResponse,
} from './types'

export function getRuns(limit = 50): Promise<ForecastRunListResponse> {
  return getJson<ForecastRunListResponse>(`/api/runs?limit=${limit}`)
}

export function getLatestRun(): Promise<ForecastRunDetail> {
  return getJson<ForecastRunDetail>('/api/runs/latest')
}

export function getRun(runId: string): Promise<ForecastRunDetail> {
  return getJson<ForecastRunDetail>(`/api/runs/${encodeURIComponent(runId)}`)
}

export function refreshRuns(): Promise<RefreshAcceptedResponse> {
  return postJson<RefreshAcceptedResponse>('/api/runs/refresh')
}
