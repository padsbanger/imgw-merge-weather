import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type {
  ForecastFrame,
  ForecastRunDetail,
  ForecastRunListResponse,
  ServiceStatusResponse,
  VideoCreateRequest,
  VideoGeneration,
} from './api/types'
import App from './App'

const frameTimes = [
  '2026-08-29T10:00:00Z',
  '2026-08-29T10:10:00Z',
  '2026-08-29T10:20:00Z',
]

function makeFrames(runId: string): ForecastFrame[] {
  return frameTimes.map((forecastTime, frameIndex) => ({
    frame_index: frameIndex,
    forecast_time: forecastTime,
    frame_url: `/api/runs/${runId}/frames/${frameIndex}`,
    source_url: `https://cmm.imgw.pl/frame-${frameIndex}.jpg`,
    width: 1700,
    height: 1600,
    size_bytes: 450_000,
    sha256: String(frameIndex).repeat(64),
    validation_status: 'valid',
    error: null,
  }))
}

function makeRun(runId = 'merge_latest'): ForecastRunDetail {
  return {
    run_id: runId,
    discovered_at: '2026-08-29T10:01:00Z',
    updated_at: '2026-08-29T10:02:00Z',
    source: 'IMGW CMM',
    product: 'MERGE',
    canonical_timezone: 'UTC',
    display_timezone: 'Europe/Warsaw',
    requested_start_time: frameTimes[0],
    resolved_start_time: frameTimes[0],
    forecast_end_time: frameTimes[2],
    interval_minutes: 10,
    forecast_hours: 8,
    status: 'completed',
    progress: { downloaded_frames: 3, expected_frames: 3, fraction: 1 },
    coverage: 1,
    missing_timestamps: [],
    error: null,
    freshness: {
      state: 'FRESH',
      reference_time: frameTimes[0],
      age_seconds: 120,
    },
    detail_url: `/api/runs/${runId}`,
    frames: makeFrames(runId),
  }
}

function makeRunList(run: ForecastRunDetail): ForecastRunListResponse {
  const { frames: _frames, ...summary } = run
  void _frames
  return { runs: [summary], count: 1, latest_run_id: run.run_id }
}

function makeRunWithTimes(runId: string, times: string[]): ForecastRunDetail {
  const run = makeRun(runId)
  return {
    ...run,
    requested_start_time: times[0],
    resolved_start_time: times[0],
    forecast_end_time: times.at(-1) ?? times[0],
    frames: times.map((forecastTime, frameIndex) => ({
      ...makeFrames(runId)[0],
      frame_index: frameIndex,
      forecast_time: forecastTime,
      frame_url: `/api/runs/${runId}/frames/${frameIndex}`,
      source_url: `https://cmm.imgw.pl/${runId}-${frameIndex}.jpg`,
      sha256: String(frameIndex).repeat(64),
    })),
  }
}

function jsonResponse(body: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: async () => body,
  })
}

function makeServiceStatus(): ServiceStatusResponse {
  return {
    service: 'imgw-merge-weather',
    version: '0.1.0',
    milestone: 11,
    server_time: '2026-08-29T10:02:00Z',
    weather_data_available: true,
    refresh_in_progress: false,
    last_refresh_at: '2026-08-29T10:01:00Z',
    last_refresh_status: 'completed',
    last_imgw_error: null,
    scheduler: { enabled: false, state: 'disabled', next_run_at: null },
  }
}

function makeVideo(
  videoId = 'video_complete1',
  status: VideoGeneration['status'] = 'completed',
): VideoGeneration {
  const completed = status === 'completed'
  return {
    video_id: videoId,
    run_id: 'merge_latest',
    created_at: '2026-08-29T10:03:00Z',
    updated_at: '2026-08-29T10:03:01Z',
    status,
    mode: 'source',
    fps: 5,
    codec: 'libx264',
    crf: 20,
    preset: 'medium',
    output_filename: `${videoId}.mp4`,
    start_frame_index: 0,
    end_frame_index: 2,
    timestamp_overlay: false,
    width: completed ? 1700 : null,
    height: completed ? 1600 : null,
    duration_seconds: completed ? 0.6 : null,
    size_bytes: completed ? 2_100 : null,
    error: null,
    detail_url: `/api/videos/${videoId}`,
    file_url: completed ? `/api/videos/${videoId}/file` : null,
  }
}

