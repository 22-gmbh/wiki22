"""Extractive thematic composition across selected sources; never infer new facts."""
import re
from collections import defaultdict, Counter
from .title_search import fold
from .encyclopedia_context import bounded_notes

STOP=set('a ad ai agli al alla alle allo all altra altre altri altro anche ancora avere aveva avevano alcuni alcuna alcune alcuno cui con che come da dal dalla dalle degli dei del della delle dello di dopo durante e ed era erano essere esso essa essi esse fra gli ha hanno i il in la le lo loro ma nei nel nella nelle nell non o ogni per poi prima primi primo più propria proprie propri proprio quale quali quando quanto questa queste questi questo se si sia sono su sul sulla sulle tra un una uno the and of to is in it as he his those they for from an by which who that this non vi ne ci fu furono viene vengono può possono trova trovano soltanto secondo invece parte parti punto modo molti molte molto meno maggior maggiore maggioranza anni anno secolo secoli fine inizio metà volta volte infatti così senza sempre circa riguardo particolarmente particolari particolare presso attraverso oggi oltre detto detta detti dette stesso stessa stessi stesse no solo soprattutto verso sia perché quindi dove quello quella quelli quelle tale tali tuttavia pur alcuni all dell dall nell sull piu cosi perche epoca generale tema temi argomento frase descrizione testo testi fonte fonti parola parole nome nomi mondo seguito diventato utilizzato noto nota esempio rispettivamente considerato considerata considerati considerano tradizionalmente mentre suoi sue suo sua tutti tutte tutta tutto diverse diversi diverso diversa presenti numerose numerosi insieme cioe pero aver erano grazie grandi grande cosiddetta cosiddetto alcuni alcune ultimi ultimo ultima prime nuove nuovi nuovo nuova antico antica antichi antiche numero giorni giorno genere vita storico storica storici storiche moderna moderno attivita periodo tempo fatto fatti caso casi modo divenne subendo nacque svolge svolto sotto sopra contro dagli dagli nelle nelle negli interno esterno molto poco pochi varie vari variamente trova trovano cio tale cui parte quali quanto quando quello quella qualcosa storia nascita regno famiglia capitolo capitoli altrettanto circa qual nonché significa presentano presenta descrive diventa usato usata usati usare chiama chiamato chiamata chiamati principalmente portato porta iniziato iniziata volta mezzo tale relativi relative relativo stata stato stati state'.split())

# Personal first names alone cannot identify a shared subject (e.g. homonyms).
NAME_ONLY=set('giovanni giuseppe paolo pietro marco luca matteo maria anna francesco carlo luigi antonio andrea alessandro roberto federico enrico william john mary david james michael'.split())
LABELS={'cristian':'Tradizioni cristiane','cattolic':'Tradizioni cattoliche','protestant':'Tradizioni protestanti','roman':'Il mondo romano','religion':'Religioni e comunità'}

def words(text):return re.findall(r'[a-zà-öø-ÿ]+',fold(text))
def stem(w):return w[:-1] if len(w)>5 and w[-1] in 'aeio' else w

def features(text):
    raw=words(text);out={}
    for i,w in enumerate(raw):
        if len(w)<4 or w in STOP:continue
        out[(stem(w),)]=w
        if i+1<len(raw) and len(raw[i+1])>=4 and raw[i+1] not in STOP:
            out[(stem(w),stem(raw[i+1]))]=w+' '+raw[i+1]
    return out


