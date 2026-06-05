"""
Arena + veRL integration example.

This script demonstrates how to use Arena as the rollout provider
for veRL training.
"""

from arena_verl import ArenaRolloutProvider

# Replace veRL's default vLLM rollout with Arena
provider = ArenaRolloutProvider(
    arena_endpoint="localhost:9090",
    sandbox_image="openhands:latest",
    llm_backend="http://localhost:8000/v1",
    verify_command="pytest -k regression",
    max_concurrent=64,
)

# Generate trajectories for a batch of SWE-bench tasks
# prompts = load_swe_bench_tasks(...)
# trajectories = provider.generate(prompts=prompts)

# Feed into veRL GRPO trainer
# trainer.train(trajectories)

print("veRL integration example — see ArenaRolloutProvider for full usage")
