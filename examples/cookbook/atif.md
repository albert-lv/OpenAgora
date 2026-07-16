# Cookbook: ATIF Trajectory Export

OpenAgora can export rollouts to the **Agent Trajectory Interchange Format (ATIF) v1.7**, the same format used by Harbor.

## Export after a run

When you run with `--wait`, the CLI automatically writes an ATIF file to:

```text
jobs/<rollout_id>/trajectory.atif.json
```

## Export manually

```bash
./bin/arena trajectory export --rollout <rollout_id> --agent arena-minimal --output out.atif.json
```

## Schema coverage

The current exporter maps OpenAgora `TrajectoryStep` records to ATIF:

- `schema_version`: `ATIF-v1.7`
- `trajectory_id`: random UUID per export
- `agent.name`: the agent adapter name
- `steps`: system/user messages + agent turns with tool calls and observations
- `final_metrics`: aggregated prompt/completion tokens

Future improvements:

- `session_id` linked to rollout trace ID
- `subagent_trajectories` for multi-agent workflows
- `tool_definitions` from agent adapter metadata
