# Cookbook: Multi-Reward Evaluation

OpenAgora's verification plane supports multiple reward dimensions. Instead of a single pass/fail score, a rollout can produce:

```text
correctness: 1.0
style:       0.8
efficiency:  0.7
total:       0.88
```

## How it works

1. The agent writes rewards to `/sandbox/.arena/rewards.jsonl`, one JSON object per line:

```json
{"name": "correctness", "value": 1.0, "weight": 0.6, "source": "agent:test"}
{"name": "style", "value": 0.8, "weight": 0.3, "source": "agent:rubric"}
{"name": "efficiency", "value": 0.7, "weight": 0.1, "source": "agent:profiler"}
```

2. The server reads these rewards alongside the verifier command output.
3. `verify.TotalReward()` computes the weighted average.
4. The gRPC `VerificationReport` includes `rewards` and `total_reward`.

## Running with the CLI

```bash
./bin/arena run --env docker --task examples/tasks/multi-reward
```

## Future: reward.toml

Following Harbor's rewardkit, OpenAgora will support `tests/reward.toml` to declare dimensions and aggregation rules declaratively:

```toml
[[reward]]
name = "correctness"
weight = 0.6
aggregation = "all_pass"

[[reward]]
name = "style"
weight = 0.4
aggregation = "mean"
```

Each subdirectory of `tests/` will become an independent verifier.
