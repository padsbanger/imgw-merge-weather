import { getJson } from './client'
import type { HealthResponse, ServiceStatusResponse } from './types'

export function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>('/health')
}

export function getStatus(): Promise<ServiceStatusResponse> {
  return getJson<ServiceStatusResponse>('/api/status')
}
