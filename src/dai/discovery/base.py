"""Search provider interface and shared types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str = ""
    snippet: str = ""


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int, lang: str = "en") -> list[SearchResult]:
        ...
