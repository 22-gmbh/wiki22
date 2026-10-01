"""Source-bound proposition graph with explicit discourse obligations.

A sentence that may qualify another claim cannot be discarded. Retractions and
confirmations are about claims, not new independent facts about the world.
This remains a bounded grammar/semantic contract, not unrestricted Italian.
"""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
from .dependency_reader import (solver, _lock, children, subtree, tense, role,
                                argument_key, BADVERBS)
from .factuality import FactualityClassifier

META_NOUNS = frozenset(('affermazione frase notizia ricostruzione dichiarazione '
                       'ipotesi tesi versione conclusione dato asserzione racconto').split())
META_NEGATIVE = frozenset(('falso errato inesatto sbagliato infondato inventato '
                          'inattendibile infondare inventare smentire ritrattare correggere rettificare scherzo').split())
META_POSITIVE = frozenset(('vero corretto esatto confermare verificare').split())
NEGATION = frozenset(('non mai niente nulla nessuno').split())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def signature(tokens, root):
    args = []
    for t in children(tokens, root.id):
        if t.rel in {'punct', 'cop'} or t.rel.startswith('aux') or t.lemma == 'non':
            continue
        args.append((role(tokens, t), argument_key(tokens, t)))
    return digest((root.lemma, tense(tokens, root), sorted(args)))


def build_graph(documents):
    if len(documents) > 40 or sum(len(d['testo']) for d in documents) > 262144:
        raise ValueError('Discourse document budget exceeded')
    graph = dict(schema='wiki22.discourse.graph.v1', sources={}, nodes=[], edges=[],
                 obligations=[], llm_calls=0, learned_labels_authorize_answers=False)
    reader = solver()
    classifier = FactualityClassifier()
    for doc in documents:
        sid, text = doc['SOURCE_REF'], doc['testo']
        sha = hashlib.sha256(text.encode()).hexdigest()
        if sid in graph['sources']:
            if graph['sources'][sid] != sha:
                raise ValueError('COLLISIONE_FONTE')
            continue
        graph['sources'][sid] = sha
        with _lock:
            sentences = reader.parse(text)
        prior = []
        for tokens in sentences:
            if len(graph['nodes']) >= 512:
                raise ValueError('Discourse sentence budget exceeded')
            root = next(t for t in tokens if t.head == 0)
            lo, hi = min(t.lo for t in tokens), max(t.hi for t in tokens)
            body = text[lo:hi]
            node = dict(id='P-' + digest((sid, sha, lo, hi))[:20], source=sid,
                        source_sha256=sha, span=[lo, hi], text=body,
                        kind='PROPOSITION', state='UNRESOLVED', predicate=root.lemma,
                        polarity='POSITIVE', tense=tense(tokens, root),
                        signature=signature(tokens, root), grammatical_proposal=[asdict(t) for t in tokens],
                        factuality_proposal=classifier.predict(tokens, root.id))
            graph['nodes'].append(node)
            direct = children(tokens, root.id)
            subjects = [t for t in direct if t.rel.startswith('nsubj')]
            explicit_subject = any(t.pos in {'NOUN', 'PROPN'} for t in subjects)
            finite = any('Mood=Ind' in t.feats and 'VerbForm=Fin' in t.feats
                         for t in [root] + [t for t in direct if t.rel.startswith('aux') or t.rel == 'cop'])
            negative = any(t.lemma in NEGATION for t in direct)
            if negative:
                node['polarity'] = 'NEGATIVE'
            grammatical_modal = (not finite or any('Mood=Cnd' in t.feats or 'Mood=Sub' in t.feats
                                      or t.lemma in BADVERBS for t in [root] + direct))
            quoted = any(mark in body for mark in ('«', '»', '“', '”', '"'))
            uncertain = any(t.lemma in {'forse', 'probabilmente', 'presumibilmente', 'se', 'secondo'}
                            for t in tokens)
            meta_terms = [t for t in tokens if t.lemma in META_NOUNS]
            implicit_meta = (not subjects and (any(t.rel == 'cop' for t in direct)
                                               or root.lemma in META_NEGATIVE))
            demonstrative_subject = any(t.pos == 'PRON' for t in subjects) or any(
                t.lemma in {'questo', 'quello', 'ciò'} for s in subjects for t in subtree(tokens, s.id))
            if meta_terms or implicit_meta or demonstrative_subject:
                node['kind'] = 'CLAIM_REFERENCE'
                # Do not guess between two candidate propositions. An explicit
                # ordinal licenses a reference; otherwise require uniqueness.
                words = {t.lemma for t in tokens}
                targets = prior[-1:] if words & {'ultimo', 'precedente'} else prior[:1] if 'primo' in words else prior if len(prior) == 1 else []
                if len(targets) != 1 or grammatical_modal or quoted or uncertain or negative:
                    graph['obligations'].append(dict(node=node['id'], kind='UNRESOLVED_CLAIM_REFERENCE'))
                    continue
                target = targets[0]
                if root.lemma in META_NEGATIVE:
                    node['state'] = 'RETRACTION_RECORDED'
                    target['state'] = 'DISPUTED'
                    relation = 'DISPUTES'
                elif root.lemma in META_POSITIVE:
                    node['state'] = 'CONFIRMATION_RECORDED'
                    # Confirmation cannot restore a disputed event automatically.
                    relation = 'CONFIRMS_TEXTUALLY'
                else:
                    graph['obligations'].append(dict(node=node['id'], kind='UNINTERPRETED_CLAIM_QUALIFIER'))
                    continue
                graph['edges'].append(dict(source=node['id'], target=target['id'], relation=relation))
                continue
            if quoted or uncertain or grammatical_modal or not explicit_subject:
                graph['obligations'].append(dict(node=node['id'], kind='UNRESOLVED_ASSERTION_SCOPE'))
                prior.append(node)
                continue
            # A subordinate/cross-clause reading remains open until its scope is
            # represented. Do not discard it merely because the root matches.
            if any(t.rel.split(':')[0] in {'advcl', 'acl', 'ccomp', 'xcomp', 'parataxis', 'conj'} for t in tokens):
                graph['obligations'].append(dict(node=node['id'], kind='UNRESOLVED_CLAUSE_SCOPE'))
                prior.append(node)
                continue
            node['state'] = 'NEGATED' if negative else 'ASSERTED'
            if not negative and node['factuality_proposal']['veto']:
                node['state'] = 'UNCERTAIN_PROPOSAL'
                graph['obligations'].append(dict(node=node['id'], kind='LEARNED_FACTUALITY_VETO'))
            prior.append(node)
    # Equal complete role/time signatures with opposing polarity are a conflict.
    groups = {}
    for node in graph['nodes']:
        if node['state'] in {'ASSERTED', 'NEGATED'}:
            groups.setdefault(node['signature'], []).append(node)
    for nodes in groups.values():
        if len({n['polarity'] for n in nodes}) > 1:
            for node in nodes:
                node['state'] = 'CONFLICT'
            graph['obligations'].append(dict(kind='CONTRADICTORY_PROPOSITIONS', nodes=[n['id'] for n in nodes]))
    graph['identity'] = digest(graph)
    return graph


