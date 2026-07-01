#!/usr/bin/env python3
"""Import a curated subset of HumanEval into the Code Colosseum problem bank.

HumanEval does not publish difficulty labels, so this script uses a small
hand-curated map.  Run it after adding new tasks to the map to regenerate the
problem directories under ../problems/.
"""

import argparse
import gzip
import json
import os
import shutil
import urllib.request
from pathlib import Path

DATASET_URL = "https://github.com/openai/human-eval/raw/master/data/HumanEval.jsonl.gz"

# Curated subset with rough difficulty tags.  Expand as needed.
CURATED = {
    "HumanEval/0": {"difficulty": "easy", "tags": ["string"]},
    "HumanEval/1": {"difficulty": "easy", "tags": ["string"]},
    "HumanEval/2": {"difficulty": "easy", "tags": ["array", "math"]},
    "HumanEval/3": {"difficulty": "easy", "tags": ["array"]},
    "HumanEval/4": {"difficulty": "easy", "tags": ["array"]},
    "HumanEval/5": {"difficulty": "medium", "tags": ["string", "regex"]},
    "HumanEval/6": {"difficulty": "medium", "tags": ["array", "sorting"]},
    "HumanEval/7": {"difficulty": "medium", "tags": ["string"]},
    "HumanEval/8": {"difficulty": "medium", "tags": ["array", "dp"]},
    "HumanEval/9": {"difficulty": "medium", "tags": ["string", "dp"]},
    "HumanEval/10": {"difficulty": "medium", "tags": ["math", "recursion"]},
    "HumanEval/11": {"difficulty": "medium", "tags": ["array", "two-pointers"]},
    "HumanEval/12": {"difficulty": "hard", "tags": ["array", "dp"]},
    "HumanEval/13": {"difficulty": "hard", "tags": ["string", "dp"]},
    "HumanEval/14": {"difficulty": "hard", "tags": ["array", "recursion"]},
    "HumanEval/15": {"difficulty": "medium", "tags": ["array", "sorting"]},
    "HumanEval/16": {"difficulty": "medium", "tags": ["string"]},
    "HumanEval/17": {"difficulty": "hard", "tags": ["array", "dp"]},
    "HumanEval/18": {"difficulty": "medium", "tags": ["string"]},
    "HumanEval/19": {"difficulty": "hard", "tags": ["array", "greedy"]},
}


def download_dataset(cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / "HumanEval.jsonl.gz"
    if cached.exists():
        return cached
    print(f"Downloading HumanEval from {DATASET_URL} ...")
    urllib.request.urlretrieve(DATASET_URL, cached)
    print(f"Cached to {cached}")
    return cached


def extract_signature(prompt: str) -> str:
    """Extract the function signature line from a HumanEval prompt."""
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped.startswith("def "):
            return stripped
    raise ValueError("Could not find function signature in prompt")


def extract_description(prompt: str, signature: str) -> str:
    """Build a problem description from the HumanEval prompt."""
    # Drop the signature line; keep the docstring/body as the description.
    lines = prompt.splitlines()
    cleaned = []
    for line in lines:
        if line.strip() == signature.strip():
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def sanitize_id(task_id: str) -> str:
    """Map 'HumanEval/0' -> 'humaneval-0'."""
    return task_id.replace("/", "-").lower()


def convert_tests(test_code: str, entry_point: str) -> str:
    """Wrap HumanEval tests into pytest-style functions.

    HumanEval tests are plain assert statements; Code Colosseum expects
    pytest to discover test functions.
    """
    lines = test_code.splitlines()
    body_lines = []
    for line in lines:
        stripped = line.strip()
        # Drop the standalone "candidate = ..." line if present.
        if stripped.startswith(f"{entry_point} = ") or stripped.startswith(
            "candidate = "
        ):
            continue
        body_lines.append(line)
    body = "\n".join(body_lines).strip()
    body = body.replace("candidate", entry_point)
    return f"from solution import {entry_point}\n\n\ndef test_humaneval():\n{indent(body)}\n"


def indent(text: str, width: int = 4) -> str:
    prefix = " " * width
    return "\n".join(
        prefix + line if line.strip() else line for line in text.splitlines()
    )


def build_public_tests(prompt: str, entry_point: str) -> str:
    """Create minimal public tests from the docstring examples if present."""
    # HumanEval prompts usually contain examples in the docstring.  For now we
    # just emit a smoke import test so the public_tests file is non-empty.
    return f"from solution import {entry_point}\n\n\ndef test_import():\n    assert callable({entry_point})\n"


def import_problems(problems_dir: Path, overwrite: bool = False) -> list[str]:
    cache_dir = Path(
        os.environ.get("HF_CACHE", str(Path.home() / ".cache" / "huggingface"))
    )
    archive = download_dataset(cache_dir)

    with gzip.open(archive, "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    imported: list[str] = []
    for row in rows:
        task_id = row["task_id"]
        if task_id not in CURATED:
            continue
        meta = CURATED[task_id]
        problem_id = sanitize_id(task_id)
        root = problems_dir / problem_id
        if root.exists() and not overwrite:
            print(f"Skipping existing {problem_id}")
            imported.append(problem_id)
            continue
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)

        prompt = row["prompt"]
        signature = extract_signature(prompt)
        description = extract_description(prompt, signature)

        problem_json = {
            "id": problem_id,
            "title": row["entry_point"].replace("_", " ").title(),
            "difficulty": meta["difficulty"],
            "tags": meta["tags"],
            "description": description,
            "function_signature": signature,
            "language": "python",
            "time_limit_ms": 1000,
            "memory_limit_mb": 256,
        }
        (root / "problem.json").write_text(json.dumps(problem_json, indent=2) + "\n")
        (root / "solution.py").write_text(row["canonical_solution"])
        (root / "public_tests.py").write_text(
            build_public_tests(prompt, row["entry_point"])
        )
        (root / "hidden_tests.py").write_text(
            convert_tests(row["test"], row["entry_point"])
        )

        print(f"Imported {problem_id} ({meta['difficulty']})")
        imported.append(problem_id)

    return imported


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--problems-dir",
        default=str(Path(__file__).parent.parent / "problems"),
        help="Target problem bank directory",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing problem directories",
    )
    args = parser.parse_args()

    problems_dir = Path(args.problems_dir)
    imported = import_problems(problems_dir, overwrite=args.overwrite)
    print(f"Imported {len(imported)} problems to {problems_dir}")


if __name__ == "__main__":
    main()
