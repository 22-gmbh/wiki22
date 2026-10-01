"""Bounded source excerpts beyond the eight-paragraph fast reading index.

Canonical normalized text is never presented as a paraphrase or reconstruction
of original typography. Each extract retains its complete evidence context.
"""
import copy,re
from .research_document import sentence_spans
from .study import StudyEngine,normalized

def open_extended(provider,article_id,*,sentence_iterator=sentence_spans):
    book=StudyEngine(provider).open(article_id)
    if book['status']!='READY':return book
    book=copy.deepcopy(book);article=provider.get_article(article_id)
    if article is None or article.article_id!=article_id:raise ValueError('Voce non disponibile')
    prefix=article_id.partition('::')[0]+'::' if '::' in article_id else ''
    prior=[''.join(normalized(p['text']).split()) for p in book['paragraphs']]
    seen=set(prior);added=[];bytes_seen=0;examined=0
    markup=re.compile(r'[|={}<>]|https?://|\b(?:cita web|cita libro|url|thumb|px|jpg|jpeg|png|svg|accesso|archiviato)\b',re.I)
    # A breadth-first section traversal preserves coverage under the work budget.
    sections=list(article.sections);rows=[]
    for index in range(max((len(s.get('evidence',[])) for s in sections),default=0)):
        for section in sections:
            evidence=section.get('evidence',[])
            if index<len(evidence):rows.append((section,evidence[index]))
    for section,item in rows:
        if examined>=128 or bytes_seen>=262144 or len(added)>=160:break
        eid=item['id'];eid=eid if not prefix or eid.startswith(prefix) else prefix+eid
        e=provider.get_evidence(eid)
        if e is None or e.article_id!=article_id or e.text!=item['text'] or e.source!=article.source:raise ValueError('Passaggio esteso non corrisponde alla fonte')
        examined+=1;bytes_seen+=len(e.text.encode())
        for text,lo,hi in sentence_iterator(e.text):
            if len(added)>=160:break
            key=''.join(normalized(text).split())
            if not 90<=len(text)<=1400 or markup.search(text) or key in seen or any(key in p for p in prior):continue
            # Only fully bounded sentences; a truncated evidence tail stays opaque.
            if not text.endswith(('.', '!', '?')):continue
            seen.add(key);added.append(dict(text=text,heading=section.get('title','Testo locale'),
                spans=[dict(evidence_id=eid,start=lo,end=hi)],source=e.source,evidence_id=eid,article_id=article_id,
                canonical_excerpt=True,source_context=e.text,source_revision=e.revision))
    book['paragraphs'].extend(added)
    book['extended_reading']=dict(added=len(added),evidence_examined=examined,bytes_examined=bytes_seen,
        max_evidence=128,max_bytes=262144,max_passages=160,scope='Passaggi nel testo canonico normalizzato; grafia originale non ricostruita.')
    return book
