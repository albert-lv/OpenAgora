import { useEffect, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { useSSE } from '../hooks/useSSE'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { TrainingStatus } from '../types'

export function TrainingMonitor() {
  const { data, error, loading } = useApi<{ status: TrainingStatus }>('/training/status')
  const { events: liveEvents, connected } = useSSE('/api/training/stream')
  const [history, setHistory] = useState<Record<string, any>[]>([])

  // Seed history from the initial REST load.
  useEffect(() => {
    if (data?.status?.history) {
      setHistory(data.status.history)
    }
  }, [data])

  // Append live SSE records as they arrive.
  useEffect(() => {
    if (liveEvents.length === 0) return
    const latest = liveEvents[liveEvents.length - 1]
    if (latest.type === 'heartbeat') return
    setHistory((prev) => {
      if (prev.length > 0 && prev[prev.length - 1].step === latest.step) {
        return prev
      }
      return [...prev, latest]
    })
  }, [liveEvents])

  if (loading) return <div className="text-slate-400">Loading training status...</div>
  if (error) return <div className="text-red-400">Error: {error}</div>

  const status = data?.status
  const latest = history[history.length - 1] || status

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold">Training Monitor</h3>
        <div className="flex items-center gap-2">
          {connected && (
            <span className="px-2 py-0.5 rounded text-xs font-semibold bg-blue-900 text-blue-200">
              ● LIVE
            </span>
          )}
          <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
            latest?.running ? 'bg-green-900 text-green-200' : 'bg-slate-800 text-slate-300'
          }`}>
            {latest?.running ? 'RUNNING' : 'IDLE'}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="Step" value={latest?.step ?? 0} />
        <Metric label="Avg Reward" value={latest?.avg_reward ?? 0} />
        <Metric label="Pass@k" value={latest?.pass_at_k ?? 0} />
        <Metric label="KL" value={latest?.kl ?? 0} />
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={history}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="step" stroke="#94a3b8" />
            <YAxis stroke="#94a3b8" />
            <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155' }} />
            <Legend />
            <Line type="monotone" dataKey="avg_reward" stroke="#4ade80" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="policy_loss" stroke="#60a5fa" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="kl" stroke="#fbbf24" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {latest?.sample && (
        <div className="bg-slate-950 border border-slate-800 rounded-lg p-3">
          <div className="text-xs font-semibold text-slate-400 mb-2">Latest Policy Sample</div>
          <pre className="font-mono text-xs text-slate-300 whitespace-pre-wrap">{latest.sample}</pre>
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-slate-800 rounded p-3">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="text-xl font-mono font-semibold">{typeof value === 'number' ? value.toFixed(4) : value}</div>
    </div>
  )
}
