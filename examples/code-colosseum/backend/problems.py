"""Problem bank loader for Code Colosseum."""

import json
import os
from pathlib import Path
from typing import Optional


def _problems_dir() -> Path:
    return Path(os.environ.get("PROBLEMS_DIR", "../problems")).resolve()


_LANGUAGE_EXTENSIONS = {
    "python": "py",
    "javascript": "js",
    "go": "go",
}


class Problem:
    def __init__(self, root: Path):
        self.root = root
        self.id = root.name
        with open(root / "problem.json") as f:
            self.meta = json.load(f)
        ext = _LANGUAGE_EXTENSIONS.get(self.meta.get("language", "python"), "py")
        self.public_tests = (root / f"public_tests.{ext}").read_text()
        self.hidden_tests = (root / f"hidden_tests.{ext}").read_text()
        self.solution = (root / f"solution.{ext}").read_text()

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
            "public_tests": self.public_tests,
            "hidden_tests": self.hidden_tests,
        }
        return json.dumps(task).encode("utf-8")

    def build_verify_command(self) -> str:
        """Command used by Arena server to verify the solution."""
        language = self.meta.get("language", "python")
        framework = self.meta.get("framework", "pytest")

        if language == "python":
            if framework == "pytest":
                return "cd /sandbox && python -m pytest hidden_tests.py -q"
            return f"cd /sandbox && python {framework} hidden_tests.py"

        if language == "javascript":
            runner = framework or "node"
            return f"cd /sandbox && {runner} hidden_tests.js"

        if language == "go":
            return "cd /sandbox && go test ./..."

        return "cd /sandbox && echo 'unsupported language' && exit 1"


def load_problems() -> dict[str, Problem]:
    problems = {}
    for entry in sorted(_problems_dir().iterdir()):
        if entry.is_dir() and (entry / "problem.json").exists():
            problems[entry.name] = Problem(entry)
    return problems


def get_problem(problem_id: str) -> Optional[Problem]:
    return load_problems().get(problem_id)
