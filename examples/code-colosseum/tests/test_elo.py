import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from elo import EloService


def test_elo_initial_rating():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        service = EloService(state_path=Path(path))
        board = service.leaderboard()
        assert board == []
    finally:
        os.unlink(path)


def test_elo_record_match():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        service = EloService(state_path=Path(path))
        service.record_match("a", "b", 1.0, name_a="Agent A", name_b="Agent B")
        board = service.leaderboard()
        assert len(board) == 2
        assert board[0]["id"] == "a"
        assert board[0]["wins"] == 1
        assert board[1]["losses"] == 1
    finally:
        os.unlink(path)


def test_elo_draw():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        service = EloService(state_path=Path(path))
        service.record_match("a", "b", 0.5)
        a = next(e for e in service.leaderboard() if e["id"] == "a")
        b = next(e for e in service.leaderboard() if e["id"] == "b")
        assert a["draws"] == 1
        assert b["draws"] == 1
        assert a["rating"] == b["rating"]
    finally:
        os.unlink(path)
