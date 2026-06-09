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
import torch

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
        
        response_ids_t = torch.tensor(response_ids, dtype=torch.long)
        response_mask_t = torch.tensor(response_mask, dtype=torch.long)
        token_rewards_t = torch.tensor(token_rewards, dtype=torch.float32)
        
        # Build full sequence
        prompt_ids = prompts.batch["input_ids"] if "input_ids" in prompts.batch._data else torch.zeros(bsz, prompt_length, dtype=torch.long)
        input_ids = torch.cat([prompt_ids, response_ids_t], dim=1)
        attention_mask = torch.cat([
            torch.ones(bsz, prompt_length, dtype=torch.long),
            response_mask_t
        ], dim=1)
        position_ids = (attention_mask.cumsum(dim=1) - 1) * attention_mask
        
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
        prompt_ids = torch.randint(0, VOCAB_SIZE, (bsz, prompt_length))
        
        batch = MockTensorDict({
            "input_ids": prompt_ids,
            "attention_mask": torch.ones(bsz, prompt_length, dtype=torch.long),
            "position_ids": torch.arange(prompt_length).unsqueeze(0).expand(bsz, -1),
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
    print(" 1. Arena Server: ./bin/arena-server --sandbox=docker")
    print(" 2. vLLM: vllm serve Qwen/Qwen3.5-0.8B --enable-auto-tool-choice")
    print(" 3. Then run: python demo.py --mode real")
    return 0


def run_real_demo(arena_endpoint: str, repo_path: str, issue: str):
    """Run with real Arena Server + vLLM + SWE-agent Docker."""
    print("=" * 60)
    print("Arena + veRL + SWE-agent + Qwen3.5-0.8B REAL Demo")
    print("=" * 60)
    
    try:
        from arena_sdk import ArenaClient
    except ImportError:
        print("ERROR: arena_sdk not installed. Install with: pip install -e python/arena-sdk")
        return 1
    
    client = ArenaClient(arena_endpoint)
    
    # Check Arena server health (gRPC)
    try:
        import grpc
        channel = grpc.insecure_channel(arena_endpoint)
        grpc.channel_ready_future(channel).result(timeout=5)
        print(f"Arena Server OK: {arena_endpoint}")
    except Exception as e:
        print(f"ERROR: Cannot connect to Arena Server at {arena_endpoint}: {e}")
        return 1
    
    # Load tools
    with open("tools.json") as f:
        tools = json.load(f)
    
    # Create task
    task_config = {
        "task_id": f"swe-demo-{issue[:20]}",
        "sandbox": {
            "image": "arena-swe-agent:latest",
            "resources": {"memory": "4g", "cpu": "2"},
            "mounts": [{"source": repo_path, "target": "/testbed", "read_only": False}]
        },
        "llm_backend": "http://host.docker.internal:8000/v1",
        "tools": tools,
        "max_turns": 15,
        "sampling": {"temperature": 0.3, "top_p": 0.9, "max_tokens": 1024},
        "verify": {
            "command": "cd /testbed && pytest tests/ -v",
            "timeout": 120
        }
    }
    
    print(f"Creating rollout: {issue}")
    rollout = client.create_rollout(
        task_id=f"swe-demo-{issue[:20]}",
        image="arena-swe-agent:latest",
        llm_backend="http://host.docker.internal:11434/v1",
        sampling={"temperature": 0.3, "top_p": 0.9, "max_tokens": 1024},
        verify={"command": "cd /testbed && pytest tests/ -v", "timeout": 120},
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
        resp = step.get("response", {})
        tool_calls = resp.get("tool_calls", [])
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                print(f"  Step {i}: {fn.get('name')}({str(fn.get('arguments', {}))[:80]})")
        else:
            print(f"  Step {i}: [text] {resp.get('content', '')[:60]}...")
    
    return 0 if info["status"] == "success" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["mock", "real"], default="mock",
                        help="mock: no external deps, real: needs Arena+vLLM+Docker")
    parser.add_argument("--arena", default="localhost:9090")
    parser.add_argument("--repo", default="/tmp/test-repo")
    parser.add_argument("--issue", default="Fix simple bug")
    parser.add_argument("--steps", type=int, default=100)
    args = parser.parse_args()
    
    if args.mode == "mock":
        return run_mock_demo(args.steps)
    else:
        return run_real_demo(args.arena, args.repo, args.issue)


if __name__ == "__main__":
    sys.exit(main())