function mockVideoApi() {
  const run = makeRun()
  const listing = makeRunList(run)
  let videos = [makeVideo()]
  const createRequests: VideoCreateRequest[] = []
  const deletedIds: string[] = []

  vi.stubGlobal(
    'fetch',
    vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/runs/latest' || path === `/api/runs/${run.run_id}`) {
        return jsonResponse(run)
      }
      if (path === '/api/runs?limit=20') return jsonResponse(listing)
      if (path === '/api/status') return jsonResponse(makeServiceStatus())
      if (path === '/api/videos?limit=50&run_id=merge_latest') {
        return jsonResponse({ videos, count: videos.length })
      }
      if (path === '/api/runs/merge_latest/videos' && init?.method === 'POST') {
        const request = JSON.parse(String(init.body)) as VideoCreateRequest
        createRequests.push(request)
        const pending = {
          ...makeVideo('video_pending1', 'pending'),
          mode: request.mode,
          fps: request.fps,
          start_frame_index: request.start_frame_index,
          end_frame_index: request.end_frame_index,
          timestamp_overlay: request.timestamp_overlay,
        }
        videos = [pending, ...videos]
        return jsonResponse(pending, true, 202)
      }
      const deleteMatch = path.match(/^\/api\/videos\/(video_[a-z0-9]+)$/)
      if (deleteMatch && init?.method === 'DELETE') {
        deletedIds.push(deleteMatch[1])
        videos = videos.filter((video) => video.video_id !== deleteMatch[1])
        return jsonResponse({ video_id: deleteMatch[1], status: 'deleted' })
      }
      return jsonResponse({ detail: 'Not found' }, false, 404)
    }),
  )

  return { createRequests, deletedIds }
}

function mockForecastApi(
  run = makeRun(),
  statusAvailable = true,
  serviceStatus = makeServiceStatus(),
) {
  const listing = makeRunList(run)
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string | URL | Request) => {
      const path = String(input)
      if (path === '/api/runs/latest' || path === `/api/runs/${run.run_id}`) {
        return jsonResponse(run)
      }
      if (path === '/api/runs?limit=20') return jsonResponse(listing)
      if (path === '/api/status') {
        return statusAvailable
          ? jsonResponse(serviceStatus)
          : jsonResponse({ detail: 'Offline' }, false, 503)
      }
      return jsonResponse({ detail: 'Not found' }, false, 404)
    }),
  )
}

function mockRunHistory(runs: ForecastRunDetail[], latestRunId: string) {
  const listing: ForecastRunListResponse = {
    runs: runs.map(({ frames: _frames, ...summary }) => {
      void _frames
      return summary
    }),
    count: runs.length,
    latest_run_id: latestRunId,
  }
  const latest = runs.find((run) => run.run_id === latestRunId)
  if (latest === undefined) throw new Error('Latest test run is missing')

  vi.stubGlobal(
    'fetch',
    vi.fn((input: string | URL | Request) => {
      const path = String(input)
      if (path === '/api/runs/latest') return jsonResponse(latest)
      if (path === '/api/runs?limit=20') return jsonResponse(listing)
      if (path === '/api/status') return jsonResponse(makeServiceStatus())
      const run = runs.find((item) => path === `/api/runs/${item.run_id}`)
      return run === undefined
        ? jsonResponse({ detail: 'Not found' }, false, 404)
        : jsonResponse(run)
    }),
  )
}

