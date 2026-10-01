from __future__ import annotations

import json
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any

from wiki22.knowledge.synthetic import SyntheticProvider


class RealKnowledgeProvider(
    SyntheticProvider
):
    """Local pack reader with sentence-level, fail-closed extractive retrieval.

    Uses the shared pack contract; the synthetic provider's overlap search and
    experimental relevance environment switches do not control real libraries.
    """

    provider_name = "RealKnowledgeProvider"

    def __init__(
        self,
        pack_path: str | Path,
    ) -> None:

        self.real_pack_path = Path(
            pack_path
        ).resolve()

        if not self.real_pack_path.is_file():
            raise FileNotFoundError(
                f"Real knowledge pack missing: "
                f"{self.real_pack_path}"
            )

        raw = json.loads(
            self.real_pack_path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            raw,
            dict,
        ):
            raise ValueError(
                "Real knowledge pack must be a JSON object"
            )

        articles = raw.get(
            "articles"
        )

        if not isinstance(
            articles,
            list,
        ) or not articles:
            raise ValueError(
                "Real knowledge pack contains no articles"
            )

        for article in articles:
            if not isinstance(
                article,
                dict,
            ):
                raise ValueError(
                    "Invalid article record"
                )

            metadata = article.get(
                "metadata",
                {},
            )

            if (
                isinstance(
                    metadata,
                    dict,
                )
                and metadata.get(
                    "synthetic"
                ) is True
            ):
                raise ValueError(
                    "Synthetic article cannot be mounted "
                    "as real product knowledge"
                )

        super().__init__(self.real_pack_path, data=raw)

    def get_metadata(
        self,
    ) -> dict[str, Any]:

        result = dict(
            super().get_metadata()
        )

        result["provider"] = (
            self.provider_name
        )

        result["synthetic"] = False
        result["temporary"] = False

        result["pack_path"] = str(
            self.real_pack_path
        )

        return result

    def health(self):
        value = super().health()

        if is_dataclass(value):
            available = {
                field.name
                for field in fields(value)
            }

            updates = {}

            if "provider" in available:
                updates["provider"] = (
                    self.provider_name
                )

            if updates:
                return replace(
                    value,
                    **updates,
                )

        if isinstance(
            value,
            dict,
        ):
            result = dict(value)
            result["provider"] = (
                self.provider_name
            )
            return result

        if hasattr(
            value,
            "_replace",
        ):
            try:
                return value._replace(
                    provider=self.provider_name
                )
            except Exception:
                pass

        return value


    def search(self, query: str, *, limit: int = 5):
        from time import perf_counter
        from wiki22.contracts import SearchHit
        from .grounding import candidates, candidate_plan, Passage
        from .propositions import analyze_query
        start = perf_counter()
        analysis = analyze_query(query)
        plan = candidate_plan(analysis)
        timing = {"inspected_sentences": 0, "semantic_gate_seconds": 0.0}
        self.selected_passages = {}
        hits = []
        records = []
        for article in self._articles.values():
            eligible = []
            browse = []
            for section in article.get("sections", []):
                for evidence in section.get("evidence", []):
                    for text, left, right, score, gate in candidates(
                            analysis, article["title"], evidence["text"], plan=plan, timing=timing,
                            allow_unterminated=section is article["sections"][-1]):
                        record = {"library_id":article.get("metadata",{}).get("library_id"),
                            "article_id":article["id"], "evidence_id":evidence["id"],
                            "source":article["source"], "title":article["title"],
                            "text":text, "start":left, "end":right,
                            "candidate_score":score, "semantic_gate":gate.to_dict()}
                        records.append(record)
                        if gate.accepted:
                            passage=Passage(text,left,right,score,gate.reason,gate.to_dict())
                            previous=self.selected_passages.get(evidence["id"])
                            if previous is None or (score,-len(text))>(previous.score,-len(previous.text)):
                                self.selected_passages[evidence["id"]]=passage
                            eligible.append((score, len(text), evidence["id"]))
                        elif analysis.kind == "SEARCH":
                            # Browsing retains broad search results, but no passage is
                            # authorized for QueryEngine/AI22 without a proposition.
                            browse.append((score,len(text),evidence["id"]))
            ranked=eligible or (browse if analysis.kind=="SEARCH" else [])
            if ranked:
                ranked.sort(key=lambda x:(-x[0],x[1]))
                hits.append(SearchHit(article["id"],article["title"],ranked[0][0],
                            tuple(dict.fromkeys(eid for _,_,eid in ranked))))
        hits.sort(key=lambda h:(-h.score, len(self.selected_passages[h.evidence_ids[0]].text)
                  if h.evidence_ids[0] in self.selected_passages else 0,h.article_id))
        self.last_retrieval_trace = {"query_analysis":analysis.to_dict(),
            "provider":self.stats(), "candidates":records,
            "accepted":sum(r["semantic_gate"]["decision"]=="PASS" for r in records),
            "rejected":sum(r["semantic_gate"]["decision"]=="REJECT" for r in records),
            "retrieval_seconds":perf_counter()-start, **timing}
        return hits[:max(0,limit)]

    def raw_candidates(self, query, *, limit=80):
        from heapq import nsmallest
        from .grounding import terms
        if not 0 <= limit <= 256:
            raise ValueError('Candidate request exceeds bounded retrieval budget')
        wanted = set(terms(query))
        def rows():
            for eid, evidence in self._evidence.items():
                score = len(wanted & set(terms(evidence['text'])))
                if score:
                    article = self._articles[evidence['article_id']]
                    yield {'evidence_id': eid, 'article_id': evidence['article_id'],
                           'title': article['title'], 'text': evidence['text'], 'score': score}
        return nsmallest(limit, rows(), key=lambda row: (-row['score'], row['evidence_id']))

    def get_passage(self, evidence_id):
        return getattr(self, "selected_passages", {}).get(evidence_id)

    def stats(
        self,
    ) -> dict[str, Any]:

        result = dict(
            super().stats()
        )

        result["provider"] = (
            self.provider_name
        )

        result["synthetic"] = False

        return result
