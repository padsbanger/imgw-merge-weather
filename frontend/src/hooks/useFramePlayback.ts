import { useEffect, useMemo, useState } from 'react'

import type { ForecastFrame } from '../api/types'

const PLAYBACK_INTERVAL_MS = 500

export function useFramePlayback(
  frames: ForecastFrame[],
  selectedFrameIndex: number,
  onSelect: (frameIndex: number) => void,
) {
  const [isPlaying, setIsPlaying] = useState(false)
  const validFrameIndices = useMemo(
    () => frames.filter((frame) => frame.validation_status === 'valid').map((frame) => frame.frame_index),
    [frames],
  )

  useEffect(() => {
    if (!isPlaying || validFrameIndices.length < 2) return
    const timer = window.setInterval(() => {
      const currentPosition = validFrameIndices.indexOf(selectedFrameIndex)
      const nextPosition = currentPosition < 0 ? 0 : (currentPosition + 1) % validFrameIndices.length
      onSelect(validFrameIndices[nextPosition])
    }, PLAYBACK_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [isPlaying, onSelect, selectedFrameIndex, validFrameIndices])

  function selectAdjacent(direction: -1 | 1) {
    if (validFrameIndices.length === 0) return
    const currentPosition = validFrameIndices.indexOf(selectedFrameIndex)
    const fallbackPosition = direction === 1 ? 0 : validFrameIndices.length - 1
    const nextPosition = Math.min(
      validFrameIndices.length - 1,
      Math.max(0, currentPosition < 0 ? fallbackPosition : currentPosition + direction),
    )
    onSelect(validFrameIndices[nextPosition])
  }

  return {
    isPlaying,
    canPlay: validFrameIndices.length > 1,
    play: () => setIsPlaying(true),
    pause: () => setIsPlaying(false),
    previous: () => selectAdjacent(-1),
    next: () => selectAdjacent(1),
    stop: () => setIsPlaying(false),
  }
}
