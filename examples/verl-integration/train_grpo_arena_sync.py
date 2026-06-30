#!/usr/bin/env python3
"""Wrapper to launch veRL's TransferQueue-based sync PPO trainer with Arena.

This entry point explicitly installs OpenAgora's TransferQueue adapter (no
monkey patching) and then delegates to ``verl.trainer.main_ppo_sync``. The
adapter ensures that data read from TransferQueue conforms to veRL's
nested/padded tensor contract.

Usage is identical to ``train_grpo_arena.py`` except that it targets the sync
PPO trainer with TransferQueue::

    python3 examples/verl-integration/train_grpo_arena_sync.py \
        algorithm.adv_estimator=grpo \
        actor_rollout_ref.rollout.agent.default_agent_loop=arena_agent \
        ...
"""

from __future__ import annotations

import os
import sys


def _add_openagora_verl_to_path() -> None:
    """Insert the openagora-verl source tree into sys.path if it exists locally."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    openagora_verl_src = os.path.normpath(
        os.path.join(script_dir, "../../python/openagora-verl/src")
    )
    if os.path.isdir(openagora_verl_src) and openagora_verl_src not in sys.path:
        sys.path.insert(0, openagora_verl_src)


_add_openagora_verl_to_path()

# Importing this package registers ArenaAgentLoop with veRL and installs the
# TransferQueue adapter explicitly (no runtime monkey patching).
import openagora_verl  # noqa: E402,F401

openagora_verl.install_transfer_queue_backend()


def main() -> None:
    """Delegate to veRL's main_ppo_sync trainer."""
    from verl.trainer.main_ppo_sync import main as verl_main_ppo_sync

    verl_main_ppo_sync()


if __name__ == "__main__":
    main()
