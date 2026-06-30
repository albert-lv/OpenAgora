import { useEffect, useMemo, useState } from 'react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  AreaChart,
  Area,
  Line,
} from 'recharts'
import { useApi } from '../hooks/useApi'
import { useSSE } from '../hooks/useSSE'
import type { Duel, GroupStat, TrainingStatus } from '../types'

interface DuelsResponse {
  duels: Duel[]
}

interface TrainingResponse {
  status: TrainingStatus
}

function useLiveDuel(pollInterval = 2000) {
  const { data: duelsData } = useApi<DuelsResponse>('/duels', [], pollInterval)
  const duels = duelsData?.duels || []

  const selectedDuel = useMemo(() => {
    if (duels.length === 0) return null
    const running = duels.find((d) => d.status === 'running')
    return running || duels[0]
  }, [duels])

  const { data: detail } = useApi<Duel>(
    selectedDuel ? `/duels/${selectedDuel.id}` : '',
    [selectedDuel?.id],
    pollInterval
  )
  const { events } = useSSE(
    selectedDuel ? `/api/duels/${selectedDuel.id}/stream` : null
  )

  const [liveDuel, setLiveDuel] = useState<Duel | null>(null)

  useEffect(() => {
    if (detail) setLiveDuel(detail)
  }, [detail])

  useEffect(() => {
    if (!events.length || !liveDuel) return
    const latest = events[events.length - 1]
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

  return liveDuel
}

export function ArenaDashboard() {
  const duel = useLiveDuel(2000)
  const { data: trainingData } = useApi<TrainingResponse>('/training/status', [], 2000)
  const status = trainingData?.status

  const groupData = useMemo(() => {
    const stats = status?.group_stats || []
    return stats.map((g: GroupStat) => ({
      name: `G${g.group + 1}`,
      mean: Number(g.mean.toFixed(3)),
      std: Number(g.std.toFixed(3)),
      min: Number(g.min.toFixed(3)),
      max: Number(g.max.toFixed(3)),
    }))
  }, [status?.group_stats])

  const groupRewardData = useMemo(() => {
    const rewards = status?.group_rewards || []
    return rewards.flatMap((groupRewards: number[], groupIdx: number) =>
      groupRewards.map((r, rolloutIdx) => ({
        group: `G${groupIdx + 1}`,
        rollout: `${groupIdx + 1}.${rolloutIdx + 1}`,
        reward: Number(r.toFixed(2)),
      }))
    )
  }, [status?.group_rewards])

  const history = useMemo(() => {
    return (status?.history || []).map((h) => ({
      step: Number(h.step ?? 0),
      avg_reward: Number(h.avg_reward ?? 0),
      policy_loss: Number(h.policy_loss ?? 0),
      kl: Number(h.kl ?? 0),
    }))
  }, [status?.history])

  const isLive = duel?.status === 'running'

  return (
    <div className="relative min-h-[calc(100vh-7rem)] overflow-hidden rounded-2xl border border-indigo-500/20 bg-slate-950/70 p-6 shadow-[0_0_60px_rgba(79,70,229,0.12)]">
      {/* animated background layers */}
      <div className="pointer-events-none absolute inset-0 cyber-grid opacity-30" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_-20%,rgba(99,102,241,0.18),transparent_60%)]" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_80%_80%,rgba(236,72,153,0.10),transparent_50%)]" />
      <div className="pointer-events-none absolute inset-0 scanline opacity-[0.03]" />

      <div className="relative z-10">
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
          <div>
            <h2 className="text-3xl md:text-4xl font-black tracking-tighter text-transparent bg-clip-text bg-gradient-to-r from-amber-300 via-orange-400 to-purple-500 text-glow">
              CODE COLOSSEUM
            </h2>
            <p className="text-sm md:text-base text-slate-400 mt-1">
              Live Arena <span className="text-slate-600">/</span> GRPO Distribution <span className="text-slate-600">/</span> Real-time Training Command Center
            </p>
          </div>
          <div className={`flex items-center gap-3 px-4 py-2 rounded-full border shadow-[0_0_20px_rgba(239,68,68,0.25)] animate-pulse-glow ${isLive ? 'bg-red-950/30 border-red-500/40 text-red-300' : 'bg-slate-900/50 border-slate-600/40 text-slate-400'}`}>
            <span className="relative flex h-3 w-3">
              {isLive && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />}
              <span className={`relative inline-flex rounded-full h-3 w-3 ${isLive ? 'bg-red-500' : 'bg-slate-500'}`} />
            </span>
            <span className="font-black tracking-widest text-sm">{isLive ? 'LIVE' : 'STANDBY'}</span>
          </div>
        </header>

        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
          {/* LEFT: Arena live */}
          <section className="xl:col-span-7 space-y-5">
            <div className="panel-glow p-5 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xl font-black text-slate-100">{duel?.problem_title || 'Waiting for duel...'}</h3>
                  {duel && (
                    <p className="text-xs text-slate-400 font-mono mt-0.5">
                      duel_id={duel.id.slice(-8)} · status={duel.status}
                    </p>
                  )}
                </div>
                {duel && (
                  <span className={`px-4 py-1.5 rounded-full text-xs font-black uppercase tracking-wider border ${isLive ? 'bg-blue-950/40 text-blue-300 border-blue-500/60 animate-pulse' : 'bg-slate-900/50 text-slate-300 border-slate-600/60'}`}>
                    {isLive ? 'Fighting' : duel.status}
                  </span>
                )}
              </div>

              {duel && (
                <>
                  <div className="text-center py-1">
                    <span className="inline-block px-8 py-2 rounded-full bg-gradient-to-r from-red-600 to-orange-500 text-white font-black text-lg uppercase tracking-[0.3em] shadow-lg shadow-red-900/40 animate-fight">
                      Fight!
                    </span>
                  </div>

                  <div className="relative grid grid-cols-1 md:grid-cols-2 gap-5">
                    <div className="absolute left-1/2 top-6 -translate-x-1/2 z-10 hidden md:block">
                      <div className="w-12 h-12 rounded-full bg-slate-900 border-2 border-amber-500 flex items-center justify-center text-amber-400 font-black text-lg shadow-[0_0_20px_rgba(245,158,11,0.4)]">
                        VS
                      </div>
                    </div>
                    <AgentCard agent={duel.agent_a} color="blue" />
                    <AgentCard agent={duel.agent_b} color="red" />
                  </div>
                </>
              )}

              {!duel && (
                <div className="text-center py-12 text-slate-500">
                  No duel available. Start one from the Arena tab.
                </div>
              )}
            </div>

            <div className="panel-glow p-4">
              <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
                Live Battle Report / Battle Log
              </h3>
              <div className="h-40 overflow-auto rounded-lg bg-slate-950/80 p-3 border border-slate-800 font-mono text-xs space-y-1.5">
                {duel ? (
                  <>
                    <LogLine type="agent_status" agent="agent_a" status={duel.agent_a.status} />
                    <LogLine type="agent_status" agent="agent_b" status={duel.agent_b.status} />
                    {duel.agent_a.status !== 'pending' && (
                      <LogLine type="agent_completed" agent="agent_a" status={duel.agent_a.status} reward={duel.agent_a.reward} />
                    )}
                    {duel.agent_b.status !== 'pending' && (
                      <LogLine type="agent_completed" agent="agent_b" status={duel.agent_b.status} reward={duel.agent_b.reward} />
                    )}
                    {duel.status === 'completed' && duel.winner && (
                      <LogLine type="completed" text={`winner=${duel.winner}`} />
                    )}
                  </>
                ) : (
                  <LogLine type="info" text="Waiting for duel data..." />
                )}
              </div>
            </div>
          </section>

          {/* RIGHT: GRPO distribution */}
          <section className="xl:col-span-5 space-y-5">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <Metric label="Step" value={status?.step ?? 0} />
              <Metric label="Avg Reward" value={status?.avg_reward ?? 0} />
              <Metric label="Pass@k" value={status?.pass_at_k ?? 0} />
              <Metric label="KL Divergence" value={status?.kl ?? 0} />
              <Metric label="Entropy" value={status?.entropy ?? 0} />
              <Metric label="Policy Loss" value={status?.policy_loss ?? 0} />
            </div>

            <div className="panel-glow p-4">
              <h3 className="text-lg font-black text-slate-100 mb-1">GRPO Reward Distribution</h3>
              <p className="text-xs text-slate-400 mb-3">Reward for each rollout per group / greener means closer to full score</p>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={groupRewardData} margin={{ top: 5, right: 10, left: -10, bottom: 20 }}>
                    <defs>
                      <linearGradient id="rewardGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#4ade80" stopOpacity={1} />
                        <stop offset="100%" stopColor="#16a34a" stopOpacity={0.7} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="rollout" stroke="#64748b" fontSize={9} angle={-35} textAnchor="end" interval={0} />
                    <YAxis domain={[0, 1]} stroke="#64748b" fontSize={10} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#020617', borderColor: '#334155', borderRadius: '0.5rem' }}
                      itemStyle={{ color: '#e2e8f0' }}
                      formatter={(value: number) => [value.toFixed(2), 'reward']}
                    />
                    <ReferenceLine y={status?.avg_reward ?? 0} stroke="#f472b6" strokeDasharray="4 4" label={{ value: 'mean', fill: '#f472b6', fontSize: 10, position: 'insideTopRight' }} />
                    <Bar dataKey="reward" radius={[3, 3, 0, 0]}>
                      {groupRewardData.map((entry, index) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={entry.reward >= 0.85 ? '#4ade80' : entry.reward >= 0.5 ? '#fbbf24' : '#f87171'}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="panel-glow p-4">
              <h3 className="text-lg font-black text-slate-100 mb-1">Group Statistics</h3>
              <p className="text-xs text-slate-400 mb-3">Mean / Std / Min / Max reward per group</p>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={groupData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="name" stroke="#64748b" fontSize={10} />
                    <YAxis domain={[0, 1]} stroke="#64748b" fontSize={10} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#020617', borderColor: '#334155', borderRadius: '0.5rem' }}
                      itemStyle={{ color: '#e2e8f0' }}
                      formatter={(value: number, name: string) => [value.toFixed(3), name]}
                    />
                    <Bar dataKey="mean" name="Mean" fill="#60a5fa" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="std" name="Std" fill="#a78bfa" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="min" name="Min" fill="#f87171" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="max" name="Max" fill="#4ade80" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="panel-glow p-4">
              <h3 className="text-lg font-black text-slate-100 mb-1">Reward Curve</h3>
              <div className="h-36">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={history} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
                    <defs>
                      <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#34d399" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="#34d399" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="step" stroke="#64748b" fontSize={9} />
                    <YAxis domain={[0, 1]} stroke="#64748b" fontSize={9} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#020617', borderColor: '#334155', borderRadius: '0.5rem' }}
                      itemStyle={{ color: '#e2e8f0' }}
                    />
                    <Area type="monotone" dataKey="avg_reward" stroke="#34d399" strokeWidth={2} fill="url(#areaGradient)" />
                    <Line type="monotone" dataKey="policy_loss" stroke="#60a5fa" strokeWidth={1.5} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

function AgentCard({
  agent,
  color,
}: {
  agent: Duel['agent_a']
  color: 'blue' | 'red'
}) {
  const rewardPct = Math.max(0, Math.min(100, agent.reward * 100))
  const glow = color === 'blue' ? 'shadow-[0_0_30px_rgba(37,99,235,0.20)]' : 'shadow-[0_0_30px_rgba(220,38,38,0.20)]'
  const barGradient =
    color === 'blue'
      ? 'bg-gradient-to-r from-blue-700 via-blue-500 to-cyan-400'
      : 'bg-gradient-to-r from-red-700 via-red-500 to-orange-400'
  const header =
    color === 'blue'
      ? 'bg-gradient-to-br from-blue-950/60 to-slate-900'
      : 'bg-gradient-to-br from-red-950/60 to-slate-900'

  return (
    <div className={`rounded-xl border ${color === 'blue' ? 'border-blue-500/30' : 'border-red-500/30'} overflow-hidden ${glow} transition-all duration-500`}>
      <div className={`${header} p-4`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className={`w-3 h-3 rounded-full ${color === 'blue' ? 'bg-blue-500' : 'bg-red-500'} shadow-lg animate-pulse`} />
            <h4 className="font-black text-lg tracking-wide text-slate-100">{agent.name}</h4>
          </div>
          <span className={`font-mono text-xs font-bold ${color === 'blue' ? 'text-blue-300' : 'text-red-300'} uppercase`}>{agent.status}</span>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-300">
            <span>Score</span>
            <span className="font-mono font-bold text-lg">{agent.reward.toFixed(2)}</span>
          </div>
          <div className="h-3 bg-slate-950/70 rounded-full overflow-hidden border border-slate-700/50">
            <div
              className={`h-full rounded-full ${barGradient} relative overflow-hidden`}
              style={{ width: `${rewardPct}%` }}
            >
              <div className="absolute inset-0 bar-shine" />
            </div>
          </div>
        </div>
      </div>
      <div className="bg-slate-950 p-3">
        <div className="h-40 overflow-auto rounded-lg bg-[#0b1120] p-3 border border-slate-800 font-mono text-[11px] leading-relaxed text-slate-300">
          <pre>{agent.code || '// waiting for solution...'}</pre>
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  const display = typeof value === 'number' ? (value < 10 ? value.toFixed(4) : value.toString()) : value
  return (
    <div className="panel-glow p-3 text-center hover:scale-[1.02] transition-transform">
      <div className="text-[10px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className="text-xl font-mono font-black text-transparent bg-clip-text bg-gradient-to-r from-cyan-300 to-indigo-300">
        {display}
      </div>
    </div>
  )
}

function LogLine({
  type,
  agent,
  status,
  reward,
  text,
}: {
  type: string
  agent?: string
  status?: string
  reward?: number
  text?: string
}) {
  return (
    <div className="font-mono">
      <span className="text-indigo-400">[{type}]</span>{' '}
      {agent && (
        <span className={`font-bold ${agent === 'agent_a' ? 'text-blue-400' : 'text-red-400'}`}>{agent}</span>
      )}{' '}
      {status && <span className="text-yellow-400">{status}</span>}{' '}
      {reward !== undefined && <span className="text-green-400">reward={reward.toFixed(2)}</span>}{' '}
      {text && <span className="text-slate-400">{text}</span>}
    </div>
  )
}
