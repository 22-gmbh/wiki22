"""Bounded Italian study instructions and transparent statistical grammar analysis.

No exam IDs, answer keys, factuality labels or answer-choice text authorize the
analysis. It describes words in the supplied text, never truth about the world.
"""
from dataclasses import asdict, dataclass
import hashlib
import re
from .dependency_reader import solver, _lock

QUOTES = re.compile(r'«([^»]+)»|“([^”]+)”|"([^"\n]+)"')
POS_NAMES = {'NOUN': 'nome', 'PROPN': 'nome proprio', 'VERB': 'verbo',
             'AUX': 'verbo ausiliare', 'ADJ': 'aggettivo', 'ADV': 'avverbio',
             'DET': 'determinante', 'PRON': 'pronome', 'ADP': 'preposizione',
             'CCONJ': 'congiunzione coordinante', 'SCONJ': 'congiunzione subordinante',
             'NUM': 'numerale', 'INTJ': 'interiezione', 'PUNCT': 'punteggiatura',
             'X': 'categoria non determinata'}
FEATURE_NAMES = {'Mood': 'modo', 'Tense': 'tempo', 'Number': 'numero',
                 'Gender': 'genere', 'Person': 'persona', 'VerbForm': 'forma verbale'}
FEATURE_VALUES = {'Ind': 'indicativo', 'Sub': 'congiuntivo', 'Cnd': 'condizionale',
                  'Imp': 'imperativo', 'Inf': 'infinito', 'Ger': 'gerundio',
                  'Part': 'participio', 'Fin': 'finita', 'Pres': 'presente',
                  'Past': 'passato', 'Fut': 'futuro', 'Sing': 'singolare',
                  'Plur': 'plurale', 'Masc': 'maschile', 'Fem': 'femminile'}
CATEGORY_POS = {'nome': {'NOUN', 'PROPN'}, 'verbo': {'VERB', 'AUX'},
                'aggettivo': {'ADJ'}, 'avverbio': {'ADV'}, 'pronome': {'PRON'},
                'preposizione': {'ADP'}, 'congiunzione': {'CCONJ', 'SCONJ'}}


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def normalized(text):
    return text.casefold().replace('’', "'").strip()


def quoted(text):
    return [dict(text=m.group(i), span=[m.start(i), m.end(i)])
            for m in QUOTES.finditer(text) for i in range(1, 4) if m.group(i)]


@dataclass(frozen=True)
class StudyRequest:
    kind: str
    passage: str
    passage_origin: str
    passage_span: tuple
    target: str = ''
    category: str = ''
    feature: str = ''


def interpret(question, context=None):
    if not isinstance(question, str) or len(question) > 8192:
        return None
    clean = normalized(question)
    kind = None
    category = feature = ''
    binary = re.search(r'(?:è|e) (?:un |una )?(nome|verbo|aggettivo|avverbio|pronome|preposizione|congiunzione) o no', clean)
    if binary:
        kind, category = 'CATEGORY_MEMBERSHIP', binary.group(1)
    elif re.search(r'\blemma\b', clean) or ('dizionario' in clean and 'forma' in clean and 'parola' in clean):
        kind = 'LEMMA'
    elif re.search(r'(?:categoria grammaticale|parte del discorso)', clean):
        kind = 'CATEGORY'
    elif re.search(r'(?:che|quale) (tempo|modo|numero|genere|persona)\b', clean):
        kind = 'FEATURE'
        feature = re.search(r'(?:che|quale) (tempo|modo|numero|genere|persona)\b', clean).group(1)
    elif re.search(r'\banalizza (?:grammaticalmente )?(?:la |questa )?frase\b|\banalisi grammaticale\b', clean):
        kind = 'ANALYSIS'
    if kind is None:
        return None
    quotes = quoted(question)
    passages = [q for q in quotes if len(q['text'].split()) >= 2]
    if len(passages) == 1:
        p = passages[0]
        passage, origin, span = p['text'], 'question', tuple(p['span'])
    elif len(passages) > 1:
        return None
    elif isinstance(context, str) and context.strip():
        passage, origin, span = context, 'context', (0, len(context))
    elif kind == 'ANALYSIS' and ':' in question:
        start = question.index(':') + 1
        while start < len(question) and question[start].isspace():
            start += 1
        passage, origin, span = question[start:], 'question', (start, len(question))
    else:
        return None
    if not passage or len(passage) > 16384:
        return None
    target = ''
    if kind != 'ANALYSIS':
        candidates = [q['text'] for q in quotes if q['text'] != passage and len(q['text'].split()) == 1]
        if binary and ':' in question:
            tail = question.rsplit(':', 1)[1].strip()
            if re.fullmatch(r"[\w’'-]+", tail):
                candidates.append(tail)
        # An explicit unquoted target after parola/verbo is also accepted.
        if not candidates:
            m = re.search(r'\b(?:parola|verbo)\s+([\w’\'-]+)(?:\s|[?.]|$)', question, re.I)
            if m and normalized(m.group(1)) not in {'è', 'e', 'un', 'una', 'che', 'trovi'}:
                candidates.append(m.group(1))
        candidates = list(dict.fromkeys(normalized(t) for t in candidates))
        if len(candidates) != 1:
            return None
        target = candidates[0]
    return StudyRequest(kind, passage, origin, span, target, category, feature)


def unknown(reason):
    return dict(STATO='SCONOSCIUTA', MOTIVO=reason, VALORE=None,
                RISPOSTA='Non riesco a determinare questa analisi dal testo fornito.',
                FONTI=[], LLM_CALLS=0)


