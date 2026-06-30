import { useApi } from '../hooks/useApi'
import type { LeaderboardEntry } from '../types'

export function Leaderboard() {
  const { data, error, loading } = useApi<{ leaderboard: LeaderboardEntry[] }>('/leaderboard')

  if (loading) return <div className="text-slate-400">Loading leaderboard...</div>
  if (error) return <div className="text-red-400">Error: {error}</div>

  const entries = data?.leaderboard || []

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 p-4">
      <h3 className="text-lg font-bold mb-4">Leaderboard</h3>
      {entries.length === 0 ? (
        <div className="text-slate-500">No matches yet.</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-400 border-b border-slate-700">
              <th className="text-left py-2">#</th>
              <th className="text-left">Agent</th>
              <th className="text-right">Rating</th>
              <th className="text-right">W</th>
              <th className="text-right">L</th>
              <th className="text-right">D</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, idx) => (
              <tr key={entry.id} className="border-b border-slate-800">
                <td className="py-2 text-slate-400">{idx + 1}</td>
                <td className="font-medium">{entry.name}</td>
                <td className="text-right font-mono text-yellow-400">{entry.rating}</td>
                <td className="text-right text-green-400">{entry.wins}</td>
                <td className="text-right text-red-400">{entry.losses}</td>
                <td className="text-right text-slate-400">{entry.draws}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
