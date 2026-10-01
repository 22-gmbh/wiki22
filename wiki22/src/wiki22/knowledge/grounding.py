"""Candidate generation and exact-span selection, separate from authorization.

Lexical scores only retrieve/rank. Proposition compatibility in propositions.py
is the sole eligibility gate for real-library QA.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from .relevance import _tokens
from .propositions import analyze_query, evaluate

_FUNCTIONS = set('the a an of in on at to is are was were be been does do did what which who how why when where che cosa cos si ha hanno quale qual quali sono essere un una uno'.split())

def terms(text):
    return [t for t in _tokens(text) if t not in _FUNCTIONS]

@dataclass(frozen=True)
class Passage:
    text: str
    start: int
    end: int
    score: float
    reason: str
    semantic_gate: dict

def sentences(text):
    # Preserve exact offsets and bytes, including existing imports with literal \\n.
    boundary = re.compile(r'(?<=[.!?])\s+|\n+|\\n')
    start = 0
    depth = 0
    scanned = 0
    for match in boundary.finditer(text):
        # Pronunciation annotations contain filenames such as .ogg. A period
        # inside balanced parentheses is not an independent sentence boundary.
        for char in text[scanned:match.start()]:
            if char == '(': depth += 1
            elif char == ')': depth = max(0, depth - 1)
        scanned = match.start()
        if depth and '\n' not in match[0] and '\\n' not in match[0]:
            continue
        depth = 0
        end = match.start()
        piece = text[start:end]
        if piece.strip():
            left = start + len(piece) - len(piece.lstrip())
            yield text[left:end].rstrip(), left, end - len(piece) + len(piece.rstrip())
        start = match.end()
    piece = text[start:]
    if piece.strip():
        left = start + len(piece) - len(piece.lstrip())
        yield text[left:].rstrip(), left, len(text.rstrip())


def candidate_plan(analysis):
    anchors=set(terms(analysis.text))
    required=analysis.required
    if required:
        anchors.update(terms(required.subject))
        surface = {
            "capital_of": ["capitale"],
            "president_of": ["presidente", "vicepresidente"],
            "authored_by": ["scritto", "scritta", "scrisse", "autore"],
            "located_in": ["trova", "trovano", "situato", "situata", "localizzato", "localizzata", "sorge"],
            "distance_rank": ["vicino", "prossimo", "lontano"],
        }.get(required.predicate)
        if required.predicate.startswith("property_of:"):
            surface=[required.predicate.split(":",1)[1]]
        if surface is None:
            surface=terms(required.subject)
    else:
        surface=list(anchors)
    pattern=re.compile(r"(?<!\w)(?:"+"|".join(re.escape(t) for t in surface)+r")(?!\w)",re.I) if surface else None
    return anchors,pattern


def candidates(analysis, title, text, *, allow_unterminated=True, plan=None, timing=None):
    from time import perf_counter
    anchors,pattern = plan or candidate_plan(analysis)
    if pattern is None:
        return
    for sentence, start, end in sentences(text):
        if timing is not None:
            timing["inspected_sentences"] += 1
        if not pattern.search(sentence):
            continue
        actual=set(terms(sentence))
        overlap=sum(any(q==t or (len(q)>=5 and (q.startswith(t) or t.startswith(q)))
                        for t in actual) for q in anchors)
        lexical_score=overlap/max(1,len(anchors))
        before=perf_counter()
        gate=evaluate(analysis,sentence,title=title)
        if timing is not None:
            timing["semantic_gate_seconds"] += perf_counter()-before
        if len(sentence)>1800 or (not allow_unterminated and not sentence.endswith(('.', '!', ';', ':'))):
            from dataclasses import replace
            gate=replace(gate,accepted=False,reason='INCOMPLETE_OR_OVERSIZE_SENTENCE')
        yield sentence,start,end,lexical_score,gate


def select_passage(query: str, title: str, text: str, *, allow_unterminated=True) -> Passage | None:
    analysis=analyze_query(query)
    eligible=[]
    for sentence,start,end,score,gate in candidates(analysis,title,text,allow_unterminated=allow_unterminated):
        if gate.accepted:
            eligible.append(Passage(sentence,start,end,score,gate.reason,gate.to_dict()))
    return max(eligible,key=lambda p:(p.score,-len(p.text),-p.start),default=None)
