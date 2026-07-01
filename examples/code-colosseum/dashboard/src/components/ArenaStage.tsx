import { useEffect, useState } from 'react'
import Editor from '@monaco-editor/react'
import { useApi } from '../hooks/useApi'
import { useSSE } from '../hooks/useSSE'
import type { Duel, DuelAgent, Problem, SSEEvent } from '../types'

interface Props {
  duelId: string | null
  problem: Problem | null
}

export function ArenaStage({ duelId, problem }: Props) {
  const { data: detail, error } = useApi<Duel>(duelId ? `/duels/${duelId}` : '', [duelId])
  const { events } = useSSE(duelId ? `/api/duels/${duelId}/stream` : null)
  const [liveDuel, setLiveDuel] = useState<Duel | null>(null)
  const [logs, setLogs] = useState<SSEEvent[]>([])

  useEffect(() => {
    if (detail) setLiveDuel(detail)
  }, [detail])

  useEffect(() => {
    if (!events.length) return
    const latest = events[events.length - 1]
    setLogs((prev) => [...prev, latest])

    setLiveDuel((prev) => {
      if (!prev) return prev
      const next = { ...prev }
      if (latest.type === 'agent_status') {
        const agent = latest.agent === 'agent_a' ? next.agent_a : next.agent_b
        agent.status = latest.status as string
      }
      if (latest.type === 'agent_completed') {
        const agent = latest.agent === 'agent_a' ? next.agent_a : next.agent_b
        agent.status = latest.status as string
        agent.reward = (latest.reward as number) ?? 0
        agent.code = (latest.code as string) ?? ''
        agent.stdout = (latest.stdout as string) ?? ''
        agent.stderr = (latest.stderr as string) ?? ''
        agent.usage = (latest.usage as DuelAgent['usage']) ?? agent.usage
      }
      if (latest.type === 'completed') {
        next.status = 'completed'
        next.winner = latest.winner as string
        next.agent_a.reward = (latest.agent_a_reward as number) ?? 0
        next.agent_b.reward = (latest.agent_b_reward as number) ?? 0
      }
      return next
    })
  }, [events])

  if (!duelId) {
    return (
      <div className="bg-slate-900 rounded-lg border border-slate-700 p-8 text-center text-slate-400">
        Start a duel to see the Arena Stage.
      </div>
    )
  }

  if (error) {
    return <div className="text-red-400">Error: {error}</div>
  }

  const d = liveDuel
  if (!d) {
    return <div className="text-slate-400">Loading duel...</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">{problem?.title || d.problem_title}</h2>
        <span className={`px-3 py-1 rounded text-sm font-semibold ${
          d.status === 'completed'
            ? 'bg-green-900 text-green-200'
            : d.status === 'running'
            ? 'bg-blue-900 text-blue-200 animate-pulse'
            : 'bg-slate-800 text-slate-300'
        }`}>
          {d.status.toUpperCase()}
        </span>
      </div>

      {d.winner && (
        <div className="bg-gradient-to-r from-indigo-900 to-purple-900 rounded-lg p-4 text-center font-bold text-lg">
          🏆 Winner: {d.winner}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AgentCard agent={d.agent_a} />
        <AgentCard agent={d.agent_b} />
      </div>

      <div className="bg-slate-900 rounded-lg border border-slate-700 p-4">
        <h3 className="font-bold mb-2">Battle Log</h3>
        <div className="h-48 overflow-auto code-panel text-xs">
          {logs.length === 0 && <span className="text-slate-500">Waiting for events...</span>}
          {logs.map((ev, i) => (
            <div key={i} className="mb-1">
              <span className="text-indigo-400">[{ev.type}]</span>{' '}
              {Boolean(ev.agent) && <span className="text-slate-400">{String(ev.agent)}</span>}{' '}
              {Boolean(ev.status) && <span className="text-yellow-400">{String(ev.status)}</span>}{' '}
              {ev.reward !== undefined && (
                <span className="text-green-400">reward={Number(ev.reward).toFixed(2)}</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function AgentCard({ agent }: { agent: Duel['agent_a'] }) {
  const statusColor =
    agent.status === 'success'
      ? 'text-green-400'
      : agent.status === 'failed'
      ? 'text-red-400'
      : agent.status === 'running'
      ? 'text-blue-400 animate-pulse'
      : 'text-slate-400'

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-bold">{agent.name}</h3>
        <span className={`font-mono text-sm ${statusColor}`}>{agent.status}</span>
      </div>
      <div className="mb-2 text-sm space-x-3">
        <span>
          Reward: <span className="font-mono font-semibold text-green-400">{agent.reward.toFixed(2)}</span>
        </span>
        {agent.usage && agent.usage.total_tokens > 0 && (
          <span className="text-slate-400">
            Tokens:{' '}
            <span className="font-mono text-slate-200">
              {agent.usage.total_tokens.toLocaleString()}
            </span>{' '}
            <span className="text-xs">({agent.usage.steps} call{agent.usage.steps === 1 ? '' : 's'})</span>
          </span>
        )}
      </div>
      <div className="rounded-lg border border-slate-700 overflow-hidden" style={{ minHeight: 320 }}>
        <Editor
          height="320px"
          language="python"
          theme="vs-dark"
          value={agent.code || '// waiting for solution...'}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            fontSize: 13,
            padding: { top: 12 },
          }}
        />
      </div>
      {agent.stderr && (
        <div className="mt-2 p-2 bg-red-950 border border-red-800 rounded text-xs text-red-200 font-mono overflow-auto max-h-32">
          {agent.stderr}
        </div>
      )}
    </div>
  )
}
