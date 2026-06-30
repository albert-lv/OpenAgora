#!/usr/bin/env python3
"""
Deploy a relationship-chat RL checkpoint to Ollama.

Because the base model is qwen3.5:0.8b (Qwen3.5 architecture), Ollama can import
the PEFT/LoRA adapter directly in Safetensors format using the ADAPTER
instruction. No GGUF conversion or model merging is required.

Usage:
    python deploy_to_ollama.py ./checkpoints/checkpoint-6

Then chat with the model:
    ollama run relationship-chat
"""

import argparse
import subprocess
import sys
from pathlib import Path

MODELFILE_TEMPLATE = """# RL-tuned relationship-chat assistant
FROM qwen3.5:0.8b
ADAPTER .

SYSTEM \"\"\"
You are her caring boyfriend/husband. She just sent a message. Please reply in English.
First acknowledge her emotions, then gently ask or express support;
do not blame, lecture, say "calm down" or "what's the big deal";
be warm and sincere, keep it under 150 words.
\"\"\"

PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER num_ctx 2048
"""


def main():
    parser = argparse.ArgumentParser(description="Deploy a relationship-chat checkpoint to Ollama")
    parser.add_argument(
        "checkpoint",
        nargs="?",
        default="./checkpoints/checkpoint-6",
        help="Path to the LoRA checkpoint directory (default: ./checkpoints/checkpoint-6)",
    )
    parser.add_argument(
        "--model-name",
        default="relationship-chat",
        help="Name of the Ollama model to create (default: relationship-chat)",
    )
    args = parser.parse_args()

    checkpoint_path = Path(args.checkpoint).resolve()
    if not checkpoint_path.exists():
        print(f"Checkpoint not found: {checkpoint_path}", file=sys.stderr)
        sys.exit(1)

    required = ["adapter_config.json", "adapter_model.safetensors"]
    missing = [f for f in required if not (checkpoint_path / f).exists()]
    if missing:
        print(
            f"Checkpoint directory is missing adapter files: {missing}",
            file=sys.stderr,
        )
        sys.exit(1)

    modelfile_path = checkpoint_path / "Modelfile"
    modelfile_path.write_text(MODELFILE_TEMPLATE, encoding="utf-8")
    print(f"Wrote {modelfile_path}")

    print(f"Creating Ollama model '{args.model_name}' from {checkpoint_path} ...")
    result = subprocess.run(
        ["ollama", "create", args.model_name, "-f", str(modelfile_path)],
        cwd=str(checkpoint_path),
    )
    if result.returncode != 0:
        print("ollama create failed", file=sys.stderr)
        sys.exit(result.returncode)

    print(f"\nDone! Run: ollama run {args.model_name}")


if __name__ == "__main__":
    main()
