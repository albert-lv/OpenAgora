#!/usr/bin/env python3
"""Arena + veRL + SWE-agent + Qwen3.5-0.8B Demo.

支持两种模式:
 --mode mock : 纯 mock 运行，不依赖任何外部服务（默认）
 --mode real : 连接真实 Arena Server + vLLM + SWE-agent Docker

Mock 模式用于验证脚本逻辑和接口正确性。
Real 模式需要预先启动: Arena Server, vLLM (Qwen3.5-0.8B), Docker
"""

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np

# ------------------------------------------------------------------
# Mock veRL DataProto / TensorDict (interface-compatible)
# ------------------------------------------------------------------
class MockTensorDict:
    def __init__(self, data, batch_size=None):
        self._data = data
        self.batch_size = batch_size
    def __getitem__(self, key):
        return self._data[key]
    def keys(self):
        return self._data.keys()

class MockDataProto:
    def __init__(self, batch=None, non_tensor_batch=None, meta_info=None):
        self.batch = batch or MockTensorDict({})
        self.non_tensor_batch = non_tensor_batch or {}
        self.meta_info = meta_info or {}

# ------------------------------------------------------------------
# Mock Arena Client + SWE-agent Rollout Provider
# ------------------------------------------------------------------
VOCAB_SIZE = 50
PAD_ID = 0

class MockArenaRolloutProvider:
    """Mock provider simulating SWE-agent tool calling in Arena sandbox."""
    
    TOOLS = ["open", "goto", "scroll_down", "scroll_up", "search_dir", 
             "search_file", "find_file", "edit", "create", "submit"]
    
    def __init__(self, max_turns=15, success_rate=0.3):
        self.max_turns = max_turns
        self.success_rate = success_rate
        self.history = []
    
    def generate_sequences(self, prompts: MockDataProto) -> MockDataProto:
        """Simulate a SWE-agent rollout: view -> search -> edit -> submit."""
        bsz = prompts.batch["input_ids"].shape[0] if "input_ids" in prompts.batch._data else 1
        prompt_length = 10
        response_length = 20
        
        # Simulate tool call sequence
        response_ids = []
        response_mask = []
        token_rewards = []
        
        for i in range(bsz):
            # Simulate a trajectory: mix of tool calls and text
            traj = self._simulate_trajectory()
            self.history.append(traj)
            
            # Encode trajectory as token IDs (simplified)
            ids = [hash(t["action"]) % VOCAB_SIZE for t in traj]
            ids = ids[:response_length] + [PAD_ID] * (response_length - len(ids))
            
            mask = [1] * min(len(traj), response_length) + [0] * (response_length - min(len(traj), response_length))
            
            # Reward: success gets 1.0, distributed over tokens
            reward = 1.0 if traj[-1]["action"] == "submit" and random.random() < self.success_rate else 0.0
            n_real = sum(1 for m in mask if m == 1)
            rewards = [reward / n_real if n_real > 0 else 0.0] * response_length
            
            response_ids.append(ids)
            response_mask.append(mask)
            token_rewards.append(rewards)
        
        response_ids_t = np.array(response_ids, dtype=np.int64)
        response_mask_t = np.array(response_mask, dtype=np.int64)
        token_rewards_t = np.array(token_rewards, dtype=np.float32)
        
        # Build full sequence
        prompt_ids = prompts.batch["input_ids"] if "input_ids" in prompts.batch._data else np.zeros((bsz, prompt_length), dtype=np.int64)
        input_ids = np.concatenate([prompt_ids, response_ids_t], axis=1)
        attention_mask = np.concatenate([
            np.ones((bsz, prompt_length), dtype=np.int64),
            response_mask_t
        ], axis=1)
        position_ids = (np.cumsum(attention_mask, axis=1) - 1) * attention_mask
        
        batch = MockTensorDict({
            "prompts": prompt_ids,
            "responses": response_ids_t,
            "response_mask": response_mask_t,
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "position_ids": position_ids,
            "token_level_rewards": token_rewards_t,
        }, batch_size=bsz)
        
        return MockDataProto(
            batch=batch,
            non_tensor_batch=prompts.non_tensor_batch,
            meta_info={"trajectory": self.history[-bsz:]}
        )
    
    def _simulate_trajectory(self):
        """Simulate a SWE-agent tool call sequence."""
        trajectory = []
        # Typical successful pattern: open -> search -> edit -> submit
        actions = ["open", "search_file", "edit", "submit"]
        for action in actions:
            trajectory.append({
                "action": action,
                "arguments": {"path": "/testbed/src/main.py"} if action == "open" else {},
                "observation": f"Executed {action}",
            })
        return trajectory


# ------------------------------------------------------------------
# Simple RL Trainer (Direct Policy Gradient)
# ------------------------------------------------------------------
class SimpleRLTrainer:
    def __init__(self, lr=1e-3, entropy_coef=0.02):
        self.lr = lr
        self.entropy_coef = entropy_coef
        self.history = []
    
    def update(self, rollout_output: MockDataProto):
        """Simple policy gradient update (mock, no actual model)."""
        rewards = rollout_output.batch["token_level_rewards"]
        avg_reward = rewards.sum().item() / (rewards != 0).sum().item() if (rewards != 0).sum() > 0 else 0.0
        
        self.history.append({
            "reward": avg_reward,
            "num_tools": rollout_output.meta_info.get("trajectory", [[]])[-1].__len__() if rollout_output.meta_info.get("trajectory") else 0,
        })
        
        return {
            "reward": avg_reward,
            "policy_loss": random.uniform(-0.1, 0.1),
        }


