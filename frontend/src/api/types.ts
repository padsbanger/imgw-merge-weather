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
    state: 'disabled' | 'running' | 'stopped' | 'unavailable'
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

export type VideoGenerationStatus = 'pending' | 'rendering' | 'completed' | 'failed'
export type VideoMode = 'source' | '1:1'
export type VideoInterpolation = 'none' | 'crossfade' | 'motion'
export type VideoSmoothing = 'none' | 'crossfade'

export interface VideoGeneration {
  video_id: string
  run_id: string
  created_at: string
  updated_at: string
  status: VideoGenerationStatus
  mode: VideoMode
  source_fps: number
  output_fps: number
  interpolation: VideoInterpolation
  codec: string
  crf: number
  preset: string
  output_filename: string
  start_frame_index: number
  end_frame_index: number | null
  timestamp_overlay: boolean
  width: number | null
  height: number | null
  duration_seconds: number | null
  size_bytes: number | null
  error: string | null
  detail_url: string
  file_url: string | null
}

export interface VideoGenerationListResponse {
  videos: VideoGeneration[]
  count: number
}

export interface VideoCreateRequest {
  mode: VideoMode
  source_fps: number
  output_fps: number
  interpolation: VideoSmoothing
  start_frame_index: number
  end_frame_index: number
  timestamp_overlay: boolean
}

export interface VideoDeleteResponse {
  video_id: string
  status: 'deleted'
}
