"""Literal Stato source roles; no country-to-answer table or online lookup."""
import hashlib,json,re,threading,unicodedata
from pathlib import Path
from .knowledge.compact22.format import _tokens
from .knowledge.propositions import analyze_query,entity
from .knowledge.atlas import browse_titles
SCHEMA='wiki22.geo001.source_fields.v1'
PROMOTION='GEO001_LITERAL_STATO_V1'
MAX_BYTES=8*1024*1024
FIELDS={'nomecorrente':'nome corrente','nomecompleto':'nome completo','capitale':'capitale',
        'lingua':'lingue','governo':'forma di governo','valuta':'valuta','continente':'continente','confini':'confini'}
def name_matches(title,value):
    title=' '.join(unicodedata.normalize('NFKC',title).casefold().split())
    value=' '.join(unicodedata.normalize('NFKC',value).casefold().split())
    if value==title:return True
    if not value.startswith(title+' '):return False
    translated=value[len(title)+1:]
    letters=[c for c in translated if unicodedata.category(c).startswith('L')]
    return bool(letters) and all('LATIN' not in unicodedata.name(c,'') for c in letters) and all(unicodedata.category(c)[0] in {'L','M','Z'} for c in translated)

def stamp(p):
    s=p.stat();return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns

def reflect(reader,row):
    from .knowledge.compact_access import article_metadata
    aid=row['article_id'];a=article_metadata(reader,aid) if hasattr(reader,'store') else reader.get_article(aid)
    if a['title']!=row['title'] or not re.fullmatch(r'ITWIKI-\d+',aid):raise ValueError('Geographic article changed')
    if type(row['revision_id']) is not int or row['revision_id']<=0:raise ValueError('Invalid revision')
    if not 1<=len(row['fields'])<=len(FIELDS):raise ValueError('Geographic field bounds')
    result={}
    for name,field in row['fields'].items():
        if name not in FIELDS:raise ValueError('Unknown geographic role')
        if not 1<=len(field['value'])<=1200 or not 1<=len(field['spans'])<=8:raise ValueError('Oversized field')
        spans=[];pieces=[]
        for s in field['spans']:
            e=reader.get_evidence(s['evidence_id']);l=s['start'];r=s['end']
            if e['article_id']!=aid or type(l)is not int or type(r)is not int or not 0<=l<r<=len(e['text']):raise ValueError('Invalid field source')
            if e['source_ref']!='https://it.wikipedia.org/?curid='+aid[7:]:raise ValueError('Invalid original source')
            piece=e['text'][l:r];pieces.append(piece);spans.append(dict(s,text=piece,article_id=aid))
        pair=' '.join(pieces)
        if hashlib.sha256(pair.encode()).hexdigest()!=field['pair_sha256'] or not pair.startswith(name+' = '):raise ValueError('Changed source role')
        words=pair[len(name)+3:].split();positions=field['positions'];previous=-1;selected=[]
        if not positions or len(positions)>1200:raise ValueError('Invalid value projection')
        for i in positions:
            if type(i)is not int or not previous<i<len(words):raise ValueError('Invalid token order')
            selected.append(words[i]);previous=i
        if selected!=list(_tokens(field['value'])):raise ValueError('Value changes source words')
        notes=[]
        if len(field.get('notes',[]))>4:raise ValueError('Geographic note bounds')
        for note in field.get('notes',[]):
            if not 20<=len(note['value'])<=800:raise ValueError('Geographic note size')
            indices=note['positions']
            if not indices or any(type(i)is not int or not 0<=i<len(words) for i in indices) or any(a>=b for a,b in zip(indices,indices[1:])):raise ValueError('Geographic note order')
            if [words[i] for i in indices]!=list(_tokens(note['value'])):raise ValueError('Geographic note changes source')
            notes.append(note['value'])
        result[name]=dict(value=field['value'],spans=spans)
        if notes:result[name]['notes']=notes
    if 'nomecorrente' not in result or not name_matches(a['title'],result['nomecorrente']['value']):raise ValueError('State identity mismatch')
    return dict(article_id=aid,title=a['title'],revision_id=row['revision_id'],fields=result,
        original_revision_url=f"https://it.wikipedia.org/w/index.php?oldid={row['revision_id']}")

