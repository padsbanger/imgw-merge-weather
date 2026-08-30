import { deleteJson, getJson, postJson } from './client'
import type {
  VideoCreateRequest,
  VideoDeleteResponse,
  VideoGeneration,
  VideoGenerationListResponse,
} from './types'

export function getVideos(
  runId?: string,
  limit = 50,
): Promise<VideoGenerationListResponse> {
  const runFilter = runId === undefined ? '' : `&run_id=${encodeURIComponent(runId)}`
  return getJson<VideoGenerationListResponse>(
    `/api/videos?limit=${limit}${runFilter}`,
  )
}

export async function getLatestCompletedVideo(
  runIdsNewestFirst?: readonly string[],
): Promise<VideoGeneration | undefined> {
  const response = await getVideos(undefined, 200)
  const completed = response.videos.filter(
    (video) => video.status === 'completed' && video.file_url !== null,
  )
  if (runIdsNewestFirst === undefined) return completed[0]

  const videoByRun = new Map<string, VideoGeneration>()
  for (const video of completed) {
    if (!videoByRun.has(video.run_id)) videoByRun.set(video.run_id, video)
  }
  for (const runId of runIdsNewestFirst) {
    const video = videoByRun.get(runId)
    if (video !== undefined) return video
  }
  return completed[0]
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
