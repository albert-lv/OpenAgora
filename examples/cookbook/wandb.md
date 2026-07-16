# Cookbook: Weights & Biases Observability

The Arena CLI can log every rollout to Weights & Biases (W&B).

## Setup

```bash
export WANDB_API_KEY=...
export WANDB_PROJECT=openagora  # optional, default is "openagora"
export WANDB_ENTITY=your-team   # optional
```

Install the CLI with W&B support:

```bash
cd python/openagora-cli
uv pip install -e '.[wandb]'
```

## Run

```bash
./bin/arena run --env docker --dataset simple-code-tasks --agent arena-minimal
```

You will see `[dim]Plugins enabled: wandb[/dim]` and each rollout will be logged as a W&B run step. ATIF trajectory files are uploaded as artifacts.

## What is logged

- One W&B run per `arena run` invocation
- Metrics per rollout: `reward`, `reward/<dimension>`
- ATIF trajectory artifacts under `atif-trajectory`

## Future

- Hyperparameter sweeps integration
- W&B Tables for trajectory inspection
- Lineage between rollouts and datasets
