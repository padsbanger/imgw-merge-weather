import type { KeyboardEvent, RefObject } from 'react'

import type { ForecastFrame, VideoGeneration } from '../api/types'
import {
  formatForecastOffset,
  formatLocalDate,
  formatLocalTime,
  formatUtcTime,
} from '../utils/time'

interface ForecastVideoViewerProps {
  video: VideoGeneration | undefined
  selectedFrame: ForecastFrame | undefined
  startTime: string | null
  timeZone: string
  loading: boolean
  rendering: boolean
  videoFailed: boolean
  isPlaying: boolean
  videoRef: RefObject<HTMLVideoElement | null>
  onLoadedMetadata: () => void
  onTimeUpdate: () => void
  onPlay: () => void
  onPause: () => void
  onError: () => void
  onPrevious: () => void
  onNext: () => void
  onTogglePlayback: () => void
  onOpenVideos: () => void
}

export function ForecastVideoViewer({
  video,
  selectedFrame,
  startTime,
  timeZone,
  loading,
  rendering,
  videoFailed,
  isPlaying,
  videoRef,
  onLoadedMetadata,
  onTimeUpdate,
  onPlay,
  onPause,
  onError,
  onPrevious,
  onNext,
  onTogglePlayback,
  onOpenVideos,
}: ForecastVideoViewerProps) {
  function handleKeyboard(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      onPrevious()
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      onNext()
    }
    if (event.key === ' ') {
      event.preventDefault()
      onTogglePlayback()
    }
  }

  return (
    <section
      className="viewer"
      aria-label="MERGE precipitation forecast video viewer"
      tabIndex={0}
      onKeyDown={handleKeyboard}
    >
      <div className="forecast-media-stage">
        {video?.file_url && !videoFailed ? (
          <video
            ref={videoRef}
            key={video.video_id}
            className="forecast-video"
            src={video.file_url}
            aria-label="Generated forecast video"
            autoPlay
            loop
            muted
            playsInline
            preload="auto"
            onClick={onTogglePlayback}
            onLoadedMetadata={onLoadedMetadata}
            onTimeUpdate={onTimeUpdate}
            onPlay={onPlay}
            onPause={onPause}
            onError={onError}
          />
        ) : (
          <div className="viewer-message" role="status">
            <span className="eyebrow">IMGW CMM · MERGE · VIDEO</span>
            <strong>
              {loading
                ? 'Loading forecast video'
                : rendering
                  ? 'Forecast video is rendering'
                  : videoFailed
                    ? 'Forecast video could not be played'
                    : 'No generated forecast video'}
            </strong>
            <span>
              {rendering
                ? 'The viewer will update when rendering completes.'
                : videoFailed
                  ? 'Open the video panel to retry, download, or generate another MP4.'
                  : 'Generate an MP4 to explore this forecast run.'}
            </span>
            {!loading ? (
              <button type="button" onClick={onOpenVideos}>
                {rendering
                  ? 'View video progress'
                  : videoFailed
                    ? 'Open video panel'
                    : 'Generate video'}
              </button>
            ) : null}
          </div>
        )}
      </div>

      {video ? (
        <div className="generated-video-readout">
          <span>FORECAST VIDEO</span>
          <strong>
            {video.mode === '1:1' ? '1:1' : 'SOURCE'} · {video.output_fps} FPS
          </strong>
          <span>
            {formatLocalDate(video.created_at, timeZone)} ·{' '}
            {formatLocalTime(video.created_at, timeZone)}
          </span>
        </div>
      ) : null}

      {video && selectedFrame ? (
        <div className="forecast-readout">
          <div>
            <span className="forecast-date">
              {formatLocalDate(selectedFrame.forecast_time, timeZone)}
            </span>
            <strong>{formatLocalTime(selectedFrame.forecast_time, timeZone)}</strong>
            <span>{formatUtcTime(selectedFrame.forecast_time)}</span>
          </div>
          <div className="forecast-offset">
            <span>FORECAST OFFSET</span>
            <strong>{formatForecastOffset(selectedFrame.forecast_time, startTime)}</strong>
          </div>
        </div>
      ) : null}

      <span className="sr-only" aria-live="polite">
        {isPlaying ? 'Forecast video playing' : 'Forecast video paused'}
      </span>
    </section>
  )
}
