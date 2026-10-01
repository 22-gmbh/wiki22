from __future__ import annotations

import json
import re
from pathlib import Path

from wiki22.contracts import (
    Article,
    EvidenceRef,
    ProviderHealth,
    SearchHit,
)


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if (
            len(token) > 1
            or token.isdigit()
        )
    }


class SyntheticProvider:
    """Temporary local provider for Wiki22 V0.1 architecture validation."""

    provider_name = "SyntheticProvider"

    def __init__(
        self,
        pack_path: str | Path,
        *, data: dict | None = None,
    ) -> None:

        self.pack_path = Path(pack_path)

        if not self.pack_path.is_file():
            raise FileNotFoundError(
                self.pack_path
            )

        self._data = data if data is not None else json.loads(
            self.pack_path.read_text(
                encoding="utf-8-sig"
            )
        )

        self._articles = {
            row["id"]:
                row
            for row in self._data.get(
                "articles",
                []
            )
        }

        self._evidence: dict[str, dict] = {}

        for article in self._articles.values():
            for section in article.get(
                "sections",
                []
            ):
                for evidence in section.get(
                    "evidence",
                    []
                ):
                    self._evidence[
                        evidence["id"]
                    ] = {
                        **evidence,
                        "article_id":
                            article["id"],
                        "section_id":
                            section["id"],
                        "source":
                            article["source"],
                        "revision":
                            article["revision"],
                    }

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[SearchHit]:

        query_tokens = _tokens(query)
        scored = []

        for article in self._articles.values():

            text_parts = [
                article.get(
                    "title",
                    "",
                )
            ]

            evidence_ids = []

            for section in article.get(
                "sections",
                []
            ):
                text_parts.append(
                    section.get(
                        "heading",
                        "",
                    )
                )

                for evidence in section.get(
                    "evidence",
                    []
                ):
                    text_parts.append(
                        evidence.get(
                            "text",
                            "",
                        )
                    )

                    evidence_ids.append(
                        evidence["id"]
                    )

            article_tokens = _tokens(
                " ".join(text_parts)
            )

            if not query_tokens:
                score = 0.0
            else:
                score = (
                    len(
                        query_tokens
                        & article_tokens
                    )
                    / len(
                        query_tokens
                    )
                )

            if score > 0:
                scored.append(
                    SearchHit(
                        article_id=
                            article["id"],

                        title=
                            article["title"],

                        score=
                            float(score),

                        evidence_ids=
                            tuple(evidence_ids),
                    )
                )

        scored.sort(
            key=lambda hit: (
                -hit.score,
                hit.article_id,
            )
        )

        return scored[:limit]

    def get_article(
        self,
        article_id: str,
    ) -> Article | None:

        row = self._articles.get(
            article_id
        )

        if row is None:
            return None

        return Article(
            article_id=
                row["id"],

            title=
                row["title"],

            domain=
                row["domain"],

            source=
                row["source"],

            revision=
                row["revision"],

            sections=
                tuple(
                    row.get(
                        "sections",
                        []
                    )
                ),

            metadata=
                dict(
                    row.get(
                        "metadata",
                        {}
                    )
                ),
        )

    def get_evidence(
        self,
        evidence_id: str,
    ) -> EvidenceRef | None:

        row = self._evidence.get(
            evidence_id
        )

        if row is None:
            return None

        return EvidenceRef(
            evidence_id=
                row["id"],

            article_id=
                row["article_id"],

            section_id=
                row["section_id"],

            source=
                row["source"],

            revision=
                row["revision"],

            text=
                row["text"],
        )

    def get_relations(
        self,
        entity: str,
    ) -> list[dict]:

        wanted = entity.strip().lower()
        rows = []

        for article in self._articles.values():
            for relation in article.get(
                "relations",
                []
            ):
                if (
                    str(
                        relation.get(
                            "subject",
                            "",
                        )
                    ).lower()
                    == wanted
                    or str(
                        relation.get(
                            "object",
                            "",
                        )
                    ).lower()
                    == wanted
                ):
                    rows.append(
                        dict(relation)
                    )

        return rows

    def get_metadata(
        self,
    ) -> dict:

        return dict(
            self._data.get(
                "metadata",
                {}
            )
        )

    def health(
        self,
    ) -> ProviderHealth:

        return ProviderHealth(
            status="READY",
            provider=self.provider_name,
            offline=True,
            detail={
                "articles":
                    len(
                        self._articles
                    ),

                "evidence_units":
                    len(
                        self._evidence
                    ),
            },
        )

    def stats(
        self,
    ) -> dict:

        return {
            "provider":
                self.provider_name,

            "articles":
                len(
                    self._articles
                ),

            "evidence_units":
                len(
                    self._evidence
                ),

            "pack_path":
                str(
                    self.pack_path
                ),

            "synthetic":
                True,
        }
