"""Explicit, conservative Italian proposition compatibility for offline QA.

This is a bounded grammar, not an entailment model. It parses full argument
spans and named relations, retains modifiers/time/polarity, and refuses unknown
forms. Lexical retrieval is separate and cannot grant a semantic PASS. No
entity-to-answer table, inference from world knowledge, or RC modification.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace
import re
import unicodedata

_PREP = r"(?:dell'|d'|(?:della|delle|dello|degli|del|dei|di)\s+)"
# Predicate vocabulary maps surface grammar, never entities or answers.
_HEADS = {'capitale':'capital_of', 'presidente':'president_of', 'autore':'authored_by'}
_MODIFIERS = {'politica':'political', 'politico':'political', 'culturale':'culture',
              'cultura':'culture', 'economica':'economic', 'economico':'economic'}
_COPULA = re.compile(r'\s+(?:(non)\s+)?(è|sono|era|erano|fu|furono|sarà|saranno)\s+', re.I)
_UNCERTAIN = re.compile(r'\b(?:forse|probabilmente|presumibilmente|potrebbe|potrebbero|sarebbe|sarebbero|ipoteticamente|ignot[oa]|sconosciut[oa]|presunt[oa]|candidat[oa])\b',re.I)
_NEGATIVE = re.compile(r'\b(?:non|mai|nessun[oa]?)\b',re.I)


def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(text)).replace('’',"'").replace('ʼ',"'").replace('‘',"'")).strip()


def bare(text: str) -> str:
    text = normalize(text).strip(' .!?;:«»"')
    # Determiners must be complete words; "Italia" is not "i" + "talia".
    return re.sub(r"^(?:(?:il|lo|la|i|gli|le|un|uno|una)\s+|l')", '', text, flags=re.I).strip()


def entity(text: str) -> str:
    value = bare(text).casefold()
    value = re.sub(r"\s*'\s*", "'", value)
    # A typed polity phrase can use the ordinary -iana/-ia inflection.
    # Never strip company/kingdom modifiers or fuzzy-match proper names.
    m = re.fullmatch(r'repubblica ([a-zà-ÿ]+)iana', value)
    if m:
        return m[1] + 'ia'
    return value


@dataclass(frozen=True)
class Proposition:
    predicate: str
    subject: str
    object: str | None = None
    modifiers: tuple[str, ...] = ()
    category: str | None = None
    years: tuple[str, ...] = ()
    tense: str = 'current'
    polarity: str = 'positive'
    certain: bool = True
    location: str | None = None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class QueryAnalysis:
    text: str
    required: Proposition | None
    kind: str

    def to_dict(self):
        return {'text':self.text,'kind':self.kind,
                'required':self.required.to_dict() if self.required else None}


@dataclass(frozen=True)
class GateDecision:
    accepted: bool
    reason: str
    required: Proposition | None
    candidate: Proposition | None

    def to_dict(self):
        return {'decision':'PASS' if self.accepted else 'REJECT','reason':self.reason,
                'required':self.required.to_dict() if self.required else None,
                'candidate':self.candidate.to_dict() if self.candidate else None}


def _time(text):
    """Remove explicitly delimited temporal adjuncts, retaining their values."""
    years = []
    def capture(m):
        years.extend(re.findall(r'\b\d{4}\b', m[0])); return ' '
    result = re.sub(r"\b(?:nel|nell'anno|nell'|per l'anno|per il|per|durante il|dal)\s*(\d{4})(?:\s*(?:al|-)\s*(\d{4}))?\b", capture, text, flags=re.I)
    # Award titles often carry a bare trailing year.
    result = re.sub(r'\s+(\d{4})\s*$', capture, result)
    return normalize(result).strip(' ,'), tuple(years)


def nominal(text, *, title=''):
    """Parse PROPERTY [modifiers] of OWNER; preserve full argument spans."""
    value = bare(text)
    # Honorific award is a different subtype from a polity's capital.
    culture = re.fullmatch(r"capitale\s+([\wà-ÿ]+)\s+della\s+cultura",value,re.I)
    if culture:
        return Proposition('capital_of', entity(culture[1]), modifiers=('culture',))
    if re.match(r"s(?:ua|uo|ue|uoi)\s+",value,re.I):
        m = re.fullmatch(r"s(?:ua|uo|ue|uoi)\s+([\wà-ÿ]+)(?:\s+(.+))?", value, re.I)
        if m and title:
            head=m[1].casefold(); mods=tuple((m[2] or '').casefold().split())
            return _role(head,entity(re.sub(r'^\d+[\s_-]+','',title)),mods)
    head_match = re.fullmatch(r"([\wà-ÿ]+)\s+(.+)", value, re.I)
    if not head_match:
        return None
    head=head_match[1].casefold(); tail=head_match[2]
    prep=re.search(r"(?<!\w)"+_PREP,tail,re.I)
    if prep is None:
        return None
    mods=tuple(tail[:prep.start()].casefold().split())
    owner=entity(tail[prep.end():])
    if not owner or re.search(r'[,;!?]|\b(?:è|era|sono|fu)\b',owner):
        return None
    return _role(head,owner,mods)


def _role(head, owner, mods):
    mapped=tuple(_MODIFIERS.get(x,x) for x in mods)
    if head == 'capitale' and mapped == ('de', 'facto'):
        mapped = ('political', 'de_facto')
    if head=='capitale' and not mapped:
        mapped=('political',)
    return Proposition(_HEADS.get(head,'property_of:'+head),owner,modifiers=mapped)


def _nearest(text):
    m = re.fullmatch(r"(?:il\s+)?([\wà-ÿ]+)\s+(?:più\s+(vicino|prossimo|lontano)|meno\s+(vicino))\s+(?:al|alla|allo|all'|a)\s*(.+)",text,re.I)
    if not m: return None
    degree = 'nearest' if (m[2] or '').casefold() in {'vicino','prossimo'} else 'farthest'
    return Proposition('distance_rank',entity(m[4]),modifiers=(degree,),category=m[1].casefold())


def _context(text):
    m=re.fullmatch(r"(.+),\s*(?:a|in)\s+(.+)",text,re.I)
    return (m[1],entity(m[2])) if m else (text,None)


def analyze_query(query: str) -> QueryAnalysis:
    q=normalize(query).rstrip(' ?!.')
    clean,years=_time(q)
    clean,location_qualifier=_context(clean)
    temporal='past' if re.search(r'\b(?:era|erano|fu|furono)\b',clean,re.I) else 'current'
    result=None
    # Keep definition syntax distinct from "chi ha scritto".
    definition=re.fullmatch(r"(?:chi\s+è|che\s+cos'è|cos'è|che\s+cosa\s+è|che\s+cosa\s+sono)\s+(.+)",clean,re.I)
    if definition:
        result=nominal(definition[1]) or Proposition('definition_of',entity(definition[1]))
        if result.predicate=='authored_by': result=replace(result,tense='event')
    location=re.fullmatch(r"dove\s+(?:si\s+trova(?:no)?|è\s+(?:situat[oa]|localizzat[oa])|sorge)\s+(.+)",clean,re.I)
    if location:
        result=Proposition('located_in',entity(location[1]))
    author=re.fullmatch(r"(?:chi\s+(?:ha\s+scritto|scrisse|è\s+l'autore\s+di)|da\s+chi\s+è\s+stat[oa]\s+scritt[oa])\s+(.+)",clean,re.I)
    if author:
        result=Proposition('authored_by',entity(author[1]),tense='event')
    prop=re.fullmatch(r"qual(?:e|i)?\s+(?:è|sono|era|erano|fu)\s+(.+)",clean,re.I)
    if prop:
        phrase=bare(prop[1])
        result=_nearest(phrase) or nominal(phrase)
        if result is None:
            # "Qual è l'autore della ..." is a voice variant of authorship.
            result=None
        if result and result.predicate=='property_of:autore':
            result=replace(result,predicate='authored_by',tense='event')
    if result is None and '?' in query:
        # Closed proposition questions compare both subject and object.
        result=parse_candidate(clean)
    if result:
        result=replace(result,years=years,location=location_qualifier,tense='event' if result.tense=='event' else temporal)
    interrogative=bool(re.match(r'^(?:chi|che|cos|qual|dove|quando|come|perch)',q,re.I)) or '?' in query
    return QueryAnalysis(query,result,'QUESTION' if result else ('UNRESOLVED' if interrogative else 'SEARCH'))


def _city_role(sentence, title):
    """A bounded coordinated capital role asserted by one explicit city subject.

    Pronunciation markup and population placeholders belong to the other
    descriptive conjunct; they never supply the country/capital answer.
    Unknown clauses, qualifiers, negation and reporting scopes fail closed.
    """
    m = re.fullmatch(r"(.+?)\s+è\s+(?:la\s+)?capitale\s+(.+)", sentence, re.I)
    coordinated = re.fullmatch(r"(.+?)\s+è\s+(un(?:a)?\s+(?:comune|città)\s+.+),\s*nonché\s+capitale\s+(.+)", sentence, re.I)
    federal = re.fullmatch(r"(.+?)\s+è\s+una\s+città\s+federale\s+" + _PREP + r"(.+?)\s*,\s*sede\s+dei\s+suoi\s+organi\s+federali\s+nonché\s+de\s+facto\s+sua\s+capitale", sentence, re.I)
    qualified = federal is not None
    if federal:
        subject, owner = federal.groups()
        owner = 'di ' + owner
    elif coordinated:
        subject, descriptor, owner = coordinated.groups()
        # Only nominal description, never another assertion or scoped claim.
        if re.search(r"[;!?<>={}\[\]\"«»]|\b(?:non|mai|nessun\w*|che|se|quando|secondo|salvo|tranne|eccetto|senza|invece|era|fu|sarà|sono|è|stato|stata|divenne|dice|afferma|sostiene|potrebbe|sarebbe|forse|probabilmente|presunt\w*)\b", descriptor, re.I):
            return None
        if '|' in descriptor and not re.fullmatch(r"[^|]*popolazione\s*\|\s*[a-z]{3}\s+abitanti[^|]*", descriptor, re.I):
            return None
    elif m:
        subject, owner = m.groups()
    else:
        return None
    annotated = re.fullmatch(r"(.+?)\s*\(([^()]*)\)", subject)
    if annotated:
        name, note = annotated.groups()
        note = note.strip()
        # Require an explicitly marked pronunciation annotation and the exact
        # article title; identity/context parentheses are not disposable.
        if (not title or entity(name) != entity(title)
            or not re.match(r"(?:ipa|afi)\s*(?:\||:)", note, re.I)
            or re.search(r"[!?=<>]|\b(?:non|se|che|secondo|era|fu|è|sono|sarebbe|forse|capitale)\b", note, re.I)
            or any(not re.fullmatch(r"[a-zà-ÿ]+\s*\|\s*[^\W\d_]+(?:[ '-][^\W\d_]+)*", part.strip(), re.I) for part in note.split(";")[1:])):
            return None
        subject = name
    elif '(' in subject or ')' in subject:
        return None
    if not re.fullmatch(r"[^\W\d_]+(?:[ '\-][^\W\d_]+)*", bare(subject)):
        return None
    role = nominal('capitale ' + owner)
    if role is None or role.modifiers != ('political',):
        return None
    return replace(role, object=entity(subject),
                   modifiers=("political", "de_facto") if qualified else role.modifiers)


def parse_candidate(sentence: str, *, title: str='') -> Proposition | None:
    if '?' in sentence or re.match(r'\s*(?:se|secondo|ipoteticamente)\b', sentence, re.I):
        return None
    raw=normalize(sentence).strip(' .!?;:')
    # Do not reinterpret quotes, bullet fragments, subordinate clauses or lists
    # as an independently asserted proposition.
    if not raw or raw.startswith(('*','-','«','"')):
        return None
    certain=not bool(_UNCERTAIN.search(raw))
    polarity='negative' if _NEGATIVE.search(raw) else 'positive'
    raw,years=_time(raw)
    city_role = _city_role(raw, title)
    if city_role is not None:
        return replace(city_role, years=years, polarity=polarity, certain=certain)
    raw,location_qualifier=_context(raw)
    raw=re.sub(r'^\s*,\s*','',raw)
    result=None; tense='current'
    # Active / passive authorship preserve the same work/author roles.
    m=re.fullmatch(r'(.+?)\s+(?:ha\s+scritto|scrisse)\s+(.+)',raw,re.I)
    if m:
        result=Proposition('authored_by',entity(m[2]),entity(m[1]));tense='event'
    m=re.fullmatch(r'(.+?)\s+(?:non\s+)?(?:è\s+stat[oa]|fu|venne)\s+scritt[oa]\s+da\s+(.+)',raw,re.I)
    if m:
        result=Proposition('authored_by',entity(m[1]),entity(m[2]));tense='event'
    m=re.fullmatch(r"(.+?)\s+è\s+(?:l'|un\s+)?autore\s+"+_PREP+r'\s*(.+)',raw,re.I)
    if m:
        result=Proposition('authored_by',entity(m[2]),entity(m[1]));tense='event'
    # An explicit location relation; wine/other similarly worded entities never
    # match a mountain just because a descriptive word is shared.
    m=re.fullmatch(r"(.+?)\s+(?:non\s+)?(?:si\s+trova(?:no)?|sorge|è\s+(?:situat[oa]|localizzat[oa]))\s+(.+)",raw,re.I)
    if m:
        result=Proposition('located_in',entity(m[1]),entity(m[2]))
    # Nomination/designation asserts a title for its explicit year. It cannot
    # establish a current unqualified fact.
    m=re.fullmatch(r"(.+?)\s+(?:è\s+stata|è\s+stato|fu|venne)\s+(?:designat[oa]|proclamat[oa]|nominat[oa])\s+(.+)",raw,re.I)
    if m:
        role=nominal(m[2],title=title)
        if role: result=replace(role,object=entity(m[1]));tense='event'
    copula=_COPULA.search(raw)
    if result is None and copula:
        left=raw[:copula.start()];right=raw[copula.end():]
        tense='past' if copula[2].casefold() in {'era','erano','fu','furono'} else ('future' if copula[2].casefold() in {'sarà','saranno'} else 'current')
        lrole=nominal(left,title=title);rrole=nominal(right,title=title)
        lnear=_nearest(bare(left));rnear=_nearest(bare(right))
        if lnear: result=replace(lnear,object=entity(right))
        elif rnear: result=replace(rnear,object=entity(left))
        elif lrole: result=replace(lrole,object=entity(right))
        elif rrole and not re.match(r"^un[ao]?\s+",right,re.I): result=replace(rrole,object=entity(left))
        elif re.match(r"^(?:un[ao]?|il|lo|la|i|le|gli)\s+|^l'",right,re.I):
            result=Proposition('definition_of',entity(left),normalize(right))
    # Definition voice variant, preserving the exact named term.
    m=re.fullmatch(r"(?:il\s+termine\s+)?(.+?)\s+(?:indica|designa|consiste\s+in)\s+(.+)",raw,re.I)
    if result is None and m:
        result=Proposition('definition_of',entity(m[1]),normalize(m[2]))
    if result:
        if result.predicate=='authored_by': tense='event'
        return replace(result,years=years,location=location_qualifier,tense=tense,polarity=polarity,certain=certain)
    return None


def _atomic_argument(value):
    # This grammar accepts noun-phrase arguments, not embedded propositions,
    # conditional/reporting clauses, or unparsed contextual adjuncts.
    if value is None:
        return True
    return not bool(re.search(
        r"[,;!?()|<>=\[\]{}]|\b(?:che|se|quando|qualora|secondo|perché|perche|ma|in|nel|nella|nelle|sotto)\b|\b(?:è|era|sono|fu|sarà)\b",
        value,re.I))


def compatible(required: Proposition | None, candidate: Proposition | None) -> GateDecision:
    def decision(reason,accepted=False): return GateDecision(accepted,reason,required,candidate)
    if required is None: return decision('UNRESOLVED_QUERY_PROPOSITION')
    if candidate is None: return decision('UNRESOLVED_EVIDENCE_PROPOSITION')
    if required.predicate != candidate.predicate: return decision('PREDICATE_MISMATCH')
    if required.modifiers != candidate.modifiers: return decision('MODIFIER_OR_SUBTYPE_MISMATCH')
    if required.category != candidate.category: return decision('CATEGORY_MISMATCH')
    if required.subject != candidate.subject: return decision('SUBJECT_ENTITY_MISMATCH')
    if required.object is not None and required.object != candidate.object: return decision('OBJECT_ENTITY_MISMATCH')
    if not candidate.object: return decision('MISSING_ANSWER_ARGUMENT')
    if not _atomic_argument(candidate.subject): return decision('UNRESOLVED_ARGUMENT_STRUCTURE')
    if candidate.predicate not in {'definition_of','located_in'} and not _atomic_argument(candidate.object):
        return decision('UNRESOLVED_ARGUMENT_STRUCTURE')
    if not candidate.certain: return decision('UNCERTAIN_EVIDENCE')
    if required.polarity != candidate.polarity: return decision('POLARITY_MISMATCH')
    if required.location != candidate.location: return decision('LOCATION_QUALIFIER_MISMATCH')
    if required.years:
        if required.years != candidate.years: return decision('TEMPORAL_QUALIFIER_MISMATCH')
    elif required.tense!='event' and (candidate.years or candidate.tense!=required.tense):
        return decision('TEMPORAL_SCOPE_MISMATCH')
    return decision('COMPATIBLE_PROPOSITION',True)


def evaluate(analysis: QueryAnalysis, text: str, *, title='') -> GateDecision:
    candidate = parse_candidate(text, title=title)
    required = analysis.required
    if (required is not None and candidate is not None
        and required.predicate == 'capital_of' and required.object is None
        and required.modifiers == ('political',)
        and candidate.modifiers == ('political', 'de_facto')):
        gate = compatible(replace(required, modifiers=candidate.modifiers), candidate)
        return replace(gate, required=required, reason='QUALIFIED_DE_FACTO_ANSWER' if gate.accepted else gate.reason)
    return compatible(required, candidate)
