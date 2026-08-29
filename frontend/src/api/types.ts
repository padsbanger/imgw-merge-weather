export interface HealthResponse {
  status: string
  service: string
  version: string
}

export interface ServiceStatusResponse {
  service: string
  version: string
  milestone: number
  server_time: string
  weather_data_available: boolean
  refresh_in_progress: boolean
  last_refresh_at: string | null
  last_refresh_status: string | null
  last_imgw_error: string | null
  scheduler: {
    enabled: boolean
    state: string
    next_run_at: string | null
  }
}

export type ForecastRunStatus = 'pending' | 'probing' | 'downloading' | 'completed' | 'failed'
export type FrameValidationStatus = 'pending' | 'valid' | 'missing' | 'failed'
export type FreshnessState = 'FRESH' | 'DELAYED' | 'STALE'

export interface Freshness {
  state: FreshnessState
  reference_time: string
  age_seconds: number
}

export interface RunProgress {
  downloaded_frames: number
  expected_frames: number
  fraction: number
}

export interface ForecastFrame {
  frame_index: number
  forecast_time: string
  frame_url: string
  source_url: string
  width: number | null
  height: number | null
  size_bytes: number | null
  sha256: string | null
  validation_status: FrameValidationStatus
  error: string | null
}

export interface ForecastRunSummary {
  run_id: string
  discovered_at: string
  updated_at: string
  source: string
  product: string
  canonical_timezone: string
  display_timezone: string
  requested_start_time: string
  resolved_start_time: string | null
  forecast_end_time: string | null
  interval_minutes: number
  forecast_hours: number
  status: ForecastRunStatus
  progress: RunProgress
  coverage: number
  missing_timestamps: string[]
  error: string | null
  freshness: Freshness
  detail_url: string
}

export interface ForecastRunDetail extends ForecastRunSummary {
  frames: ForecastFrame[]
}

export interface ForecastRunListResponse {
  runs: ForecastRunSummary[]
  count: number
  latest_run_id: string | null
}

export interface RefreshAcceptedResponse {
  status: string
  detail: string
}
