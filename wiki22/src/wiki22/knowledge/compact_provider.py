"""Paged 22CK libraries exposed through the product's provider contract.

Container ranking produces candidates only. The existing proposition gate
still authorizes exact source spans. No full corpus is materialized at startup.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import hashlib
import json
import time

from wiki22.contracts import Article, EvidenceRef, ProviderHealth, SearchHit
from .compact22 import TwentyTwoCKReader
from .grounding import Passage, candidate_plan, candidates
from .propositions import analyze_query

CATALOG_SCHEMA = 'wiki22.22ck.library.v1'


class CompactKnowledgeProvider:
    provider_name = 'CompactKnowledgeProvider'

    def __init__(self, pack_path):
        self.path = Path(pack_path).resolve()
        self.readers = []
        self._bio_specs = []
        self._bio_indexes = {}
        self._reading_indexes = {}
        self._reading_specs = []
        self._geo_specs = []
        self._geo_indexes = {}
        self.expected_hashes = []
        self.selected_passages = {}
        self.last_retrieval_trace = {}
        self.full_integrity_verified = False
        initial_catalog_stamp = self._stamp(self.path)
        if self.path.name.endswith('.22lib.json'):
            if self.path.stat().st_size > 262144:
                raise ValueError('Compact library catalog too large')
            catalog = json.loads(self.path.read_text())
            if catalog.get('schema') != CATALOG_SCHEMA:
                raise ValueError('Unsupported compact library catalog')
            parts = catalog.get('parts', [])
            if not 1 <= len(parts) <= 32:
                raise ValueError('Invalid compact partition count')
            paths = []
            for part in parts:
                path = (self.path.parent / part['path']).resolve()
                if not path.is_relative_to(self.path.parent) or path in paths:
                    raise ValueError('Unsafe or duplicate compact partition path')
                if path.stat().st_size != part['bytes']:
                    raise ValueError('Compact partition size changed')
                digest = part['sha256'].upper()
                if len(digest) != 64 or any(c not in '0123456789ABCDEF' for c in digest):
                    raise ValueError('Invalid compact partition identity')
                paths.append(path)
                self.expected_hashes.append(digest)
                bio = part.get('biographic_index')
                if bio:
                    from .biographic_index import PROMOTION, MAX_BYTES
                    bio_path=(self.path.parent / bio['path']).resolve()
                    if (not bio_path.is_relative_to(self.path.parent) or bio_path==path
                        or bio.get('promotion')!=PROMOTION or not 1<=bio['bytes']<=MAX_BYTES
                        or bio_path.stat().st_size!=bio['bytes']):
                        raise ValueError('Unsafe, unpromoted or changed biographic index')
                    self._bio_specs.append(dict(bio,path=bio_path,canonical_sha256=digest))
                else:self._bio_specs.append(None)
                reading=part.get('reading_index')
                if reading:
                    from wiki22.reading import PROMOTION as READING_PROMOTION,MAX_INDEX
                    rp=(self.path.parent / reading['path']).resolve()
                    if (not rp.is_relative_to(self.path.parent) or rp==path
                        or reading.get('promotion')!=READING_PROMOTION
                        or not 1<=reading['bytes']<=MAX_INDEX or rp.stat().st_size!=reading['bytes']):
                        raise ValueError('Unsafe, unpromoted or changed reading index')
                    proof=reading.get('proof')
                    if proof:
                        pp=(self.path.parent / proof['path']).resolve()
                        if (not pp.is_relative_to(self.path.parent) or pp in {rp,path}
                            or pp.stat().st_size!=proof['bytes']):raise ValueError('Unsafe reading proof')
                        reading=dict(reading,proof=dict(proof,path=pp))
                    self._reading_specs.append(dict(reading,path=rp,canonical_sha256=digest))
                else:self._reading_specs.append(None)
                geo=part.get('geographic_index')
                if geo:
                    from wiki22.geography import PROMOTION as GEO_PROMOTION,MAX_BYTES as GEO_MAX
                    gp=(self.path.parent / geo['path']).resolve()
                    if (not gp.is_relative_to(self.path.parent) or gp==path or geo.get('promotion')!=GEO_PROMOTION
                        or not 1<=geo['bytes']<=GEO_MAX or gp.stat().st_size!=geo['bytes']):
                        raise ValueError('Unsafe, unpromoted or changed geographic index')
                    self._geo_specs.append(dict(geo,path=gp,canonical_sha256=digest))
                else:self._geo_specs.append(None)
            self.complete = catalog.get('complete') is True
        else:
            catalog = {}
            paths = [self.path]
            self.expected_hashes = [None]
            self.complete = False
            self._bio_specs = [None]
            self._reading_specs = [None]
            self._geo_specs = [None]
        self.supports_geographic_fields=any(self._geo_specs)
        self._file_stamps = {path: self._stamp(path) for path in paths}
        self._file_stamps[self.path] = initial_catalog_stamp
        for spec in self._bio_specs+self._reading_specs+self._geo_specs:
            if spec:
                self._file_stamps[spec['path']]=self._stamp(spec['path'])
                if spec.get('proof'):self._file_stamps[spec['proof']['path']]=self._stamp(spec['proof']['path'])
        try:
            for path in paths:
                self.readers.append(TwentyTwoCKReader(path))
            identities = {r.manifest['library_id'] for r in self.readers}
            if len(identities) != 1:
                raise ValueError('Compact partitions belong to different libraries')
            self.library_id = identities.pop()
            if catalog and catalog['library_id'] != self.library_id:
                raise ValueError('Catalog library identity mismatch')
            self.library_name = catalog.get('name', self.readers[0].manifest['library_name'])
            self._ensure_unchanged()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _stamp(path):
        stat = path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def _ensure_unchanged(self):
        for path, expected in self._file_stamps.items():
            if self._stamp(path) != expected:
                self.full_integrity_verified = False
                raise ValueError('La libreria è cambiata durante la consultazione: riaprila e verifica l’integrità')

    def close(self):
        for index in self._geo_indexes.values():index.close()
        self._geo_indexes = {}
        for index in self._reading_indexes.values():index.close()
        self._reading_indexes = {}
        for index in self._bio_indexes.values():index.close()
        self._bio_indexes = {}
        for reader in self.readers:
            reader.close()
        self.readers = []

    def _lookup(self, method, ident):
        self._ensure_unchanged()
        found = None
        for reader in self.readers:
            try:
                result = getattr(reader, method)(ident)
            except KeyError:
                continue
            if found is not None:
                raise ValueError('Ambiguous identity across compact partitions')
            found = result
        self._ensure_unchanged()
        return found

    def browse_titles(self, prefix='', *, after='', limit=30):
        self._ensure_unchanged()
        from .compact_access import title_page
        if not 1 <= limit <= 100:
            raise ValueError('Title page exceeds budget')
        rows = [row for reader in self.readers
                for row in title_page(reader, prefix, after, limit)]
        return sorted(rows, key=lambda r: (r['key'], r['article_id']))[:limit]

    def exact_topic_candidates(self, topic, *, limit=8):
        """Bounded direct-title reading for literal source-field questions."""
        return self.raw_candidates(topic, limit=limit, focused=True)

    def raw_candidates(self, query, *, limit=80, focused=False):
        self._ensure_unchanged()
        from .compact_access import article_evidence
        import re
        if not 0 <= limit <= 256:
            raise ValueError('Candidate request exceeds bounded retrieval budget')
        if not limit:
            return []
        analysis = analyze_query(query)
        topic = analysis.required.subject if analysis.required else query.strip()
        stop = set("il lo la i gli le un uno una di del della dello dei delle degli a al alla allo ai alle da dal dalla in nel nella con per su e è sono era che cosa chi qual quale dove si trova".split())
        content = [w for w in re.findall(r"[^\W_]+", query.casefold()) if w not in stop]
        lexical_query = ' '.join(content) or query
        selected = {}
        owners = {}
        title_hints = set()
        # An exact article title is a retrieval hint, never a truth decision.
        for reader_number, reader in enumerate(self.readers):
            try:
                direct = article_evidence(reader, topic, min(limit, 8 if focused else 32))
            except KeyError:
                direct = []
            if analysis.required and analysis.required.predicate == 'capital_of':
                for row in direct[:4]:
                    # A flattened template can suggest a title to retrieve,
                    # never authorize a proposition or a factual answer.
                    for match in re.finditer(r'(?<!\w)capitale\s*=\s*(.{1,220}?)\s+capitaleabitanti\s*=', row['text'], re.I):
                        value = match[1].strip()
                        symbol = re.fullmatch(r'simbolo\s*\|[^|=]{1,150}\.\s*(?:svg|png)\s+(.+)', value, re.I)
                        flag = re.fullmatch(r'band div\s*\|\s*[a-z]{3}\s*\|\s*([^|]+)\s*\|\s*2', value, re.I)
                        value = (symbol[1] if symbol else flag[1] if flag else value).strip()
                        if re.fullmatch(r'[^\W\d_]+(?:[ \'-][^\W\d_]+)*', value) and len(value) <= 100:
                            title_hints.add(value)
            if analysis.required and analysis.required.predicate == 'capital_of':
                for row in direct[:4]:
                    # Qualified template values remain retrieval hints only.
                    # The independent grammar must retain the qualification.
                    for field in re.finditer(r'(?<!\w)capitale\s*=\s*(.{1,4096}?)\s+capitaleabitanti\s*=', row['text'], re.I):
                        for hint in re.finditer(r"simbolo\s*\|[^|=]{1,150}\.\s*(?:svg|png)\s+([^\W\d_]+(?:[ '-][^\W\d_]+)*)\s*\(\s*de facto\s*\)", field[1], re.I):
                            title_hints.add(hint[1].strip())
            for row in direct:
                previous_owner = owners.setdefault(row['evidence_id'], reader_number)
                if previous_owner != reader_number:
                    raise ValueError('Duplicate evidence across compact partitions')
                selected[row['evidence_id']] = dict(row, score=len(content)+1,
                                                    retrieval_reason='EXACT_TITLE')
            lexical = [] if focused else getattr(reader, "search_references", reader.search)(lexical_query, limit=limit)
            for row in lexical:
                previous_owner = owners.setdefault(row['evidence_id'], reader_number)
                if previous_owner != reader_number:
                    raise ValueError('Duplicate evidence across compact partitions')
                previous = selected.get(row['evidence_id'])
                if previous is None:
                    selected[row['evidence_id']] = dict(row, retrieval_reason='LEXICAL')
                elif 'article_id' in row and previous['article_id'] != row['article_id']:
                    raise ValueError('Ambiguous evidence across partitions')
        # At most three one-hop hints, eight opening blocks each. All spans
        # still pass the independent proposition and frozen documentary gates.
        for hint in sorted(title_hints)[:3]:
            for reader_number, reader in enumerate(self.readers):
                try: linked = article_evidence(reader, hint, 8)
                except KeyError: continue
                for row in linked:
                    previous_owner = owners.setdefault(row['evidence_id'], reader_number)
                    if previous_owner != reader_number:
                        raise ValueError('Duplicate evidence across compact partitions')
                    if row['evidence_id'] not in selected:
                        selected[row['evidence_id']] = dict(row, score=len(content)+.5,
                            retrieval_reason='UNTRUSTED_CAPITAL_TITLE_HINT')
        ranked = sorted(selected.values(), key=lambda row: (-row['score'], row['evidence_id']))[:limit]
        result = []
        for row in ranked:
            if 'text' not in row:
                reader = self.readers[owners[row['evidence_id']]]
                row = dict(reader.get_evidence(row['evidence_id']), score=row['score'],
                           retrieval_reason=row['retrieval_reason'])
            result.append(row)
        self._ensure_unchanged()
        return result

    def search(self, query, *, limit=5):
        if limit <= 0:
            return []
        start = time.perf_counter()
        analysis = analyze_query(query)
        plan = candidate_plan(analysis)
        self.selected_passages = {}
        grouped = defaultdict(list)
        records = []
        timing = {'inspected_sentences': 0, 'semantic_gate_seconds': 0.0}
        budget = min(256, max(80, limit * 8))
        def inspect(rows):
            for row in rows:
                if analysis.kind == 'SEARCH':
                    grouped[(row['article_id'], row['title'])].append((row['score'], row['evidence_id']))
                for text, left, right, score, gate in candidates(
                        analysis, row['title'], row['text'], plan=plan, timing=timing,
                        allow_unterminated=False):
                    records.append({'evidence_id': row['evidence_id'], 'semantic_gate': gate.to_dict()})
                    if gate.accepted:
                        passage = Passage(text, left, right, score, gate.reason, gate.to_dict())
                        previous = self.selected_passages.get(row['evidence_id'])
                        if previous is None or (score, -len(text)) > (previous.score, -len(previous.text)):
                            self.selected_passages[row['evidence_id']] = passage
                        grouped[(row['article_id'], row['title'])].append((score, row['evidence_id']))
        required = analysis.required
        focused = required is not None and required.predicate == 'capital_of' and required.object is None
        if focused:
            inspect(self.raw_candidates(query, limit=budget, focused=True))
        if not grouped:
            inspect(self.raw_candidates(query, limit=budget))
        hits = []
        for (ident, title), rows in grouped.items():
            rows.sort(key=lambda row: (-row[0], row[1]))
            hits.append(SearchHit(ident, title, rows[0][0], tuple(dict.fromkeys(eid for _, eid in rows))))
        self.last_retrieval_trace = {
            'query_analysis': analysis.to_dict(), 'candidates': records,
            'accepted': sum(row['semantic_gate']['decision'] == 'PASS' for row in records),
            'candidate_budget': budget, 'exhaustive_corpus_semantic_scan': False,
            'focused_title_first': focused,
            'retrieval_seconds': time.perf_counter() - start, **timing}
        return sorted(hits, key=lambda hit: (-hit.score, hit.article_id))[:limit]

    def _biographic_index(self, number):
        spec=self._bio_specs[number]
        if spec is None:return None
        if number not in self._bio_indexes:
            from .biographic_index import BiographicIndex
            self._bio_indexes[number]=BiographicIndex(spec['path'],sha256=spec['sha256'],
                canonical_sha256=spec['canonical_sha256'],promotion=spec['promotion'])
        return self._bio_indexes[number]

    def biographic_record(self, evidence_id):
        self._ensure_unchanged()
        found=None
        for number,reader in enumerate(self.readers):
            if self._bio_specs[number] is None:continue
            try:source=reader.get_evidence(evidence_id)
            except KeyError:continue
            record=self._biographic_index(number).record(reader,source['article_id'],evidence_id)
            if record is not None:
                if found is not None:raise ValueError('Ambiguous biography across partitions')
                found=record
        self._ensure_unchanged()
        return found

    def geographic_record(self, article_id):
        from .compact_access import article_metadata
        from wiki22.geography import GeographicIndex
        self._ensure_unchanged();found=None
        for number,reader in enumerate(self.readers):
            spec=self._geo_specs[number]
            if spec is None:continue
            try:article_metadata(reader,article_id)
            except KeyError:continue
            if number not in self._geo_indexes:
                self._geo_indexes[number]=GeographicIndex(spec['path'],sha256=spec['sha256'],
                    canonical_sha256=spec['canonical_sha256'],promotion=spec['promotion'])
            record=self._geo_indexes[number].read(reader,article_id)
            if record is not None:
                if found is not None:raise ValueError('Ambiguous geography across partitions')
                found=record
        self._ensure_unchanged();return found

    def reading_record(self, article_id):
        from .compact_access import article_metadata
        from wiki22.reading import ReadingIndex
        self._ensure_unchanged()
        found=None
        for number,reader in enumerate(self.readers):
            spec=self._reading_specs[number]
            if spec is None:continue
            try:article_metadata(reader,article_id)
            except KeyError:continue
            if number not in self._reading_indexes:
                self._reading_indexes[number]=ReadingIndex(spec['path'],sha256=spec['sha256'],
                    canonical_sha256=spec['canonical_sha256'],promotion=spec['promotion'],proof=spec.get('proof'))
            record=self._reading_indexes[number].read(reader,article_id)
            if record is not None:
                if found is not None:raise ValueError('Ambiguous reading across partitions')
                found=record
        self._ensure_unchanged()
        return found

    def get_passage(self, evidence_id):
        return self.selected_passages.get(evidence_id)

    def get_article_summary(self, article_id, *, evidence_id=None):
        from .compact_access import article_metadata
        self._ensure_unchanged()
        found = None
        evidence = self._lookup('get_evidence', evidence_id) if evidence_id is not None else None
        if evidence_id is not None and evidence is None:
            raise ValueError('Missing evidence for article summary')
        for reader in self.readers:
            try: row = article_metadata(reader, article_id)
            except KeyError: continue
            if found is not None: raise ValueError('Ambiguous article across partitions')
            sections = ()
            if evidence is not None:
                if evidence['article_id'] != row['article_id'] or evidence['source_ref'] != row['source_ref']:
                    raise ValueError('Evidence does not belong to this article')
                sections = (dict(id=evidence['section_id'], title=evidence['section_title'], evidence=[]),)
            found = Article(row['article_id'], row['title'], 'knowledge', row['source_ref'],
                '22CK_CANONICAL', sections, dict(library_id=self.library_id, library_name=self.library_name,
                    synthetic=False, format='22CK', complete_library=self.complete))
        self._ensure_unchanged()
        return found

    def get_article(self, article_id):
        row = self._lookup('get_article', article_id)
        if row is None:
            return None
        sections = {}
        for evidence in row['evidence']:
            section = sections.setdefault(evidence['section_id'], {
                'id': evidence['section_id'], 'title': evidence['section_title'], 'evidence': []})
            section['evidence'].append({'id': evidence['evidence_id'], 'text': evidence['text']})
        return Article(row['article_id'], row['title'], 'knowledge', row['source_ref'],
                       '22CK_CANONICAL', tuple(sections.values()), {
                           'library_id': self.library_id, 'library_name': self.library_name,
                           'synthetic': False, 'format': '22CK', 'complete_library': self.complete})

    def get_evidence(self, evidence_id):
        row = self._lookup('get_evidence', evidence_id)
        if row is None:
            return None
        return EvidenceRef(row['evidence_id'], row['article_id'], row['section_id'],
                           row['source_ref'], '22CK_BLOCK_SHA256:' + row['block_sha256'], row['text'])

    def iter_canonical_articles(self):
        self._ensure_unchanged()
        for reader in self.readers:
            yield from reader.iter_articles()

    def get_relations(self, entity):
        return []  # Relation extraction belongs to MEMIDX, not lexical search.

    def get_metadata(self):
        return dict(self.stats(), library_name=self.library_name, pack_path=str(self.path))

    def stats(self):
        self._ensure_unchanged()
        return {'provider': self.provider_name, 'library_id': self.library_id,
                'articles': sum(r.manifest['article_count'] for r in self.readers),
                'evidence': sum(r.manifest['evidence_count'] for r in self.readers),
                'partitions': len(self.readers), 'complete_library': self.complete,
                'synthetic': False, 'offline': True, 'full_integrity_verified': self.full_integrity_verified}

    def verify_integrity(self):
        self._ensure_unchanged()
        self.full_integrity_verified = False
        for reader, expected in zip(self.readers, self.expected_hashes):
            if not reader.verify_integrity():
                raise ValueError('Compact integrity failure')
            if expected:
                with reader.path.open('rb') as stream:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest().upper()
                if actual != expected:
                    raise ValueError('Compact artifact differs from catalog identity')
        for number,spec in enumerate(self._bio_specs):
            if spec:self._biographic_index(number).unchanged()
        for spec in self._reading_specs+self._geo_specs:
            if spec:
                for entry in [spec]+([spec['proof']] if spec.get('proof') else []):
                    with entry['path'].open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest().upper()
                    if actual!=entry['sha256'].upper():raise ValueError('Reading artifact differs from pinned manifest')
        self._ensure_unchanged()
        self.full_integrity_verified = True
        return True

    def health(self):
        return ProviderHealth('READY', self.provider_name, True, self.stats())


def open_library(path):
    """Preserve existing JSON libraries while mounting paged compact corpora."""
    path = Path(path)
    if path.suffix == '.22ck' or path.name.endswith('.22lib.json'):
        return CompactKnowledgeProvider(path)
    from .real import RealKnowledgeProvider
    return RealKnowledgeProvider(path)
