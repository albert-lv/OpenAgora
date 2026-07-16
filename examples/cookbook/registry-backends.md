# Cookbook: Dataset Registry Backends

Arena's dataset registry supports multiple backends.

## Built-in registry

```bash
./bin/arena dataset list
```

Reads from `python/openagora-cli/src/openagora_cli/registry/builtin.json`.

## URL registry

Point to a remote registry JSON:

```bash
export ARENA_REGISTRY_URL=https://example.com/arena-registry.json
./bin/arena dataset list
```

The URL backend merges remote datasets with built-in ones.

## GitHub registry

Use a GitHub repo as the registry source:

```bash
export ARENA_REGISTRY_GITHUB=owner/arena-datasets
./bin/arena dataset list
```

The first call clones the repo with `--sparse` and reads `registry.json`.
Subsequent calls fetch the latest ref and update the sparse checkout.

## Registry JSON format

```json
{
  "datasets": [
    {
      "name": "my-benchmark",
      "version": "0.1.0",
      "description": "...",
      "task_ids": ["task-1"],
      "task_dir": "examples/tasks/my-benchmark",
      "tags": ["code"]
    }
  ]
}
```

## Future

- `arena dataset add --url` / `arena dataset add --github` to persist registry sources
  in `~/.arena/config.toml`
- Version resolution: `dataset@latest`, `dataset@^0.1.0`
