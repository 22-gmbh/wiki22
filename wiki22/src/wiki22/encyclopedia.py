"""Bounded documentary pages. Literal reading and native synthesis stay distinct."""
from .study import StudyEngine, normalized
from .research_document import compose_document
from .extended_reading import open_extended

def compose_reading(provider, topic, *, pages=2, verification='standard', article_id=None):
    if type(pages) is not int or not 1 <= pages <= 12 or verification not in ('standard','deep'):raise ValueError('Invalid reading configuration')
    engine=StudyEngine(provider)
    choices=engine.find(topic)
    if article_id is not None and article_id not in [r['article_id'] for r in choices]:
        raise ValueError('La voce scelta non appartiene ai risultati correnti.')
    if article_id is None and len(choices)!=1:
        return dict(status='CHOOSE' if choices else 'NOT_FOUND', choices=choices, title=topic)
    book=open_extended(provider,article_id or choices[0]['article_id'])
    if book['status']!='READY':return dict(status='NO_READING', choices=choices, title=choices[0]['title'])
    # Keep whole paragraphs in original order; no sentence/qualification is cut.
    # A screen page is indicative (~2000 chars), not a promise of printed length.
    selected=[];size=0;budget=pages*2000
    for index,p in enumerate(book['paragraphs']):
        if selected and size+len(p['text'])>budget:break
        selected.append(dict(p,index=index));size+=len(p['text'])
    if not selected:raise ValueError('Nessun passaggio leggibile.')
    # Ordinary reading is already authenticated by the reader. Controller reread
    # is mandatory; deep mode adds a separate pass over the same source identity.
    rereads=2 if verification=='deep' else 1
    for _ in range(rereads):
        if open_extended(provider,book['article_id'])!=book:raise ValueError('La fonte è cambiata durante la lettura.')
    sheets=[[]]
    for p in selected:
        if sheets[-1] and sum(len(x['text']) for x in sheets[-1])+len(p['text'])>2000 and len(sheets)<pages:
            sheets.append([])
        sheets[-1].append(p)
    return dict(status='READY',title=book['title'],book=book,pages=sheets,choices=choices,
                document=compose_document(book,pages=pages),
                paragraphs=selected,available=len(book['paragraphs']),rereads=rereads,
                complete_article=False,model_calls=0,
                note='Lettura enciclopedica: passaggi della voce locale, nel loro ordine originale. '
                     'È una selezione documentaria, non una sintesi esaustiva. Testo Wikipedia · CC BY-SA; '
                     'attribuzione e revisione sono consultabili nelle fonti.')
