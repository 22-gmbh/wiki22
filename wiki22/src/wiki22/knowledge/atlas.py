"""Lazy, bounded MEMIDX/LOCO over canonical product library providers.

Indexes are derived observations, never an authority for factual answers.
Search uses the full existing corpus index; only a bounded working set is
expanded into a graph. Every navigation back to evidence checks current bytes.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3

from .memidx_candidate import MemIndex, canonical, digest, KINDS
from .atlas_extractor import EvidenceGraphExtractor

MAX_EVIDENCE = 48
MAX_TEXT_BYTES = 262144
MAX_CACHE_BYTES = 32 * 1024 * 1024
VERSION = 'MEMIDX001-LAZY-PRODUCT-02'


def canonical_record(provider, eid):
    e = provider.get_evidence(eid)
    if e is None:
        raise ValueError('Evidenza non disponibile nella selezione corrente')
    summary = getattr(provider, 'get_article_summary', None)
    a = summary(e.article_id, evidence_id=e.evidence_id) if summary else provider.get_article(e.article_id)
    if a is None:
        raise ValueError('Documento della fonte non disponibile')
    section = next((s for s in a.sections if s['id'] == e.section_id), None)
    if section is None or not e.source or a.source != e.source:
        raise ValueError('Provenienza incompleta o incoerente')
    prefix, separator, _ = e.evidence_id.partition('::')
    lid = (prefix if separator and prefix in getattr(provider, 'providers', {}) else
           a.metadata.get('library_id') or provider.stats().get('library_id'))
    if not lid:
        raise ValueError('Identità della libreria assente')
    row = dict(evidence_id=e.evidence_id, article_id=e.article_id, library_id=lid,
               title=a.title, source_ref=e.source, revision=e.revision,
               section_id=e.section_id, section_title=section.get('title', section.get('heading', '')),
               text=e.text, locale='it-IT')
    return row


def identity(row):
    return digest({k: row[k] for k in ('evidence_id','article_id','library_id','title',
                   'source_ref','revision','section_id','section_title','text')})


class DerivedCache:
    """Bounded append-only derived records; no canonical text duplication."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_CACHE_BYTES:
            raise ValueError('Derived cache exceeds its storage budget')
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA page_size=4096')
        self.db.execute('PRAGMA max_page_count=8192')
        self.db.execute('CREATE TABLE IF NOT EXISTS observations (identity TEXT PRIMARY KEY, library TEXT, article TEXT, evidence TEXT, model TEXT, bytes INTEGER)')
        self.db.execute('CREATE INDEX IF NOT EXISTS library_article ON observations(library,article)')
        self.full = False

    def remember(self, binding, row, model):
        body = canonical(model).decode()
        size = len(body.encode()) + 1024
        used = self.db.execute('SELECT coalesce(sum(bytes),0) FROM observations').fetchone()[0]
        if used + size > MAX_CACHE_BYTES // 2:
            self.full = True
            return
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)',
                (binding,row['library_id'],row['article_id'],row['evidence_id'],body,size))

    def close(self):
        self.db.close()


