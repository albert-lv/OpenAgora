"""Problem bank loader for Code Colosseum."""

import json
import os
from pathlib import Path
from typing import Optional


PROBLEMS_DIR = Path(os.environ.get("PROBLEMS_DIR", "../problems")).resolve()


class Problem:
    def __init__(self, root: Path):
        self.root = root
        self.id = root.name
        with open(root / "problem.json") as f:
            self.meta = json.load(f)
        self.public_tests = (root / "public_tests.py").read_text()
        self.hidden_tests = (root / "hidden_tests.py").read_text()
        self.solution = (root / "solution.py").read_text()

    @property
    def title(self) -> str:
        return self.meta["title"]

    @property
    def difficulty(self) -> str:
        return self.meta["difficulty"]

    @property
    def tags(self) -> list[str]:
        return self.meta.get("tags", [])

    @property
    def description(self) -> str:
        return self.meta["description"]

    @property
    def function_signature(self) -> str:
        return self.meta["function_signature"]

    @property
    def language(self) -> str:
        return self.meta.get("language", "python")

    def to_dict(self, include_tests: bool = False) -> dict:
        data = {
            "id": self.id,
            "title": self.title,
            "difficulty": self.difficulty,
            "tags": self.tags,
            "description": self.description,
            "function_signature": self.function_signature,
            "language": self.language,
        }
        if include_tests:
            data["public_tests"] = self.public_tests
            data["hidden_tests"] = self.hidden_tests
            data["solution"] = self.solution
        return data

    def build_task_file(self) -> bytes:
        """Build task.json bytes for the Arena sandbox agent."""
        task = {
            "problem": {
                "id": self.id,
                "title": self.title,
                "description": self.description,
                "function_signature": self.function_signature,
                "language": self.language,
            },
            "hidden_tests": self.hidden_tests,
        }
        return json.dumps(task).encode("utf-8")

    def build_verify_command(self) -> str:
        """Command used by Arena server to verify the solution."""
        return "cd /sandbox && python -m pytest hidden_tests.py -q"


def load_problems() -> dict[str, Problem]:
    problems = {}
    for entry in sorted(PROBLEMS_DIR.iterdir()):
        if entry.is_dir() and (entry / "problem.json").exists():
            problems[entry.name] = Problem(entry)
    return problems


def get_problem(problem_id: str) -> Optional[Problem]:
    return load_problems().get(problem_id)