function renderApp(route = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('weather viewer', () => {
  it('loads the latest run with weather image, freshness, timeline, and metadata', async () => {
    mockForecastApi()
    renderApp()

    const image = await screen.findByRole('img', {
      name: 'IMGW MERGE precipitation forecast for 12:00',
    })
    expect(image).toHaveAttribute('src', '/api/runs/merge_latest/frames/0')
    expect(screen.getByText('LIVE')).toBeInTheDocument()
    expect(screen.getByText('LIVE · 2 min ago')).toBeInTheDocument()
    expect(screen.getByText('LATEST')).toBeInTheDocument()
    expect(screen.getByText('3 / 3')).toBeInTheDocument()
    expect(screen.getAllByText('10:00 UTC')).toHaveLength(2)
    expect(screen.getByText('+00:00')).toBeInTheDocument()
    expect(screen.getByText('SOURCE UPDATE')).toBeInTheDocument()
    expect(screen.getByText('ONLINE')).toBeInTheDocument()
    expect(screen.getByText('DISABLED')).toBeInTheDocument()
    expect(screen.getByText('WARSAW')).toBeInTheDocument()
    expect(screen.getByRole('slider', { name: 'Select forecast frame' })).toHaveValue('0')
  })

  it('supports tick clicks, range scrubbing, buttons, and keyboard arrows', async () => {
    mockForecastApi()
    renderApp()
    await screen.findByRole('img', { name: /12:00/ })

    fireEvent.click(screen.getByRole('button', { name: 'Forecast 12:10' }))
    expect(screen.getByRole('img', { name: /12:10/ })).toHaveAttribute(
      'src',
      '/api/runs/merge_latest/frames/1',
    )

    fireEvent.change(screen.getByRole('slider', { name: 'Select forecast frame' }), {
      target: { value: '2' },
    })
    expect(screen.getByRole('img', { name: /12:20/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Previous forecast frame' }))
    expect(screen.getByRole('img', { name: /12:10/ })).toBeInTheDocument()

    fireEvent.keyDown(screen.getByLabelText('MERGE precipitation forecast viewer'), {
      key: 'ArrowRight',
    })
    expect(screen.getByRole('img', { name: /12:20/ })).toBeInTheDocument()
  })

  it('plays valid frames, pauses, and loops at the end', async () => {
    mockForecastApi()
    renderApp()
    await screen.findByRole('img', { name: /12:00/ })
    vi.useFakeTimers()

    fireEvent.click(screen.getByRole('button', { name: 'Play forecast animation' }))
    act(() => vi.advanceTimersByTime(500))
    expect(screen.getByRole('img', { name: /12:10/ })).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(500))
    expect(screen.getByRole('img', { name: /12:20/ })).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(500))
    expect(screen.getByRole('img', { name: /12:00/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Pause forecast animation' }))
    act(() => vi.advanceTimersByTime(1_000))
    expect(screen.getByRole('img', { name: /12:00/ })).toBeInTheDocument()
  })

  it('loads a specific historical run route', async () => {
    const historical = makeRun('merge_historical')
    mockForecastApi(historical)
    renderApp('/runs/merge_historical')

    const image = await screen.findByRole('img', { name: /12:00/ })
    expect(image).toHaveAttribute('src', '/api/runs/merge_historical/frames/0')
    expect(fetch).toHaveBeenCalledWith('/api/runs/merge_historical', {
      headers: { Accept: 'application/json' },
    })
  })

  it('switches publications while preserving the selected forecast offset', async () => {
    const latest = makeRunWithTimes('merge_latest', [
      '2026-08-29T10:00:00Z',
      '2026-08-29T10:10:00Z',
      '2026-08-29T10:20:00Z',
    ])
    const historical = makeRunWithTimes('merge_historical', [
      '2026-08-29T09:00:00Z',
      '2026-08-29T09:10:00Z',
      '2026-08-29T09:20:00Z',
    ])
    mockRunHistory([latest, historical], latest.run_id)
    renderApp()

    await screen.findByRole('img', { name: /12:00/ })
    fireEvent.click(screen.getByRole('button', { name: 'Forecast 12:20' }))
    fireEvent.click(
      screen.getByRole('link', {
        name: /Open historical forecast run 11:00, completed/,
      }),
    )

    const historicalImage = await screen.findByRole('img', { name: /11:20/ })
    expect(historicalImage).toHaveAttribute(
      'src',
      '/api/runs/merge_historical/frames/2',
    )
    expect(screen.getByText('HISTORICAL')).toBeInTheDocument()
    expect(screen.queryByText('LATEST')).not.toBeInTheDocument()
  })

  it('marks missing frames and exposes a selected ingestion failure', async () => {
    const latest = makeRun()
    const partial = makeRunWithTimes('merge_partial', frameTimes)
    partial.frames[1] = {
      ...partial.frames[1],
      width: null,
      height: null,
      size_bytes: null,
      sha256: null,
      validation_status: 'missing',
      error: 'HTTP 404',
    }
    partial.progress = { downloaded_frames: 2, expected_frames: 3, fraction: 2 / 3 }
    partial.coverage = 2 / 3
    partial.missing_timestamps = [frameTimes[1]]

    const failed = makeRunWithTimes('merge_failed', frameTimes)
    failed.status = 'failed'
    failed.error = 'Required forecast frames are unavailable'
    failed.frames = failed.frames.map((item, index) => ({
      ...item,
      width: index === 0 ? item.width : null,
      height: index === 0 ? item.height : null,
      size_bytes: index === 0 ? item.size_bytes : null,
      sha256: index === 0 ? item.sha256 : null,
      validation_status: index === 0 ? 'valid' : 'missing',
      error: index === 0 ? null : 'HTTP 404',
    }))
    failed.progress = { downloaded_frames: 1, expected_frames: 3, fraction: 1 / 3 }
    failed.coverage = 1 / 3
    failed.missing_timestamps = [frameTimes[1], frameTimes[2]]

    mockRunHistory([latest, partial, failed], latest.run_id)
    renderApp()

    await screen.findByRole('img', { name: /12:00/ })
    expect(screen.getByText('1 missing')).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('link', {
        name: /Open historical forecast run 12:00, failed, 2 missing frames/,
      }),
    )

    expect(await screen.findByText('INGESTION FAILED')).toBeInTheDocument()
    expect(screen.getByText('Required forecast frames are unavailable')).toBeInTheDocument()
    expect(screen.getByText(/Missing 2:/)).toBeInTheDocument()
    expect(screen.getByText('HISTORICAL')).toBeInTheDocument()
  })

  it('marks cached forecast data offline when backend status is unreachable', async () => {
    mockForecastApi(makeRun(), false)
    renderApp()

    await screen.findByRole('img', { name: /12:00/ })
    expect(await screen.findAllByText('OFFLINE')).toHaveLength(2)
    expect(screen.getByText(/OFFLINE · 2 min ago/)).toBeInTheDocument()
    expect(screen.getByText('cached data shown')).toBeInTheDocument()
  })

  it('surfaces active refresh state and the last IMGW error compactly', async () => {
    const status = makeServiceStatus()
    status.refresh_in_progress = true
    status.last_refresh_status = 'failed'
    status.last_imgw_error = 'IMGW returned HTTP 503'
    mockForecastApi(makeRun(), true, status)
    renderApp()

    await screen.findByRole('img', { name: /12:00/ })
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
    expect(screen.getByText('LAST IMGW ERROR')).toBeInTheDocument()
    expect(screen.getByText('IMGW returned HTTP 503')).toBeInTheDocument()
  })

  it('shows the next automatic forecast refresh in Warsaw time', async () => {
    const status = makeServiceStatus()
    status.scheduler = {
      enabled: true,
      state: 'running',
      next_run_at: '2026-08-29T10:12:00Z',
    }
    mockForecastApi(makeRun(), true, status)
    renderApp()

    await screen.findByRole('img', { name: /12:00/ })
    expect(screen.getByText('RUNNING')).toBeInTheDocument()
    expect(screen.getByText('next 12:12')).toBeInTheDocument()
  })

  it('generates a selected video range and keeps the weather viewer secondary', async () => {
    const api = mockVideoApi()
    renderApp()

    await screen.findByRole('img', { name: /12:00/ })
    fireEvent.click(screen.getByRole('button', { name: 'Generate video' }))

    expect(screen.getByRole('dialog', { name: 'Forecast videos' })).toBeInTheDocument()
    expect(await screen.findByLabelText('source generated forecast video')).toHaveAttribute(
      'src',
      '/api/videos/video_complete1/file',
    )
    expect(screen.getByRole('link', { name: 'Download' })).toHaveAttribute(
      'href',
      '/api/videos/video_complete1/file',
    )

    fireEvent.click(screen.getByRole('radio', { name: /1:1/ }))
    fireEvent.change(screen.getByLabelText('Video range start'), {
      target: { value: '1' },
    })
    fireEvent.change(screen.getByLabelText('Video range end'), {
      target: { value: '2' },
    })
    fireEvent.change(screen.getByLabelText('Video FPS'), { target: { value: '7' } })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Timestamp overlay' }))
    fireEvent.click(screen.getByRole('button', { name: 'Generate MP4' }))

    expect(await screen.findByText('Queued for rendering…')).toBeInTheDocument()
    expect(api.createRequests).toEqual([
      {
        mode: '1:1',
        fps: 7,
        start_frame_index: 1,
        end_frame_index: 2,
        timestamp_overlay: true,
      },
    ])
    expect(screen.getByRole('img', { name: /12:00/ })).toBeInTheDocument()
  })

  it('requires confirmation before deleting a completed video', async () => {
    const api = mockVideoApi()
    renderApp()

    await screen.findByRole('img', { name: /12:00/ })
    fireEvent.click(screen.getByRole('button', { name: 'Generate video' }))
    await screen.findByLabelText('source generated forecast video')

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByRole('button', { name: 'Confirm delete' })).toBeInTheDocument()
    expect(api.deletedIds).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))

    await waitFor(() => {
      expect(screen.queryByLabelText('source generated forecast video')).not.toBeInTheDocument()
    })
    expect(api.deletedIds).toEqual(['video_complete1'])
  })

  it('shows explicit loading and backend error states', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => undefined)))
    const loadingView = renderApp()
    expect(screen.getByRole('heading', { name: 'Loading latest forecast' })).toBeInTheDocument()
    loadingView.unmount()

    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({}, false, 500)))
    renderApp()
    expect(
      await screen.findByRole('heading', { name: 'Forecast unavailable' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
