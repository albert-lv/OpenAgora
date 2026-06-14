import { useApi } from '../hooks/useApi'
import type { Duel } from '../types'

interface Props {
  onSelect: (duelId: string) => void
  selectedId: string | null
}

export function DuelHistory({ onSelect, selectedId }: Props) {
  const { data, error, loading } = useApi<{ duels: Duel[] }>('/duels')

  if (loading) return <div className="text-slate-400">Loading duels...</div>
  if (error) return <div className="text-red-400">Error: {error}</div>

  const duels = data?.duels || []

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 p-4">
      <h3 className="text-lg font-bold mb-3">Duel History</h3>
      {duels.length === 0 ? (
        <div className="text-slate-500">No duels yet.</div>
      ) : (
        <ul className="space-y-2 max-h-96 overflow-auto">
          {duels.map((duel) => (
            <li
              key={duel.id}
              onClick={() => onSelect(duel.id)}
              className={`p-3 rounded cursor-pointer border ${
                selectedId === duel.id
                  ? 'bg-indigo-900/40 border-indigo-500'
                  : 'bg-slate-800 border-slate-700 hover:bg-slate-750'
              }`}
            >
              <div className="flex justify-between items-center">
                <span className="font-medium">{duel.problem_title}</span>
                <span className={`text-xs px-2 py-0.5 rounded ${
                  duel.status === 'completed' ? 'bg-green-900 text-green-200' : 'bg-slate-700 text-slate-300'
                }`}>
                  {duel.status}
                </span>
              </div>
              <div className="text-xs text-slate-400 mt-1">
                {duel.agent_a.name}: {duel.agent_a.reward.toFixed(2)} vs{' '}
                {duel.agent_b.name}: {duel.agent_b.reward.toFixed(2)}
              </div>
              {duel.winner && (
                <div className="text-xs text-yellow-400 mt-1">Winner: {duel.winner}</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
