import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from problems import Problem, load_problems


def test_load_problems():
    os.environ["PROBLEMS_DIR"] = str(Path(__file__).parent.parent / "problems")
    problems = load_problems()
    assert "roman-to-integer-strict" in problems
    assert "merge-sorted-logs" in problems


def test_problem_metadata():
    os.environ["PROBLEMS_DIR"] = str(Path(__file__).parent.parent / "problems")
    problem = load_problems()["roman-to-integer-strict"]
    assert problem.title == "Strict Roman to Integer"
    assert problem.language == "python"
    assert "def roman_to_int" in problem.function_signature


def test_build_verify_command_python():
    os.environ["PROBLEMS_DIR"] = str(Path(__file__).parent.parent / "problems")
    problem = load_problems()["merge-sorted-logs"]
    assert (
        problem.build_verify_command()
        == "cd /sandbox && python -m pytest hidden_tests.py -q"
    )


def test_build_verify_command_javascript():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "js-stub"
        root.mkdir()
        (root / "problem.json").write_text(
            '{"id": "js-stub", "title": "JS Stub", "language": "javascript", "framework": "node"}'
        )
        (root / "public_tests.js").write_text("")
        (root / "hidden_tests.js").write_text("")
        (root / "solution.js").write_text("")
        problem = Problem(root)
        assert problem.build_verify_command() == "cd /sandbox && node hidden_tests.js"
