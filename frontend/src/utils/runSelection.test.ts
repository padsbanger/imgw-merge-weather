import { describe, expect, it } from 'vitest'

import type { ForecastFrame } from '../api/types'
import {
  frameOffsetMinutes,
  parseForecastOffset,
  selectFrameForOffset,
} from './runSelection'

function frame(
  frameIndex: number,
  forecastTime: string,
  validationStatus: ForecastFrame['validation_status'] = 'valid',
): ForecastFrame {
  return {
    frame_index: frameIndex,
    forecast_time: forecastTime,
    source_url: `https://cmm.imgw.pl/${frameIndex}.jpg`,
    width: validationStatus === 'valid' ? 1700 : null,
    height: validationStatus === 'valid' ? 1600 : null,
    size_bytes: validationStatus === 'valid' ? 400_000 : null,
    sha256: validationStatus === 'valid' ? 'a'.repeat(64) : null,
    validation_status: validationStatus,
    error: validationStatus === 'valid' ? null : 'missing',
  }
}

describe('forecast run selection', () => {
  it('parses bounded signed minute offsets', () => {
    expect(parseForecastOffset('120')).toBe(120)
    expect(parseForecastOffset('0')).toBe(0)
    expect(parseForecastOffset('-120')).toBe(-120)
    expect(parseForecastOffset('10.5')).toBeNull()
    expect(parseForecastOffset('1441')).toBeNull()
    expect(parseForecastOffset('-1441')).toBeNull()
    expect(parseForecastOffset(null)).toBeNull()
  })

  it('selects the same offset and falls back to the nearest valid frame', () => {
    const frames = [
      frame(0, '2026-08-29T09:00:00Z'),
      frame(1, '2026-08-29T09:10:00Z', 'missing'),
      frame(2, '2026-08-29T09:20:00Z'),
    ]

    expect(selectFrameForOffset(frames, frames[0].forecast_time, 20)).toBe(2)
    expect(selectFrameForOffset(frames, frames[0].forecast_time, 10)).toBe(0)
    expect(selectFrameForOffset(frames, frames[0].forecast_time, null)).toBe(0)
  })

  it('calculates an offset from the selected frame', () => {
    const selected = frame(2, '2026-08-29T09:20:00Z')
    expect(frameOffsetMinutes(selected, '2026-08-29T09:00:00Z')).toBe(20)
    expect(frameOffsetMinutes(selected, '2026-08-29T10:00:00Z')).toBe(-40)
    expect(frameOffsetMinutes(undefined, '2026-08-29T09:00:00Z')).toBeNull()
  })

  it('defaults to the current cycle when frames include lookback history', () => {
    const frames = [
      frame(0, '2026-08-29T08:00:00Z'),
      frame(1, '2026-08-29T09:00:00Z'),
      frame(2, '2026-08-29T10:00:00Z'),
    ]

    expect(selectFrameForOffset(frames, '2026-08-29T10:00:00Z', null)).toBe(2)
    expect(selectFrameForOffset(frames, '2026-08-29T10:00:00Z', -120)).toBe(0)
  })
})