def propose_answer(question, documents):
    """Align isolated claims only after checking their entire source context."""
    graph = build_graph(documents)
    out = dict(status='unknown', reason='DISCOURSE_NOT_RESOLVED', graph=graph)
    if graph['obligations']:
        return out
    matches = []
    reader = solver()
    for node in graph['nodes']:
        if node['kind'] != 'PROPOSITION' or node['state'] != 'ASSERTED':
            continue
        with _lock:
            proposal = reader.solve(question, [dict(SOURCE_REF=node['source'], testo=node['text'])])
        if proposal['status'] != 'candidate':
            continue
        for proof in proposal['proofs']:
            offset = node['span'][0]
            proof = dict(proof, span=[x + offset for x in proof['span']],
                         sentence_span=node['span'], source_sha256=node['source_sha256'], node=node['id'])
            matches.append(proof)
    if not matches:
        out['reason'] = 'NO_UNDISPUTED_STRUCTURAL_MATCH'
        return out
    if len({p['value'].casefold() for p in matches}) != 1:
        out['reason'] = 'MULTIPLE_UNDISPUTED_ANSWERS'
        return out
    return dict(status='candidate', proofs=matches, graph=graph)


def check_answer(question, documents, proof):
    if proof.get('status') != 'candidate':
        return False
    texts = {d['SOURCE_REF']: d['testo'] for d in documents}
    eligible = {n['id'] for n in proof['graph']['nodes'] if n['state'] == 'ASSERTED'}
    for p in proof.get('proofs', []):
        text = texts.get(p['source'])
        if text is None or p['node'] not in eligible:
            return False
        lo, hi = p['span']
        a, b = p['sentence_span']
        if not 0 <= a <= lo < hi <= b <= len(text):
            return False
        if text[lo:hi] != p['value'] or text[a:b] != p['sentence']:
            return False
        if hashlib.sha256(text.encode()).hexdigest() != p['source_sha256']:
            return False
    return bool(proof.get('proofs')) and propose_answer(question, documents) == proof
