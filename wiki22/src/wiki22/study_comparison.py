"""Two-source reading comparison, without inferring facts from word overlap."""
import re
from .geography import comparison_body
from .knowledge.propositions import entity
from .study import StudyEngine,normalized

def mentions(text,title):
    needle=normalized(title);hay=normalized(text)
    return re.search(r'(?<!\w)'+re.escape(needle)+r'(?!\w)',hay) is not None

def compare_readings(query,provider):
    body=comparison_body(query)
    if not body or not callable(getattr(provider,'reading_record',None)):return None
    engine=StudyEngine(provider);matches=[]
    for sep in re.finditer(r'\s+e\s+',body,re.I):
        topics=(entity(body[:sep.start()]),entity(body[sep.end():]));books=[]
        for topic in topics:
            choices=engine.find(topic);exact=[r for r in choices if entity(r['title'])==topic]
            if len(exact)!=1:break
            book=engine.open(exact[0]['article_id'])
            if book['status']!='READY':break
            books.append(book)
        if len(books)==2 and books[0]['article_id']!=books[1]['article_id']:matches.append(books)
    if len(matches)!=1:return None
    books=matches[0];lines=['Confronto: '+books[0]['title']+' e '+books[1]['title']];sources=[];seen=set()
    def cite(book,index):
        key=(book['article_id'],index)
        if key not in seen:
            seen.add(key);p=book['paragraphs'][index]
            sources.append(dict(p,article=book['title'],source=book['original_revision_url'],revision=str(book['revision_id'])))
    for book in books:
        guide=book['guide'];claims=guide['claims']
        if claims and not guide['conflicts']:
            lines.extend([book['title']+' · descrizione nella fonte',claims[0]['text']]);cite(book,claims[0]['paragraph'])
    explicit=0
    for book in books:
        for index in book['guide']['passages']['distinction']:
            paragraph=book['paragraphs'][index]
            if all(mentions(paragraph['text'],b['title']) for b in books):
                lines.extend(['Il confronto descritto dalla voce «'+book['title']+'»',paragraph['text']]);cite(book,index);explicit+=1;break
    if not sources:return None
    if not explicit:lines.append('Le descrizioni sono affiancate. Non ho ricostruito una distinzione esplicita tra i due argomenti nei passaggi disponibili.')
    lines.append('Per studiare il confronto, annota la definizione di ciascun termine e le condizioni in cui si applica. Ritrova le affermazioni nei passaggi citati.')
    for book in books:
        if engine.open(book['article_id'])!=book:raise ValueError('A comparison source changed')
    return dict(status='READING',query=query,answer='\n\n'.join(lines),supporting_evidence=sources,
        answer_type='TWO_SOURCE_DOCUMENTARY_COMPARISON',trace=dict(model_calls=0,reflection='BOTH_READING_RECORDS_REREAD',
            compared_articles=[b['article_id'] for b in books],explicit_comparison_passages=explicit,
            semantic_difference_inferred=False))
