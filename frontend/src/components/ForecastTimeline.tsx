import type { ForecastFrame } from '../api/types'
import { formatLocalTime } from '../utils/time'

interface ForecastTimelineProps {
  frames: ForecastFrame[]
  selectedFrameIndex: number
  timeZone: string
  isPlaying: boolean
  canPlay: boolean
  canStepPrevious: boolean
  canStepNext: boolean
  disabled: boolean
  playbackFps: number | null
  onSelect: (frameIndex: number) => void
  onPrevious: () => void
  onNext: () => void
  onPlay: () => void
  onPause: () => void
}

export function ForecastTimeline({
  frames,
  selectedFrameIndex,
  timeZone,
  isPlaying,
  canPlay,
  canStepPrevious,
  canStepNext,
  disabled,
  playbackFps,
  onSelect,
  onPrevious,
  onNext,
  onPlay,
  onPause,
}: ForecastTimelineProps) {
  if (frames.length === 0) {
    return (
      <section className="timeline timeline--empty" aria-label="Forecast timeline">
        No forecast timestamps are available for this video.
      </section>
    )
  }
  const selectedPosition = Math.max(
    0,
    frames.findIndex((frame) => frame.frame_index === selectedFrameIndex),
  )
  const selectedFrame = frames[selectedPosition]

  return (
    <section className="timeline" aria-label="Forecast timeline">
      <div className="playback-controls">
        <button
          type="button"
          onClick={onPrevious}
          disabled={disabled || !canStepPrevious}
          aria-label="Previous forecast time"
        >
          ◀
        </button>
        {isPlaying ? (
          <button type="button" onClick={onPause} aria-label="Pause forecast video">
            Ⅱ
          </button>
        ) : (
          <button
            type="button"
            onClick={onPlay}
            disabled={disabled || !canPlay}
            aria-label="Play forecast video"
          >
            ▶
          </button>
        )}
        <button
          type="button"
          onClick={onNext}
          disabled={disabled || !canStepNext}
          aria-label="Next forecast time"
        >
          ▶|
        </button>
      </div>

      <div className="timeline-scroll">
        <div className="timeline-track" style={{ minWidth: `${Math.max(640, frames.length * 18)}px` }}>
          <input
            className="timeline-range"
            type="range"
            min="0"
            max={Math.max(0, frames.length - 1)}
            value={selectedPosition}
            disabled={disabled}
            onChange={(event) => onSelect(frames[Number(event.currentTarget.value)].frame_index)}
            aria-label="Select forecast time"
            aria-valuetext={
              selectedFrame ? formatLocalTime(selectedFrame.forecast_time, timeZone) : undefined
            }
          />
          <div
            className="timeline-ticks"
            style={{ gridTemplateColumns: `repeat(${Math.max(1, frames.length)}, 1fr)` }}
          >
            {frames.map((frame, position) => {
              const time = formatLocalTime(frame.forecast_time, timeZone)
              const major = position === 0 || position === frames.length - 1 || time.endsWith(':00')
              return (
                <button
                  className={`timeline-tick ${major ? 'timeline-tick--major' : ''}`}
                  type="button"
                  key={frame.frame_index}
                  onClick={() => onSelect(frame.frame_index)}
                  disabled={disabled || frame.validation_status !== 'valid'}
                  aria-label={`Forecast ${time}`}
                  aria-current={frame.frame_index === selectedFrameIndex ? 'time' : undefined}
                >
                  {major ? <span>{time}</span> : null}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      <div className="playback-rate" aria-label="Playback settings">
        <span>{playbackFps === null ? '— FPS' : `${playbackFps} FPS`}</span>
        <span>LOOP</span>
      </div>
    </section>
  )
}
