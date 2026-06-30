import { useEffect, useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { Benchmark, BenchmarkSummary, Problem } from '../types'

const AGENT_TYPES = ['claude', 'codex', 'opencode', 'kimi']

function formatCurrency(n: number) {
  return `$${n.toFixed(4)}`
}

export function BenchmarkStage({ problems }: { problems: Problem[] }) {
  const [selectedAgents, setSelectedAgents] = useState<string[]>(['claude', 'kimi'])
  const [selectedProblems, setSelectedProblems] = useState<string[]>(problems.map((p) => p.id))
  const [runningId, setRunningId] = useState<string | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const { data: _listData } = useApi<{ benchmarks: Benchmark[] }>('/benchmarks')
  const { data: detailData } = useApi<{ id: string; status: string; summary: BenchmarkSummary }>(
    runningId ? `/benchmarks/${runningId}` : null,
    [runningId],
    runningId ? 2000 : undefined
  )

  useEffect(() => {
    if (detailData?.status === 'completed' || detailData?.status === 'failed') {
      setRunningId(null)
    }
  }, [detailData])

  const toggleAgent = (agent: string) => {
    setSelectedAgents((prev) =>
      prev.includes(agent) ? prev.filter((a) => a !== agent) : [...prev, agent]
    )
  }

  const toggleProblem = (problemId: string) => {
    setSelectedProblems((prev) =>
      prev.includes(problemId) ? prev.filter((id) => id !== problemId) : [...prev, problemId]
    )
  }

  const runBenchmark = async () => {
    if (selectedAgents.length === 0 || selectedProblems.length === 0) return
    setLogs([])
    const resp = await fetch('/api/benchmarks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_types: selectedAgents,
        problem_ids: selectedProblems,
      }),
    })
    const data = await resp.json()
    if (data.benchmark_id) {
      setRunningId(data.benchmark_id)
      const es = new EventSource(`/api/benchmarks/${data.benchmark_id}/stream`)
      es.onmessage = (e) => {
        const event = JSON.parse(e.data)
        if (event.type === 'run_completed') {
          const r = event.result
          setLogs((prev) => [
            ...prev,
            `${r.agent_type} / ${r.problem_id}: ${r.status} reward=${r.reward.toFixed(2)} tokens=${r.usage?.total_tokens || 0} cost=${formatCurrency(r.estimated_cost_usd || 0)}`,
          ])
        }
        if (event.type === 'done') {
          es.close()
        }
      }
    }
  }

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-5">
        <h2 className="text-lg font-bold mb-4">Benchmark Configuration</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div>
            <h3 className="text-sm font-semibold text-slate-400 mb-2">Agents</h3>
            <div className="flex flex-wrap gap-2">
              {AGENT_TYPES.map((agent) => (
                <button
                  key={agent}
                  onClick={() => toggleAgent(agent)}
                  className={`px-3 py-1 rounded-full text-sm border ${
                    selectedAgents.includes(agent)
                      ? 'bg-indigo-600 border-indigo-500 text-white'
                      : 'bg-slate-800 border-slate-600 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  {agent}
                </button>
              ))}
            </div>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-400 mb-2">Problems</h3>
            <div className="max-h-40 overflow-y-auto space-y-1 pr-2">
              {problems.map((p) => (
                <label
                  key={p.id}
                  className="flex items-center gap-2 text-sm text-slate-300 hover:bg-slate-800/50 px-2 py-1 rounded cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedProblems.includes(p.id)}
                    onChange={() => toggleProblem(p.id)}
                    className="rounded border-slate-600 bg-slate-800 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="flex-1">{p.title}</span>
                  <span className="text-xs text-slate-500 capitalize">{p.difficulty}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
        <button
          onClick={runBenchmark}
          disabled={runningId !== null || selectedAgents.length === 0 || selectedProblems.length === 0}
          className="mt-5 px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-400 text-white rounded-lg font-semibold transition-colors"
        >
          {runningId ? 'Running...' : 'Run Benchmark'}
        </button>
      </div>

      {detailData?.summary && (
        <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-5">
          <h2 className="text-lg font-bold mb-4">Results</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-slate-400 border-b border-slate-700">
                <tr>
                  <th className="text-left py-2 px-3">Agent</th>
                  <th className="text-right py-2 px-3">Runs</th>
                  <th className="text-right py-2 px-3">Pass@1</th>
                  <th className="text-right py-2 px-3">Avg Reward</th>
                  <th className="text-right py-2 px-3">Avg Cost</th>
                  <th className="text-right py-2 px-3">Reward/$</th>
                  <th className="text-right py-2 px-3">Total Tokens</th>
                  <th className="text-right py-2 px-3">Avg Tokens</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(detailData.summary).map(([agent, s]) => (
                  <tr key={agent} className="border-b border-slate-800/50">
                    <td className="py-2 px-3 font-medium">{agent}</td>
                    <td className="text-right py-2 px-3">{s.runs}</td>
                    <td className="text-right py-2 px-3">{(s.pass_at_1 * 100).toFixed(1)}%</td>
                    <td className="text-right py-2 px-3">{s.average_reward.toFixed(2)}</td>
                    <td className="text-right py-2 px-3">{formatCurrency(s.average_cost_usd)}</td>
                    <td className="text-right py-2 px-3">{s.reward_per_dollar.toFixed(1)}</td>
                    <td className="text-right py-2 px-3">{s.total_tokens.toLocaleString()}</td>
                    <td className="text-right py-2 px-3">
                      {s.runs ? Math.round(s.total_tokens / s.runs).toLocaleString() : 0}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {logs.length > 0 && (
        <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-5">
          <h2 className="text-lg font-bold mb-2">Live Log</h2>
          <div className="h-48 overflow-y-auto font-mono text-xs text-slate-300 bg-slate-950 rounded-lg p-3">
            {logs.map((log, i) => (
              <div key={i}>{log}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
