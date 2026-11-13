"""Immutable data model shared by every pipeline stage."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RawPage:
    url: str
    final_url: str = ""
    status: int = 0
    content_type: str = ""
    body: bytes = b""
    fetched_at: float = 0.0
    content_hash: str = ""
    from_cache: bool = False
    error: str | None = None
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300


@dataclass(frozen=True, slots=True)
class Document:
    url: str
    domain: str
    title: str = ""
    author: str = ""
    publisher: str = ""
    published: str | None = None
    language: str = "en"
    text: str = ""
    word_count: int = 0
    external_links: int = 0
    canonical_url: str = ""
    fetched_at: float = 0.0


@dataclass(frozen=True, slots=True)
class Claim:
    text: str
    normalized: str
    lang: str
    claim_type: str
    subject: str = ""
    predicate: str = ""
    value: str = ""
    numbers: tuple = ()
    num_ctx: tuple = ()          # parallel to numbers: frozenset of context markers
    dates: tuple = ()
    negated: bool = False
    entities: frozenset = frozenset()
    stems: frozenset = frozenset()
    doc_url: str = ""
    start: int = 0
    end: int = 0
    relevance: float = 0.0


@dataclass(frozen=True, slots=True)
class TrustReport:
    url: str
    score: float                  # 0..1
    tier: str
    subscores: dict = field(default_factory=dict)
    signals: tuple = ()


@dataclass(frozen=True, slots=True)
class Evidence:
    url: str
    domain: str
    title: str
    quote: str
    trust: float
    published: str | None = None
    claim_type: str = "fact"


@dataclass(slots=True)
class Relation:
    a: int = 0
    b: int = 0
    kind: str = "unrelated"      # agreement|contradiction|update|nuance|unrelated
    signals: list = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Statement:
    text: str
    claim_type: str
    confidence: float             # 0..1 evidence balance, NOT a probability
    relevance: float
    status: str                   # corroborated|single-source|disputed|mixed
    cluster_size: int
    independent_sources: int
    supporting: tuple = ()
    dissent: tuple = ()
    notes: tuple = ()


@dataclass(slots=True)
class ResearchResult:
    question: str
    language: str = "en"
    output_language: str = "en"
    statements: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    trace: dict = field(default_factory=dict)
    run_id: int | None = None

    def to_dict(self) -> dict:
        from ..render.json_out import result_to_dict
        return result_to_dict(self)

    def json(self) -> str:
        from ..render.json_out import render_json
        return render_json(self)

    def text(self) -> str:
        from ..render.text_out import render_text
        return render_text(self.to_dict())
