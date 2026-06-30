import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { TrajectoryStep } from '../types'

function parseChoices(choicesJson: string | Uint8Array | null | undefined): { role?: string; content?: string }[] {
  if (!choicesJson) return []
  const text = typeof choicesJson === 'string' ? choicesJson : new TextDecoder().decode(choicesJson)
  try {
    const payload = JSON.parse(text)
    const choices = payload.choices ?? payload
    if (!Array.isArray(choices)) return []
    return choices.map((c: any) => ({
      role: c.message?.role,
      content: c.message?.content,
    }))
  } catch {
    return []
  }
}

export function TrajectoryStage() {
  const [rolloutId, setRolloutId] = useState('')
  const [url, setUrl] = useState<string | null>(null)
  const { data, loading, error } = useApi<{ rollout_id: string; trajectory: TrajectoryStep[] }>(url)

  const load = () => {
    if (rolloutId.trim()) {
      setUrl(`/rollouts/${rolloutId.trim()}/trajectory`)
    }
  }

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-5">
        <h2 className="text-lg font-bold mb-4">Rollout Trajectory</h2>
        <p className="text-sm text-slate-400 mb-4">
          Inspect every LLM request/response captured by the Arena proxy. Paste a
          rollout ID from the Arena stage or duel history.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={rolloutId}
            onChange={(e) => setRolloutId(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && load()}
            placeholder="e.g. r-abc123"
            className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          />
          <button
            onClick={load}
            disabled={loading}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 text-white rounded-lg text-sm font-semibold"
          >
            {loading ? 'Loading...' : 'Load'}
          </button>
        </div>
        {error && <div className="text-red-400 text-sm mt-3">{error}</div>}
      </div>

      {data?.trajectory && (
        <div className="space-y-4">
          <div className="text-sm text-slate-400">
            Rollout <span className="font-mono text-slate-200">{data.rollout_id}</span> —{' '}
            {data.trajectory.length} step{data.trajectory.length === 1 ? '' : 's'}
          </div>
          {data.trajectory.map((step, idx) => {
            const choices = parseChoices(step.response?.choices_json)
            const usage = step.response?.usage
            return (
              <div
                key={idx}
                className="bg-slate-900 border border-slate-700/50 rounded-xl overflow-hidden"
              >
                <div className="bg-slate-800/50 px-4 py-2 text-xs font-semibold text-slate-400 flex justify-between">
                  <span>Step {idx + 1}</span>
                  {usage && (
                    <span className="font-mono">
                      {usage.prompt_tokens ?? 0} prompt / {usage.completion_tokens ?? 0} completion
                    </span>
                  )}
                </div>
                <div className="p-4 space-y-3">
                  {step.request?.messages?.map((msg: any, mIdx: number) => (
                    <div key={mIdx} className="text-sm">
                      <span className="text-xs font-bold uppercase text-indigo-400">{msg.role}</span>
                      <pre className="mt-1 whitespace-pre-wrap font-mono text-slate-300 bg-slate-950 rounded-lg p-3 text-xs">
                        {msg.content}
                      </pre>
                    </div>
                  ))}
                  {choices.map((choice, cIdx) => (
                    <div key={cIdx} className="text-sm">
                      <span className="text-xs font-bold uppercase text-green-400">{choice.role || 'assistant'}</span>
                      <pre className="mt-1 whitespace-pre-wrap font-mono text-slate-300 bg-slate-950 rounded-lg p-3 text-xs">
                        {choice.content}
                      </pre>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
