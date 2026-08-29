import { useQuery } from '@tanstack/react-query'
import { Route, Routes } from 'react-router-dom'

import { getHealth } from './api/status'

function WeatherFoundation() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    retry: 1,
  })

  const backendState = health.isPending
    ? 'CONNECTING'
    : health.isError
      ? 'OFFLINE'
      : 'READY'

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <span className="wordmark">imgw-merge-weather</span>
          <span className="product-label">MERGE · Poland</span>
        </div>
        <div className={`connection-state connection-state--${backendState.toLowerCase()}`}>
          <span aria-hidden="true" className="status-dot" />
          <span>{backendState}</span>
        </div>
      </header>

      <main className="weather-layout">
        <section className="viewer" aria-labelledby="viewer-title">
          <div className="viewer-grid" aria-hidden="true" />
          <div className="viewer-empty">
            <p className="eyebrow">IMGW CMM · MERGE</p>
            <h1 id="viewer-title">IMGW frame client ready</h1>
            <p>
              No forecast run has been collected yet. The backend can now retrieve and
              validate individual MERGE frames without inventing missing weather data.
            </p>
          </div>
          <div className="viewer-footer">
            <span>PRECIPITATION FORECAST</span>
            <span>NO DATA</span>
          </div>
        </section>

        <section className="timeline" aria-label="Forecast timeline unavailable">
          <button type="button" disabled aria-label="Previous forecast frame">
            ◀
          </button>
          <div className="timeline-track">
            <span>Forecast timeline will appear after collection</span>
          </div>
          <button type="button" disabled aria-label="Next forecast frame">
            ▶
          </button>
        </section>

        <aside className="metadata" aria-label="Application status">
          <div>
            <span className="metadata-label">FOUNDATION</span>
            <strong>Milestone 1</strong>
          </div>
          <div>
            <span className="metadata-label">BACKEND</span>
            <strong>{backendState}</strong>
          </div>
          <div>
            <span className="metadata-label">SOURCE</span>
            <strong>IMGW CMM</strong>
          </div>
          <div>
            <span className="metadata-label">PRODUCT</span>
            <strong>MERGE</strong>
          </div>
        </aside>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="*" element={<WeatherFoundation />} />
    </Routes>
  )
}
