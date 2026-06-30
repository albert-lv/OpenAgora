from typing import Dict


class PytestRunner:
    """Runs pytest inside a sandbox and parses results into Arena rewards."""

    def __init__(self, command: str = "pytest"):
        self.command = command

    def run(self, sandbox_id: str) -> Dict[str, float]:
        """Execute pytest and return reward dict.

        For now this is a placeholder. In a real deployment it would
        invoke the sandbox provider (e.g. via Arena gRPC or Docker exec).
        """
        # Placeholder: return neutral reward.
        return {"pytest": 0.0}

    def parse_output(self, stdout: str) -> float:
        """Parse pytest stdout and return a reward in [0, 1]."""
        # Simple heuristic: look for "X passed" and "Y failed".
        passed = 0
        failed = 0
        for line in stdout.splitlines():
            if "passed" in line:
                try:
                    parts = line.split()
                    passed = int(parts[0])
                except (ValueError, IndexError):
                    pass
            if "failed" in line:
                try:
                    parts = line.split()
                    failed = int(parts[0])
                except (ValueError, IndexError):
                    pass
        total = passed + failed
        if total == 0:
            return 0.0
        return passed / total
