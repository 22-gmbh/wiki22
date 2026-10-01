"""Source-bound study paths: short complete readings, examples and glossary.

Selection and ordering are pedagogical aids, not semantic entailment. No
paraphrase or human language/IQ score is fabricated by this module.
"""
import re
from .knowledge.grounding import sentences
from .knowledge.propositions import entity
from .study_guide import build_guide

SIMPLE=re.compile(r'\b(?:in altre parole|più informalmente|detto in modo|cioè|vale a dire)\b',re.I)
EXAMPLE=re.compile(r'\b(?:ad esempio|per esempio|un esempio|a titolo esemplificativo)\b',re.I)
DEFINITION_HEADING=re.compile(r'^definizion[ei](?:\b|$)',re.I)
DEPENDENT=re.compile(r'^(?:Questo|Questa|Questi|Queste|Esso|Essa|Essi|Esse|Ciò|Tale|Tali|Tuttavia|Inoltre|Pertanto|Quindi)\b',re.I)

def mentions(text,title):
    base=re.sub(r'\s*\([^()]*\)$','',title).strip()
    return bool(base and re.search(r'(?<!\w)'+re.escape(base)+r'(?!\w)',text,re.I))

def lesson_cards(book):
    """Return exact source slices. Conditions remain in the same sentence.

    Marked definitional sections are preferred to history when the grammar has
    no description. A heading is a retrieval clue, never proof of a proposition.
    """
    guide=build_guide(book);paragraphs=book.get('paragraphs',[]);candidates=[]
    definitions={c['paragraph'] for c in guide['claims']}
    for i,p in enumerate(paragraphs):
        heading=bool(DEFINITION_HEADING.search(p['heading']))
        for text,start,end in sentences(p['text']):
            if not 25<=len(text)<=900 or not text.endswith(('.', '!', '?')):continue
            if DEPENDENT.search(text) or not mentions(text,book['title']):continue
            # This rank chooses a source passage, never authorizes an answer.
            simple_rank=2 if re.search(r'\b(?:più informalmente|in altre parole|in parole semplici)\b',text,re.I) else int(bool(SIMPLE.search(text)))
            rank=(simple_rank,int(i in definitions),int(heading),-i,-start)
            candidates.append((rank,dict(kind='starting_point',text=text,paragraph=i,start=start,end=end)))
    cards=[]
    if candidates:
        first=max(candidates,key=lambda x:x[0])[1];cards.append(first)
    elif paragraphs:
        # No invented short definition: the original paragraph stays intact.
        p=paragraphs[0];cards.append(dict(kind='reading',text=p['text'],paragraph=0,start=0,end=len(p['text'])))
    examples=[]
    for i,p in enumerate(paragraphs):
        if EXAMPLE.search(p['text']):
            # A whole paragraph retains an example's referents and restrictions.
            examples.append(dict(kind='example',text=p['text'],paragraph=i,start=0,end=len(p['text'])))
    if examples:cards.append(min(examples,key=lambda c:(len(c['text']),c['paragraph'])))
    for card in cards:
        if paragraphs[card['paragraph']]['text'][card['start']:card['end']]!=card['text']:
            raise ValueError('Lesson slice differs from source')
    return cards

def glossary_links(book,selected_text):
    """Rank existing links by occurrence in the reading, never invent aliases."""
    result=[];seen=set()
    for title in book.get('links',[]):
        base=re.sub(r'\s*\([^()]*\)$','',title).strip()
        key=entity(base)
        if key in seen or key==entity(book['title']) or len(base)<3:continue
        match=re.search(r'(?<!\w)'+re.escape(base)+r'(?!\w)',selected_text,re.I)
        if match:result.append((match.start(),title));seen.add(key)
    return [title for _,title in sorted(result)][:6]

def build_lesson(book,provider,purpose=None):
    cards=lesson_cards(book);glossary=[]
    from .study import StudyEngine,normalized
    engine=StudyEngine(provider)
    selected_cards=cards[:1] if purpose=='step' else [c for c in cards if c['kind']=='example'] if purpose=='example' else cards
    selected=' '.join(c['text'] for c in selected_cards)
    for title in glossary_links(book,selected):
        rows=engine.find(title)
        exact=[r for r in rows if normalized(r['title'])==normalized(title)]
        if len(exact)!=1:continue
        other=engine.open(exact[0]['article_id'])
        if other.get('status')!='READY':continue
        guide=other['guide']
        if not guide['claims'] or guide['conflicts']:continue
        claim=guide['claims'][0]
        if len(claim['text'])>600:continue
        if engine.open(other['article_id'])!=other:raise ValueError('Glossary source changed')
        glossary.append(dict(title=other['title'],article_id=other['article_id'],text=claim['text'],
            paragraph=claim['paragraph'],source=other['paragraphs'][claim['paragraph']],
            revision=other['revision_id'],index_sha256=other['index_sha256']))
        if len(glossary)==3:break
    if engine.open(book['article_id'])!=book:raise ValueError('Lesson source changed')
    return dict(cards=cards,glossary=glossary,model_calls=0,
        interpretation='EXACT_SOURCE_READING_WITH_PEDAGOGICAL_ORDER',language_level=None,human_iq=None)
