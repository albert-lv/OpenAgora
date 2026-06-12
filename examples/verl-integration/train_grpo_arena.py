#!/usr/bin/env python3
"""Wrapper to launch the veRL GRPO trainer with the Arena agent loop registered.

veRL discovers agent loops by importing modules that decorate subclasses of
``AgentLoopBase`` with ``@register(...)``. Simply setting
``default_agent_loop=arena_agent`` in the Hydra config is not enough if the
module that performs the registration has never been imported in the trainer
process.

This wrapper imports ``openagora_verl`` (which triggers the registration of
``ArenaAgentLoop`` as ``"arena_agent"``) and then delegates to veRL's
``main_ppo`` entry point. All command-line arguments and environment variables
are forwarded unchanged.
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

# Importing this package registers ArenaAgentLoop with veRL's AgentLoop registry.
import openagora_verl  # noqa: F401


def main() -> None:
    """Delegate to veRL's main_ppo trainer."""
    # veRL uses Hydra's config search path based on the main module's file
    # location when invoked via ``python -m verl.trainer.main_ppo``. When we
    # import ``main`` and call it directly, Hydra still resolves configs
    # relative to the verl package, so behavior is preserved.
    from verl.trainer.main_ppo import main as verl_main_ppo

    verl_main_ppo()


if __name__ == "__main__":
    main()
