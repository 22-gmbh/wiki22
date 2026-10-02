"""Display-only typography and quarantine of obvious canonical extraction debris.

Original note excerpts, contexts, spans and document identity remain untouched.
No paraphrase, grammar inference or invented proper-name capitalization.
"""
import re

DEBRIS=re.compile(r'https?\s*:\s*/\s*/|\bwww\s*\.|(?:\w\s*/\s*){2,}|%\s*20|\b(?:isbn|issn)\s*[\d:]|\b(?:cita\s+(?:web|libro)|urlarchivio|urlmorto|formatnum|thumb)\b|[\[\]{}|=<>]',re.I)
BIBLIO=re.compile(r'\b(?:editore|edizioni|routledge|gremese|op\s*\.\s*cit)\b|\benciclopedia\s+italiana\s+treccani\s+alla\s+voce\b|\b(?:pp?|cap|cit)\s*\.\s*(?:\d+|[ivxlcdm]+)?\s*[).]*$',re.I)
REFERENCE_HEADING=re.compile(r'^(?:bibliografia|note|collegamenti esterni|riferimenti bibliografici)(?:\s|$)',re.I)

def typography(text):
    """Only spacing and sentence-initial case. Never changes words/numbers."""
    out=re.sub(r'\s+([,.;:!?%)])',r'\1',text)
    out=re.sub(r'([(«])\s+',r'\1',out)
    out=re.sub(r'\s+([»])',r'\1',out)
    out=re.sub(r"(?<=\w)\s*(['’])\s*(?=\w)",r'\1',out)
    out=re.sub(r'(?<=\d)\s*-\s*(?=\d)','-',out)
    out=re.sub(r'\b([ad])\s*\.\s*c\s*\.',lambda m:m[1]+'.C.',out,flags=re.I)
    # Sentence-initial capitals only; a lost name spelling cannot be recovered safely.
    m=re.search(r'[A-Za-zÀ-ÖØ-öø-ÿ]',out)
    if m and not out[:m.start()].strip(' «“"('):out=out[:m.start()]+out[m.start()].upper()+out[m.end():]
    return out

def token_key(text):
    return tuple(re.findall(r'\w+|[!?]',text.casefold()))

def canonical_issue(text,heading):
    if DEBRIS.search(text):return 'residuo di estrazione o collegamento'
    if REFERENCE_HEADING.search(heading) or BIBLIO.search(text):return 'riferimento bibliografico'
    if re.match(r'^[,;:\].]|^(?:nd|px|upright|thumb)\b',text,re.I):return 'frammento incompleto'
    return None

def prepare_pages(pages,notes,budget=3600,*,preserve_order=False):
    # Original reading paragraphs take priority over equivalent normalized extracts.
    known={token_key(n['excerpt']) for n in notes if not n.get('canonical_excerpt')}
    groups={};omitted=[];formatted=0
    for page in pages:
        for block in page:
            sentences=[]
            for s in block['sentences']:
                n=notes[s['note']-1];canonical=n.get('canonical_excerpt',False)
                if canonical:
                    reason=canonical_issue(s['text'],block['heading'])
                    key=token_key(s['text'])
                    if key in known:reason='passaggio già presente'
                    if reason:omitted.append(dict(note=s['note'],reason=reason));continue
                    known.add(key);text=typography(s['text']);formatted+=text!=s['text']
                    sentences.append(dict(s,text=text))
                else:
                    text=s['text']
                    if str(n.get('revision_url','')).startswith('https://it.wikipedia.org/') and re.match(r'^(?:e|ma|inoltre|infine|anche)\s',text):
                        text=text[0].upper()+text[1:];formatted+=1
                    sentences.append(dict(s,text=text))
            if not sentences:continue
            heading=re.sub(r'\s*\(parte \d+\)$','',block['heading']) if any(notes[s['note']-1].get('canonical_excerpt') for s in block['sentences']) else block['heading']
            key=(len(groups),heading) if preserve_order else heading
            groups.setdefault(key,[]).append(dict(heading=heading,sentences=sentences))
    output=[[]];toc=[];used=0
    for blocks in groups.values():
        for block in blocks:
            heading=block['heading']
            length=sum(len(s['text']) for s in block['sentences'])
            if preserve_order:
                # Short web paragraphs and headings need space as well as text.
                length+=110+(80 if not output[-1] or output[-1][-1]['heading']!=heading else 0)
            if output[-1] and used+length>budget:output.append([]);used=0
            if not any(t['heading']==heading for t in toc):toc.append(dict(heading=heading,page=len(output)-1))
            output[-1].append(block);used+=length
    return output,toc,dict(omitted=omitted,formatted_sentences=formatted,method='Il testo da leggere esclude residui di collegamenti, riferimenti bibliografici isolati e duplicati riconoscibili. Nei passaggi normalizzati sono regolarizzati spazi e maiuscola iniziale. Le fonti conservano testo e contesto originali; non è una riscrittura linguistica.')
