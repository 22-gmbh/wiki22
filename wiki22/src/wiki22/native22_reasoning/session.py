"""Bounded, replayable native learning from actual provider evidence.

The journal stores observations, never executable or trusted engine state.
Curriculum and journal facts cannot supply answers: every answer uses freshly
read evidence from the selected provider. Human assertions remain separate.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sqlite3

from .language_engine import Motore, impronta

RESOURCES = Path(__file__).with_name('resources')
MAX_OBSERVATIONS = 4096
MAX_OBSERVED_BYTES = 4 * 1024 * 1024
MAX_JOURNAL_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_BYTES = 16_384
MAX_QUERY_EVIDENCES = 40
MAX_QUERY_BYTES = 262_144


def make_engine():
    load = lambda name: json.loads((RESOURCES / name).read_text())
    engine = Motore(load('lessico_seme.json'), load('grammatica.json'), load('regole_ragionamento.json'))
    for doc in load('reading_curriculum.json')['documenti']:
        engine.osserva(doc)
    return engine


def binding(provider, evidence_id):
    evidence = provider.get_evidence(evidence_id)
    if evidence is None:
        raise ValueError('Evidence unavailable in selected scope')
    article = provider.get_article(evidence.article_id)
    if article is None:
        raise ValueError('Evidence parent unavailable in selected scope')
    if article.metadata.get('synthetic'):
        raise ValueError('Synthetic fixtures cannot become real product observations')
    identity = {'library_id': article.metadata.get('library_id', provider.stats().get('library_id')),
                'article_id': evidence.article_id, 'evidence_id': evidence.evidence_id,
                'source': evidence.source, 'revision': evidence.revision,
                'text_sha256': hashlib.sha256(evidence.text.encode()).hexdigest()}
    if not identity['library_id'] or not identity['source']:
        raise ValueError('Incomplete source provenance')
    doc = {'SOURCE_REF': 'WIKI22:' + impronta(identity), 'testo': evidence.text,
           'statuto': 'EVIDENZA_LOCALE', 'provenance': identity}
    return doc, evidence, article


class NativeSession:
    def __init__(self, journal_path=None):
        from .identity import verify_implementation
        self.identity = verify_implementation()
        self.engine = make_engine()
        self.journal = None
        self.learning_limit_reached = False
        if journal_path is not None:
            path = Path(journal_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > MAX_JOURNAL_BYTES:
                raise ValueError("Learning journal physical size exceeds budget")
            self.journal = sqlite3.connect(path)
            self.journal.execute('PRAGMA journal_mode=DELETE')
            self.journal.execute('PRAGMA foreign_keys=ON')
            page_size=self.journal.execute('PRAGMA page_size').fetchone()[0]
            self.journal.execute('PRAGMA max_page_count='+str(MAX_JOURNAL_BYTES//page_size))
            self.journal.execute('CREATE TABLE IF NOT EXISTS observations (source_id TEXT PRIMARY KEY, body TEXT NOT NULL, digest TEXT NOT NULL, bytes INTEGER NOT NULL)')
            self.journal.execute('CREATE TABLE IF NOT EXISTS user_assertions (id INTEGER PRIMARY KEY, question_ref TEXT NOT NULL, text TEXT NOT NULL, statute TEXT NOT NULL CHECK(statute="USER_ASSERTED"))')
            self.journal.execute('CREATE TABLE IF NOT EXISTS learning_status (id INTEGER PRIMARY KEY CHECK(id=1), limited INTEGER NOT NULL CHECK(limited IN (0,1)))')
            self.journal.execute('INSERT OR IGNORE INTO learning_status VALUES (1,0)')
            self.journal.commit()
            try:self._replay()
            except BaseException:self.close();raise

    def _replay(self):
        """Restore only committed, hash-bound observations; never serialized code."""
        engine=make_engine()
        count,total=self.journal.execute('SELECT count(*), coalesce(sum(bytes),0) FROM observations').fetchone()
        if count>MAX_OBSERVATIONS or total>MAX_OBSERVED_BYTES:
            raise ValueError('Learning journal exceeds its fixed budget')
        for source_id,body,digest,size in self.journal.execute('SELECT source_id,body,digest,bytes FROM observations ORDER BY rowid'):
            if len(body.encode())!=size or size<0 or impronta(body.encode())!=digest:
                raise ValueError('Learning observation integrity failure')
            doc=json.loads(body)
            if doc['SOURCE_REF']!=source_id or source_id!='WIKI22:'+impronta(doc['provenance']):
                raise ValueError('Learning observation identity failure')
            if hashlib.sha256(doc['testo'].encode()).hexdigest()!=doc['provenance']['text_sha256']:
                raise ValueError('Learning source bytes changed')
            engine.osserva(doc)
        self.engine=engine
        self.learning_limit_reached=bool(self.journal.execute('SELECT limited FROM learning_status WHERE id=1').fetchone()[0])

    def close(self):
        if self.journal is not None:
            self.journal.close()
            self.journal = None

    def observe(self, provider, evidence_id):
        doc, _, _ = binding(provider, evidence_id)
        if self.journal is None:
            return {'status': 'PERSISTENT_MEMORY_UNAVAILABLE'}
        if len(doc['testo'].encode()) > MAX_EVIDENCE_BYTES:
            return {'status': 'EVIDENCE_OVER_LEARNING_BUDGET'}
        body = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        size = len(body.encode())
        try:
            with self.journal:
                self.journal.execute('BEGIN IMMEDIATE')
                if self.journal.execute('SELECT 1 FROM observations WHERE source_id=?',(doc['SOURCE_REF'],)).fetchone():
                    return {'status':'ALREADY_OBSERVED'}
                count,total=self.journal.execute('SELECT count(*),coalesce(sum(bytes),0) FROM observations').fetchone()
                if count>=MAX_OBSERVATIONS or total+size>MAX_OBSERVED_BYTES:
                    self.learning_limit_reached=True
                    self.journal.execute('UPDATE learning_status SET limited=1 WHERE id=1')
                    return {'status':'LEARNING_BUDGET_REACHED'}
                self.engine.osserva(doc)
                self.journal.execute('INSERT INTO observations VALUES (?,?,?,?)',
                                     (doc['SOURCE_REF'],body,impronta(body.encode()),size))
        except BaseException:
            # Failure is exceptional: replay committed rows after rollback.
            # Successful reading avoids copying the entire growing memory.
            self._replay()
            raise
        return {'status':'OBSERVED','provenance':doc['provenance'],
                'observations':count+1,'observed_bytes':total+size}

    def user_assertion(self, question_ref, text):
        if self.journal is None:
            raise ValueError('Persistent memory unavailable')
        if not question_ref or not text or len(text.encode()) > 4096:
            raise ValueError('Invalid bounded human assertion')
        with self.journal:
            if self.journal.execute('SELECT count(*) FROM user_assertions').fetchone()[0] >= 128:
                raise ValueError('Human assertion budget reached')
            self.journal.execute('INSERT INTO user_assertions(question_ref,text,statute) VALUES (?,?,?)',
                                 (question_ref, text, 'USER_ASSERTED'))
        return {'statute': 'USER_ASSERTED', 'independently_verified': False}

    def answer(self, query, provider, evidence_ids):
        ids = list(dict.fromkeys(evidence_ids))
        if len(ids) > MAX_QUERY_EVIDENCES:
            return {'STATO': 'SCONOSCIUTA', 'MOTIVO': 'QUERY_EVIDENCE_BUDGET', 'FONTI': []}
        documents = []
        originals = {}
        total = 0
        for eid in ids:
            doc, evidence, article = binding(provider, eid)
            total += len(doc['testo'].encode())
            if total > MAX_QUERY_BYTES:
                return {'STATO': 'SCONOSCIUTA', 'MOTIVO': 'QUERY_TEXT_BUDGET', 'FONTI': []}
            documents.append(doc)
            originals[doc['SOURCE_REF']] = (doc, evidence, article)
        result = self.engine.rispondi(query, documents, usa_memoria=False)
        for source in result['FONTI']:
            doc, evidence, article = originals[source['SOURCE_REF']]
            left, right = source['TEXT_SPAN']
            if evidence.text[left:right] != source['testo']:
                raise ValueError('Native answer source span mismatch')
            source['provenance'] = copy.deepcopy(doc['provenance'])
            source['article_title'] = article.title
        result['CURRICULUM_FACTS_ELIGIBLE'] = False
        result['MODEL_CALLS'] = 0
        return result

    def metrics(self):
        return {**self.engine.metriche_stato(), 'learning_limit_reached': self.learning_limit_reached,
                'max_observed_bytes': MAX_OBSERVED_BYTES, 'max_observations': MAX_OBSERVATIONS,
                'max_journal_bytes': MAX_JOURNAL_BYTES,
                'scope': 'Bounded native reading; no general Italian proficiency claim',
                'AI22_LANG_LEVEL': None, 'AI22_REASON_PERCENTILE': None,
                'model_calls': 0, 'internet_required': False}
