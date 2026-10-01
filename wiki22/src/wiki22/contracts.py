from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    article_id: str
    section_id: str
    source: str
    revision: str
    text: str


@dataclass(frozen=True)
class SearchHit:
    article_id: str
    title: str
    score: float
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Article:
    article_id: str
    title: str
    domain: str
    source: str
    revision: str
    sections: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderHealth:
    status: str
    provider: str
    offline: bool
    detail: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class KnowledgeProvider(Protocol):

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[SearchHit]:
        ...

    def get_article(
        self,
        article_id: str,
    ) -> Article | None:
        ...

    def get_evidence(
        self,
        evidence_id: str,
    ) -> EvidenceRef | None:
        ...

    def get_relations(
        self,
        entity: str,
    ) -> list[dict[str, Any]]:
        ...

    def get_metadata(
        self,
    ) -> dict[str, Any]:
        ...

    def health(
        self,
    ) -> ProviderHealth:
        ...

    def stats(
        self,
    ) -> dict[str, Any]:
        ...
