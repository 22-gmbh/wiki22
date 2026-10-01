"""Bounded question equivalence, never an authority for factual answers.

Only complete, positive information requests are rewritten. Entity text is
copied, not inferred; source/time/negation qualifiers cannot be discarded.
The downstream engines must still resolve entities and reflect fresh sources.
"""
from dataclasses import dataclass
import re

VERSION = 'REQUEST022'
PREP = r"(?:dell['’]|d['’]|(?:di|del|della|dello)\s+)"
ENTITY = r"(?P<topic>.+)"


@dataclass(frozen=True)
class RequestMeaning:
    relation: str
    topic: str | None
    canonical: str | None
    rule: str


TEMPLATES = {
    'capital_of': 'Qual è la capitale di {topic}?',
    'nascita_tempo': 'Quando nacque {topic}?',
    'nascita_anno': 'In quale anno nacque {topic}?',
    'nascita_luogo': 'Dove nacque {topic}?',
    'morte_tempo': 'Quando morì {topic}?',
    'morte_anno': 'In quale anno morì {topic}?',
    'morte_luogo': 'Dove morì {topic}?',
    'attività': 'Quale professione svolgeva {topic}?',
    'nazionalità': 'Di quale nazionalità era {topic}?',
    'valuta': 'Qual è la valuta di {topic}?',
    'lingua': 'Qual è la lingua di {topic}?',
    'continente': 'In quale continente si trova {topic}?',
}

# These are question productions, not a table of world facts or entities.
PRODUCTIONS = (
    ('capital_of', r'(?:quale città è|come si chiama) la capitale '+PREP+ENTITY),
    ('capital_of', ENTITY+r' ha quale capitale'),
    ('capital_of', r'qual(?:e)? è la capitale '+PREP+ENTITY),
    ('nascita_tempo', r'(?:qual(?:e)? è la data di nascita|quando è la nascita) '+PREP+ENTITY),
    ('nascita_luogo', r'(?:qual(?:e)? è il luogo di nascita|in (?:che|quale) luogo (?:è nat[oa]|nacque)) (?:di )?'+ENTITY),
    ('morte_tempo', r'qual(?:e)? è la data di morte '+PREP+ENTITY),
    ('morte_luogo', r'qual(?:e)? è il luogo di morte '+PREP+ENTITY),
    ('attività', r'che (?:lavoro|mestiere) faceva '+ENTITY),
    ('nazionalità', r'qual(?:e)? era la nazionalità '+PREP+ENTITY),
    ('valuta', r'(?:che|quale) (?:moneta|valuta) si usa in '+ENTITY),
    ('lingua', r'(?:che|quale) lingua si parla in '+ENTITY),
    ('continente', r'(?:a (?:che|quale) continente appartiene|in (?:che|quale) continente (?:è|si trova)) '+ENTITY),
) + tuple(
    (event+'_'+field, prefix+' '+ENTITY+' '+verb)
    for event, verb in [('nascita',r'(?:è nat[oa]|nacque)'),('morte',r'(?:è mort[oa]|morì)')]
    for field, prefix in [('tempo','quando'),('luogo','dove'),('anno',r'in (?:che|quale) anno')]
) + tuple(
    (event+'_'+field, ENTITY+' '+prefix+' '+verb)
    for event, verb in [('nascita',r'(?:è nat[oa]|nacque)'),('morte',r'(?:è mort[oa]|morì)')]
    for field, prefix in [('tempo','quando'),('luogo','dove'),('anno',r'in (?:che|quale) anno')]
) + tuple(
    (event+'_'+field, prefix+' '+verb+' '+ENTITY)
    for event, verb in [('nascita',r'(?:è nat[oa]|nacque)'),('morte',r'(?:è mort[oa]|morì)')]
    for field, prefix in [('tempo','quando'),('luogo','dove'),('anno',r'in (?:che|quale) anno')]
)

# Whole entities only. Complex descriptions stay with the original interpreter.
# Rejecting one here means *no rewrite*, not that its name is invalid knowledge.
CLAUSE = re.compile(r'\b(?:non|se|forse|secondo|prima|dopo|quando|dove|perché|perche|che|quale|quali|oppure|o|e|nel|durante|oggi|ieri|domani|attuale|storica|culturale|economica|de|facto|iure|lui|lei|esso|essa|sua|suo|sue|suoi|questo|questa|quello|quella|è|era|sarebbe|fosse)\b',re.I)


def entity(text):
    text=text.strip()
    if not 1 <= len(text) <= 160 or not re.fullmatch(r"[^\W\d_]+(?:[ '\u2019-][^\W\d_]+)*",text):
        return None
    if CLAUSE.search(text):return None
    return text


def clean(query):
    if not isinstance(query,str) or len(query)>240 or '\n' in query:return None
    text=' '.join(query.strip().split())
    if text.endswith('?'):text=text[:-1].rstrip()
    # Only a single complete question, with no embedded quotation/instruction.
    if any(c in text for c in '?!.:;,"«»(){}[]='):return None
    return text


def interpret(query):
    text=clean(query)
    if not text:return None
    for i,(relation,pattern) in enumerate(PRODUCTIONS):
        match=re.fullmatch(pattern,text,re.I)
        if match:
            topic=entity(match['topic'])
            if topic:
                return RequestMeaning(relation,topic,TEMPLATES[relation].format(topic=topic),f'Q{i+1:02}')
    return None


def contextual(query):
    text=clean(query)
    if not text:return None
    text=re.sub(r'^e\s+','',text,flags=re.I)
    if re.fullmatch(r'(?:qual(?:e)? è )?la (?:sua )?capitale',text,re.I):
        return RequestMeaning('capital_of',None,None,'CONTEXT_CAPITAL')
    for event,verb in [('nascita',r'(?:è nat[oa]|nacque)'),('morte',r'(?:è mort[oa]|morì)')]:
        for field,prefix in [('tempo','quando'),('luogo','dove'),('anno',r'in (?:che|quale) anno')]:
            if re.fullmatch(prefix+r' (?:'+verb+r'(?: (?:lui|lei))?|(?:lui|lei) '+verb+r')',text,re.I):
                return RequestMeaning(event+'_'+field,None,None,'CONTEXT_EVENT')
    return None


def trace(original,normalized):
    meaning=interpret(original) or interpret(normalized)
    return dict(original=original,normalized=normalized,
                scope='BOUNDED_REQUEST_EQUIVALENCE' if meaning else 'REQUEST_WRAPPER_ONLY',
                interpreter=VERSION,relation=meaning.relation if meaning else None,
                factual_authority=False)