def describe(token):
    morphology = {}
    for field in token.feats.split('|'):
        if '=' not in field:
            continue
        key, value = field.split('=', 1)
        if key in FEATURE_NAMES:
            translated = ('imperfetto' if key == 'Tense' and value == 'Imp'
                          else FEATURE_VALUES.get(value, value))
            morphology[FEATURE_NAMES[key]] = translated
    return dict(form=token.form, lemma=token.lemma, category=POS_NAMES.get(token.pos, token.pos),
                upos=token.pos, morphology=morphology, relation=token.rel,
                head=token.head, token_id=token.id, span=[token.lo, token.hi])


def verb_group(token, sentence):
    """A bounded compound-tense interpretation with all contributing token spans."""
    members = [token] + [t for t in sentence if t.head == token.id and t.rel.startswith('aux')]
    finite = [t for t in members if 'VerbForm=Fin' in t.feats]
    morphology = describe(token)['morphology'].copy()
    if token.pos == 'VERB' and 'VerbForm=Part' in token.feats and len(finite) == 1:
        auxiliary = finite[0]
        if auxiliary.lemma in {'avere', 'essere'} and 'Tense=Past' in token.feats:
            am = describe(auxiliary)['morphology']
            compound = {('indicativo', 'presente'): 'passato prossimo',
                        ('indicativo', 'imperfetto'): 'trapassato prossimo',
                        ('indicativo', 'passato'): 'trapassato remoto',
                        ('indicativo', 'futuro'): 'futuro anteriore',
                        ('condizionale', 'presente'): 'passato',
                        ('congiuntivo', 'presente'): 'passato',
                        ('congiuntivo', 'imperfetto'): 'trapassato'}
            label = compound.get((am.get('modo'), am.get('tempo')))
            if label:
                morphology.update({k: v for k, v in am.items() if k in {'modo', 'persona', 'numero'}})
                morphology['tempo'] = label
    return dict(morphology=morphology, members=[describe(t) for t in members])


def analyze(question, context=None):
    request = interpret(question, context)
    if request is None:
        return unknown('UNSUPPORTED_OR_AMBIGUOUS_STUDY_INSTRUCTION')
    try:
        with _lock:
            sentences = solver().parse(request.passage)
    except (ImportError, OSError, ValueError):
        return unknown('GRAMMAR_ANALYSIS_UNAVAILABLE')
    tokens = [token for sentence in sentences for token in sentence]
    if not tokens:
        return unknown('EMPTY_GRAMMAR_ANALYSIS')
    selected = tokens
    if request.target:
        selected = [t for t in tokens if normalized(t.form) == request.target]
        # Repeated words may have different roles: request a unique occurrence.
        if len(selected) != 1:
            return unknown('TARGET_MISSING_OR_AMBIGUOUS')
    analyses = [dict(sentence=i, **describe(t)) for i, sentence in enumerate(sentences)
                for t in sentence if t in selected]
    token = selected[0]
    sentence = next(sentence for sentence in sentences if token in sentence)
    group = verb_group(token, sentence)
    if request.kind == 'LEMMA':
        if token.pos in {'PUNCT', 'X'}:
            return unknown('LEMMA_UNAVAILABLE')
        value = token.lemma
        explanation = f'Nel testo, «{token.form}» è ricondotto al lemma «{value}».'
    elif request.kind == 'CATEGORY_MEMBERSHIP':
        if token.pos == 'X':
            return unknown('CATEGORY_UNAVAILABLE')
        matches = token.pos in CATEGORY_POS[request.category]
        value = ('È un ' if matches else 'Non è un ') + request.category
        explanation = f'«{token.form}» è analizzato come {POS_NAMES[token.pos]}: {value.casefold()}.'
    elif request.kind == 'CATEGORY':
        value = POS_NAMES.get(token.pos)
        if not value or token.pos == 'X':
            return unknown('CATEGORY_UNAVAILABLE')
        explanation = f'Nel testo, «{token.form}» è analizzato come {value}.'
    elif request.kind == 'FEATURE':
        value = group['morphology'].get(request.feature)
        if value is None:
            return unknown('REQUESTED_FEATURE_UNAVAILABLE')
        explanation = f'Per «{token.form}» nel suo contesto, {request.feature}: {value}.'
    else:
        value = None
        explanation = '\n'.join(f"{a['form']} — {a['category']}; lemma: {a['lemma']}" for a in analyses)
    proof = dict(schema='wiki22.study.analysis.v1', question_sha256=sha(question),
                 context_sha256=sha(context) if isinstance(context, str) else None,
                 request=asdict(request), passage_sha256=sha(request.passage), analyses=analyses,
                 selected_verb_group=group if request.kind == 'FEATURE' else None,
                 statistical=True, factual_answer_authorized=False)
    return dict(STATO='ANALISI_LINGUISTICA', VALORE=value, RISPOSTA=explanation,
                AVVERTENZA='Analisi grammaticale automatica: può contenere errori.',
                FONTI=[dict(ORIGINE=request.passage_origin, TEXT_SPAN=list(request.passage_span),
                            testo=request.passage, sha256=sha(request.passage))],
                PROVA=proof, LLM_CALLS=0, LOCAL_STATISTICAL_INFERENCE_REQUIRED=True)


def check_analysis(question, context, result):
    if result.get('STATO') != 'ANALISI_LINGUISTICA':
        return False
    return analyze(question, context) == result
