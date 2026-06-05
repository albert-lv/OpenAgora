import subprocess
from typing import List, Dict

class PytestRunner:
    """Runs pytest inside a sandbox and parses results into Arena rewards."""

    def __init__(self, command: str = "pytest"):
        self.command = command

    def run(self, sandbox_id: str) -> Dict[str, float]:
        """Execute pytest and return reward dict."""
        raise NotImplementedError()