def compose_shared(documents,readable,depth='essential'):
    from .encyclopedia_research import profile
    config=profile(depth)
    units=[];omitted=[];examined=[];forms=defaultdict(Counter)
    for di,d in enumerate(documents):
        pool=bounded_notes(d);examined.append(len(pool));allowed={n['number'] for n in pool};bad=0
        for page in d['pages']:
            for b in page:
                if not b['sentences'] or not all(s['note'] in allowed for s in b['sentences']):continue
                if not readable(b):bad+=1;continue
                text=' '.join(s['text'] for s in b['sentences'])
                if (len(text)>5000 or not text[0].isalpha() or '*' in text or re.search(r'(?:\bn\s*\.|[:;]|\bit\s*/.*)\s*$',text,re.I)):
                    bad+=1;continue
                feats=features(text)
                for k,v in feats.items():forms[k][v]+=1
                units.append(dict(di=di,block=b,text=text,features=set(feats),heading_features=set(features(b['heading'])),key=(di,tuple(s['note'] for s in b['sentences']))))
        omitted.append(bad)
    matches=defaultdict(list)
    for i,u in enumerate(units):
        for k in u['features']:matches[k].append(i)
    titles={tuple(stem(w) for w in words(d['title'])) for d in documents}
    candidates=[]
    for k,indices in matches.items():
        origins={units[i]['di'] for i in indices}
        if len(origins)<2 or k in titles or (len(k)==1 and any(k[0]==stem(n) for n in NAME_ONLY)):continue
        # A heading match in several entries gives a better topic than a frequent word.
        heading_origins={units[i]['di'] for i in indices if k in units[i]['heading_features']}
        score=100*len(origins)+24*len(heading_origins)+12*(len(k)-1)+min(len(indices),15)
        candidates.append((score,k,indices))
    candidates.sort(key=lambda x:(-x[0],x[1]))
    refined=[]
    for score,k,indices in candidates[:80]:
        # A shared first name or a generic word alone cannot connect two passages.
        buckets=defaultdict(list)
        for i in indices:
            if len(buckets[units[i]['di']])<16:buckets[units[i]['di']].append(i)
        shortlist=[i for bucket in buckets.values() for i in bucket];edges=defaultdict(set)
        for offset,i in enumerate(shortlist):
            for j in shortlist[offset+1:]:
                if units[i]['di']==units[j]['di']:continue
                shared=units[i]['features'] & units[j]['features']
                if any(len(f)==2 for f in shared) or sum(len(f)==1 for f in shared)>=3:
                    edges[i].add(j);edges[j].add(i)
        remaining=set(edges);components=[]
        while remaining:
            todo=[min(remaining)];component=set()
            while todo:
                i=todo.pop()
                if i in component:continue
                component.add(i);todo.extend(edges[i]-component)
            remaining-=component;components.append(component)
        if not components:continue
        component=max(components,key=lambda c:(len({units[i]['di'] for i in c}),len(c),-min(c)))
        origins={units[i]['di'] for i in component}
        if len(origins)<2:continue
        heading_origins={units[i]['di'] for i in component if k in units[i]['heading_features']}
        refined.append((100*len(origins)+24*len(heading_origins)+12*(len(k)-1)+min(len(component),15),k,sorted(component),edges))
    refined.sort(key=lambda x:(-x[0],x[1]))
    selected=[];used=set();covered=set();selected_terms=[]
    for score,k,indices,edges in refined:
        if len(selected)>=config['themes']:break
        if any(set(k)<=set(t) or set(t)<=set(k) for t in selected_terms):continue
        options=defaultdict(list)
        for i in indices:
            u=units[i]
            if u['key'] in used:continue
            # Avoid isolated continuation pronouns without their antecedent.
            if re.match(r'^(?:egli|essi|esse|questi|queste|questo|questa|li|lo|ne|ciò|cio|tale|tali|i primi|le prime)\b',u['text'],re.I):continue
            options[u['di']].append(i)
        if len(options)<2:continue
        chosen=[]
        for di,opts in options.items():
            name=fold(documents[di]['title']);root=name[:-1] if len(name)>5 and name[-1] in 'aeio' else name
            opts.sort(key=lambda i:(-int(any(w.startswith(root) for w in words(units[i]['text'])) if len(root)>=4 else name in fold(units[i]['text'])),-len({units[j]['di'] for j in edges[i]}),-int(units[i]['text'][0].isupper()),-int(k in units[i]['heading_features']),len(units[i]['text']),units[i]['block']['sentences'][0]['note']))
            chosen.append(opts[0])
        # Put a new contributing source into the conversation early.
        ranks={i:rank for opts in options.values() for rank,i in enumerate(opts)}
        chosen.sort(key=lambda i:(ranks[i],units[i]['di'] in covered,units[i]['di']))
        for i in chosen:used.add(units[i]['key']);covered.add(units[i]['di'])
        label=LABELS.get(k[0],forms[k].most_common(1)[0][0]) if len(k)==1 else forms[k].most_common(1)[0][0];label=label[:1].upper()+label[1:]
        selected.append((label,k,chosen));selected_terms.append(k)
    # Enlarge established themes after choosing their anchors. This retains the
    # essential passages and avoids consuming another theme's anchors too early.
    if config['per_source']>1:
        expanded=[]
        for label,k,anchors in selected:
            counts=Counter(units[i]['di'] for i in anchors);extra=[]
            for i in matches[k]:
                u=units[i]
                if u['key'] in used or counts[u['di']]>=config['per_source']:continue
                if re.match(r'^(?:egli|essi|esse|questi|queste|questo|questa|li|lo|ne|ciò|cio|tale|tali)\b',u['text'],re.I):continue
                supported=False
                for j in anchors:
                    if units[j]['di']==u['di']:continue
                    shared=u['features'] & units[j]['features']
                    if any(len(f)==2 for f in shared) or sum(len(f)==1 for f in shared)>=3:supported=True;break
                if supported:
                    extra.append(i);used.add(u['key']);covered.add(u['di']);counts[u['di']]+=1
            expanded.append((label,k,anchors+extra))
        selected=expanded
    # Keep separate evidence when no trustworthy shared textual topic is available.
    if not selected:
        from .encyclopedia_research import compose_individual
        fallback=compose_individual(documents,depth)
        fallback.update(themes=[],unconnected=[d['title'] for d in documents],
            overview='Non emergono temi condivisi sufficienti nei passaggi disponibili. Le fonti restano distinte: non viene inventato un collegamento.')
        return fallback
    pages=[[]];notes=[];toc=[];themes=[];size=0;mentions=defaultdict(set)
    patterns=[re.compile(r'(?<!\w)'+re.escape(fold(d['title']))+r'(?!\w)') for d in documents]
    for label,k,indices in selected:
        toc.append(dict(heading=label,page=len(pages)-1));contributing=[]
        for i in indices:
            u=units[i];di=u['di'];d=documents[di];contributing.append(di);sentences=[]
            for item in u['block']['sentences']:
                old=d['notes'][item['note']-1];n=len(notes)+1
                notes.append(dict(old,number=n,original_number=old['number'],title=d['title'],library_name=d['library_name'],library_id=d['library_id'],article_id=d['article_id'],document_source_hash=d['source_hash']))
                sentences.append(dict(text=item['text'],note=n))
                for j,pattern in enumerate(patterns):
                    if j!=di and pattern.search(fold(old['excerpt'])):mentions[tuple(sorted((di,j)))].add(n)
            length=len(u['text'])
            if pages[-1] and size+length>4200:pages.append([]);size=0
            previous=pages[-1][-1] if pages[-1] else None
            # Combine complete source paragraphs into a thematic paragraph, with citations
            # at every sentence. No fabricated causal/temporal connector is introduced.
            if previous and previous['heading']==label and sum(len(s['text']) for s in previous['sentences'])+length<2400:
                previous['sentences'].extend(sentences);previous['origins'].append(d['title']);previous['origin']=' · '.join(previous['origins'])
            else:pages[-1].append(dict(heading=label,sentences=sentences,origins=[d['title']],origin=d['title']))
            size+=length
        if k:themes.append(dict(heading=label,anchor=forms[k].most_common(1)[0][0],documents=[documents[di]['title'] for di in dict.fromkeys(contributing)],kind='SHARED_TEXT_TOPIC'))
    for t in toc:t['page']=next(i for i,p in enumerate(pages) if any(b['heading']==t['heading'] for b in p))
    missing=[d['title'] for di,d in enumerate(documents) if di not in covered]
    return dict(kind='SYNTHESIS069',title=' · '.join(d['title'] for d in documents),library_name=' + '.join(dict.fromkeys(d['library_name'] for d in documents)),
        documents=[{k:d[k] for k in ['title','library_id','article_id','library_name','source_hash']} for d in documents],pages=pages,notes=notes,toc=toc,themes=themes,unconnected=missing,
        connections=[dict(left=documents[i]['title'],right=documents[j]['title'],kind='EXPLICIT_TITLE_MENTION',passages=len(ns),notes=sorted(ns)) for (i,j),ns in sorted(mentions.items())],
        examined=examined,available=[len(d['notes']) for d in documents],omitted_blocks=omitted,selected=len(notes),complete=False,model_calls=0,
        method='Composizione per temi condivisi: paragrafi di più voci entrano nella stessa trattazione con citazioni per ogni frase. I temi derivano da termini comuni nei testi e non provano da soli relazioni storiche o accordo fra fonti. Le parole delle fonti, comprese negazioni e attribuzioni, sono conservate; non vengono inventate spiegazioni o collegamenti.',
        reading_kind='Ricerca enciclopedica unificata · temi e fonti',
        overview='La ricerca mette in dialogo le fonti attraverso questi temi: '+', '.join(t['heading'].lower() for t in themes)+'.' if themes else 'Nei passaggi disponibili non emergono temi condivisi sufficienti. È mostrato un quadro delle fonti, senza inventare collegamenti.')
