from __future__ import annotations

from dataclasses import asdict

from wiki22.contracts import (
    KnowledgeProvider,
)


class KnowledgeViewer:

    def __init__(
        self,
        provider: KnowledgeProvider,
    ) -> None:

        self.provider = provider

    def article(
        self,
        article_id: str,
    ) -> dict | None:

        article = self.provider.get_article(
            article_id
        )

        if article is None:
            return None

        return asdict(article)

    def evidence(
        self,
        evidence_id: str,
    ) -> dict | None:

        evidence = self.provider.get_evidence(
            evidence_id
        )

        if evidence is None:
            return None

        return asdict(evidence)
