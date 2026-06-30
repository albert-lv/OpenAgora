#!/usr/bin/env python3
"""
Prepare a real SWE-bench Lite task for the Arena × SWE-agent demo.

Usage:
    python prepare_task.py [--instance-id pallets__flask-4045]

The script:
1. Loads the SWE-bench_Lite dataset from Hugging Face.
2. Selects a task instance (default: a small Flask instance).
3. Computes the official SWE-bench Docker image name.
4. Builds the unit-test verification command from FAIL_TO_PASS tests.
5. Writes task.json ready for run_rollout.py.
"""

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

from datasets import load_dataset
from swebench.harness.utils import get_modified_files


def swebench_image_name(instance_id: str, arch: str = "x86_64") -> str:
    """
    Construct the official SWE-bench instance image name.
    SWE-bench replaces the repo delimiter '__' with '_1776_' in image tags.
    """
    tag = instance_id.lower().replace("__", "_1776_")
    return f"swebench/sweb.eval.{arch}.{tag}:latest"


def parse_test_name(test_str: str) -> tuple[str | None, str | None, str]:
    """
    Parse a FAIL_TO_PASS entry into (module_or_file, class, method).

    Supports:
    - pytest node ids: ``path/to/test.py::method`` or ``path/to/test.py::Class::method``
    - unittest-style strings: ``test_method (module.submodule.Class)``
    - bare method names: ``test_method``
    """
    # pytest node id
    if "::" in test_str:
        parts = test_str.split("::")
        file_part = parts[0]
        method = parts[-1]
        cls = parts[-2] if len(parts) >= 3 else None
        return file_part, cls, method

    # unittest style: "test_method (module.submodule.Class)"
    m = re.match(r"(\w+)\s+\(([\w.]+)\.(\w+)\)", test_str)
    if m:
        return m.group(2), m.group(3), m.group(1)

    return None, None, test_str


def build_test_command(fail_to_pass: list[str], test_patch: str, repo: str) -> str:
    """
    Build a bash command that activates the SWE-bench conda environment and
    runs the FAIL_TO_PASS unit tests.

    SWE-bench's FAIL_TO_PASS values are not always valid pytest node ids; they
    can be unittest-style strings or bare function names. We therefore run the
    test files modified by test_patch and filter to the target test names. For
    Django we use the official ``runtests.py`` entry point which configures the
    settings module automatically.

    Arena's verify runner executes the command via ``sh -c``, so we wrap the
    conda activation in ``bash -lc`` to avoid dash's lack of ``source``.
    """
    if not fail_to_pass:
        raise ValueError("No FAIL_TO_PASS tests found for the selected instance")

    test_files = get_modified_files(test_patch)

    if repo == "django/django":
        labels = []
        for t in fail_to_pass:
            mod, cls, method = parse_test_name(t)
            if mod and cls:
                labels.append(f"{mod}.{cls}.{method}")
            else:
                labels.append(t)
        label_str = " ".join(shlex.quote(l) for l in labels)
        inner = (
            "source /opt/miniconda3/bin/activate && "
            "conda activate testbed && "
            f"cd /testbed && ./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 {label_str}"
        )
    else:
        names = []
        for t in fail_to_pass:
            _, _, method = parse_test_name(t)
            names.append(method)
        name_filter = " or ".join(names)
        files = " ".join(shlex.quote(f) for f in test_files) if test_files else ""
        inner = (
            "source /opt/miniconda3/bin/activate && "
            "conda activate testbed && "
            f"cd /testbed && pytest -x -k {shlex.quote(name_filter)} {files}"
        ).strip()

    return f"bash -lc {shlex.quote(inner)}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a SWE-bench task for Arena")
    parser.add_argument(
        "--instance-id",
        default="pallets__flask-4045",
        help="SWE-bench instance id to use (default: pallets__flask-4045)",
    )
    parser.add_argument(
        "--output",
        default="task.json",
        help="Path to write the task JSON (default: task.json)",
    )
    args = parser.parse_args()

    print(f"Loading SWE-bench_Lite dataset and looking for {args.instance_id} ...")
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test", streaming=True)

    instance = None
    for row in ds:
        if row["instance_id"] == args.instance_id:
            instance = row
            break

    if instance is None:
        print(f"Instance {args.instance_id} not found in SWE-bench_Lite", file=sys.stderr)
        return 1

    # FAIL_TO_PASS may be a JSON string or a list.
    f2p = instance["FAIL_TO_PASS"]
    if isinstance(f2p, str):
        f2p = json.loads(f2p)

    task = {
        "task_id": f"swe-bench/{args.instance_id}",
        "description": instance["problem_statement"],
        "repository": f"https://github.com/{instance['repo']}",
        "commit": instance["base_commit"],
        "base_commit": instance["base_commit"],
        "sandbox_image": swebench_image_name(args.instance_id),
        "test_command": build_test_command(f2p, instance["test_patch"], instance["repo"]),
        "FAIL_TO_PASS": f2p,
        "golden_patch": instance["patch"],
        "test_patch": instance["test_patch"],
        "env_vars": {
            "USE_LLM": "1",
            "ARENA_MODEL": "qwen2.5-coder:1.5b",
            "LLM_MAX_TURNS": "3",
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}")
    print(f"  image:        {task['sandbox_image']}")
    print(f"  test_command: {task['test_command']}")
    print(f"  #fail_to_pass: {len(f2p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
