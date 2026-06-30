import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from openagora_verify.pytest_runner import PytestRunner


def test_placeholder():
    """Placeholder test until real tests are added."""
    runner = PytestRunner()
    result = runner.run("sandbox-1")
    assert "pytest" in result
