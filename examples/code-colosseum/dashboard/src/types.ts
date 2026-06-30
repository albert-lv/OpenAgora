export interface Problem {
  id: string
  title: string
  difficulty: string
  tags: string[]
  description: string
  function_signature: string
  language: string
}

export interface UsageInfo {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  steps: number
}

export interface DuelAgent {
  name: string
  rollout_id?: string
  status: string
  reward: number
  code?: string
  stdout?: string
  stderr?: string
  usage?: UsageInfo
  estimated_cost_usd?: number
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

export interface GroupStat {
  group: number
  mean: number
  std: number
  min: number
  max: number
}

export interface TrainingStatus {
  running: boolean
  step: number
  avg_reward: number
  pass_at_k: number
  policy_loss: number
  kl: number
  entropy: number
  kl_loss?: number
  group_stats: GroupStat[]
  group_rewards: number[][]
  sample?: string
  history: Record<string, number | boolean | string>[]
}

export interface SSEEvent {
  type: string
  [key: string]: unknown
}

export interface BenchmarkSummaryEntry {
  runs: number
  passed: number
  total_reward: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  total_duration_seconds: number
  total_cost_usd: number
  pass_at_1: number
  average_reward: number
  average_cost_usd: number
  reward_per_dollar: number
}

export interface BenchmarkSummary {
  [agent: string]: BenchmarkSummaryEntry
}

export interface Benchmark {
  id: string
  status: string
  created_at: number
  finished_at?: number
  agent_types: string[]
  problem_ids: string[]
  total_runs: number
  completed_runs: number
}

export interface TrajectoryStep {
  request?: {
    messages?: { role: string; content: string }[]
    [key: string]: unknown
  }
  response?: {
    choices_json?: string | Uint8Array
    usage?: UsageInfo
    [key: string]: unknown
  }
}
