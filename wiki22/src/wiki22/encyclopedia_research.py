"""Source-bound encyclopedic reading: whole paragraphs, ordered sections, citations."""
import re
from .title_search import fold
from .encyclopedia_context import bounded_notes

# Editorial selection limits; never truncate a sentence or fabricate connective prose.
SECTION_CHARS = 3800
DOCUMENT_CHARS = 10000
PAGE_CHARS = 4200
REFERENCE_HEADING = re.compile(r'^(?:note|bibliografia|collegamenti esterni|voci correlate|riferimenti bibliografici)(?:\s|$)', re.I)
DEBRIS = re.compile(r'\b(?:formatnum\s*:|thumb\s*\||ISBN\b)|\{\{|\}\}', re.I)


def readable(block):
    text=' '.join(s['text'] for s in block['sentences']).strip()
    # Only obvious extraction/reference debris is rejected; no linguistic truth judgment.
    return bool(text and (text[0].isalnum() or text[0] in '«“"') and not DEBRIS.search(text)
                and not re.search(r'\b(?:pp?|cfr|op\s*\.\s*cit)\s*\.\s*$', text, re.I)
                and not REFERENCE_HEADING.search(block['heading']))


PROFILES = {
    'essential': dict(label='Essenziale',sections=3,section_chars=3800,document_chars=10000,themes=6,per_source=1),
    'extended': dict(label='Estesa',sections=10,section_chars=7500,document_chars=35000,themes=12,per_source=3),
    'deep': dict(label='Approfondita',sections=30,section_chars=16000,document_chars=100000,themes=20,per_source=6),
}


def profile(depth):
    if not isinstance(depth,str) or depth not in PROFILES:raise ValueError('Ampiezza della ricerca non valida.')
    return PROFILES[depth]


def compose_individual(documents, depth='essential'):
    config=profile(depth)
    pools=[bounded_notes(d) for d in documents]
    patterns=[re.compile(r'(?<!\w)'+re.escape(fold(d['title']))+r'(?!\w)') for d in documents]
    sections=[]; omitted=[]
    for di,d in enumerate(documents):
        allowed={n['number'] for n in pools[di]}
        groups={};skipped=0
        for page in d['pages']:
            for b in page:
                if not b['sentences']:continue
                if not all(s['note'] in allowed for s in b['sentences']):continue
                if not readable(b):skipped+=1;continue
                heading=re.sub(r'\s*\(parte \d+\)$', '', b['heading'], flags=re.I)
                groups.setdefault(heading,[]).append(b)
        omitted.append(skipped)
        headings=list(groups)
        if not headings:continue
        # Introduction first, then sections that explicitly mention another selected topic,
        # then an initial substantive section. Keep source order within every section.
        related=sorted(headings[1:],key=lambda h:-sum(bool(patterns[j].search(fold(' '.join(s['text'] for s in b['sentences'])))) for b in groups[h] for j in range(len(documents)) if j!=di))
        chosen=[headings[0]]
        for h in related:
            if any(patterns[j].search(fold(' '.join(s['text'] for b in groups[h] for s in b['sentences']))) for j in range(len(documents)) if j!=di):chosen.append(h)
            if len(chosen)>=config['sections']:break
        for h in headings:
            if len(chosen)>=config['sections']:break
            if h not in chosen:chosen.append(h)
        total=0
        for h in chosen:
            blocks=[];size=0
            for b in groups[h]:
                length=sum(len(s['text']) for s in b['sentences'])
                if size+length>config['section_chars'] or total+length>config['document_chars']:break
                blocks.append(b);size+=length;total+=length
            if blocks:
                label=d['title'] if h==headings[0] else d['title']+' — '+h
                sections.append((label,di,blocks))
    pages=[[]];notes=[];toc=[];size=0;seen_mentions={}
    for heading,di,blocks in sections:
        origin=documents[di];toc.append(dict(heading=heading,page=len(pages)-1))
        previous_original=None
        for b in blocks:
            length=sum(len(s['text']) for s in b['sentences'])
            if pages[-1] and size+length>PAGE_CHARS:pages.append([]);size=0;previous_original=None
            sentences=[]
            for s in b['sentences']:
                n=origin['notes'][s['note']-1];number=len(notes)+1
                notes.append(dict(n,number=number,original_number=n['number'],title=origin['title'],library_name=origin['library_name'],library_id=origin['library_id'],article_id=origin['article_id'],document_source_hash=origin['source_hash']))
                sentences.append(dict(text=s['text'],note=number))
                for j,p in enumerate(patterns):
                    if j!=di and p.search(fold(n['excerpt'])):
                        seen_mentions.setdefault(tuple(sorted((di,j))),set()).add(number)
            # Single-sentence imported blocks may form one paragraph only when contiguous
            # in the original section and from the same source. Never bridge a skipped gap.
            last=pages[-1][-1] if pages[-1] else None
            if (len(sentences)==1 and previous_original is not None
                    and b['sentences'][0]['note']==previous_original+1
                    and last and last['heading']==heading and last['origin']==origin['title']
                    and last['source_heading']==b['heading']
                    and sum(len(s['text']) for s in last['sentences'])+length<=1100):
                last['sentences'].extend(sentences)
            else:pages[-1].append(dict(heading=heading,sentences=sentences,origin=origin['title'],source_heading=b['heading']))
            previous_original=b['sentences'][-1]['note'];size+=length
    if not notes:
        raise ValueError('Non ci sono paragrafi leggibili sufficienti per comporre la ricerca. Apri le voci originali per consultarne i passaggi disponibili.')
    for item in toc:item['page']=next(i for i,p in enumerate(pages) if any(b['heading']==item['heading'] for b in p))
    connections=[dict(left=documents[i]['title'],right=documents[j]['title'],kind='EXPLICIT_TITLE_MENTION',passages=len(nums),notes=sorted(nums)) for (i,j),nums in sorted(seen_mentions.items())]
    return dict(kind='RESEARCH067',title=' · '.join(d['title'] for d in documents),library_name=' + '.join(dict.fromkeys(d['library_name'] for d in documents)),
        documents=[{k:d[k] for k in ['title','library_id','article_id','library_name','source_hash']} for d in documents],
        pages=pages,toc=toc,notes=notes,connections=connections,
        examined=[len(p) for p in pools],available=[len(d['notes']) for d in documents],omitted_blocks=omitted,
        selected=len(notes),complete=False,model_calls=0,
        method='Lettura enciclopedica composta da paragrafi delle voci selezionate, con ordine e attribuzioni della fonte conservati. I richiami tra titoli non provano da soli una relazione storica. La selezione omette apparati bibliografici e frammenti con evidenti residui di estrazione; le voci originali restano consultabili.',
        reading_kind='Ricerca enciclopedica · paragrafi con fonti')


def compose(documents, depth='essential'):
    config=profile(depth)
    if len(documents)==1:result=compose_individual(documents,depth)
    else:
        from .encyclopedia_synthesis import compose_shared
        result=compose_shared(documents,readable,depth)
    result.update(depth=depth,depth_label=config['label'])
    result['coverage']=dict(selected=result['selected'],available=sum(result['available']),examined=sum(result['examined']),
        note='L’ampiezza aumenta i paragrafi selezionabili, non garantisce un numero di pagine. Testi brevi o pochi temi condivisi possono limitare l’estensione. Le voci originali restano consultabili.')
    return result
