#!/usr/bin/env python3
"""
Pre-download HuggingFace model for offline Docker usage.

Usage:
    # With proxy (if behind firewall):
    HF_PROXY=socks5h://127.0.0.1:YOUR_PROXY_PORT python3 download_model.py

    # Without proxy:
    python3 download_model.py

The model will be cached to ~/.cache/huggingface (or $HF_HOME).
Mount this directory into the Docker container when running train_cpu.py.
"""

import os

HF_PROXY = os.environ.get("HF_PROXY")
if HF_PROXY:
    os.environ["HTTP_PROXY"] = HF_PROXY
    os.environ["HTTPS_PROXY"] = HF_PROXY
    print(f"Using proxy: {HF_PROXY}")

from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen3.5-0.8B")

def main():
    print(f"Downloading model: {MODEL_NAME}")
    print("This may take a while depending on your network...")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    print(f"Tokenizer downloaded: {tokenizer.__class__.__name__}")

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        trust_remote_code=True,
        torch_dtype="auto",
    )
    print(f"Model downloaded: {model.__class__.__name__}")
    print(f"Parameters: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M")

    cache_dir = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
    print(f"\nModel cached at: {cache_dir}")
    print(f"\nRun training with:")
    print(f"  docker run -v {cache_dir}:/app/.cache/huggingface openagora-cpu-trainer:latest")


if __name__ == "__main__":
    main()
