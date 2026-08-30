import { useCallback, useEffect, useRef, useState } from 'react'

import type { ForecastFrame, VideoGeneration } from '../api/types'

export function useVideoPlayback(
  video: VideoGeneration | undefined,
  frames: ForecastFrame[],
  selectedFrameIndex: number,
  onSelect: (frameIndex: number) => void,
) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [videoFailed, setVideoFailed] = useState(false)

  useEffect(() => {
    setIsPlaying(false)
    setVideoFailed(false)
  }, [video?.video_id])

  const seek = useCallback(
    (frameIndex: number) => {
      if (!video || frames.length === 0) return
      const position = frames.findIndex((frame) => frame.frame_index === frameIndex)
      if (position < 0) return
      if (videoRef.current) {
        videoRef.current.currentTime = position / video.source_fps
      }
      onSelect(frameIndex)
    },
    [frames, onSelect, video],
  )

  const selectAdjacent = useCallback(
    (direction: -1 | 1) => {
      const currentPosition = frames.findIndex(
        (frame) => frame.frame_index === selectedFrameIndex,
      )
      if (currentPosition < 0) return
      const nextPosition = Math.min(
        frames.length - 1,
        Math.max(0, currentPosition + direction),
      )
      seek(frames[nextPosition].frame_index)
    },
    [frames, seek, selectedFrameIndex],
  )

  const play = useCallback(() => {
    if (!videoRef.current || videoFailed) return
    try {
      const playRequest = videoRef.current.play()
      void playRequest?.catch(() => setIsPlaying(false))
    } catch {
      setIsPlaying(false)
    }
  }, [videoFailed])

  const pause = useCallback(() => {
    videoRef.current?.pause()
  }, [])

  const syncSelectedFrame = useCallback(() => {
    if (!video || !videoRef.current || frames.length === 0) return
    const position = Math.min(
      frames.length - 1,
      Math.max(
        0,
        Math.floor(videoRef.current.currentTime * video.source_fps + 0.001),
      ),
    )
    onSelect(frames[position].frame_index)
  }, [frames, onSelect, video])

  const seekToInitialFrame = useCallback(() => {
    seek(selectedFrameIndex)
  }, [seek, selectedFrameIndex])

  return {
    videoRef,
    isPlaying,
    videoFailed,
    canPlay: video !== undefined && frames.length > 1 && !videoFailed,
    canStepPrevious:
      frames.findIndex((frame) => frame.frame_index === selectedFrameIndex) > 0,
    canStepNext:
      frames.findIndex((frame) => frame.frame_index === selectedFrameIndex) >= 0 &&
      frames.findIndex((frame) => frame.frame_index === selectedFrameIndex) < frames.length - 1,
    seek,
    previous: () => selectAdjacent(-1),
    next: () => selectAdjacent(1),
    play,
    pause,
    onLoadedMetadata: seekToInitialFrame,
    onTimeUpdate: syncSelectedFrame,
    onPlay: () => setIsPlaying(true),
    onPause: () => setIsPlaying(false),
    onError: () => {
      setIsPlaying(false)
      setVideoFailed(true)
    },
  }
}
