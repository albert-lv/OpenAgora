#!/usr/bin/env python3
"""Generate a minimal Parquet dataset for CPU GRPO demo."""

import json
import sys

import pandas as pd


def main():
    data = []
    for i in range(8):
        data.append(
            {
                "index": i,
                "prompt": json.dumps(
                    [
                        {
                            "role": "system",
                            "content": "You are a helpful coding assistant.",
                        },
                        {
                            "role": "user",
                            "content": "Write a Python function `add(a, b)` that returns the sum of two integers.",
                        },
                    ]
                ),
                "raw_prompt": [
                    {
                        "role": "system",
                        "content": "You are a helpful coding assistant.",
                    },
                    {
                        "role": "user",
                        "content": "Write a Python function `add(a, b)` that returns the sum of two integers.",
                    },
                ],
                "extra_info": json.dumps(
                    {"arena_verify": "cd /sandbox && python -c \"from solution import add; assert add(2,3)==5; print('PASS')\""}
                ),
                "reward": 0.0,
            }
        )

    df = pd.DataFrame(data)
    output = sys.argv[1] if len(sys.argv) > 1 else "demo_dataset.parquet"
    df.to_parquet(output, index=False)
    print(f"Wrote {len(df)} rows to {output}")


if __name__ == "__main__":
    main()