# ------------------------------------------------------------------
# Main Demo
# ------------------------------------------------------------------
def run_mock_demo(n_steps=100):
    """Run mock demo without any external dependencies."""
    print("=" * 60)
    print("Arena + veRL + SWE-agent + Qwen3.5-0.8B MOCK Demo")
    print("=" * 60)
    print("\nThis demo simulates the full pipeline without external services:")
    print(" - Mock ArenaRolloutProvider (SWE-agent tool calls)")
    print(" - Mock DataProto / TensorDict (veRL interface)")
    print(" - Simple RL Trainer (Direct Policy Gradient)")
    print("\n")
    
    provider = MockArenaRolloutProvider(max_turns=15, success_rate=0.3)
    trainer = SimpleRLTrainer(lr=1e-3, entropy_coef=0.02)
    
    print(f"Running {n_steps} mock training steps...")
    print("-" * 60)
    
    for step in range(n_steps):
        # Build fake prompts
        bsz = 4
        prompt_length = 10
        prompt_ids = np.random.randint(0, VOCAB_SIZE, size=(bsz, prompt_length))
        
        batch = MockTensorDict({
            "input_ids": prompt_ids,
            "attention_mask": np.ones((bsz, prompt_length), dtype=np.int64),
            "position_ids": np.arange(prompt_length).reshape(1, -1).repeat(bsz, axis=0),
        }, batch_size=bsz)
        
        prompts = MockDataProto(
            batch=batch,
            non_tensor_batch={"raw_prompt": [f"Fix bug #{i}" for i in range(bsz)]}
        )
        
        # Rollout (simulates SWE-agent in Arena sandbox)
        rollout_output = provider.generate_sequences(prompts)
        
        # RL update
        metrics = trainer.update(rollout_output)
        
        if step % 20 == 0:
            print(f"Step {step:3d}: reward={metrics['reward']:.3f}")
    
    print("-" * 60)
    print(f"Final reward: {metrics['reward']:.3f}")
    print("\nMock demo completed successfully!")
    print("\nTo run with REAL services, start:")
    print(" 1. Arena Server: ./bin/openagora-server --sandbox=docker")
    print(" 2. vLLM: vllm serve Qwen/Qwen3.5-0.8B --enable-auto-tool-choice")
    print(" 3. Then run: python demo.py --mode real")
    return 0


def run_real_demo(arena_endpoint: str, repo_path: str, issue: str, llm_backend: str = "http://host.docker.internal:11434/v1"):
    """Run with real Arena Server + LLM backend + SWE-agent Docker."""
    print("=" * 60)
    print("Arena + veRL + SWE-agent + Qwen3.5-0.8B REAL Demo")
    print("=" * 60)
    
    try:
        from openagora_sdk import ArenaClient
    except ImportError:
        print("ERROR: openagora_sdk not installed. Install with: pip install -e python/openagora-sdk")
        return 1
    
    client = ArenaClient(arena_endpoint)
    
    # Check Arena server health (gRPC - just check port is open)
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        host, port = arena_endpoint.split(':')
        result = sock.connect_ex((host, int(port)))
        sock.close()
        if result != 0:
            print(f"ERROR: Cannot connect to Arena Server at {arena_endpoint}: port not open")
            return 1
        print(f"Arena Server OK: {arena_endpoint}")
    except Exception as e:
        print(f"ERROR: Cannot connect to Arena Server at {arena_endpoint}: {e}")
        return 1
    
    # Check LLM backend health
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{llm_backend}/models",
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
        print(f"LLM Backend OK: {llm_backend}")
    except Exception as e:
        print(f"WARNING: Cannot connect to LLM backend at {llm_backend}: {e}")
        print("Continuing anyway...")
    
    # Create rollout using the ArenaClient API
    print(f"Creating rollout: {issue}")
    rollout = client.create_rollout(
        task_id=f"swe-demo-{issue[:20]}",
        image="openagora-swe-agent:latest",
        llm_backend=llm_backend,
        sampling={"temperature": 0.3, "top_p": 0.9, "max_tokens": 1024},
        verify={"command": "cd /testbed && pytest tests/ -v"},
        memory="4g",
        cpus=2.0,
    )
    rollout_id = rollout["rollout_id"]
    print(f"Rollout ID: {rollout_id}")
    
    print("Waiting for completion...")
    info = client.wait(rollout_id)
    
    print(f"\nStatus: {info['status']}")
    print(f"Reward: {info['reward']}")
    
    trajectory = client.get_trajectory(rollout_id)
    print(f"\nTool call sequence ({len(trajectory)} steps):")
    for i, step in enumerate(trajectory):
        resp = step.get("response", {}) or {}
        content = resp.get("content", "")
        print(f"  Step {i}: {content[:80]}...")
    
    return 0 if info["status"] == "success" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["mock", "real"], default="mock",
                        help="mock: no external deps, real: needs Arena+LLM+Docker")
    parser.add_argument("--arena", default="localhost:9090")
    parser.add_argument("--repo", default="/tmp/test-repo")
    parser.add_argument("--issue", default="Fix simple bug")
    parser.add_argument("--llm-backend", default="http://host.docker.internal:11434/v1",
                        help="LLM backend URL (default: Ollama endpoint)")
    parser.add_argument("--steps", type=int, default=100)
    args = parser.parse_args()
    
    if args.mode == "mock":
        return run_mock_demo(args.steps)
    else:
        return run_real_demo(args.arena, args.repo, args.issue, args.llm_backend)


if __name__ == "__main__":
    sys.exit(main())
