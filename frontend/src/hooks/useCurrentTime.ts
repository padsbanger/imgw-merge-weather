import { useEffect, useState } from 'react'

export function useCurrentTime(): Date {
  const [currentTime, setCurrentTime] = useState(() => new Date())

  useEffect(() => {
    const timer = window.setInterval(() => setCurrentTime(new Date()), 1_000)
    return () => window.clearInterval(timer)
  }, [])

  return currentTime
}
