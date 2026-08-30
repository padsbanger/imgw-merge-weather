import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'

import { createVideo, deleteVideo, getVideos } from '../api/videos'
import type {
  ForecastRunDetail,
  VideoCreateRequest,
  VideoGeneration,
  VideoInterpolation,
  VideoMode,
  VideoSmoothing,
} from '../api/types'
import { formatLocalDate, formatLocalTime, formatUtcTime } from '../utils/time'

interface VideoDrawerProps {
  run: ForecastRunDetail
  open: boolean
  onClose: () => void
}

export function VideoDrawer({ run, open, onClose }: VideoDrawerProps) {
  const queryClient = useQueryClient()
  const frameIndices = useMemo(
    () => run.frames.map((frame) => frame.frame_index).sort((left, right) => left - right),
    [run.frames],
  )
  const [startFrameIndex, setStartFrameIndex] = useState(frameIndices[0] ?? 0)
  const [endFrameIndex, setEndFrameIndex] = useState(frameIndices.at(-1) ?? 0)
  const [sourceFps, setSourceFps] = useState(3)
  const [outputFps, setOutputFps] = useState(30)
  const [interpolation, setInterpolation] =
    useState<VideoSmoothing>('crossfade')
  const [mode, setMode] = useState<VideoMode>('source')
  const [timestampOverlay, setTimestampOverlay] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const videosQuery = useQuery({
    queryKey: ['videos', run.run_id],
    queryFn: () => getVideos(run.run_id),
    enabled: open,
    refetchInterval: (query) =>
      query.state.data?.videos.some(
        (video) => video.status === 'pending' || video.status === 'rendering',
      )
        ? 1_000
        : 10_000,
  })
  const createMutation = useMutation({
    mutationFn: (request: VideoCreateRequest) => createVideo(run.run_id, request),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['videos', run.run_id] })
    },
  })
  const deleteMutation = useMutation({
    mutationFn: deleteVideo,
    onSuccess: async () => {
      setConfirmDeleteId(null)
      await queryClient.invalidateQueries({ queryKey: ['videos', run.run_id] })
    },
  })

  if (!open) return null

  const rangeValid = startFrameIndex <= endFrameIndex
  const outputFpsValid =
    Number.isInteger(outputFps) && outputFps >= 15 && outputFps <= 60
  const selectedFrameCount = run.frames.filter(
    (frame) =>
      frame.validation_status === 'valid' &&
      frame.frame_index >= startFrameIndex &&
      frame.frame_index <= endFrameIndex,
  ).length
  const canGenerate =
    run.status === 'completed' &&
    selectedFrameCount > 0 &&
    rangeValid &&
    outputFpsValid

  function submitVideo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canGenerate) return
    createMutation.mutate({
      mode,
      source_fps: sourceFps,
      output_fps: outputFps,
      interpolation,
      start_frame_index: startFrameIndex,
      end_frame_index: endFrameIndex,
      timestamp_overlay: timestampOverlay,
    })
  }

  return (
    <div className="video-drawer-backdrop" onMouseDown={onClose}>
      <aside
        className="video-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="video-drawer-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="video-drawer-header">
          <div>
            <span className="eyebrow">Secondary output</span>
            <h2 id="video-drawer-title">Forecast videos</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close video panel">
            ×
          </button>
        </header>

        <form className="video-form" onSubmit={submitVideo}>
          <div className="video-run-readout">
            <span>RUN</span>
            <strong>
              {run.resolved_start_time
                ? `${formatLocalDate(run.resolved_start_time, run.display_timezone)} ${formatLocalTime(run.resolved_start_time, run.display_timezone)}`
                : 'Unresolved'}
            </strong>
            <small>{run.run_id}</small>
          </div>

          <fieldset className="video-presets">
            <legend>OUTPUT FORMAT</legend>
            <label className={mode === 'source' ? 'video-preset--selected' : ''}>
              <input
                type="radio"
                name="video-mode"
                value="source"
                checked={mode === 'source'}
                onChange={() => setMode('source')}
              />
              <span className="preset-shape preset-shape--source" />
              <strong>Source</strong>
              <small>Original map ratio</small>
            </label>
            <label className={mode === '1:1' ? 'video-preset--selected' : ''}>
              <input
                type="radio"
                name="video-mode"
                value="1:1"
                checked={mode === '1:1'}
                onChange={() => setMode('1:1')}
              />
              <span className="preset-shape preset-shape--square" />
              <strong>1:1</strong>
              <small>1080×1080 padded</small>
            </label>
          </fieldset>

          <div className="video-range-fields">
            <label>
              <span>FROM</span>
              <select
                aria-label="Video range start"
                value={startFrameIndex}
                onChange={(event) => setStartFrameIndex(Number(event.currentTarget.value))}
              >
                {run.frames.map((frame) => (
                  <option key={frame.frame_index} value={frame.frame_index}>
                    {formatLocalTime(frame.forecast_time, run.display_timezone)} ·{' '}
                    {formatUtcTime(frame.forecast_time)} ·{' '}
                    {formatRangeOffset(frame.forecast_time, run.resolved_start_time)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>TO</span>
              <select
                aria-label="Video range end"
                value={endFrameIndex}
                onChange={(event) => setEndFrameIndex(Number(event.currentTarget.value))}
              >
                {run.frames.map((frame) => (
                  <option key={frame.frame_index} value={frame.frame_index}>
                    {formatLocalTime(frame.forecast_time, run.display_timezone)} ·{' '}
                    {formatUtcTime(frame.forecast_time)} ·{' '}
                    {formatRangeOffset(frame.forecast_time, run.resolved_start_time)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {!rangeValid ? <p className="video-form-error">Range end precedes its start.</p> : null}
          {!outputFpsValid ? (
            <p className="video-form-error">Output FPS must be from 15 to 60.</p>
          ) : null}

          <fieldset className="video-speed-options">
            <legend>Animation speed</legend>
            {([
              ['Slow', 2],
              ['Normal', 3],
              ['Fast', 5],
            ] as const).map(([label, value]) => (
              <label key={label} className={sourceFps === value ? 'selected' : ''}>
                <input
                  type="radio"
                  name="animation-speed"
                  value={value}
                  checked={sourceFps === value}
                  onChange={() => setSourceFps(value)}
                />
                <strong>{label}</strong>
                <small>{value} frames/s</small>
              </label>
            ))}
          </fieldset>

          <fieldset className="video-smoothing-options">
            <legend>Motion smoothing</legend>
            <SmoothingOption
              value="none"
              label="None"
              description="Uses only original IMGW frames."
              selected={interpolation}
              onSelect={setInterpolation}
            />
            <SmoothingOption
              value="crossfade"
              label="Crossfade"
              description="Smoothly blends between consecutive IMGW frames."
              selected={interpolation}
              onSelect={setInterpolation}
            />
          </fieldset>

          <p className="video-interpolation-note">
            Interpolated frames are visual smoothing only. IMGW source data remains at
            10-minute intervals.
          </p>

          <p className="video-duration-estimate">
            Estimated duration <strong>{estimateDuration(selectedFrameCount, sourceFps)}</strong>
          </p>

          <details className="video-advanced-settings">
            <summary>Advanced settings</summary>
            <div className="video-options-row">
              <label>
                <span>OUTPUT FPS</span>
                <input
                  aria-label="Output FPS"
                  type="number"
                  min="15"
                  max="60"
                  value={outputFps}
                  onChange={(event) => setOutputFps(Number(event.currentTarget.value))}
                />
              </label>
              <label className="video-checkbox">
                <input
                  type="checkbox"
                  checked={timestampOverlay}
                  onChange={(event) => setTimestampOverlay(event.currentTarget.checked)}
                />
                Timestamp overlay
              </label>
            </div>
          </details>

          {createMutation.isError ? (
            <p className="video-form-error" role="alert">
              {createMutation.error.message}
            </p>
          ) : null}
          <button
            className="generate-video-submit"
            type="submit"
            disabled={!canGenerate || createMutation.isPending}
          >
            {createMutation.isPending ? 'Starting…' : 'Generate MP4'}
          </button>
        </form>

        <section className="video-outputs" aria-label="Generated videos">
          <div className="section-heading">
            <span>Outputs</span>
            <span>{videosQuery.data?.count ?? 0}</span>
          </div>
          {videosQuery.isPending ? <p className="video-empty">Loading videos…</p> : null}
          {videosQuery.isError ? (
            <p className="video-form-error" role="alert">
              Could not load video outputs.
            </p>
          ) : null}
          {videosQuery.data?.videos.length === 0 ? (
            <p className="video-empty">No videos generated for this run.</p>
          ) : null}
          {deleteMutation.isError ? (
            <p className="video-form-error" role="alert">
              {deleteMutation.error.message}
            </p>
          ) : null}
          {videosQuery.data?.videos.map((video) => (
            <VideoOutput
              key={video.video_id}
              video={video}
              timeZone={run.display_timezone}
              rangeLabel={formatVideoRange(video, run)}
              sourceFrameCount={sourceFrameCountForVideo(video, run)}
              weatherIntervalMinutes={run.interval_minutes}
              confirmDelete={confirmDeleteId === video.video_id}
              deleting={deleteMutation.isPending && confirmDeleteId === video.video_id}
              onAskDelete={() => setConfirmDeleteId(video.video_id)}
              onCancelDelete={() => setConfirmDeleteId(null)}
              onDelete={() => deleteMutation.mutate(video.video_id)}
            />
          ))}
        </section>
      </aside>
    </div>
  )
}

interface VideoOutputProps {
  video: VideoGeneration
  timeZone: string
  rangeLabel: string
  sourceFrameCount: number
  weatherIntervalMinutes: number
  confirmDelete: boolean
  deleting: boolean
  onAskDelete: () => void
  onCancelDelete: () => void
  onDelete: () => void
}

function VideoOutput({
  video,
  timeZone,
  rangeLabel,
  sourceFrameCount,
  weatherIntervalMinutes,
  confirmDelete,
  deleting,
  onAskDelete,
  onCancelDelete,
  onDelete,
}: VideoOutputProps) {
  const active = video.status === 'pending' || video.status === 'rendering'
  return (
    <article className={`video-output video-output--${video.status}`}>
      <header>
        <div>
          <strong>{video.mode === '1:1' ? '1:1 · SOCIAL' : 'SOURCE · MAP'}</strong>
          <small>
            {formatLocalDate(video.created_at, timeZone)} ·{' '}
            {formatLocalTime(video.created_at, timeZone)}
          </small>
        </div>
        <span>{video.status.toUpperCase()}</span>
      </header>
      {active ? (
        <div className="video-render-progress" role="status">
          <span>{video.status === 'pending' ? 'Queued for rendering…' : 'Rendering MP4…'}</span>
          <div><span /></div>
        </div>
      ) : null}
      {video.status === 'completed' && video.file_url ? (
        <video
          className="generated-video-player"
          controls
          preload="metadata"
          aria-label={`${video.mode} generated forecast video`}
          src={video.file_url}
        />
      ) : null}
      {video.status === 'failed' ? (
        <p className="video-output-error" role="status">{video.error ?? 'Video generation failed.'}</p>
      ) : null}
      <dl className="video-output-metadata">
        <div>
          <dt>RANGE</dt>
          <dd title={`frames ${video.start_frame_index}–${video.end_frame_index ?? 'end'}`}>
            {rangeLabel}
          </dd>
        </div>
        <div><dt>Source frames</dt><dd>{sourceFrameCount}</dd></div>
        <div><dt>Weather interval</dt><dd>{weatherIntervalMinutes} min</dd></div>
        <div><dt>Animation speed</dt><dd>{video.source_fps} frames/s</dd></div>
        <div><dt>Output</dt><dd>{video.output_fps} FPS</dd></div>
        <div><dt>Smoothing</dt><dd>{formatInterpolation(video.interpolation)}</dd></div>
        <div><dt>SIZE</dt><dd>{formatBytes(video.size_bytes)}</dd></div>
        <div><dt>FRAME</dt><dd>{video.width && video.height ? `${video.width}×${video.height}` : '—'}</dd></div>
        <div><dt>DURATION</dt><dd>{formatApproxDuration(video.duration_seconds)}</dd></div>
        <div><dt>OVERLAY</dt><dd>{video.timestamp_overlay ? 'TIME' : 'OFF'}</dd></div>
      </dl>
      <div className="video-output-actions">
        {video.file_url ? (
          <a href={video.file_url} download={video.output_filename}>Download</a>
        ) : null}
        {!active && !confirmDelete ? (
          <button type="button" onClick={onAskDelete}>Delete</button>
        ) : null}
        {confirmDelete ? (
          <>
            <button className="danger-action" type="button" onClick={onDelete} disabled={deleting}>
              {deleting ? 'Deleting…' : 'Confirm delete'}
            </button>
            <button type="button" onClick={onCancelDelete}>Cancel</button>
          </>
        ) : null}
      </div>
    </article>
  )
}

function formatBytes(value: number | null): string {
  if (value === null) return '—'
  if (value < 1_000_000) return `${Math.round(value / 1_000)} kB`
  return `${(value / 1_000_000).toFixed(2)} MB`
}

function estimateDuration(frameCount: number, sourceFps: number): string {
  if (frameCount <= 0 || sourceFps <= 0) return '—'
  return `~${(frameCount / sourceFps).toFixed(1)} s`
}

function formatApproxDuration(value: number | null): string {
  return value === null ? '—' : `~${value.toFixed(1)} s`
}

function formatInterpolation(interpolation: VideoInterpolation): string {
  if (interpolation === 'crossfade') return 'Crossfade'
  if (interpolation === 'motion') return 'Legacy (removed)'
  return 'None'
}

function sourceFrameCountForVideo(
  video: VideoGeneration,
  run: ForecastRunDetail,
): number {
  const endIndex = video.end_frame_index ?? run.frames.at(-1)?.frame_index ?? -1
  return run.frames.filter(
    (frame) =>
      frame.validation_status === 'valid' &&
      frame.frame_index >= video.start_frame_index &&
      frame.frame_index <= endIndex,
  ).length
}

interface SmoothingOptionProps {
  value: VideoSmoothing
  label: string
  description: string
  selected: VideoSmoothing
  onSelect: (value: VideoSmoothing) => void
}

function SmoothingOption({
  value,
  label,
  description,
  selected,
  onSelect,
}: SmoothingOptionProps) {
  return (
    <label className={selected === value ? 'selected' : ''}>
      <input
        type="radio"
        name="visual-smoothing"
        value={value}
        checked={selected === value}
        onChange={() => onSelect(value)}
      />
      <span>
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
    </label>
  )
}

function formatVideoRange(video: VideoGeneration, run: ForecastRunDetail): string {
  const start = run.frames.find((frame) => frame.frame_index === video.start_frame_index)
  const endIndex = video.end_frame_index ?? run.frames.at(-1)?.frame_index
  const end = run.frames.find((frame) => frame.frame_index === endIndex)
  if (!start || !end) return `${video.start_frame_index}–${video.end_frame_index ?? 'end'}`
  return `${formatLocalTime(start.forecast_time, run.display_timezone)}–${formatLocalTime(end.forecast_time, run.display_timezone)}`
}

function formatRangeOffset(timestamp: string, currentCycle: string | null): string {
  if (currentCycle === null) return '—'
  const minutes = Math.round(
    (new Date(timestamp).getTime() - new Date(currentCycle).getTime()) / 60_000,
  )
  if (minutes === 0) return 'NOW'
  const sign = minutes < 0 ? '-' : '+'
  const absoluteMinutes = Math.abs(minutes)
  const hours = Math.floor(absoluteMinutes / 60)
  const remainder = absoluteMinutes % 60
  return remainder === 0
    ? `${sign}${hours}h`
    : `${sign}${hours}h ${remainder}m`
}
