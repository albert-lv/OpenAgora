import pyarrow as pa
from typing import List, Dict, Any

class Trajectory:
    """Structured trajectory data for RL training."""

    def __init__(self, steps: List[Dict[str, Any]]):
        self.steps = steps

    def to_arrow(self) -> pa.Table:
        """Convert to PyArrow Table for efficient training data loading."""
        raise NotImplementedError()

    def to_parquet(self, path: str) -> None:
        """Write trajectory as Parquet file."""
        raise NotImplementedError()
