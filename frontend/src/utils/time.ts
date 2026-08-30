const utcTimeFormatter = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'UTC',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

export function formatLocalTime(timestamp: string, timeZone: string): string {
  return new Intl.DateTimeFormat('pl-PL', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(timestamp))
}

export function formatLocalDate(timestamp: string, timeZone: string): string {
  return new Intl.DateTimeFormat('pl-PL', {
    timeZone,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(new Date(timestamp))
}

export function formatLocalClock(timestamp: Date, timeZone: string): string {
  return new Intl.DateTimeFormat('pl-PL', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).format(timestamp)
}

export function formatUtcTime(timestamp: string): string {
  return `${utcTimeFormatter.format(new Date(timestamp))} UTC`
}

export function formatForecastOffset(timestamp: string, startTimestamp: string | null): string {
  if (startTimestamp === null) return '—'
  const offsetMinutes = Math.round(
    (new Date(timestamp).getTime() - new Date(startTimestamp).getTime()) / 60_000,
  )
  const minutes = Math.abs(offsetMinutes)
  const hoursPart = Math.floor(minutes / 60).toString().padStart(2, '0')
  const minutesPart = (minutes % 60).toString().padStart(2, '0')
  return `${offsetMinutes < 0 ? '-' : '+'}${hoursPart}:${minutesPart}`
}

export function formatAge(ageSeconds: number): string {
  if (ageSeconds < 60) return '<1 min ago'
  const minutes = Math.floor(ageSeconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return remainingMinutes === 0 ? `${hours} h ago` : `${hours} h ${remainingMinutes} min ago`
}
