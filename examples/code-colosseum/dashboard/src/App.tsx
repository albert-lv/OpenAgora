import { useState } from 'react'
import { useApi } from './hooks/useApi'
import { ArenaStage } from './components/ArenaStage'
import { DuelCreator } from './components/DuelCreator'
import { DuelHistory } from './components/DuelHistory'
import { Leaderboard } from './components/Leaderboard'
import { ProblemPanel } from './components/ProblemPanel'
import { TrainingMonitor } from './components/TrainingMonitor'
import { ArenaDashboard } from './components/ArenaDashboard'
import { BenchmarkStage } from './components/BenchmarkStage'
import { TrajectoryStage } from './components/TrajectoryStage'
import type { Problem } from './types'

type Tab = 'dashboard' | 'arena' | 'leaderboard' | 'training' | 'benchmark' | 'trajectory'

function App() {
  const { data: problemsData } = useApi<{ problems: Problem[] }>('/problems')
  const problems = problemsData?.problems || []
  const [selectedProblemId, setSelectedProblemId] = useState<string>(problems[0]?.id || '')
  const [selectedDuelId, setSelectedDuelId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('dashboard')

  const selectedProblem = problems.find((p) => p.id === selectedProblemId) || null

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="bg-slate-900 border-b border-slate-700/70 px-6 py-4 shadow-lg shadow-indigo-900/10">
        <div className="flex items-center justify-between max-w-[1600px] mx-auto">
          <div className="flex items-center gap-3">
            <div className="text-3xl">🏟️</div>
            <div>
              <h1 className="text-2xl font-extrabold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-amber-300 via-orange-400 to-purple-500">
                Code Colosseum
              </h1>
              <p className="text-sm text-slate-400">Professional RL Arena for Competitive Programming</p>
            </div>
          </div>
          <nav className="flex gap-2 bg-slate-950/40 p-1 rounded-lg border border-slate-700/50">
            <TabButton active={tab === 'dashboard'} onClick={() => setTab('dashboard')}>
              🌌 Command Center
            </TabButton>
            <TabButton active={tab === 'arena'} onClick={() => setTab('arena')}>
              ⚔️ Arena
            </TabButton>
            <TabButton active={tab === 'leaderboard'} onClick={() => setTab('leaderboard')}>
              🏆 Leaderboard
            </TabButton>
            <TabButton active={tab === 'training'} onClick={() => setTab('training')}>
              📈 Training
            </TabButton>
            <TabButton active={tab === 'benchmark'} onClick={() => setTab('benchmark')}>
              📊 Benchmark
            </TabButton>
            <TabButton active={tab === 'trajectory'} onClick={() => setTab('trajectory')}>
              🔍 Trajectory
            </TabButton>
          </nav>
        </div>
      </header>

      <main className="p-6 max-w-[1600px] mx-auto">
        {tab === 'dashboard' && (
          <ArenaDashboard />
        )}

        {tab === 'arena' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1 space-y-4">
              <DuelCreator
                problems={problems}
                selectedProblemId={selectedProblemId}
                onProblemChange={setSelectedProblemId}
                onCreated={(id) => {
                  setSelectedDuelId(id)
                }}
              />
              <ProblemPanel problem={selectedProblem} />
              <DuelHistory onSelect={setSelectedDuelId} selectedId={selectedDuelId} />
            </div>
            <div className="lg:col-span-2">
              <ArenaStage duelId={selectedDuelId} problem={selectedProblem} />
            </div>
          </div>
        )}

        {tab === 'leaderboard' && (
          <div className="max-w-3xl">
            <Leaderboard />
          </div>
        )}

        {tab === 'training' && (
          <div className="max-w-6xl">
            <TrainingMonitor />
          </div>
        )}

        {tab === 'benchmark' && (
          <div className="max-w-6xl">
            <BenchmarkStage problems={problems} />
          </div>
        )}

        {tab === 'trajectory' && (
          <div className="max-w-6xl">
            <TrajectoryStage />
          </div>
        )}
      </main>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-md text-sm font-semibold transition-all duration-200 ${
        active
          ? 'bg-indigo-600 text-white shadow-md shadow-indigo-900/40'
          : 'bg-transparent text-slate-300 hover:bg-slate-800 hover:text-white'
      }`}
    >
      {children}
    </button>
  )
}

export default App
