"""Simple Elo rating system for Code Colosseum agents."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_K = 32
INITIAL_RATING = 1500
STATE_PATH = Path(os.environ.get("ELO_STATE_PATH", "/app/data/elo.json"))


@dataclass
class Player:
    id: str
    name: str
    rating: float = INITIAL_RATING
    wins: int = 0
    losses: int = 0
    draws: int = 0
    matches: int = 0


class EloService:
    def __init__(self, state_path: Optional[Path] = None):
        self.state_path = state_path or STATE_PATH
        self._players: dict[str, Player] = {}
        self._load()

    def _load(self):
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                for pid, p in data.items():
                    self._players[pid] = Player(**p)
            except Exception:
                self._players = {}

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {p.id: p.__dict__ for p in self._players.values()},
                indent=2,
            )
        )

    def get_or_create(self, player_id: str, name: Optional[str] = None) -> Player:
        if player_id not in self._players:
            self._players[player_id] = Player(id=player_id, name=name or player_id)
        return self._players[player_id]

    def record_match(
        self,
        player_a_id: str,
        player_b_id: str,
        score_a: float,  # 1 win, 0.5 draw, 0 loss
        name_a: Optional[str] = None,
        name_b: Optional[str] = None,
    ):
        """Record a match and update Elo ratings."""
        a = self.get_or_create(player_a_id, name_a)
        b = self.get_or_create(player_b_id, name_b)

        expected_a = 1 / (1 + 10 ** ((b.rating - a.rating) / 400))
        expected_b = 1 / (1 + 10 ** ((a.rating - b.rating) / 400))

        a.rating += DEFAULT_K * (score_a - expected_a)
        b.rating += DEFAULT_K * ((1 - score_a) - expected_b)

        a.matches += 1
        b.matches += 1
        if score_a == 1:
            a.wins += 1
            b.losses += 1
        elif score_a == 0:
            a.losses += 1
            b.wins += 1
        else:
            a.draws += 1
            b.draws += 1

        self._save()

    def leaderboard(self) -> list[dict]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "rating": round(p.rating, 1),
                "wins": p.wins,
                "losses": p.losses,
                "draws": p.draws,
                "matches": p.matches,
            }
            for p in sorted(
                self._players.values(), key=lambda x: x.rating, reverse=True
            )
        ]
