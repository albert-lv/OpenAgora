# Harbor Integration

OpenAgora can discover and import tasks from the [Harbor](https://github.com/all-hands-ai/harbor) registry. Harbor tasks already use the same `task.toml` + `instruction.md` format that OpenAgora expects, so the integration only needs to download and register the dataset.

## Installation

Harbor support is an optional extra. Install it with:

```bash
uv pip install 'openagora-cli[harbor]'
```

The `harbor` package is not required for the rest of the CLI to work. If it is missing, Harbor-related commands will print a friendly installation hint.

## Enable Harbor discovery

Set the environment variable before running any registry command:

```bash
export ARENA_HARBOR=1
```

When enabled, `arena dataset list` will include public datasets from the Harbor registry, and `arena run --dataset <name@version>` can load them automatically.

## Import a Harbor dataset explicitly

To download a dataset into the local cache without running it yet:

```bash
arena dataset import-harbor swe-bench@1.0.0
```

The dataset is cached under `~/.arena/harbor/<name>@<version>` and can then be used like any local dataset:

```bash
arena run --dataset swe-bench@1.0.0 --agent arena-minimal -n 1
```

## How it works

- `openagora_cli.harbor.client.HarborClient` wraps `harbor.registry.client.factory.RegistryClientFactory` and exposes two async operations: `list_datasets()` and `import_dataset()`.
- `openagora_cli.harbor.backend.HarborRegistryBackend` implements the OpenAgora `RegistryBackend` interface on top of that client. It converts Harbor datasets into OpenAgora `DatasetSpec` objects.
- `default_registry()` adds the Harbor backend only when `ARENA_HARBOR=1` and the `harbor` package is importable.

## Troubleshooting

- `Harbor integration requires 'harbor'` — install the optional extra shown above.
- `could not import ... from Harbor` — check that `ARENA_HARBOR=1` and that the dataset name includes a version (`name@version`).
- Empty Harbor list — the public registry may be unreachable or require authentication; the backend falls back to an empty list so the CLI remains usable.
