class Rollout:
    """Represents a single rollout execution."""

    def __init__(self, rollout_id: str, task_id: str, status: str):
        self.id = rollout_id
        self.task_id = task_id
        self.status = status

    def __repr__(self):
        return f"Rollout(id={self.id}, task={self.task_id}, status={self.status})"
