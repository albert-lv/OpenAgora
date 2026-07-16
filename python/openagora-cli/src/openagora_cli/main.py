"""Arena CLI — Harbor-style command line interface for OpenAgora."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from openagora_sdk import ArenaClient

from openagora_cli.agents.registry import default_registry as default_agent_registry
from openagora_cli.plugins.manager import PluginManager
from openagora_cli.registry.registry import default_registry as default_dataset_registry
from openagora_cli.task.loader import load_task
from openagora_cli.trajectory import atif

app = typer.Typer(
    name="arena",
    help="Run agent evaluations and benchmarks in OpenAgora.",
    no_args_is_help=True,
)
dataset_app = typer.Typer(name="dataset", help="Dataset / benchmark registry commands.")
provider_app = typer.Typer(name="provider", help="Sandbox provider commands.")
trajectory_app = typer.Typer(name="trajectory", help="Trajectory / ATIF commands.")
app.add_typer(dataset_app)
app.add_typer(provider_app)
app.add_typer(trajectory_app)
console = Console()


@dataset_app.command(name="list", help="List built-in datasets/benchmarks.")
def datasets_list():
    registry = default_dataset_registry()
    specs = registry.list()
    table = Table(title="Arena Datasets")
    table.add_column("Name", style="cyan")
    table.add_column("Version", style="magenta")
    table.add_column("Description")
    table.add_column("Tags", style="green")
    for spec in specs:
        table.add_row(
            spec.name,
            spec.version,
            spec.description,
            ", ".join(spec.tags),
        )
    console.print(table)


@dataset_app.command(name="add", help="Register a dataset source (URL or GitHub).")
def dataset_add(
    url: Annotated[
        Optional[str],
        typer.Option("--url", "-u", help="URL to a registry JSON file."),
    ] = None,
    github: Annotated[
        Optional[str],
        typer.Option(
            "--github", "-g", help="GitHub repo owner/name containing registry.json."
        ),
    ] = None,
):
    if url:
        os.environ["ARENA_REGISTRY_URL"] = url
        console.print(f"[green]Added[/green] URL registry: {url}")
        return
    if github:
        os.environ["ARENA_REGISTRY_GITHUB"] = github
        console.print(f"[green]Added[/green] GitHub registry: {github}")
        return
    console.print("[red]Error:[/red] Either --url or --github must be provided.")
    raise typer.Exit(1)


@dataset_app.command(
    name="import-harbor",
    help="Import a dataset from the Harbor registry into the local cache.",
)
def dataset_import_harbor(
    spec: Annotated[
        str,
        typer.Argument(help="Dataset name[@version] from the Harbor registry."),
    ],
    cache_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--cache-dir",
            "-c",
            help="Directory to cache the downloaded dataset.",
        ),
    ] = None,
):
    """Download a Harbor dataset so it can be used with ``arena run --dataset``.

    This command requires the ``harbor`` extra to be installed and the
    ``ARENA_HARBOR`` environment variable to be enabled.
    """
    from openagora_cli.harbor.backend import HarborRegistryBackend

    backend = HarborRegistryBackend(cache_dir=cache_dir)
    dataset_spec = backend.load(spec)
    if dataset_spec is None:
        console.print(
            f"[red]Error:[/red] could not import {spec!r} from Harbor. "
            "Ensure 'openagora-cli[harbor]' is installed and ARENA_HARBOR=1."
        )
        raise typer.Exit(1)

    console.print(
        f"[green]Imported[/green] {dataset_spec.full_name} -> {dataset_spec.task_dir}"
    )


@app.command(name="run", help="Run a single task or dataset.")
def run(
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Sandbox provider (registered in openagora-server).",
        ),
    ] = "docker",
    task: Annotated[
        Optional[str],
        typer.Option(
            "--task",
            "-t",
            help="Path to a task directory or legacy task.json.",
        ),
    ] = None,
    dataset: Annotated[
        Optional[str],
        typer.Option(
            "--dataset",
            "-d",
            help="Dataset name[@version] from `arena dataset list`.",
        ),
    ] = None,
    agent: Annotated[
        str,
        typer.Option(
            "--agent",
            "-a",
            help="Agent adapter name (e.g. arena-minimal).",
        ),
    ] = "arena-minimal",
    model: Annotated[
        Optional[str],
        typer.Option(
            "--model",
            "-m",
            help="Model override passed to the agent adapter.",
        ),
    ] = None,
    llm_backend: Annotated[
        str,
        typer.Option(
            "--llm-backend",
            help="Upstream LLM backend URL.",
        ),
    ] = "http://localhost:8000/v1",
    endpoint: Annotated[
        str,
        typer.Option(
            "--endpoint",
            help="OpenAgora gRPC endpoint.",
        ),
    ] = "localhost:9090",
    n: Annotated[
        int,
        typer.Option(
            "-n",
            help="Number of tasks to run (for datasets).",
        ),
    ] = 1,
    wait: Annotated[
        bool,
        typer.Option(
            "--wait/--no-wait",
            help="Wait for rollout completion.",
        ),
    ] = True,
):
    if task is None and dataset is None:
        console.print("[red]Error:[/red] Either --task or --dataset must be provided.")
        raise typer.Exit(1)

    registry = default_agent_registry()
    try:
        agent_adapter = registry.get(agent)
    except KeyError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    client = ArenaClient(endpoint=endpoint)
    plugins = PluginManager()
    if plugins.enabled_plugins:
        console.print(
            f"[dim]Plugins enabled: {', '.join(plugins.enabled_plugins)}[/dim]"
        )

    # Validate requested skills once we have the task config (done in the loop).

    job_context = {
        "command": "run",
        "env": env,
        "agent": agent,
        "model": model,
        "dataset": dataset,
        "task": task,
        "endpoint": endpoint,
    }
    plugins.on_job_start(job_context)

    tasks: list[tuple[str, Path]] = []
    if task:
        tasks.append((task, Path(task)))
    else:
        tasks = _resolve_dataset_tasks(dataset, n)

    results = []
    for task_name, task_path in tasks:
        try:
            bundle = load_task(task_path)
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

        if model:
            bundle.config.agent.model = model

        unsupported = agent_adapter.validate_skills(bundle.config.agent.skills)
        if unsupported:
            console.print(
                f"[red]Error:[/red] agent {agent} does not support skills: {unsupported}"
            )
            raise typer.Exit(1)

        task_json, agent_env = agent_adapter.prepare_task(
            bundle.config, bundle.instruction
        )
        image = agent_adapter.resolve_image(bundle.config)
        command = agent_adapter.entrypoint(
            bundle.config, task_json, bundle.instruction, agent_env
        )
        env_vars = {**bundle.config.environment.env_vars, **agent_env}

        console.print(f"[bold]Running[/bold] {task_name} with {agent} on {env}")
        result = client.create_rollout(
            task_id=bundle.task_id,
            image=image,
            llm_backend=llm_backend,
            verify=bundle.config.to_verify_dict(),
            memory=bundle.config.environment.memory,
            cpus=bundle.config.environment.cpus,
            timeout_seconds=bundle.config.environment.timeout_seconds,
            env_vars=env_vars,
            task_file=bundle.to_task_file_bytes(),
            command=command,
        )
        rollout_id = result["rollout_id"]
        console.print(f"  Rollout: {rollout_id}")

        plugins.on_rollout_start(
            rollout_id,
            {
                "task_id": bundle.task_id,
                "instruction": bundle.instruction,
                "agent": agent,
                "provider": env,
                "model": model,
            },
        )

        if wait:
            info = client.wait(rollout_id, poll_interval=1.0)
            _print_result(info)
            info["task_id"] = bundle.task_id
            info["instruction"] = bundle.instruction
            info["agent"] = agent
            info["provider"] = env
            info["model"] = model
            info["trajectory_path"] = _write_atif(client, rollout_id, agent, model)
            plugins.on_rollout_end(rollout_id, info)
            results.append(info)
        else:
            plugins.on_rollout_end(
                rollout_id, {"rollout_id": rollout_id, "status": "pending"}
            )
            results.append(result)

    plugins.on_job_end(job_context)

    if wait and len(results) == 1:
        sys.exit(0 if results[0]["status"] == "success" else 1)


def _write_atif(
    client: ArenaClient, rollout_id: str, agent: str, model: Optional[str]
) -> Optional[str]:
    """Fetch trajectory and write ATIF file. Returns the file path or None."""
    try:
        steps = client.get_trajectory(rollout_id)
        if not steps:
            return None
        trajectory = atif.convert(steps, agent_name=agent, model_name=model)
        out_dir = Path("jobs") / rollout_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "trajectory.atif.json"
        out_path.write_text(atif.to_json(trajectory), encoding="utf-8")
        return str(out_path)
    except Exception as exc:
        console.print(f"[yellow]warning:[/yellow] failed to write ATIF: {exc}")
        return None


@trajectory_app.command(name="export", help="Export a rollout trajectory to ATIF v1.7.")
def trajectory_export(
    rollout_id: Annotated[str, typer.Option("--rollout", "-r", help="Rollout ID")],
    agent: Annotated[
        str, typer.Option("--agent", "-a", help="Agent name")
    ] = "arena-minimal",
    model: Annotated[
        Optional[str], typer.Option("--model", "-m", help="Model name")
    ] = None,
    endpoint: Annotated[str, typer.Option("--endpoint")] = "localhost:9090",
    output: Annotated[
        Optional[str], typer.Option("--output", "-o", help="Output file path")
    ] = None,
):
    client = ArenaClient(endpoint=endpoint)
    steps = client.get_trajectory(rollout_id)
    if not steps:
        console.print(f"[red]Error:[/red] no trajectory found for {rollout_id}")
        raise typer.Exit(1)
    trajectory = atif.convert(steps, agent_name=agent, model_name=model)
    if output is None:
        out_dir = Path("jobs") / rollout_id
        out_dir.mkdir(parents=True, exist_ok=True)
        output = str(out_dir / "trajectory.atif.json")
    Path(output).write_text(atif.to_json(trajectory), encoding="utf-8")
    console.print(f"ATIF trajectory written to {output}")


def _resolve_dataset_tasks(dataset_arg: str, n: int) -> list[tuple[str, Path]]:
    name, _, version = dataset_arg.partition("@")
    registry = default_dataset_registry()
    spec = registry.load(name, version)
    if spec is None:
        console.print(f"[red]Error:[/red] dataset {dataset_arg!r} not found.")
        raise typer.Exit(1)

    task_dir = Path(spec.task_dir) if spec.task_dir else None
    if task_dir is None or not task_dir.exists():
        console.print(
            f"[red]Error:[/red] task directory for {dataset_arg} not found: {task_dir}"
        )
        raise typer.Exit(1)

    # Discover task subdirectories or fall back to task.json.
    candidates = []
    for sub in sorted(task_dir.iterdir()):
        if sub.is_dir() and (sub / "task.toml").exists():
            candidates.append((sub.name, sub))
        elif sub.is_file() and sub.name.endswith(".json"):
            candidates.append((sub.stem, sub))

    if not candidates:
        # Treat the dataset dir itself as a single task.
        candidates.append((spec.name, task_dir))

    return candidates[:n]


def _print_result(info: dict) -> None:
    status = info.get("status", "unknown")
    color = (
        "green" if status == "success" else "red" if status == "failed" else "yellow"
    )
    console.print(f"  Status: [{color}]{status}[/{color}]")
    reward = info.get("reward")
    if reward is not None:
        console.print(f"  Reward: {reward}")
    report = info.get("verification_report") or {}
    rewards = report.get("rewards", [])
    if len(rewards) > 1:
        table = Table(title="Reward dimensions")
        table.add_column("Name")
        table.add_column("Value")
        table.add_column("Weight")
        for rw in rewards:
            table.add_row(
                rw.get("name", "-"), str(rw.get("value", "")), str(rw.get("weight", ""))
            )
        console.print(table)


@provider_app.command(name="list", help="List built-in sandbox providers.")
def providers_list():
    console.print("Sandbox providers are resolved by openagora-server --sandbox flag.")
    console.print("Built-in: docker, local, mock")


if __name__ == "__main__":
    app()
