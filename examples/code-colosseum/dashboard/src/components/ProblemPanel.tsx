import type { Problem } from '../types'

interface Props {
  problem: Problem | null
}

export function ProblemPanel({ problem }: Props) {
  if (!problem) {
    return <div className="text-slate-400">Select a problem to start a duel.</div>
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 p-4">
      <div className="flex items-center gap-3 mb-2">
        <h2 className="text-xl font-bold">{problem.title}</h2>
        <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
          problem.difficulty === 'easy'
            ? 'bg-green-900 text-green-200'
            : problem.difficulty === 'medium'
            ? 'bg-yellow-900 text-yellow-200'
            : 'bg-red-900 text-red-200'
        }`}>
          {problem.difficulty.toUpperCase()}
        </span>
      </div>
      <p className="text-slate-300 whitespace-pre-wrap mb-4">{problem.description}</p>
      <div className="code-panel text-emerald-400">{problem.function_signature}</div>
      <div className="flex gap-2 mt-3">
        {problem.tags.map((tag) => (
          <span key={tag} className="px-2 py-0.5 bg-slate-800 rounded text-xs text-slate-300">
            {tag}
          </span>
        ))}
      </div>
    </div>
  )
}
