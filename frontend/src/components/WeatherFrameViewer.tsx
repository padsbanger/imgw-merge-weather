import { useState } from 'react'
import type { KeyboardEvent } from 'react'

import type { ForecastFrame } from '../api/types'
import {
  formatForecastOffset,
  formatLocalDate,
  formatLocalTime,
  formatUtcTime,
} from '../utils/time'

interface WeatherFrameViewerProps {
  frame: ForecastFrame | undefined
  startTime: string | null
  timeZone: string
  onPrevious: () => void
  onNext: () => void
}

export function WeatherFrameViewer({
  frame,
  startTime,
  timeZone,
  onPrevious,
  onNext,
}: WeatherFrameViewerProps) {
  const [imageFailed, setImageFailed] = useState(false)
  const available = frame?.validation_status === 'valid' && !imageFailed

  function handleKeyboard(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      onPrevious()
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      onNext()
    }
  }

  return (
    <section
      className="viewer"
      aria-label="MERGE precipitation forecast viewer"
      tabIndex={0}
      onKeyDown={handleKeyboard}
    >
      {available && frame ? (
        <img
          key={frame.frame_url}
          className="forecast-image"
          src={frame.frame_url}
          alt={`IMGW MERGE precipitation forecast for ${formatLocalTime(frame.forecast_time, timeZone)}`}
          draggable={false}
          onError={() => setImageFailed(true)}
          onLoad={() => setImageFailed(false)}
        />
      ) : (
        <div className="viewer-message" role="status">
          <span className="eyebrow">IMGW CMM · MERGE</span>
          <strong>{imageFailed ? 'Frame could not be loaded' : 'Frame unavailable'}</strong>
          <span>No substitute weather data is shown.</span>
        </div>
      )}

      {frame ? (
        <div className="frame-readout">
          <div>
            <span className="frame-date">{formatLocalDate(frame.forecast_time, timeZone)}</span>
            <strong>{formatLocalTime(frame.forecast_time, timeZone)}</strong>
            <span>{formatUtcTime(frame.forecast_time)}</span>
          </div>
          <div className="frame-offset">
            <span>FORECAST OFFSET</span>
            <strong>{formatForecastOffset(frame.forecast_time, startTime)}</strong>
          </div>
        </div>
      ) : null}
    </section>
  )
}
