import { useState } from 'react'
import { useApi } from './hooks/useApi'
import { ArenaStage } from './components/ArenaStage'
import { DuelCreator } from './components/DuelCreator'
import { DuelHistory } from './components/DuelHistory'
import { Leaderboard } from './components/Leaderboard'
import { ProblemPanel } from './components/ProblemPanel'
import { TrainingMonitor } from './components/TrainingMonitor'
import type { Problem } from './types'

type Tab = 'arena' | 'leaderboard' | 'training'

function App() {
  const { data: problemsData } = useApi<{ problems: Problem[] }>('/problems')
  const problems = problemsData?.problems || []
  const [selectedProblemId] = useState<string>(problems[0]?.id || '')
  const [selectedDuelId, setSelectedDuelId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('arena')

  const selectedProblem = problems.find((p) => p.id === selectedProblemId) || null

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="bg-slate-900 border-b border-slate-700 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-purple-400">
              Code Colosseum
            </h1>
            <p className="text-sm text-slate-400">Professional RL Arena for Competitive Programming</p>
          </div>
          <nav className="flex gap-2">
            <TabButton active={tab === 'arena'} onClick={() => setTab('arena')}>
              Arena
            </TabButton>
            <TabButton active={tab === 'leaderboard'} onClick={() => setTab('leaderboard')}>
              Leaderboard
            </TabButton>
            <TabButton active={tab === 'training'} onClick={() => setTab('training')}>
              Training
            </TabButton>
          </nav>
        </div>
      </header>

      <main className="p-6 max-w-7xl mx-auto">
        {tab === 'arena' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1 space-y-4">
              <DuelCreator
                problems={problems}
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
          <div className="max-w-5xl">
            <TrainingMonitor />
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
      className={`px-4 py-2 rounded-md text-sm font-semibold transition ${
        active
          ? 'bg-indigo-600 text-white'
          : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
      }`}
    >
      {children}
    </button>
  )
}

export default App
