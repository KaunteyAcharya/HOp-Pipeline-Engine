"""Search provider interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchHit:
    url: str
    title: str
    description: str = ""


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 10) -> list[SearchHit]: ...
