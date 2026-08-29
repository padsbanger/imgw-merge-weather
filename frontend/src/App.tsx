import { Navigate, Route, Routes } from 'react-router-dom'

import { WeatherViewerPage } from './pages/WeatherViewerPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<WeatherViewerPage />} />
      <Route path="/runs/:runId" element={<WeatherViewerPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
