import { useState } from 'react'
import { postJson } from '../hooks/useApi'
import type { Problem } from '../types'

interface Props {
  problems: Problem[]
  onCreated: (duelId: string) => void
}

export function DuelCreator({ problems, onCreated }: Props) {
  const [problemId, setProblemId] = useState(problems[0]?.id || '')
  const [agentA, setAgentA] = useState('Agent A')
  const [agentB, setAgentB] = useState('Agent B')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await postJson<{ duel_id: string }>('/duels', {
        problem_id: problemId,
        agent_a_name: agentA,
        agent_b_name: agentB,
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
          value={problemId}
          onChange={(e) => setProblemId(e.target.value)}
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
      <button
        type="submit"
        disabled={loading || !problemId}
        className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 text-white font-semibold py-2 rounded"
      >
        {loading ? 'Starting...' : 'Start Duel'}
      </button>
    </form>
  )
}
