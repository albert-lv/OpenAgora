import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from arena_verl.rollout_provider import ArenaRolloutProvider


def test_placeholder():
    """Placeholder test until real tests are added."""
    assert ArenaRolloutProvider is not None
