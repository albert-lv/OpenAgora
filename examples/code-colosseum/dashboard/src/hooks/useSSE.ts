import { useEffect, useState } from 'react'
import type { SSEEvent } from '../types'

export function useSSE(url: string | null) {
  const [events, setEvents] = useState<SSEEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!url) return

    setEvents([])
    setError(null)
    const es = new EventSource(url)

    es.onopen = () => setConnected(true)

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as SSEEvent
        setEvents((prev) => [...prev, data])
      } catch (err) {
        setEvents((prev) => [...prev, { type: 'raw', raw: e.data }])
      }
    }

    es.onerror = (err) => {
      setConnected(false)
      setError(String(err))
    }

    return () => es.close()
  }, [url])

  return { events, connected, error }
}
