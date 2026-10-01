from __future__ import annotations

from dataclasses import asdict

from wiki22.contracts import (
    KnowledgeProvider,
)


class QueryEngine:

    def __init__(
        self,
        provider: KnowledgeProvider,
        native_session=None,
    ) -> None:

        self.provider = provider
        self.native_session = native_session

    def _retrieve(
        self,
        query: str,
        *,
        limit: int,
    ) -> dict:

        hits = self.provider.search(
            query,
            limit=limit,
        )

        self.last_retrieval_trace = getattr(self.provider, "last_retrieval_trace", {})

        if not hits:

            return {
                "hit":
                    None,

                "article":
                    None,

                "evidence":
                    [],
            }

        hit = hits[0]

        article = getattr(self.provider, "get_article_summary", self.provider.get_article)(hit.article_id)

        evidence_rows = []

        for evidence_id in hit.evidence_ids:

            evidence = (
                self.provider.get_evidence(
                    evidence_id
                )
            )

            if evidence is None:
                continue

            evidence_rows.append(
                asdict(evidence)
            )

        return {
            "hit":
                hit,

            "article":
                article,

            "evidence":
                evidence_rows,
        }

    def answer(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> dict:

        retrieved = self._retrieve(
            query,
            limit=limit,
        )

        hit = retrieved["hit"]
        article = retrieved["article"]
        evidence_rows = retrieved["evidence"]

        if (
            hit is None
            or not evidence_rows
        ):

            return {
                "status":
                    "NO_EVIDENCE",

                "answer":
                    None,

                "supporting_evidence":
                    [],

                "article":
                    (
                        asdict(article)
                        if article
                        else None
                    ),

                "ai22_processing":
                    "NOT_REQUESTED",
            }

        if hasattr(self.provider, "get_passage"):
            passage = self.provider.get_passage(evidence_rows[0]["evidence_id"])
            from wiki22.knowledge.propositions import analyze_query, evaluate
            if passage is None or not evaluate(analyze_query(query),passage.text,title=article.title).accepted:
                return {"status":"NO_EVIDENCE", "answer":None,
                        "supporting_evidence":[], "ai22_processing":"NOT_REQUESTED"}
            evidence_rows = [dict(evidence_rows[0], text=passage.text,
                                 start=passage.start, end=passage.end)]

        return {
            "status":
                "ANSWERED",

            "query":
                query,

            "answer":
                evidence_rows[0]["text"],

            "supporting_evidence":
                evidence_rows,

            "article":
                (
                    asdict(article)
                    if article
                    else None
                ),

            "retrieval": {
                "article_id":
                    hit.article_id,

                "title":
                    hit.title,

                "score":
                    hit.score,
            },

            "knowledge_provider":
                self.provider.stats(),

            "ai22_processing":
                "NOT_REQUESTED",
        }

    def answer_with_ai22(self,query,*,ai22_adapter,limit=5):
        from .language_requests import normalize_request
        from .request_meaning import trace as request_trace
        normalized=normalize_request(query)
        result=self._answer_with_ai22(normalized,ai22_adapter=ai22_adapter,limit=limit)
        if normalized!=query:
            result.setdefault('trace',{})['request_normalization']=request_trace(query,normalized)
        return result

    def _answer_with_ai22(
        self,
        query: str,
        *,
        ai22_adapter,
        limit: int = 5,
    ) -> dict:

        from .request_meaning import contextual
        missing=contextual(query)
        if missing:
            target='Di quale paese' if missing.relation=='capital_of' else 'Di quale persona'
            return dict(status='CLARIFY', query=query,
                        answer=target+' stai parlando?', supporting_evidence=[],
                        trace=dict(reason='MISSING_UNAMBIGUOUS_ANTECEDENT',
                                   requested_relation=missing.relation, model_calls=0))

        from wiki22.study import StudyEngine,study_plan
        if study_plan(query) is not None:
            study_result=StudyEngine(self.provider).answer(query)
            if study_result is not None:return study_result

        from wiki22.geography import answer_geographic
        geographic_result=answer_geographic(query,self.provider)
        if geographic_result is not None:return geographic_result

        from wiki22.study_comparison import compare_readings
        study_comparison=compare_readings(query,self.provider)
        if study_comparison is not None:return study_comparison

        from wiki22.biographic_qa import answer_biographic
        biographic_result = answer_biographic(query, self.provider, ai22_adapter)
        if biographic_result is not None:
            return biographic_result

        from wiki22.knowledge.propositions import analyze_query
        required = analyze_query(query).required
        direct_capital = required is not None and required.predicate == 'capital_of'
        if not direct_capital and self.native_session is not None and hasattr(self.provider, 'raw_candidates'):
            native_result = self._answer_native(query, ai22_adapter)
            if native_result is not None:
                return native_result

        # No compatible proposition can emerge from an unresolved question
        # in the older grammar. Offer a useful reformulation without scanning
        # dozens of documents and claiming that local knowledge is absent.
        analysis=analyze_query(query)
        if analysis.kind=='UNRESOLVED' and hasattr(self.provider,'get_article_summary'):
            return dict(status='CLARIFY',query=query,
                answer='Non riesco ancora a ricostruire questa domanda. Puoi chiedermi una definizione, un confronto tra due argomenti o un dato preciso; in Studio puoi leggere la voce e lavorare sui passaggi.',
                supporting_evidence=[],trace=dict(reason='UNSUPPORTED_QUESTION_STRUCTURE',model_calls=0))

        retrieved = self._retrieve(
            query,
            limit=limit,
        )

        hit = retrieved["hit"]
        article = retrieved["article"]
        evidence_rows = retrieved["evidence"]

        if (
            hit is None
            or article is None
            or not evidence_rows
        ):
            # The fast capital path remains first. A controlled successor may
            # resolve coordinated clauses that the earlier parser rejects.
            if direct_capital and self.native_session is not None and hasattr(self.provider, 'raw_candidates'):
                native_result = self._answer_native(query, ai22_adapter)
                if native_result is not None:
                    return native_result

            return {
                "status":
                    "NO_EVIDENCE",

                "answer":
                    None,

                "supporting_evidence":
                    evidence_rows,

                "ai22_processing":
                    "NOT_RUN",

                "trace": self.last_retrieval_trace,
                "related_articles": self._related_articles(query),
            }

        fixture = (
            article.metadata.get(
                "ai22_fixture"
            )
        )

        # Imported knowledge is adjudicated as an exact excerpt; only the
        # synthetic architecture fixture uses its historical structured path.
        if not article.metadata.get("synthetic", False) or not isinstance(fixture, dict):
            return self._answer_excerpt(query, retrieved, ai22_adapter)

        ai22 = ai22_adapter.adjudicate_structured(
            question=
                fixture["question"],

            evidence_payload=
                fixture["evidence_payload"],
        )

        response = ai22.get(
            "response",
            {}
        )

        data = response.get(
            "data",
            {}
        )

        decision = data.get(
            "decision"
        )

        answer_text = (
            evidence_rows[0]["text"]
            if decision == "PASS"
            else None
        )

        return {
            "status":
                (
                    "ANSWERED"
                    if decision == "PASS"
                    else "NOT_SUPPORTED"
                ),

            "query":
                query,

            "answer":
                answer_text,

            "answer_type":
                (
                    "EXTRACTIVE_EVIDENCE_AFTER_AI22_PASS"
                    if decision == "PASS"
                    else "NONE"
                ),

            "supporting_evidence":
                evidence_rows,

            "article":
                asdict(article),

            "retrieval": {
                "article_id":
                    hit.article_id,

                "title":
                    hit.title,

                "score":
                    hit.score,
            },

            "ai22_processing":
                "COMPLETE",

            "ai22_decision":
                decision,

            "ai22":
                ai22,

            "knowledge_provider":
                self.provider.stats(),
        }

    def _related_articles(self, query):
        """Exact topic matches for consultation, never supporting evidence."""
        from wiki22.knowledge.propositions import analyze_query, entity
        analysis = analyze_query(query)
        if analysis.required is None or not hasattr(self.provider, 'raw_candidates'):
            return []
        subject = analysis.required.subject
        if hasattr(self.provider, 'get_article_summary'):
            article = self.provider.get_article_summary(subject)
            return [dict(article_id=article.article_id, title=article.title)] if article and entity(article.title) == subject else []
        rows = self.provider.raw_candidates(query, limit=40)
        found = {}
        for row in rows:
            if entity(row['title']) == subject:
                found[row['article_id']] = dict(article_id=row['article_id'], title=row['title'])
        return list(found.values())[:3]

    def _answer_native(self, query, adapter):
        from .native_preflight import possibly_native_question
        if not possibly_native_question(query):return None
        session = self.native_session
        if session.engine.domanda(query) is None:
            return None
        candidates = self.provider.raw_candidates(query, limit=40)
        ids = [row['evidence_id'] for row in candidates]
        observations = [session.observe(self.provider, eid) for eid in ids] if getattr(session,'learning_enabled',True) else [{'status':'PAUSED'}]
        result = session.answer(query, self.provider, ids)
        trace = {'query': query, 'native22': result, 'learning': observations,
                 'native_metrics': session.metrics(), 'exhaustive_corpus_semantic_scan': False}
        if result['STATO'] != 'VERIFICATA':
            if result['STATO'] == 'CONFLITTO' or result.get('MOTIVO') == 'RISPOSTE_MULTIPLE_NON_DISAMBIGUATE':
                return {'status': 'NO_EVIDENCE', 'answer': None, 'supporting_evidence': [],
                        'ai22_processing': 'NATIVE_REFLECTION_REJECTED', 'trace': trace}
            # The older independently gated grammar still handles constructs
            # not covered by this native learner. It never sees a native PASS.
            return None
        sources = []
        documentary = []
        for source in result['FONTI']:
            provenance = source['provenance']
            evidence = self.provider.get_evidence(provenance['evidence_id'])
            left, right = source['TEXT_SPAN']
            if evidence is None or evidence.text[left:right] != source['testo']:
                raise ValueError('Evidence changed between native reflection and emission')
            verdict = adapter.verify_excerpt(question=query, claim=source['testo'], evidence={
                **asdict(evidence), 'document_text': evidence.text, 'start': left, 'end': right})
            documentary.append(verdict)
            if verdict.get('decision') != 'DOCUMENTED':
                return {'status': 'NOT_SUPPORTED', 'answer': None, 'supporting_evidence': [],
                        'ai22_processing': 'DOCUMENTARY_REJECTED', 'trace': trace}
            sources.append(dict(asdict(evidence), text=source['testo'], start=left, end=right,
                                library_id=provenance['library_id'], article_title=source['article_title'],
                                source_sha256=provenance['text_sha256']))
        trace['frozen_documentary_checks'] = documentary
        return {'status': 'ANSWERED', 'query': query, 'answer': result['RISPOSTA'],
                'answer_type': 'NATIVE_ITALIAN_AFTER_REFLECTION_AND_DOCUMENTARY_SUPPORT',
                'supporting_evidence': sources, 'ai22_processing': 'COMPLETE',
                'ai22_decision': 'DOCUMENTED', 'native_decision': 'VERIFICATA',
                'retrieval': {'article_id': sources[0]['article_id'], 'title': sources[0]['article_title']},
                'knowledge_provider': self.provider.stats(), 'trace': trace}

    def _answer_excerpt(self, query, retrieved, adapter):
        hit, article = retrieved["hit"], retrieved["article"]
        rows = retrieved["evidence"]
        selected = None
        for row in rows:
            getter = getattr(self.provider, "get_passage", None)
            passage = getter(row["evidence_id"]) if getter else None
            if passage is not None:
                selected = row, passage
                break
        trace = {
            "query": query, "provider": self.provider.stats(),
            "retrieval_gate": self.last_retrieval_trace,
            "retrieved_article": hit.article_id,
            "retrieved_evidence_ids": [x["evidence_id"] for x in rows],
        }
        if selected is None:
            return {"status": "NO_EVIDENCE", "answer": None,
                    "supporting_evidence": [], "ai22_processing": "NOT_RUN", "trace": trace}
        row, passage = selected
        # Defense at the generation boundary: even a faulty provider cannot
        # turn a retrieval score into authorization.
        from wiki22.knowledge.propositions import analyze_query, evaluate
        decision = evaluate(analyze_query(query), passage.text, title=article.title)
        trace["generation_gate"] = decision.to_dict()
        if not decision.accepted:
            return {"status":"NO_EVIDENCE", "answer":None, "supporting_evidence":[],
                    "ai22_processing":"NOT_RUN", "trace":trace}
        ai22_input = dict(row, document_text=row["text"], start=passage.start, end=passage.end)
        ai22 = adapter.verify_excerpt(question=query, claim=passage.text, evidence=ai22_input)
        documented = ai22.get("decision") == "DOCUMENTED"
        answer_text = passage.text
        if documented and 'nonché' in passage.text.casefold() and decision.candidate.predicate == 'capital_of':
            # Compose from the verified role, retaining the exact full source
            # span separately. Round-trip the sentence through the same gate.
            from wiki22.articles import render_claim
            answer_text = render_claim(decision.candidate)
            if not evaluate(analyze_query(query), answer_text).accepted:
                raise ValueError('Capital realization lost the verified proposition')
        source = dict(row, text=passage.text, start=passage.start, end=passage.end,
                      library_id=article.metadata.get("library_id"),
                      library_name=article.metadata.get("library_name"),
                      article_title=article.title, score=passage.score)
        trace.update(selected_evidence=source, relevance_reason=passage.reason,
                     ai22_input={"question":query,"claim":passage.text,
                                 "evidence":{"evidence_id":row["evidence_id"],"text":passage.text,
                                             "start":passage.start,"end":passage.end}}, ai22=ai22)
        return {
            "status": "ANSWERED" if documented else "NOT_SUPPORTED",
            "answer": answer_text if documented else None,
            "answer_type": "EXTRACTIVE_AI22_DOCUMENTARY_SUPPORT" if documented else "NONE",
            "supporting_evidence": [source] if documented else [],
            "article": asdict(article), "query": query,
            "retrieval": {"article_id": hit.article_id, "title": hit.title, "score": hit.score},
            "ai22_processing": "COMPLETE", "ai22_decision": ai22.get("decision"),
            "ai22": ai22, "trace": trace, "knowledge_provider": self.provider.stats(),
        }
