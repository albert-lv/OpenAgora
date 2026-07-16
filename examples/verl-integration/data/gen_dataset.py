#!/usr/bin/env python3
"""Generate minimal Parquet datasets for the Arena × veRL GRPO demo.

``extra_info`` is written as a native Parquet struct column (read back as a
``dict``), not as a JSON string, so veRL's ``rl_dataset`` consumes it without
any compatibility patching. ``ArenaAgentLoop`` still tolerates legacy
JSON-encoded ``extra_info`` strings for external datasets.

Outputs (written to the current directory, or to ``argv[1]`` if given):

- ``train.parquet``        — 8 rows; read by ``train_grpo_arena*.sh``
- ``test.parquet``         — 2 rows; validation split for the GRPO launchers
- ``demo_dataset.parquet`` — copy of the train rows for the CPU / docker demo
  (``train_cpu.py`` and the docker-compose stacks read it via ``DATASET_PATH``)
"""

import json
import sys
from pathlib import Path

import pandas as pd

MESSAGES = [
    {
        "role": "system",
        "content": "You are a helpful coding assistant.",
    },
    {
        "role": "user",
        "content": "Write a Python function `add(a, b)` that returns the sum of two integers.",
    },
]

VERIFY_COMMAND = (
    "cd /sandbox && python -c \"from solution import add; assert add(2,3)==5; print('PASS')\""
)


def _row(index: int) -> dict:
    return {
        "index": index,
        "prompt": json.dumps(MESSAGES),
        "raw_prompt": MESSAGES,
        # Native struct column: veRL reads this back as a dict.
        "extra_info": {"openagora_verify": VERIFY_COMMAND},
        "reward": 0.0,
    }


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)

    train_rows = [_row(i) for i in range(8)]
    test_rows = [_row(100 + i) for i in range(2)]

    for name, rows in (
        ("train.parquet", train_rows),
        ("test.parquet", test_rows),
        ("demo_dataset.parquet", train_rows),
    ):
        path = out_dir / name
        pd.DataFrame(rows).to_parquet(path, index=False)
        print(f"Wrote {len(rows)} rows to {path}")


if __name__ == "__main__":
    main()
