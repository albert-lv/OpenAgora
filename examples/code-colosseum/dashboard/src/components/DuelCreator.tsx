import { useState } from 'react'
import { postJson } from '../hooks/useApi'
import type { Problem } from '../types'

const AGENT_TYPES = [
  { value: 'claude', label: 'Claude Code (Kimi)' },
  { value: 'codex', label: 'OpenAI Codex (Kimi)' },
  { value: 'opencode', label: 'OpenCode (Kimi)' },
  { value: 'kimi', label: 'Kimi Code CLI' },
]

interface Props {
  problems: Problem[]
  selectedProblemId: string
  onProblemChange: (problemId: string) => void
  onCreated: (duelId: string) => void
}

export function DuelCreator({ problems, selectedProblemId, onProblemChange, onCreated }: Props) {
  const [agentA, setAgentA] = useState('Claude')
  const [agentB, setAgentB] = useState('Kimi')
  const [agentAType, setAgentAType] = useState('claude')
  const [agentBType, setAgentBType] = useState('kimi')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await postJson<{ duel_id: string }>('/duels', {
        problem_id: selectedProblemId,
        agent_a_name: agentA,
        agent_b_name: agentB,
        agent_a_type: agentAType,
        agent_b_type: agentBType,
      })
      onCreated(res.duel_id)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-slate-900 rounded-lg border border-slate-700 p-4 space-y-3">
      <h3 className="font-bold">Start a Duel</h3>
      <div>
        <label className="block text-sm text-slate-400 mb-1">Problem</label>
        <select
          value={selectedProblemId}
          onChange={(e) => onProblemChange(e.target.value)}
          className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2"
        >
          {problems.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title}
            </option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm text-slate-400 mb-1">Agent A</label>
          <input
            value={agentA}
            onChange={(e) => setAgentA(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2"
          />
        </div>
        <div>
          <label className="block text-sm text-slate-400 mb-1">Agent B</label>
          <input
            value={agentB}
            onChange={(e) => setAgentB(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2"
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm text-slate-400 mb-1">Agent A Engine</label>
          <select
            value={agentAType}
            onChange={(e) => setAgentAType(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2"
          >
            {AGENT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm text-slate-400 mb-1">Agent B Engine</label>
          <select
            value={agentBType}
            onChange={(e) => setAgentBType(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2"
          >
            {AGENT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <button
        type="submit"
        disabled={loading || !selectedProblemId}
        className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 text-white font-semibold py-2 rounded"
      >
        {loading ? 'Starting...' : 'Start Duel'}
      </button>
    </form>
  )
}