class GeographicIndex:
    def __init__(self,path,*,sha256,canonical_sha256,promotion=None,experimental=False):
        if promotion!=PROMOTION and not experimental:raise ValueError('Geographic index not promoted')
        self.path=Path(path).resolve();self.initial_stamp=stamp(self.path);self.lock=threading.RLock()
        if not 1<=self.path.stat().st_size<=MAX_BYTES:raise ValueError('Geographic index budget')
        raw=self.path.read_bytes();self.sha256=hashlib.sha256(raw).hexdigest().upper()
        if self.sha256!=sha256.upper():raise ValueError('Geographic index identity changed')
        data=json.loads(raw)
        if data.get('schema')!=SCHEMA or data.get('canonical_sha256')!=canonical_sha256.upper():raise ValueError('Different geographic corpus')
        rows=data['records']
        if not isinstance(rows,list) or len(rows)>4096:raise ValueError('Geographic record budget')
        self.rows={r['article_id']:r for r in rows}
        if len(self.rows)!=len(rows):raise ValueError('Ambiguous geographic identity')
        self.unchanged()
    def unchanged(self):
        if stamp(self.path)!=self.initial_stamp:raise ValueError('Geographic index changed')
    def read(self,reader,article_id):
        with self.lock:
            self.unchanged();row=self.rows.get(article_id)
            if row is None:return None
            result=reflect(reader,row);self.unchanged();result['index_sha256']=self.sha256
            return result
    def close(self):pass

def question_plan(query):
    if not isinstance(query,str) or len(query)>240 or '\n' in query:return None
    q=' '.join(query.strip().rstrip('?.!').split())
    required=analyze_query(query).required
    if required and required.predicate=='capital_of' and required.object is None and required.modifiers==('political',) and not required.years and required.tense=='current' and required.location is None:
        return dict(topic=required.subject,field='capitale')
    prep=r"(?:dell['’]|d['’]|(?:di|del|della|dello)\s+)"
    patterns=[(r'(?:quale|qual) è la (capitale|valuta|moneta|lingua) '+prep+r'(.+)',None),
        (r'che lingua si parla in (.+)','lingua'),(r'quali lingue si parlano in (.+)','lingua'),
        (r'in quale continente si trova (.+)','continente'),(r'con quali (?:paesi|stati) confina (.+)','confini'),
        (r'qual(?:e)? è la forma di governo '+prep+r'(.+)','governo'),
        (r'qual(?:e)? è il nome completo '+prep+r'(.+)','nomecompleto')]
    for pattern,field in patterns:
        m=re.fullmatch(pattern,q,re.I)
        if m:
            if field is None:field={'moneta':'valuta'}.get(m[1].casefold(),m[1].casefold());topic=m[2]
            else:topic=m[1]
            return dict(topic=re.sub(r"^(?:l['’]|(?:il|lo|la)\s+)",'',topic,flags=re.I),field=field)
    return None

def comparison_body(query):
    if not isinstance(query,str) or len(query)>240 or '\n' in query:return None
    m=re.fullmatch(r'(?:confronta|confrontami|quali differenze ci sono tra|qual è la differenza tra)\s+(.+)',query.strip().rstrip('?.!'),re.I)
    return m[1] if m else None

def answer_comparison(query,provider):
    body=comparison_body(query);getter=getattr(provider,'geographic_record',None)
    if not body or not callable(getter) or not getattr(provider,'supports_geographic_fields',True):return None
    interpretations=[]
    for separator in re.finditer(r'\s+e\s+',body,re.I):
        names=(body[:separator.start()],body[separator.end():]);books=[]
        for name in names:
            rows=browse_titles(provider,entity(name),limit=16);rows=[r for r in rows if entity(r['title'])==entity(name)]
            if len(rows)!=1:break
            book=getter(rows[0]['article_id'])
            if not book:break
            books.append(book)
        if len(books)==2 and books[0]['article_id']!=books[1]['article_id']:interpretations.append(books)
    if len(interpretations)!=1:return None
    books=interpretations[0];fields=[f for f in ('capitale','lingua','governo','continente','valuta') if all(f in b['fields'] for b in books)]
    if not fields:return None
    lines=['Confronto dalle voci locali: '+books[0]['title']+' e '+books[1]['title']];sources=[]
    for name in fields:
        lines.append('\n'+FIELDS[name].capitalize())
        for book in books:
            field=book['fields'][name]
            lines.append('• '+book['title']+': '+field['value'])
            for note in field.get('notes',[]):lines.append('  Nota della fonte: '+note)
            sources.append(dict(article_id=book['article_id'],article_title=book['title'],field=name,text=field['value'],
                source=book['original_revision_url'],revision_id=book['revision_id'],spans=field['spans'],
                evidence_id=field['spans'][0]['evidence_id'],index_sha256=book['index_sha256'],notes=field.get('notes',[])))
    # Different spellings are not proof of different meanings; this comparison
    # places documented values together without asserting semantic equivalence.
    for book in books:
        if getter(book['article_id'])!=book:raise ValueError('Source changed during comparison')
    return dict(status='ANSWERED',query=query,answer='\n'.join(lines),answer_type='GEO001_SOURCE_FIELD_COMPARISON',
        supporting_evidence=sources,trace=dict(compared_articles=[b['article_id'] for b in books],fields=fields,
            reflection='BOTH_SOURCE_RECORDS_REREAD',semantic_difference_inferred=False,model_calls=0))

