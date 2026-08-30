import { Link } from 'react-router-dom'

import type {
  ForecastRunDetail,
  ForecastRunSummary,
  ServiceStatusResponse,
} from '../api/types'
import type { LiveDataState } from '../utils/liveStatus'
import { formatAge, formatLocalDate, formatLocalTime, formatUtcTime } from '../utils/time'

interface RunSidebarProps {
  run: ForecastRunDetail
  runs: ForecastRunSummary[]
  latestRunId: string | null
  liveState: LiveDataState
  serviceStatus: ServiceStatusResponse | undefined
  backendState: 'checking' | 'online' | 'offline'
  selectedOffsetMinutes: number | null
  onOpenVideos: () => void
}

export function RunSidebar({
  run,
  runs,
  latestRunId,
  liveState,
  serviceStatus,
  backendState,
  selectedOffsetMinutes,
  onOpenVideos,
}: RunSidebarProps) {
  const isLatest = run.run_id === latestRunId
  return (
    <aside className="run-sidebar" aria-label="Forecast run information">
      <section className="run-summary">
        <div className="section-heading">
          <span>Current run</span>
          <span className={isLatest ? 'latest-tag' : 'historical-tag'}>
            {isLatest ? 'LATEST' : 'HISTORICAL'}
          </span>
        </div>
        <div className="run-primary-time">
          <strong>
            {run.resolved_start_time
              ? formatLocalTime(run.resolved_start_time, run.display_timezone)
              : '—'}
          </strong>
          <span>
            {run.resolved_start_time
              ? formatLocalDate(run.resolved_start_time, run.display_timezone)
              : 'Unresolved'}
          </span>
        </div>
        <div className="freshness-line">
          <span className={`freshness-dot freshness-dot--${liveState.toLowerCase()}`} />
          <strong>{liveState}</strong>
          <span>{formatAge(run.freshness.age_seconds)}</span>
        </div>
        <div className="live-data-grid" aria-label="Live data status">
          <div>
            <span>SOURCE UPDATE</span>
            <strong>
              {formatLocalTime(run.freshness.reference_time, run.display_timezone)}
            </strong>
            <small>{formatUtcTime(run.freshness.reference_time)}</small>
          </div>
          <div>
            <span>BACKEND</span>
            <strong>{backendState.toUpperCase()}</strong>
            <small>
              {backendState === 'online'
                ? 'reachable'
                : backendState === 'offline'
                  ? 'cached data shown'
                  : 'awaiting status'}
            </small>
          </div>
          <div>
            <span>REFRESH</span>
            <strong>{serviceStatus?.refresh_in_progress ? 'ACTIVE' : 'IDLE'}</strong>
            <small>{serviceStatus?.last_refresh_status ?? 'no API refresh recorded'}</small>
          </div>
          <div>
            <span>SCHEDULER</span>
            <strong>{serviceStatus?.scheduler.state.toUpperCase() ?? 'CHECKING'}</strong>
            <small>
              {serviceStatus?.scheduler.enabled
                ? serviceStatus.scheduler.next_run_at
                  ? `next ${formatLocalTime(
                      serviceStatus.scheduler.next_run_at,
                      run.display_timezone,
                    )}`
                  : 'schedule pending'
                : 'manual refresh'}
            </small>
          </div>
        </div>
        {serviceStatus?.last_imgw_error ? (
          <div className="imgw-error" role="status">
            <span>LAST IMGW ERROR</span>
            <strong>{serviceStatus.last_imgw_error}</strong>
          </div>
        ) : null}
        {run.status !== 'completed' || run.missing_timestamps.length > 0 ? (
          <div className={`run-issue run-issue--${run.status}`} role="status">
            <span>{run.status === 'failed' ? 'INGESTION FAILED' : 'INCOMPLETE RUN'}</span>
            <strong>
              {run.error ??
                `${run.progress.downloaded_frames} of ${run.progress.expected_frames} frames available`}
            </strong>
            {run.missing_timestamps.length > 0 ? (
              <small>
                Missing {run.missing_timestamps.length}:{' '}
                {run.missing_timestamps
                  .slice(0, 3)
                  .map(formatUtcTime)
                  .join(', ')}
                {run.missing_timestamps.length > 3 ? '…' : ''}
              </small>
            ) : null}
          </div>
        ) : null}
        <dl className="metadata-grid">
          <div>
            <dt>PRODUCT</dt>
            <dd>{run.product}</dd>
          </div>
          <div>
            <dt>RANGE</dt>
            <dd>{formatRunWindowHours(run)} h</dd>
          </div>
          <div>
            <dt>STEP</dt>
            <dd>{run.interval_minutes} min</dd>
          </div>
          <div>
            <dt>FRAMES</dt>
            <dd>
              {run.progress.downloaded_frames} / {run.progress.expected_frames}
            </dd>
          </div>
          <div>
            <dt>STATUS</dt>
            <dd>{run.status.toUpperCase()}</dd>
          </div>
          <div>
            <dt>SOURCE</dt>
            <dd>{run.source}</dd>
          </div>
        </dl>
        <div className="run-actions">
          <button
            type="button"
            onClick={onOpenVideos}
            disabled={run.status !== 'completed'}
          >
            Generate video
          </button>
        </div>
      </section>

      <section className="run-browser" id="forecast-runs">
        <div className="section-heading">
          <span>Forecast runs</span>
          <span>{runs.length}</span>
        </div>
        <nav aria-label="Recent forecast runs">
          {runs.map((item) => {
            const itemLatest = item.run_id === latestRunId
            const active = item.run_id === run.run_id
            const baseDestination = itemLatest ? '/' : `/runs/${item.run_id}`
            const destination =
              selectedOffsetMinutes === null
                ? baseDestination
                : `${baseDestination}?offset=${selectedOffsetMinutes}`
            const missingCount = item.missing_timestamps.length
            const statusLabel = itemLatest
              ? 'latest'
              : item.status === 'completed' && missingCount === 0
                ? 'complete'
                : item.status === 'completed'
                  ? `${missingCount} missing`
                  : item.status
            return (
              <Link
                className={`run-link ${active ? 'run-link--active' : ''}`}
                to={destination}
                key={item.run_id}
                aria-current={active ? 'page' : undefined}
                aria-label={`Open ${itemLatest ? 'latest' : 'historical'} forecast run ${
                  item.resolved_start_time
                    ? formatLocalTime(item.resolved_start_time, item.display_timezone)
                    : 'with unresolved start'
                }, ${item.status}${missingCount > 0 ? `, ${missingCount} missing frames` : ''}`}
              >
                <span
                  className={`run-status run-status--${item.status}`}
                  aria-label={item.status}
                />
                <span>
                  <strong>
                    {item.resolved_start_time
                      ? formatLocalTime(item.resolved_start_time, item.display_timezone)
                      : 'Unresolved'}
                  </strong>
                  <small>
                    {item.resolved_start_time
                      ? formatLocalDate(item.resolved_start_time, item.display_timezone)
                      : item.status}
                  </small>
                </span>
                <em className={`run-label run-label--${item.status}`}>{statusLabel}</em>
              </Link>
            )
          })}
        </nav>
      </section>
    </aside>
  )
}

function formatRunWindowHours(run: ForecastRunDetail): number {
  const first = run.frames[0]
  const last = run.frames.at(-1)
  if (!first || !last) return run.forecast_hours
  return (
    (new Date(last.forecast_time).getTime() -
      new Date(first.forecast_time).getTime()) /
    3_600_000
  )
}
