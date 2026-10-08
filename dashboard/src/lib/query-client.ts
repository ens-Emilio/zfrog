import { QueryClient } from "@tanstack/react-query"

/**
 * One client for the whole SPA. Stale time matches the polling cadence the
 * pages used to drive by hand (5 s), so a refetch on focus/mount hits the cache
 * instead of the API.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
})