def answer_geographic(query,provider):
    comparison=answer_comparison(query,provider)
    if comparison is not None:return comparison
    plan=question_plan(query);getter=getattr(provider,'geographic_record',None)
    if plan is None or not callable(getter) or not getattr(provider,'supports_geographic_fields',True):return None
    rows=browse_titles(provider,plan['topic'],limit=16);exact=[r for r in rows if entity(r['title'])==entity(plan['topic'])]
    if len(exact)>1:
        return dict(status='CLARIFY',query=query,answer='Ci sono più voci con questo nome nelle librerie selezionate. Scegli una singola libreria nel selettore Conoscenza.',
            supporting_evidence=[],related_articles=exact,trace=dict(ambiguity='MULTIPLE_SOURCE_ARTICLES',model_calls=0))
    if not exact:return None
    book=getter(exact[0]['article_id'])
    if book is None or plan['field'] not in book['fields']:return None
    field=book['fields'][plan['field']];value=field['value'];title=book['title']
    # Only a single unqualified proper name permits a direct capital sentence.
    simple=plan['field']=='capitale' and bool(re.fullmatch(r"[^\W\d_]+(?:[ '\-][^\W\d_]+)*",value)) and not re.search(r'\b(?:nessuna|non|forse|ignota|sconosciuta|oppure|e)\b',value,re.I)
    qualified=re.fullmatch(r"Nessuna \(de iure\) (.+) \(de facto\)",value,re.I) if plan['field']=='capitale' else None
    if qualified:
        answer=f"Secondo la voce «{title}», {qualified[1]} è la capitale de facto; non è indicata una capitale de iure."
    elif simple:
        answer=f"Secondo la voce «{title}», la capitale è {value}."
    else:
        answer=f"La voce «{title}» riporta — {FIELDS[plan['field']]}: {value}."
    # Independent output parse checks the generated role, value and subject.
    if qualified:
        parsed=re.fullmatch(r"Secondo la voce «(.+)», (.+) è la capitale de facto; non è indicata una capitale de iure\.",answer)
        recovered='Nessuna (de iure) '+parsed[2]+' (de facto)' if parsed else None
    elif simple:
        parsed=re.fullmatch(r"Secondo la voce «(.+)», la capitale è (.+)\.",answer)
        recovered=parsed[2] if parsed else None
    else:
        parsed=re.fullmatch(r"La voce «(.+)» riporta — "+re.escape(FIELDS[plan['field']])+r": (.+)\.",answer)
        recovered=parsed[2] if parsed else None
    if not parsed or parsed[1]!=title or recovered.casefold()!=value.casefold():raise ValueError('Geographic realization changed the source field')
    for note in field.get('notes',[]):answer+='\n\nNota della fonte: '+note
    # Re-read the canonical fields before returning; retrieval is not authority.
    if getter(book['article_id'])!=book:raise ValueError('Geographic source changed during answer')
    source=dict(article_id=book['article_id'],article_title=title,text=value,field=plan['field'],
        source=book['original_revision_url'],revision_id=book['revision_id'],spans=field['spans'],
        evidence_id=field['spans'][0]['evidence_id'],index_sha256=book['index_sha256'],notes=field.get('notes',[]))
    return dict(status='ANSWERED',query=query,answer=answer,answer_type='GEO001_REFLECTED_LITERAL_SOURCE_FIELD',
        supporting_evidence=[source],retrieval=dict(article_id=book['article_id'],title=title),
        trace=dict(geographic_question=plan,reflection='SOURCE_ROLE_AND_LITERAL_TOKENS_REREAD',
                   source_snapshot=True,current_world_verified=False,model_calls=0))
