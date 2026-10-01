from __future__ import annotations

from typing import Any


class MultiLibraryProvider:
    """
    Logical knowledge view over multiple physically separate libraries.

    Libraries remain independent on disk. Search is federated at query
    time and the highest-ranked hits are returned as one logical view.
    """

    provider_name = "MultiLibraryProvider"

    def __init__(
        self,
        providers: dict[str, Any],
    ) -> None:

        if not providers:
            raise ValueError(
                "MultiLibraryProvider requires at least one library"
            )

        self.providers = dict(
            providers
        )

    @staticmethod
    def _score(
        hit,
    ) -> float:

        value = getattr(
            hit,
            "score",
            None,
        )

        if value is None and isinstance(
            hit,
            dict,
        ):
            value = hit.get(
                "score",
                0,
            )

        try:
            return float(value)
        except (
            TypeError,
            ValueError,
        ):
            return 0.0

    @staticmethod
    def _article_id(
        hit,
    ) -> str | None:

        value = getattr(
            hit,
            "article_id",
            None,
        )

        if value is None and isinstance(
            hit,
            dict,
        ):
            value = hit.get(
                "article_id"
            )

        return (
            str(value)
            if value is not None
            else None
        )

    def search(self, query: str, *, limit: int = 5):
        from dataclasses import replace
        hits = []
        for library_id, provider in self.providers.items():
            for hit in provider.search(query, limit=limit):
                hits.append(replace(hit,
                    article_id=library_id + "::" + hit.article_id,
                    evidence_ids=tuple(library_id + "::" + eid for eid in hit.evidence_ids)))
        self.last_retrieval_trace = {
            "provider": self.stats(),
            "libraries": {lid: p.last_retrieval_trace for lid,p in self.providers.items()},
        }
        return sorted(hits, key=lambda h: (-h.score, h.article_id))[:max(0, limit)]

    def raw_candidates(self, query, *, limit=80):
        rows = []
        for library_id, provider in self.providers.items():
            if not hasattr(provider, 'raw_candidates'):
                continue
            for row in provider.raw_candidates(query, limit=limit):
                rows.append(dict(row, evidence_id=library_id+'::'+row['evidence_id'],
                                 article_id=library_id+'::'+row['article_id']))
        return sorted(rows, key=lambda row: (-row['score'], row['evidence_id']))[:limit]

    def close(self):
        for provider in self.providers.values():
            closer = getattr(provider, 'close', None)
            if closer:
                closer()

    def _resolve(self, identifier):
        library_id, sep, local_id = identifier.partition("::")
        if sep and library_id in self.providers:
            return self.providers[library_id], local_id
        return None, None

    def get_article(self, article_id):
        from dataclasses import replace
        provider, local_id = self._resolve(article_id)
        article = provider.get_article(local_id) if provider else None
        return replace(article, article_id=article_id) if article else None

    @property
    def supports_geographic_fields(self):
        return any(getattr(p,'supports_geographic_fields',False) for p in self.providers.values())

    def geographic_record(self, article_id):
        provider,local_id=self._resolve(article_id)
        getter=getattr(provider,'geographic_record',None) if provider else None
        result=getter(local_id) if getter else None
        if result is None:return None
        prefix=article_id.partition('::')[0]+'::'
        fields={k:dict(v,spans=[dict(s,evidence_id=prefix+s['evidence_id'],article_id=article_id) for s in v['spans']])
                for k,v in result['fields'].items()}
        return dict(result,article_id=article_id,fields=fields)

    def reading_record(self, article_id):
        provider, local_id=self._resolve(article_id)
        getter=getattr(provider,'reading_record',None) if provider else None
        result=getter(local_id) if getter else None
        if result is None:return None
        prefix=article_id.partition('::')[0]+'::'
        paragraphs=[dict(p,article_id=article_id,evidence_id=prefix+p['evidence_id'],
            spans=[dict(span,evidence_id=prefix+span['evidence_id']) for span in p['spans']])
            for p in result['paragraphs']]
        return dict(result,article_id=article_id,paragraphs=paragraphs)

    def get_evidence(self, evidence_id):
        from dataclasses import replace
        provider, local_id = self._resolve(evidence_id)
        evidence = provider.get_evidence(local_id) if provider else None
        if evidence is None:
            return None
        library_id = evidence_id.partition("::")[0]
        return replace(evidence, evidence_id=evidence_id,
                       article_id=library_id + "::" + evidence.article_id)

    def biographic_record(self, evidence_id):
        provider, local_id = self._resolve(evidence_id)
        getter=getattr(provider,'biographic_record',None) if provider else None
        record=getter(local_id) if getter else None
        if record is None:return None
        library_id=evidence_id.partition('::')[0]
        return dict(record,evidence_id=evidence_id,article_id=library_id+'::'+record['article_id'])

    def get_passage(self, evidence_id):
        provider, local_id = self._resolve(evidence_id)
        return provider.get_passage(local_id) if provider else None

    def get_relations(
        self,
        entity: str,
    ) -> list[dict[str, Any]]:

        rows = []

        for library_id, provider in (
            self.providers.items()
        ):

            for relation in (
                provider.get_relations(
                    entity
                )
            ):

                if isinstance(
                    relation,
                    dict,
                ):
                    item = dict(
                        relation
                    )

                    item.setdefault(
                        "library_id",
                        library_id,
                    )

                    rows.append(
                        item
                    )

        return rows

    def get_metadata(
        self,
    ) -> dict[str, Any]:

        return {
            "provider":
                self.provider_name,

            "scope":
                "MULTI_LIBRARY",

            "library_ids":
                list(
                    self.providers.keys()
                ),

            "library_count":
                len(
                    self.providers
                ),

            "synthetic":
                False,
        }

    def health(self):
        from dataclasses import asdict
        from wiki22.contracts import ProviderHealth
        children = {lid: asdict(p.health()) for lid, p in self.providers.items()}
        ready = all(x["status"] == "READY" for x in children.values())
        return ProviderHealth("READY" if ready else "DEGRADED", self.provider_name,
                              True, {"libraries": children})

    def stats(
        self,
    ) -> dict[str, Any]:

        articles = 0
        evidence_units = 0

        children = {}

        for library_id, provider in (
            self.providers.items()
        ):

            stats = provider.stats()

            children[
                library_id
            ] = stats

            try:
                articles += int(
                    stats.get(
                        "articles",
                        0,
                    )
                )
            except Exception:
                pass

            try:
                evidence_units += int(
                    stats.get(
                        "evidence_units",
                        stats.get("evidence", 0),
                    )
                )
            except Exception:
                pass

        return {
            "provider":
                self.provider_name,

            "libraries":
                len(
                    self.providers
                ),

            "articles":
                articles,

            "evidence_units":
                evidence_units,

            "children":
                children,
        }
