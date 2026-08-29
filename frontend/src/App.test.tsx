import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('renders the weather-first foundation and reports backend readiness', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: 'ok',
          service: 'imgw-merge-weather',
          version: '0.1.0',
        }),
      }),
    )
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(
      screen.getByRole('heading', { name: 'IMGW frame client ready' }),
    ).toBeInTheDocument()
    expect(await screen.findAllByText('READY')).toHaveLength(2)
    expect(screen.getByText('No forecast run has been collected yet.', { exact: false })).toBeInTheDocument()
  })
})
