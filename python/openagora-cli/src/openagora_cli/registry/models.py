"""Dataset / benchmark registry models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DatasetSpec(BaseModel):
    name: str
    version: str
    description: str
    task_ids: list[str] = Field(default_factory=list)
    task_dir: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.name}@{self.version}"
