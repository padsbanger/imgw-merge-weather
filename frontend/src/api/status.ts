import { getJson } from './client'
import type { HealthResponse } from './types'

export function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>('/health')
}

