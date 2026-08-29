import { useQuery } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { getLatestRun, getRun, getRuns } from '../api/runs'
import { getStatus } from '../api/status'
import type {
  ForecastRunDetail,
  ForecastRunSummary,
  ServiceStatusResponse,
} from '../api/types'
import { ForecastTimeline } from '../components/ForecastTimeline'
import { RunSidebar } from '../components/RunSidebar'
import { VideoDrawer } from '../components/VideoDrawer'
import { WeatherFrameViewer } from '../components/WeatherFrameViewer'
import { useCurrentTime } from '../hooks/useCurrentTime'
import { useFramePlayback } from '../hooks/useFramePlayback'
import { deriveLiveDataState } from '../utils/liveStatus'
import {
  frameOffsetMinutes,
  parseForecastOffset,
  selectFrameForOffset,
} from '../utils/runSelection'
import { formatAge, formatLocalClock, formatLocalTime } from '../utils/time'

export function WeatherViewerPage() {
  const { runId } = useParams<{ runId: string }>()
  const [searchParams] = useSearchParams()
  const requestedOffsetMinutes = parseForecastOffset(searchParams.get('offset'))
  const runQuery = useQuery({
    queryKey: ['forecast-run', runId ?? 'latest'],
    queryFn: () => (runId ? getRun(runId) : getLatestRun()),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'pending' || status === 'probing' || status === 'downloading'
        ? 1_000
        : 60_000
    },
  })
  const runsQuery = useQuery({
    queryKey: ['forecast-runs'],
    queryFn: () => getRuns(20),
    refetchInterval: 10_000,
  })
  const statusQuery = useQuery({
    queryKey: ['service-status'],
    queryFn: getStatus,
    refetchInterval: 5_000,
    retry: 1,
  })

  if (runQuery.isPending) return <ViewerState state="loading" />
  if (runQuery.isError && !runQuery.data) {
    return <ViewerState state="error" onRetry={() => runQuery.refetch()} />
  }

  return (
    <ForecastWorkspace
      key={`${runQuery.data.run_id}:${requestedOffsetMinutes ?? 'start'}`}
      run={runQuery.data}
      runs={runsQuery.data?.runs ?? [runQuery.data]}
      latestRunId={runsQuery.data?.latest_run_id ?? (runId ? null : runQuery.data.run_id)}
      serviceStatus={statusQuery.data}
      backendState={
        statusQuery.isError ? 'offline' : statusQuery.isPending ? 'checking' : 'online'
      }
      requestedOffsetMinutes={requestedOffsetMinutes}
    />
  )
}

interface ForecastWorkspaceProps {
  run: ForecastRunDetail
  runs: ForecastRunSummary[]
  latestRunId: string | null
  serviceStatus: ServiceStatusResponse | undefined
  backendState: 'checking' | 'online' | 'offline'
  requestedOffsetMinutes: number | null
}

function ForecastWorkspace({
  run,
  runs,
  latestRunId,
  serviceStatus,
  backendState,
  requestedOffsetMinutes,
}: ForecastWorkspaceProps) {
  const initialFrameIndex = useMemo(
    () =>
      selectFrameForOffset(
        run.frames,
        run.resolved_start_time,
        requestedOffsetMinutes,
      ),
    [requestedOffsetMinutes, run.frames, run.resolved_start_time],
  )
  const [selectedFrameIndex, setSelectedFrameIndex] = useState(initialFrameIndex)
  const [videoDrawerOpen, setVideoDrawerOpen] = useState(false)
  const selectFrame = useCallback((frameIndex: number) => setSelectedFrameIndex(frameIndex), [])
  const playback = useFramePlayback(run.frames, selectedFrameIndex, selectFrame)
  const currentTime = useCurrentTime()
  const liveState = deriveLiveDataState({
    backendReachable: backendState !== 'offline',
    isLatest: run.run_id === latestRunId,
    freshness: run.freshness.state,
  })

  const selectedFrame = run.frames.find(
    (frame) => frame.frame_index === selectedFrameIndex,
  )
  const selectedOffsetMinutes = frameOffsetMinutes(selectedFrame, run.resolved_start_time)

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="wordmark">imgw-merge-weather</span>
          <span className="product-label">MERGE · POLAND</span>
        </Link>
        <nav className="topnav" aria-label="Primary navigation">
          <Link to="/">Latest forecast</Link>
          <a href="#forecast-runs">History</a>
        </nav>
        <div className="live-cluster">
          <time className="current-clock" dateTime={currentTime.toISOString()}>
            <small>WARSAW</small>
            {formatLocalClock(currentTime, run.display_timezone)}
          </time>
          <div className={`live-state live-state--${liveState.toLowerCase()}`}>
            <span className="status-dot" aria-hidden="true" />
            <span>
              {liveState} · {formatAge(run.freshness.age_seconds)}
            </span>
          </div>
        </div>
      </header>

      <main className="weather-layout">
        <WeatherFrameViewer
          key={selectedFrame?.frame_url ?? 'no-frame'}
          frame={selectedFrame}
          startTime={run.resolved_start_time}
          timeZone={run.display_timezone}
          onPrevious={playback.previous}
          onNext={playback.next}
        />
        <ForecastTimeline
          frames={run.frames}
          selectedFrameIndex={selectedFrameIndex}
          timeZone={run.display_timezone}
          isPlaying={playback.isPlaying}
          canPlay={playback.canPlay}
          onSelect={selectFrame}
          onPrevious={playback.previous}
          onNext={playback.next}
          onPlay={playback.play}
          onPause={playback.pause}
        />
        <RunSidebar
          run={run}
          runs={runs}
          latestRunId={latestRunId}
          liveState={liveState}
          serviceStatus={serviceStatus}
          backendState={backendState}
          selectedOffsetMinutes={selectedOffsetMinutes}
          onOpenVideos={() => setVideoDrawerOpen(true)}
        />
      </main>

      <VideoDrawer
        run={run}
        open={videoDrawerOpen}
        onClose={() => setVideoDrawerOpen(false)}
      />

      <div className="sr-only" aria-live="polite">
        {selectedFrame
          ? `Selected forecast ${formatLocalTime(selectedFrame.forecast_time, run.display_timezone)}`
          : 'No forecast frame selected'}
      </div>
    </div>
  )
}

interface ViewerStateProps {
  state: 'loading' | 'error'
  onRetry?: () => void
}

function ViewerState({ state, onRetry }: ViewerStateProps) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="wordmark">imgw-merge-weather</span>
          <span className="product-label">MERGE · POLAND</span>
        </Link>
        <div className={`live-state live-state--${state}`}>
          <span className="status-dot" aria-hidden="true" />
          <span>{state === 'loading' ? 'CONNECTING' : 'OFFLINE'}</span>
        </div>
      </header>
      <main className="viewer-state">
        <span className="eyebrow">IMGW CMM · MERGE</span>
        <h1>{state === 'loading' ? 'Loading latest forecast' : 'Forecast unavailable'}</h1>
        <p>
          {state === 'loading'
            ? 'Reading the latest persisted forecast run.'
            : 'The backend could not provide the requested forecast run.'}
        </p>
        {state === 'error' ? (
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </main>
    </div>
  )
}
