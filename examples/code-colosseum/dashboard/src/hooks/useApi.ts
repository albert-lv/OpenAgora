import { useEffect, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

async function fetchJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json() as Promise<T>
}

export function useApi<T>(path: string | null, deps: unknown[] = [], pollInterval?: number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    if (!path) return
    setLoading(true)
    try {
      const d = await fetchJson<T>(path)
      setData(d)
      setError(null)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    const wrappedLoad = () => {
      if (!path) return
      setLoading(true)
      fetchJson<T>(path)
        .then((d) => !cancelled && setData(d))
        .catch((e) => !cancelled && setError(String(e)))
        .finally(() => !cancelled && setLoading(false))
    }
    wrappedLoad()

    let intervalId: ReturnType<typeof setInterval> | undefined
    if (pollInterval && pollInterval > 0) {
      intervalId = setInterval(wrappedLoad, pollInterval)
    }

    return () => {
      cancelled = true
      if (intervalId) clearInterval(intervalId)
    }
  }, deps)

  return { data, error, loading, refetch: load }
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json() as Promise<T>
}
