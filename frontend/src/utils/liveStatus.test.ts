import { describe, expect, it } from 'vitest'

import { deriveLiveDataState } from './liveStatus'

describe('deriveLiveDataState', () => {
  it('distinguishes latest live data, historical freshness, delay, staleness, and offline', () => {
    expect(
      deriveLiveDataState({ backendReachable: true, isLatest: true, freshness: 'FRESH' }),
    ).toBe('LIVE')
    expect(
      deriveLiveDataState({ backendReachable: true, isLatest: false, freshness: 'FRESH' }),
    ).toBe('FRESH')
    expect(
      deriveLiveDataState({ backendReachable: true, isLatest: true, freshness: 'DELAYED' }),
    ).toBe('DELAYED')
    expect(
      deriveLiveDataState({ backendReachable: true, isLatest: true, freshness: 'STALE' }),
    ).toBe('STALE')
    expect(
      deriveLiveDataState({ backendReachable: false, isLatest: true, freshness: 'FRESH' }),
    ).toBe('OFFLINE')
  })
})
