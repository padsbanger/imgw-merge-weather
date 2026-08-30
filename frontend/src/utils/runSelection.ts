import type { ForecastFrame } from '../api/types'

const MAX_FORECAST_OFFSET_MINUTES = 24 * 60

export function parseForecastOffset(value: string | null): number | null {
  if (value === null || !/^-?\d+$/.test(value)) return null
  const offset = Number(value)
  return Number.isSafeInteger(offset) && Math.abs(offset) <= MAX_FORECAST_OFFSET_MINUTES
    ? offset
    : null
}

export function frameOffsetMinutes(
  frame: ForecastFrame | undefined,
  startTimestamp: string | null,
): number | null {
  if (frame === undefined || startTimestamp === null) return null
  const offset = Math.round(
    (new Date(frame.forecast_time).getTime() - new Date(startTimestamp).getTime()) / 60_000,
  )
  return Number.isFinite(offset) ? offset : null
}

export function selectFrameForOffset(
  frames: ForecastFrame[],
  startTimestamp: string | null,
  requestedOffsetMinutes: number | null,
): number {
  const validFrames = frames.filter((frame) => frame.validation_status === 'valid')
  if (validFrames.length === 0) return frames[0]?.frame_index ?? 0
  if (startTimestamp === null) {
    return validFrames[0].frame_index
  }

  const startTime = new Date(startTimestamp).getTime()
  const targetTime = startTime + (requestedOffsetMinutes ?? 0) * 60_000
  return validFrames.reduce((closest, frame) => {
    const distance = Math.abs(new Date(frame.forecast_time).getTime() - targetTime)
    const closestDistance = Math.abs(
      new Date(closest.forecast_time).getTime() - targetTime,
    )
    return distance < closestDistance ? frame : closest
  }).frame_index
}
