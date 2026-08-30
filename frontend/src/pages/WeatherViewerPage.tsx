import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { getLatestRun, getRun, getRuns } from '../api/runs'
import { getStatus } from '../api/status'
import { getLatestCompletedVideo, getVideos } from '../api/videos'
import type {
  ForecastRunDetail,
  ForecastRunSummary,
  ServiceStatusResponse,
  VideoGeneration,
} from '../api/types'
import { ForecastTimeline } from '../components/ForecastTimeline'
import { ForecastVideoViewer } from '../components/ForecastVideoViewer'
import { RunSidebar } from '../components/RunSidebar'
import { VideoDrawer } from '../components/VideoDrawer'
import { useCurrentTime } from '../hooks/useCurrentTime'
import { useVideoPlayback } from '../hooks/useVideoPlayback'
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
    queryKey: ['forecast-run', runId ?? 'latest-video'],
    queryFn: () => (runId ? getRun(runId) : getInitialViewerRun()),
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

async function getInitialViewerRun(): Promise<ForecastRunDetail> {
  try {
    const runs = await getRuns(200)
    const video = await getLatestCompletedVideo(runs.runs.map((run) => run.run_id))
    if (video !== undefined) return await getRun(video.run_id)
  } catch {
    // Fall back to current weather when video history is temporarily unavailable.
  }
  return getLatestRun()
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
  const videosQuery = useQuery({
    queryKey: ['videos', run.run_id],
    queryFn: () => getVideos(run.run_id),
    refetchInterval: (query) =>
      query.state.data?.videos.some(
        (video) => video.status === 'pending' || video.status === 'rendering',
      )
        ? 1_000
        : 10_000,
  })
  const latestCompletedVideo = useMemo<VideoGeneration | undefined>(
    () =>
      videosQuery.data?.videos.find(
        (video) => video.status === 'completed' && video.file_url !== null,
      ),
    [videosQuery.data?.videos],
  )
  const renderingVideo = videosQuery.data?.videos.some(
    (video) => video.status === 'pending' || video.status === 'rendering',
  ) ?? false
  const videoFrames = useMemo(() => {
    if (!latestCompletedVideo) return []
    const endFrameIndex =
      latestCompletedVideo.end_frame_index ?? run.frames.at(-1)?.frame_index ?? -1
    return run.frames.filter(
      (frame) =>
        frame.validation_status === 'valid' &&
        frame.frame_index >= latestCompletedVideo.start_frame_index &&
        frame.frame_index <= endFrameIndex,
    )
  }, [latestCompletedVideo, run.frames])
  useEffect(() => {
    if (videoFrames.length === 0) return
    setSelectedFrameIndex((currentFrameIndex) => {
      if (videoFrames.some((frame) => frame.frame_index === currentFrameIndex)) {
        return currentFrameIndex
      }
      return selectFrameForOffset(
        videoFrames,
        run.resolved_start_time,
        requestedOffsetMinutes,
      )
    })
  }, [requestedOffsetMinutes, run.resolved_start_time, videoFrames])
  const selectFrame = useCallback((frameIndex: number) => {
    setSelectedFrameIndex(frameIndex)
  }, [])
  const playback = useVideoPlayback(
    latestCompletedVideo,
    videoFrames,
    selectedFrameIndex,
    selectFrame,
  )
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
  const timelineFrames = latestCompletedVideo ? videoFrames : run.frames

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="wordmark">MGW Weather</span>
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
        <ForecastVideoViewer
          key={latestCompletedVideo?.video_id ?? 'no-video'}
          video={latestCompletedVideo}
          selectedFrame={selectedFrame}
          startTime={run.resolved_start_time}
          timeZone={run.display_timezone}
          loading={videosQuery.isPending}
          rendering={renderingVideo}
          videoFailed={playback.videoFailed}
          isPlaying={playback.isPlaying}
          videoRef={playback.videoRef}
          onLoadedMetadata={playback.onLoadedMetadata}
          onTimeUpdate={playback.onTimeUpdate}
          onPlay={playback.onPlay}
          onPause={playback.onPause}
          onError={playback.onError}
          onPrevious={playback.previous}
          onNext={playback.next}
          onTogglePlayback={playback.isPlaying ? playback.pause : playback.play}
          onOpenVideos={() => setVideoDrawerOpen(true)}
        />
        <ForecastTimeline
          frames={timelineFrames}
          selectedFrameIndex={selectedFrameIndex}
          timeZone={run.display_timezone}
          isPlaying={playback.isPlaying}
          canPlay={playback.canPlay}
          canStepPrevious={playback.canStepPrevious}
          canStepNext={playback.canStepNext}
          disabled={!latestCompletedVideo || playback.videoFailed}
          playbackFps={latestCompletedVideo?.output_fps ?? null}
          onSelect={playback.seek}
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
          : 'No forecast time selected'}
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
          <span className="wordmark">MGW Weather</span>
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