class Atlas:
    def __init__(self, provider, cache_path=None):
        self.provider = provider
        self.cache = DerivedCache(cache_path) if cache_path else None
        self.indexes = {}
        self.rows = {}
        self.bindings = {}
        self.stats = {}
        self.extractor = EvidenceGraphExtractor()

    def close(self):
        if self.cache:
            self.cache.close()
            self.cache = None

    def search(self, topic):
        if not topic.strip() or len(topic) > 240:
            raise ValueError('Inserisci un argomento tra 1 e 240 caratteri')
        candidates = self.provider.raw_candidates(topic, limit=MAX_EVIDENCE)
        self.rows, self.bindings = {}, {}
        documents = defaultdict(dict)
        total, skipped = 0, 0
        for candidate in candidates:
            row = canonical_record(self.provider, candidate['evidence_id'])
            size = len(row['text'].encode())
            if size > 32768 or total + size > MAX_TEXT_BYTES:
                skipped += 1
                continue
            total += size
            eid, lid, aid = row['evidence_id'], row['library_id'], row['article_id']
            self.rows[eid], self.bindings[eid] = row, identity(row)
            article = dict(article_id=aid, title=row['title'], source_ref=row['source_ref'],
                           locale=row['locale'], evidence=[row])
            model = self.extractor.extract(article)
            existing = documents[lid].setdefault(aid, dict(article=model['article'], records=[]))
            existing['records'].extend(model['records'])
            if self.cache:
                self.cache.remember(digest([VERSION, self.bindings[eid]]), row, model)
        self.indexes = {lid: MemIndex(lid,lid,digest([VERSION,sorted(self.bindings.items())]),docs)
                        for lid,docs in documents.items()}
        self.stats = {'version':VERSION, 'evidence_examined':len(self.rows),
                      'text_bytes':total, 'skipped_over_budget':skipped,
                      'candidate_limit':MAX_EVIDENCE, 'full_corpus_graph':False,
                      'cache_full':bool(self.cache and self.cache.full),
                      'canonical_provider':self.provider.stats(), 'model_calls':0,
                      'offline':True, 'scope':'LOCAL_RESEARCH_WORKING_SET'}
        return self.stats

    def nodes(self, kind):
        if kind not in KINDS:
            raise ValueError('Vista non riconosciuta')
        return sorted((node for idx in self.indexes.values() for node in idx.nodes_of(kind)),
                      key=lambda node:(node['label'].casefold(),node['id']))

    def resolve(self, node_id):
        idx = next((idx for idx in self.indexes.values() if node_id in idx.nodes), None)
        if idx is None:
            raise KeyError(node_id)
        result = []
        for rid in sorted(idx.node_members[node_id]):
            _, record = idx.records[rid]
            eid = record['evidence_id']
            current = canonical_record(self.provider, eid)
            if identity(current) != self.bindings[eid]:
                raise ValueError('La fonte è cambiata: ripeti la ricerca')
            # Re-extract: forged or stale graph nodes can never authorize evidence.
            model = self.extractor.extract(dict(article_id=current['article_id'],
                title=current['title'],source_ref=current['source_ref'],locale=current['locale'],evidence=[current]))
            fresh = MemIndex(idx.library_id,idx.name,idx.source_sha,{current['article_id']:model})
            if node_id not in fresh.nodes or idx.nodes[node_id]['label'] != fresh.nodes[node_id]['label']:
                raise ValueError('Indice derivato non verificabile')
            result.append(current)
        return result

    def connections(self, node_id):
        self.resolve(node_id)
        idx = next(idx for idx in self.indexes.values() if node_id in idx.nodes)
        return [dict(node=idx.nodes[b if a==node_id else a], relation=role)
                for a,b,role,_ in sorted(idx.edges) if a==node_id or b==node_id]


def browse_titles(provider, prefix='', *, after='', limit=30):
    if not 1 <= limit <= 100:
        raise ValueError('Pagina troppo grande')
    cursor = tuple(after) if isinstance(after,(list,tuple)) else (after,'\uffff' if after else '')
    if hasattr(provider, 'providers'):
        rows = []
        for lid, child in provider.providers.items():
            rows.extend(dict(row,article_id=lid+'::'+row['article_id'],library_id=lid)
                        for row in browse_titles(child,prefix,after=(cursor[0],''),limit=min(100,limit+1)))
        result = sorted((r for r in rows if (r['key'],r['article_id'])>cursor),
                        key=lambda r:(r['key'],r['article_id']))[:limit]
    elif hasattr(provider, 'browse_titles'):
        result = provider.browse_titles(prefix,after=cursor,limit=limit)
    elif hasattr(provider, '_articles'):
        result = sorted((dict(key=a['title'].casefold(),title=a['title'],article_id=aid)
            for aid,a in provider._articles.items() if a['title'].casefold().startswith(prefix.casefold())
            and (a['title'].casefold(),aid)>cursor), key=lambda r:(r['key'],r['article_id']))[:limit]
    else:
        raise ValueError('Indice alfabetico non disponibile per questa libreria')
    return [dict(row,cursor=(row['key'],row['article_id'])) for row in result]
