import { deleteJson, getJson, postJson } from './client'
import type {
  VideoCreateRequest,
  VideoDeleteResponse,
  VideoGeneration,
  VideoGenerationListResponse,
} from './types'

export function getVideos(runId: string): Promise<VideoGenerationListResponse> {
  return getJson<VideoGenerationListResponse>(
    `/api/videos?limit=50&run_id=${encodeURIComponent(runId)}`,
  )
}

export function createVideo(
  runId: string,
  request: VideoCreateRequest,
): Promise<VideoGeneration> {
  return postJson<VideoGeneration>(
    `/api/runs/${encodeURIComponent(runId)}/videos`,
    request,
  )
}

export function deleteVideo(videoId: string): Promise<VideoDeleteResponse> {
  return deleteJson<VideoDeleteResponse>(`/api/videos/${encodeURIComponent(videoId)}`)
}
