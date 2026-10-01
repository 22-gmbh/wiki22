"""Bounded Italian study grammar and documentary lesson planning.

A description's subordinate clauses remain literal and opaque. Recognizing
its subject/copula/complement does not license extra inferences from clauses.
No CEFR or human IQ score is inferred from these operations.
"""
from dataclasses import dataclass, asdict
import re
import unicodedata
from .knowledge.grounding import sentences
from .knowledge.propositions import entity

@dataclass(frozen=True)
class Description:
    subject: str
    context: str
    copula: str
    negative: bool
    complement: str

def description_subject(subject,copula):
    base=subject
    if copula.startswith('si ') and base.startswith('Con '):base=base[4:]
    base=re.sub(r', (?:in|nel|nella|nelle|negli) [^,;:.]{1,60},?$', '', base, flags=re.I)
    base=re.sub(r' \([^()]*\)$','',base)
    return base

def read_description(sentence,title):
    if not 20<=len(sentence)<=700 or not sentence.endswith('.'):return None
    if any(c in sentence for c in '{}[]|<>\n\x00'):return None
    # A domain prefix remains attached to the statement; never drop its scope.
    context=''
    prefix=re.match(r'((?:In|Nella|Nel|Nelle|Negli) [^,;:.]{1,60}, )',sentence)
    if prefix:context=prefix[1];sentence=sentence[len(context):]
    # Parenthetical identity/etymology is retained verbatim in the subject.
    match=re.fullmatch(r"(.{1,180}?) (non )?(è|sono|era|erano|fu|furono|indica|indicano|designa|designano|si indica|si indicano|si intende|si intendono) (.+)\.",sentence)
    if not match:return None
    subject=match[1];base=description_subject(subject,match[3])
    title_base=re.sub(r'\s*\([^()]*\)$','',title).strip()
    if entity(base)!=entity(title_base):return None
    complement=match[4]
    if not re.match(r"(?:un[oa]?|il|lo|la|i|gli|le|quel|quella)\s+|(?:un|l)['’]|costituit[oaie] da",complement,re.I):return None
    return Description(match[1],context,match[3],bool(match[2]),complement)

def realize_description(prop):
    result=f"{prop.context}{prop.subject} {'non ' if prop.negative else ''}{prop.copula} {prop.complement}."
    base=description_subject(prop.subject,prop.copula)
    if read_description(result,base)!=prop:raise ValueError('Description realization changes roles')
    return result

MARKERS={
 'process':r'\b(?:inizia|iniziano|avviene|avvengono|fasi|fase|attraverso|per mezzo|consiste|consistono|si divide|si suddivide)\b',
 'distinction':r'\b(?:non va confus[oa]|non vanno confus[ie]|a differenza|distinguendosi|mentre|invece|tuttavia)\b',
 'cause':r'\b(?:perché|poiché|dato che|a causa|dovut[oaie] a|di conseguenza)\b',
}

def build_guide(book):
    paragraphs=book.get('paragraphs',[]);claims=[];seen=set()
    for i,p in enumerate(paragraphs):
        for sentence,start,end in sentences(p['text']):
            prop=read_description(sentence,book['title'])
            if prop is None:continue
            key=(prop.context,prop.copula,prop.negative,prop.complement)
            if key in seen:continue
            seen.add(key);text=realize_description(prop)
            if text!=p['text'][start:end]:raise ValueError('Description does not round-trip its source')
            claims.append(dict(text=text,proposition=asdict(prop),paragraph=i,start=start,end=end,
                reflection='EXACT_SUBJECT_COPULA_COMPLEMENT_REPARSED',subordinate_clauses='LITERAL_NOT_INDEPENDENTLY_INTERPRETED'))
    # Contradictory exact descriptions are exposed as source disagreement.
    conflicts=[]
    for a in claims:
        for b in claims:
            x,y=a['proposition'],b['proposition']
            if x['context']==y['context'] and x['copula']==y['copula'] and x['complement']==y['complement'] and x['negative']!=y['negative']:
                pair=sorted([a['paragraph'],b['paragraph']])
                if pair not in conflicts:conflicts.append(pair)
    grouped={kind:[i for i,p in enumerate(paragraphs) if re.search(pattern,p['text'],re.I)] for kind,pattern in MARKERS.items()}
    return dict(claims=claims,conflicts=conflicts,passages=grouped,model_calls=0)

def choose_passages(book,intent,depth='standard'):
    guide=build_guide(book);count=len(book.get('paragraphs',[]))
    if not count:return [],guide
    # Definition questions must not quietly substitute a historical passage.
    definitions=[c['paragraph'] for c in guide['claims']]
    section_definitions=[i for i,p in enumerate(book['paragraphs']) if re.match(r'^definizion[ei]\b',p['heading'],re.I)]
    first=definitions[0] if definitions else section_definitions[0] if section_definitions else 0
    if intent=='process':order=guide['passages']['process']+[first]
    elif depth=='detail':order=[first]+guide['passages']['cause']+guide['passages']['distinction']+list(range(count))
    else:order=[first]+guide['passages']['distinction']+guide['passages']['process']+list(range(count))
    maximum=1 if intent=='definition' or depth=='step' else 4 if depth=='detail' else 2
    return list(dict.fromkeys(order))[:maximum],guide

PRACTICES={
 'Individua':('Qual è l’informazione principale? Indica le parole del testo che la esprimono.',
              'Trova un termine che non conosci. Cerca il suo significato nei concetti collegati.'),
 'Spiega':('Spiega il passaggio con parole tue, conservando condizioni, negazioni ed eccezioni.',
            'Distingui ciò che il testo dice da ciò che stai deducendo tu. Quale frase sostiene la tua deduzione?'),
 'Valuta':('Quali affermazioni richiederebbero altre fonti? Specifica che cosa dovresti verificare.',
           'Confronta questo passaggio con un’altra voce: le due fonti parlano dello stesso contesto e dello stesso periodo?'),
}

def practice_prompt(mode,paragraph):
    if mode not in PRACTICES:raise ValueError('Unknown reading practice')
    return PRACTICES[mode][0]+'\n'+PRACTICES[mode][1]
