export interface Problem {
  id: string
  title: string
  difficulty: string
  tags: string[]
  description: string
  function_signature: string
  language: string
}

export interface DuelAgent {
  name: string
  rollout_id?: string
  status: string
  reward: number
  code?: string
  stdout?: string
  stderr?: string
}

export interface Duel {
  id: string
  problem_id: string
  problem_title: string
  status: string
  winner?: string
  created_at: number
  finished_at?: number
  agent_a: DuelAgent
  agent_b: DuelAgent
}

export interface LeaderboardEntry {
  id: string
  name: string
  rating: number
  wins: number
  losses: number
  draws: number
  matches: number
}

export interface TrainingStatus {
  running: boolean
  step: number
  avg_reward: number
  pass_at_k: number
  policy_loss: number
  value_loss: number
  kl: number
  entropy: number
  history: Record<string, number | boolean>[]
}

export interface SSEEvent {
  type: string
  [key: string]: unknown
}
