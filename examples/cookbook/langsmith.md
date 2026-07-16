# Cookbook: LangSmith Observability

The Arena CLI can automatically log every rollout to LangSmith.

## Setup

```bash
export LANGSMITH_API_KEY=ls-...
export LANGSMITH_PROJECT=openagora  # optional, default is "openagora"
export LANGSMITH_ENDPOINT=https://api.smith.langchain.com  # optional
```

Install the CLI with LangSmith support:

```bash
cd python/openagora-cli
uv pip install -e '.[langsmith]'
```

## Run

```bash
./bin/arena run --env docker --dataset simple-code-tasks --agent arena-minimal
```

You will see `[dim]Plugins enabled: langsmith[/dim]` and each rollout will be
uploaded as a LangSmith run under the configured project.

## What is logged

- Inputs: task_id, instruction, agent, provider, model
- Outputs: status, reward, verification_report
- Extra: rollout_id, trajectory_path (when available)

## Future

- W&B plugin for metrics and artifact logging
- Server-side event streaming so plugins receive real-time lifecycle events
- ATIF trajectory upload as LangSmith attachment
