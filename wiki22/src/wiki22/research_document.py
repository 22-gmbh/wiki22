"""Deterministic research pages; every sentence has an exact local source span.

Only round-tripped structured propositions may be reworded. Uninterpreted
sentences stay in whole-paragraph context and are visibly documentary excerpts.
"""
from dataclasses import asdict
from hashlib import sha256
from html import escape
import json
import re
from .articles import eligible, render_claim
from .study_guide import read_description, realize_description, build_guide
from .knowledge.propositions import entity


def digest(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def sentence_spans(text):
    """Conservative display segmentation, preserving abbreviation/quote context.

    These are citation units, not authorization of independent propositions.
    No clause is cut to fit a layout. A paragraph is the fallback citation unit.
    """
    start=0;depth=0;quote=False
    abbreviations=re.compile(r'(?:\b(?:ecc|es|ca|circa|sec|prof|dott|sig|art|pag|vol|n|a\.C|d\.C)|\b[A-ZÀ-Ý])\.$',re.I)
    for i,ch in enumerate(text):
        if ch in '([«':depth+=1
        elif ch in ')]»':depth=max(0,depth-1)
        elif ch=='"':quote=not quote
        if ch not in '.!?' or depth or quote or i+1<len(text) and not text[i+1].isspace():continue
        if ch=='.' and (abbreviations.search(text[start:i+1]) or i+1<len(text) and text[i+1]=='.'):continue
        if text[start:i+1].strip():
            left=start+len(text[start:i+1])-len(text[start:i+1].lstrip())
            yield text[left:i+1],left,i+1
        start=i+1
    if text[start:].strip():
        left=start+len(text[start:])-len(text[start:].lstrip());end=len(text.rstrip())
        yield text[left:end],left,end


def reflected_sentence(text,title):
    """Return controlled composition only when independent reparse is identical."""
    prop=eligible(text,title)
    if prop is not None and entity(title) in (prop.subject,entity(prop.object)):
        try:
            output=render_claim(prop,text);check=eligible(output,title)
            if check==prop:return output,'COMPOSED',asdict(prop),'PROPOSITION_REPARSED'
        except ValueError:pass
    desc=read_description(text,title)
    if desc is not None and realize_description(desc)==text:
        return text,'STRUCTURED',asdict(desc),'DESCRIPTION_ROLES_REPARSED_OPAQUE_COMPLEMENT'
    return text,'EXCERPT',None,'EXACT_LOCAL_SPAN_ONLY'


def compose_document(book,*,pages=2):
    if type(pages) is not int or not 1 <= pages <= 12:raise ValueError('Invalid page count')
    paragraphs=book['paragraphs'];guide=build_guide(book)
    if not paragraphs:raise ValueError('No source paragraphs')
    # Prioritize an introduction and distinct source sections. Marker matches
    # affect selection only and never authorize a factual or causal assertion.
    headings={};order=[0]
    for i,p in enumerate(paragraphs):headings.setdefault(p.get('heading',''),i)
    order+=list(headings.values())
    order+=guide['passages']['distinction']+guide['passages']['process']+guide['passages']['cause']
    order+=list(range(len(paragraphs)))
    order=list(dict.fromkeys(order))
    selected=[];size=0;budget=pages*3600
    for i in order:
        length=len(paragraphs[i]['text'])
        if selected and size+length>budget:continue
        selected.append(i);size+=length
        if size>=budget:break
    selected.sort() # Keep source order inside the thematic selection.
    source_hash=digest(book)
    notes=[];blocks=[];counts={'COMPOSED':0,'STRUCTURED':0,'EXCERPT':0}
    conflicts={i for pair in guide['conflicts'] for i in pair}
    # Also quarantine opposite/competing simple propositions anywhere in the
    # article, including paragraphs outside the chosen page budget.
    props=[]
    for i,p in enumerate(paragraphs):
        for text,_,_ in sentence_spans(p['text']):
            prop=eligible(text,book['title'])
            if prop is not None:props.append((i,prop))
    indexed={}
    for i,p in props:
        key=(p.predicate,p.subject,p.modifiers,p.category,p.years,p.tense,p.location)
        for j,q in indexed.get(key,[]):
            functional=p.predicate in {'capital_of','president_of'} or p.predicate.startswith('property_of:')
            if p.object==q.object and p.polarity!=q.polarity or functional and p.polarity==q.polarity=='positive' and p.object!=q.object:
                conflicts.update((i,j))
        indexed.setdefault(key,[]).append((i,p))
    for i in selected:
        paragraph=paragraphs[i];items=[]
        for original,start,end in sentence_spans(paragraph['text']):
            text,kind,prop,reflection=reflected_sentence(original,book['title'])
            if paragraph.get('canonical_excerpt'):text,kind,prop,reflection=original,'EXCERPT',None,'CANONICAL_SPAN_WITH_FULL_CONTEXT'
            if i in conflicts:text,kind,prop,reflection=original,'EXCERPT',None,'CONFLICT_RETAINED_AS_SOURCE_TEXT'
            number=len(notes)+1
            notes.append(dict(number=number,paragraph=i,start=start,end=end,excerpt=original,
                context=paragraph.get('source_context',paragraph['text']),heading=paragraph.get('heading',''),
                article_id=book['article_id'],title=book['title'],
                revision_id=book.get('revision_id'),revision_url=book.get('original_revision_url',''),
                spans=paragraph.get('spans',[]),source_sha256=source_hash))
            items.append(dict(text=text,note=number,kind=kind,proposition=prop,reflection=reflection))
            counts[kind]+=1
        if items:blocks.append(dict(heading=paragraph.get('heading','Testo locale'),paragraph=i,
            conflict=i in conflicts,sentences=items))
    # Allocate intact paragraphs to indicative pages and two balanced columns.
    sheets=[[]]
    for b in blocks:
        length=sum(len(s['text'])+6 for s in b['sentences'])
        current=sum(sum(len(s['text'])+6 for s in x['sentences']) for x in sheets[-1])
        if sheets[-1] and current+length>3600 and len(sheets)<pages:sheets.append([])
        sheets[-1].append(b)
    pages_out=[]
    for sheet in sheets:
        weights=[sum(len(s['text'])+6 for s in b['sentences'])+80 for b in sheet]
        # A single long paragraph is split between columns at sentence boundaries;
        # each continuation keeps its heading and its full-context source notes.
        if len(sheet)==1 and len(sheet[0]['sentences'])>1:
            b=sheet[0];items=b['sentences'];total=sum(len(s['text']) for s in items);used=0;cut=1
            for j,s in enumerate(items[:-1],1):
                used+=len(s['text']);cut=j
                if used>=total/2:break
            cols=[[dict(b,sentences=items[:cut])],[dict(b,sentences=items[cut:],continuation=True)]]
        else:
            cut=min(range(1,len(sheet)+1),key=lambda n:abs(sum(weights[:n])-sum(weights[n:])))
            cols=[sheet[:cut],sheet[cut:]]
        pages_out.append(cols)
    report=dict(schema='wiki22.research.document.v1',title=book['title'],article_id=book['article_id'],
        pages=pages_out,notes=notes,counts=counts,selected_paragraphs=selected,
        available_paragraphs=len(paragraphs),conflicting_paragraphs=sorted(conflicts),
        book_sha256=digest(book),model_calls=0,complete_article=False,
        method='Composizione controllata e lettura documentaria; non è una rassegna esaustiva.',
        limits='Le proposizioni semplici sono rianalizzate; i complementi complessi restano letterali. Le citazioni documentano il testo locale, non certificano la verità storica o scientifica.')
    report['document_sha256']=digest(report)
    verify_document(report,book)
    return report


def verify_document(report,book):
    if digest({k:v for k,v in report.items() if k!='document_sha256'})!=report['document_sha256']:
        raise ValueError('Pagina o note alterate: riapri la voce.')
    if digest(book)!=report['book_sha256']:raise ValueError('Fonte cambiata: riapri la voce.')
    seen=[]
    for page in report['pages']:
        for column in page:
            for block in column:
                for item in block['sentences']:
                    n=report['notes'][item['note']-1];p=book['paragraphs'][n['paragraph']]
                    if n['number']!=item['note'] or n['excerpt']!=p['text'][n['start']:n['end']] or n['context']!=p.get('source_context',p['text']):
                        raise ValueError('Citazione non corrispondente alla fonte.')
                    if (n['excerpt'],n['start'],n['end']) not in list(sentence_spans(p['text'])):
                        raise ValueError('Confine della citazione non riproducibile.')
                    expected=reflected_sentence(n['excerpt'],book['title'])
                    if p.get('canonical_excerpt'):expected=(n['excerpt'],'EXCERPT',None,'CANONICAL_SPAN_WITH_FULL_CONTEXT')
                    if block['conflict']:expected=(n['excerpt'],'EXCERPT',None,'CONFLICT_RETAINED_AS_SOURCE_TEXT')
                    if (item['text'],item['kind'],item['proposition'],item['reflection'])!=expected:
                        raise ValueError('La frase altera il contenuto della fonte.')
                    seen.append(item['note'])
    if sorted(seen)!=list(range(1,len(report['notes'])+1)):raise ValueError('Note mancanti o duplicate.')
    return True


def export_html(report,book):
    verify_document(report,book)
    esc=escape
    chunks=['<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+esc(report['title'])+' · Wiki22</title>',
    '''<style>body{background:#eeeae2;color:#26332e;margin:0;font:17px/1.65 Georgia,serif}.page{box-sizing:border-box;background:#fffdf7;width:210mm;min-height:297mm;max-width:100%;margin:28px auto;padding:18mm;box-shadow:0 4px 25px #0001}h1{font-size:42px;line-height:1.15}h2{font-size:22px;line-height:1.3}small,.meta{font:13px/1.5 sans-serif;color:#526459}.columns{display:grid;grid-template-columns:1fr 1fr;gap:40px}a{color:#17694f}sup{font:11px sans-serif;margin-left:3px}.kind{font:11px sans-serif;letter-spacing:.05em;color:#526459}blockquote{border-left:2px solid #c8d1c4;margin:0;padding-left:14px}li{margin-bottom:20px;overflow-wrap:anywhere}footer{border-top:1px solid #bcc8bb;margin-top:28px;padding-top:15px}@media(max-width:700px){.page{padding:22px}.columns{display:block}h1{font-size:30px}}@page{size:A4;margin:16mm}@media print{body{background:white}.page{width:auto;min-height:0;margin:0;padding:0;box-shadow:none;break-after:page}.page:last-child{break-after:auto}a{color:inherit}h2{break-after:avoid}p,li{orphans:3;widows:3}}</style>''']
    for num,page in enumerate(report['pages'],1):
        chunks.append('<article class="page"><div class="meta">WIKI22 / RICERCA ENCICLOPEDICA · '+str(num)+' / '+str(len(report['pages']))+'</div><h1>'+esc(report['title'])+'</h1><p class="meta">'+esc(report['method'])+'</p><div class="columns">')
        for column in page:
            chunks.append('<section>')
            for b in column:
                chunks.append('<h2>'+esc(b['heading'] or 'Introduzione')+(' · seguito' if b.get('continuation') else '')+'</h2>')
                if b['conflict']:chunks.append('<p class="meta">Disaccordo rilevato: nessuna sintesi di questo passaggio.</p>')
                last=None
                for s in b['sentences']:
                    if s['kind']!=last:
                        if last is not None:chunks.append('</p>')
                        label={'COMPOSED':'SINTESI VERIFICATA','STRUCTURED':'LETTURA STRUTTURATA','EXCERPT':'PASSAGGIO DELLA FONTE'}[s['kind']]
                        chunks.append('<div class="kind">'+label+'</div><p>');last=s['kind']
                    chunks.append(esc(s['text'])+f'<sup><a href="#note-{s["note"]}">[{s["note"]}]</a></sup> ')
                if last is not None:chunks.append('</p>')
            chunks.append('</section>')
        chunks.append('</div><footer class="meta">'+esc(report['limits'])+'</footer></article>')
    chunks.append('<section class="page"><h1>Fonti e contesto</h1><p class="meta">Wikipedia · CC BY-SA · Revisione locale. Ogni nota conserva anche il paragrafo completo.</p><ol>')
    for n in report['notes']:
        url=n['revision_url'];link='<a href="'+esc(url,quote=True)+'">Revisione originale</a>' if url.startswith('https://it.wikipedia.org/') else 'Revisione non disponibile'
        chunks.append(f'<li id="note-{n["number"]}"><strong>'+esc(n['title']+' — '+n['heading'])+'</strong><blockquote>'+esc(n['excerpt'])+'</blockquote><small>'+link+' · '+esc(n['article_id'])+'</small><details><summary>Contesto completo e riferimenti locali</summary><p>'+esc(n['context'])+'</p><pre>'+esc(json.dumps(n['spans'],ensure_ascii=False,indent=2))+'</pre></details></li>')
    chunks.append('</ol></section></html>')
    return ''.join(chunks)
