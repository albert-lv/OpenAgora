#!/usr/bin/env python3
"""Generate a veRL-compatible parquet dataset from the Code Colosseum problem bank."""

import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from problems import load_problems


def main():
    problems_dir = os.environ.get("PROBLEMS_DIR", str(Path(__file__).parent.parent / "problems"))
    os.environ["PROBLEMS_DIR"] = problems_dir
    output = Path(os.environ.get("OUTPUT", str(Path(__file__).parent.parent / "data" / "colosseum_dataset.parquet")))

    problems = load_problems()
    records = []
    for problem in problems.values():
        prompt = (
            f"Solve this problem: {problem.title}\n\n"
            f"{problem.description}\n\n"
            f"Function signature: {problem.function_signature}\n\n"
            f"Write only the Python solution."
        )
        records.append(
            {
                "index": problem.id,
                "raw_prompt": json.dumps(
                    [
                        {"role": "system", "content": "You are an expert competitive programmer."},
                        {"role": "user", "content": prompt},
                    ]
                ),
                "extra_info": json.dumps(
                    {
                        "openagora_verify": problem.build_verify_command(),
                        "task_file": problem.build_task_file().decode("utf-8"),
                    }
                ),
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)
    df.to_parquet(output, index=False)
    print(f"Wrote {len(records)} samples to {output}")


if __name__ == "__main__":
    main()
