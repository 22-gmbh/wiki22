"""MEMIDX001 EXP001: evidence-bound, regenerable per-library graph indexes.

This module has no model/network client and never writes canonical evidence.
The semantic extractor is versioned; future learned assertions must enter via
the same evidence-reference contract rather than replacing stored sources.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import re
import zlib

from wiki22.knowledge.compact22 import TwentyTwoCKReader
from wiki22.knowledge.propositions import parse_candidate, entity
from wiki22.knowledge.grounding import sentences

VERSION='MEMIDX001-EXP001.1'
MAGIC=b'MEMIDX01'
KINDS=('CATEGORIA','TEMA','ENTITÀ','RELAZIONE','TEMPO','FONTE','PROPOSIZIONE')
TYPES={'persona':'PERSONA','luogo':'LUOGO','città':'CITTÀ','paese':'PAESE',
       'organizzazione':'ORGANIZZAZIONE','opera':'OPERA','evento':'EVENTO',
       'data':'DATA','concetto':'CONCETTO'}
STOP={'della','delle','dello','degli','dell','dalla','dalle','nella','nelle','sono','come',
      'anche','questo','questa','categoria','categorie','introduzione','sezione','dati','testo'}
MAX_DERIVED_BYTES=65536
MAX_DECODED_BYTES=4*1024*1024


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest().upper()
def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest().upper()


class CanonicalLibrary:
    def __init__(self,path):
        self.path=Path(path).resolve();self.reader=TwentyTwoCKReader(self.path)
        self.library_id=self.reader.manifest['library_id'];self.name=self.reader.manifest['library_name']
        self.sha256=file_hash(self.path);self.read_articles=[]
    def articles(self):
        yield from self.reader.iter_articles()
    def article(self,ident):
        self.read_articles.append(ident);return self.reader.get_article(ident)
    def evidence(self,ident):return self.reader.get_evidence(ident)
    def close(self):self.reader.close()


def metadata_fingerprint(article):
    return digest([article[k] for k in ('article_id','title','source_ref','locale')])


class DeterministicExtractor:
    """Strict Italian evidence patterns. Unknowns remain explicit unknowns."""
    version=VERSION

    def extract(self,article):
        records=[]
        for evidence in article['evidence']:
            features={};edges=set();eid=evidence['evidence_id'];text=evidence['text']
            def add(kind,key,label=None,**attrs):
                token=(kind,str(key));entry=[kind,str(key),label or str(key),attrs]
                # Multiple observations in one evidence record remain explicit.
                if token in features:
                    previous=features[token][3]
                    for k,v in attrs.items():
                        if k in previous and previous[k]!=v:
                            previous[k]=sorted(set((previous[k] if isinstance(previous[k],list) else [previous[k]])+(v if isinstance(v,list) else [v])))
                        else:previous[k]=v
                else:features[token]=entry
                return token
            def connect(a,b,role):edges.add((a,b,role))
            def ent(name,kind='SCONOSCIUTO',**attrs):
                return add('ENTITÀ',entity(name),entity(name),entity_type=kind,**attrs)
            # Source metadata is itself part of the canonical 22CK record.
            source_nodes=[]
            for level,value in [('libreria',evidence['library_id']),('documento',article['source_ref']),
                 ('articolo',article['article_id']),('sezione',article['article_id']+'/'+evidence['section_id']),('evidenza',eid)]:
                source_nodes.append(add('FONTE',level+':'+value,value,level=level,rule='METADATI_CANONICI'))
            for a,b in zip(source_nodes,source_nodes[1:]):connect(a,b,'contiene')
            heading=evidence['section_title']
            match=re.fullmatch(r'Categorie?:\s*(.+)',heading,re.I)
            if match:
                for branch in match[1].split(';'):
                    parts=[x.strip() for x in branch.split('>') if x.strip()];previous=None
                    for i,label in enumerate(parts):
                        node=add('CATEGORIA','/'.join(parts[:i+1]),label,rule='CATEGORIA_ESPLICITA_NEL_TITOLO')
                        if previous:connect(previous,node,'sottocategoria')
                        previous=node
            else:add('CATEGORIA','UNKNOWN_CATEGORY','Categoria non determinata',rule='NESSUNA_CATEGORIA_ESPLICITA')
            words=re.findall(r"[a-zà-ÿ]{4,}",(article['title']+' '+heading+' '+text).casefold())
            frequencies=Counter(w for w in words if w not in STOP)
            title_words=set(re.findall(r'[a-zà-ÿ]{4,}',article['title'].casefold()))
            themes=sorted((w for w,n in frequencies.items() if n>=2 or w in title_words),key=lambda w:(-frequencies[w],w))[:6]
            for word in themes:add('TEMA',word,word,rule='TERMINE_OSSERVATO',frequency=frequencies[word])
            ent(article['title'])
            for sentence,start,end in sentences(text):
                typed=re.match(r"^(.+?)\s+è\s+(?:un[ao]?\s+|un['’])([\wà-ÿ]+)\b",sentence,re.I)
                if typed and typed[2] in TYPES:ent(typed[1],TYPES[typed[2]])
                prop=parse_candidate(sentence)
                # Additional explicit relations, with no fuzzy predicate match.
                extra=re.fullmatch(r'(.+?)\s+(nacque\s+a|è\s+parte\s+di|è\s+membro\s+di)\s+(.+?)(?:\s+nel\s+(\d{4}))?[ .]*',sentence,re.I)
                attrs=None
                if extra:
                    predicate={'nacque a':'nato_a','è parte di':'parte_di','è membro di':'membro_di'}[extra[2].casefold()]
                    attrs={'predicate':predicate,'subject':entity(extra[1]),'object':entity(extra[3]),'modifiers':[],
                        'years':[extra[4]] if extra[4] else [],'tense':'past' if predicate=='nato_a' else 'current','polarity':'negative' if re.search(r'\b(?:non|mai|nessuno)\b',sentence) else 'positive','certain':not bool(re.search(r'\b(?:forse|probabilmente|presumibilmente|potrebbe|sarebbe)\b',sentence)),'location':None,'category':None}
                elif prop:
                    attrs=asdict(prop)
                    if prop.predicate in {'capital_of','authored_by'}:
                        attrs['predicate']={'capital_of':'capitale_di','authored_by':'autore_di'}[prop.predicate]
                        attrs['subject'],attrs['object']=prop.object,prop.subject
                    elif prop.predicate=='located_in':attrs['predicate']='situato_in'
                alias=re.fullmatch(r'(.+?)\s+è\s+anche\s+chiamat[oa]\s+(.+?)[ .]*',sentence,re.I)
                if alias:ent(alias[1],aliases=[entity(alias[2])])
                if attrs and attrs.get('object'):
                    subject=ent(attrs['subject']);obj=ent(attrs['object'])
                    if attrs['predicate']=='definition_of':
                        m=re.match(r"^(?:un[ao]?\s+|una?['’])([\wà-ÿ]+)\b",attrs['object'],re.I)
                        if m and m[1] in TYPES:subject=ent(attrs['subject'],TYPES[m[1]])
                    relation=add('RELAZIONE',attrs['predicate'],attrs['predicate'],rule='PREDICATO_ESPLICITO')
                    key=digest([attrs,start,end])[:32]
                    label=f"{attrs['subject']} — {attrs['predicate']} — {attrs['object']}"
                    node=add('PROPOSIZIONE',key,label,proposition=attrs,span=[start,end],rule='GRAMMATICA_ESPLICITA')
                    connect(relation,node,'proposizione');connect(subject,node,'soggetto');connect(obj,node,'oggetto')
                    connect(subject,obj,attrs['predicate']);connect(node,source_nodes[-1],'evidenza')
                    state=add('TEMPO','stato:'+attrs['tense'],{'current':'Presente grammaticale','past':'Passato','event':'Evento','future':'Futuro'}.get(attrs['tense'],attrs['tense']),rule='TEMPO_VERBALE')
                    connect(node,state,'tempo')
                    for year in attrs['years']:
                        time_node=add('TEMPO','anno:'+year,year,rule='ANNO_ESPLICITO');ent(year,'DATA');connect(node,time_node,'tempo')
                for m in re.finditer(r'\b(?:nel|anno|dal|al)\s+(\d{4})\b',sentence,re.I):
                    add('TEMPO','anno:'+m[1],m[1],rule='ANNO_ESPLICITO');ent(m[1],'DATA')
                for m in re.finditer(r'\b(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})\b',sentence,re.I):
                    add('TEMPO','data:'+m[1],m[1],rule='DATA_ESPLICITA');ent(m[1],'DATA')
                for m in re.finditer(r'\bdal\s+(\d{4})\s+al\s+(\d{4})\b',sentence,re.I):
                    add('TEMPO',f'intervallo:{m[1]}:{m[2]}',m[1]+'–'+m[2],start=m[1],end=m[2],rule='INTERVALLO_ESPLICITO')
                for m in re.finditer(r'\b([ivxlcdm]+)\s+secolo\b',sentence,re.I):
                    add('TEMPO','secolo:'+m[1].upper(),m[1].upper()+' secolo',rule='SECOLO_ESPLICITO')
            records.append({'evidence_id':eid,'content_sha256':digest([evidence['text'],evidence['section_id'],evidence['section_title']]),'features':sorted(features.values()),'edges':sorted(edges)})
        return {'article':[article['article_id'],article['title'],article['source_ref'],metadata_fingerprint(article)],'records':records}


class MemIndex:
    def __init__(self,library_id,name,source_sha,documents,extractor_version=VERSION):
        self.library_id=library_id;self.name=name;self.source_sha=source_sha;self.documents=documents;self.version=extractor_version
        self._graph()

    @classmethod
    def build(cls,source,extractor=None):
        extractor=extractor or DeterministicExtractor()
        return cls(source.library_id,source.name,source.sha256,{a['article_id']:extractor.extract(a) for a in source.articles()},extractor.version)

    def _graph(self):
        self.nodes={};self.records={};self.edges=set();self.node_members=defaultdict(set)
        for aid,doc in sorted(self.documents.items()):
            for record in doc['records']:
                rid=self.library_id+':MEM:'+record['evidence_id'];self.records[rid]=(aid,record)
                for kind,key,label,attrs in record['features']:
                    nid=self.node_id(kind,key)
                    node=self.nodes.setdefault(nid,{'id':nid,'library_id':self.library_id,'type':kind,'key':key,'label':label,'observations':[]})
                    node['observations'].append({'mem_ref':rid,**attrs});self.node_members[nid].add(rid)
                for a,b,role in record['edges']:self.edges.add((self.node_id(*a),self.node_id(*b),role,rid))

    def node_id(self,kind,key):return self.library_id+':'+kind+':'+digest([kind,key])[:24]
    def nodes_of(self,kind):return sorted((n for n in self.nodes.values() if n['type']==kind),key=lambda n:(n['label'].casefold(),n['id']))
    def list_categories(self):return self.nodes_of('CATEGORIA')
    def list_topics(self):return self.nodes_of('TEMA')
    def children(self,nid):return [self.nodes[b] for a,b,role,_ in sorted(self.edges) if a==nid and role=='sottocategoria']
    def articles_for_node(self,nid):return sorted({self.records[rid][0] for rid in self.node_members[nid]})
    def entities_by_type(self,kind):return [n for n in self.nodes_of('ENTITÀ') if self.entity_type(n['id'])==kind]
    def entity_type(self,nid):
        observed=set()
        for row in self.nodes[nid]['observations']:
            value=row.get('entity_type','SCONOSCIUTO');observed.update(value if isinstance(value,list) else [value])
        observed.discard('SCONOSCIUTO')
        return next(iter(observed)) if len(observed)==1 else 'SCONOSCIUTO'
    def get_entity(self,nid):
        n=self.nodes[nid]
        if n['type']!='ENTITÀ':raise KeyError(nid)
        return dict(n,entity_type=self.entity_type(nid),aliases=sorted({a for x in n['observations'] for a in x.get('aliases',[])}))
    def related_entities(self,nid):
        refs={b for a,b,_,_ in self.edges if a==nid and self.nodes[b]['type']=='ENTITÀ'}|{a for a,b,_,_ in self.edges if b==nid and self.nodes[a]['type']=='ENTITÀ'}
        return [self.get_entity(x) for x in sorted(refs)]
    def propositions_for_entity(self,nid):return [self.nodes[b] for a,b,role,_ in sorted(self.edges) if a==nid and role in {'soggetto','oggetto'}]
    def relations_for_entity(self,nid):
        props={x['id'] for x in self.propositions_for_entity(nid)}
        return [self.nodes[a] for a,b,role,_ in sorted(self.edges) if b in props and role=='proposizione']
    def timeline(self):return self.nodes_of('TEMPO')
    def sources_for_entity(self,nid):
        mems=self.node_members[nid]
        return [n for n in self.nodes_of('FONTE') if self.node_members[n['id']]&mems]
    def propositions(self,**filters):
        result=[]
        for node in self.nodes_of('PROPOSIZIONE'):
            for observation in node['observations']:
                prop=observation['proposition']
                if all((v in prop.get('years',[]) if k=='time' else v in prop.get('modifiers',[]) if k=='qualifier' else observation['mem_ref'].endswith(v) if k=='evidence' else v in (prop['subject'],prop['object']) if k=='entity' else prop.get(k)==v) for k,v in filters.items()):
                    result.append(node);break
        return result

    def evidence_for_node(self,nid,source):
        if nid not in self.nodes:raise KeyError(nid)
        if source.library_id!=self.library_id or source.sha256!=self.source_sha:raise ValueError('MEM index/canonical library identity mismatch')
        rows=[]
        for rid in sorted(self.node_members[nid]):
            aid,record=self.records[rid];evidence=source.evidence(record['evidence_id'])
            if evidence['article_id']!=aid or digest([evidence['text'],evidence['section_id'],evidence['section_title']])!=record['content_sha256']:raise ValueError('stale MEM evidence binding')
            expected=self.documents[aid]['article']
            if evidence['title']!=expected[1] or evidence['source_ref']!=expected[2]:raise ValueError('stale MEM article metadata')
            rows.append(dict(evidence,mem_record_id=rid,index_node_id=nid,library_id=self.library_id))
        return rows

    def update(self,new_source,changed=(),removed=(),extractor=None):
        if new_source.library_id!=self.library_id:raise ValueError('cross-library incremental update forbidden')
        extractor=extractor or DeterministicExtractor()
        if extractor.version!=self.version:raise ValueError('extractor version changed: explicit reindex required')
        docs=dict(self.documents)
        for aid in removed:docs.pop(aid,None)
        for aid in changed:docs[aid]=extractor.extract(new_source.article(aid))
        return MemIndex(self.library_id,new_source.name,new_source.sha256,docs,self.version)

    def wire(self):
        keys=sorted({(f[0],f[1],f[2]) for d in self.documents.values() for r in d['records'] for f in r['features']})
        positions={(k,key):i for i,(k,key,label) in enumerate(keys)}
        nodes=[[KINDS.index(k),key,None if key==label else label] for k,key,label in keys]
        docs=[]
        for aid,doc in sorted(self.documents.items()):
            records=[]
            for r in sorted(doc['records'],key=lambda r:r['evidence_id']):
                bindings=sorted([[positions[k,key],attrs] for k,key,label,attrs in r['features']])
                edges=sorted([[positions[tuple(a)],positions[tuple(b)],role] for a,b,role in r['edges']])
                records.append([r['evidence_id'],r['content_sha256'],bindings,edges])
            docs.append([doc['article'],records])
        return [self.version,self.library_id,self.name,self.source_sha,nodes,docs]

    @property
    def identity(self):return digest(self.wire())
    def save(self,path,max_bytes=MAX_DERIVED_BYTES):
        path=Path(path)
        if path.suffix!='.memidx':raise ValueError('derived index extension required')
        raw=canonical(self.wire());blob=MAGIC+hashlib.sha256(raw).digest()+zlib.compress(raw,9)
        if len(blob)>max_bytes:raise ValueError('MEM derived-index storage budget exceeded')
        path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.memidx.tmp');temp.write_bytes(blob);temp.replace(path)
        return {'library_id':self.library_id,'index_version':self.version,'build_id':self.identity,'bytes':len(blob),'source_sha256':self.source_sha,'artifact_sha256':file_hash(path)}
    @classmethod
    def load(cls,path):
        blob=Path(path).read_bytes()
        if len(blob)>MAX_DERIVED_BYTES or blob[:8]!=MAGIC:raise ValueError('invalid MEM index header or size')
        d=zlib.decompressobj();raw=d.decompress(blob[40:],MAX_DECODED_BYTES+1)
        if not d.eof or d.unconsumed_tail or d.unused_data or len(raw)>MAX_DECODED_BYTES or hashlib.sha256(raw).digest()!=blob[8:40]:raise ValueError('MEM index integrity failure')
        version,library,name,sha,nodes,docs=json.loads(raw)
        if version!=VERSION:raise ValueError('unsupported MEM index version')
        documents={}
        for article,records in docs:
            unpacked=[]
            for eid,blockhash,bindings,edges in records:
                features=[[KINDS[nodes[n][0]],nodes[n][1],nodes[n][2] or nodes[n][1],attrs] for n,attrs in bindings]
                links=[((KINDS[nodes[a][0]],nodes[a][1]),(KINDS[nodes[b][0]],nodes[b][1]),role) for a,b,role in edges]
                unpacked.append({'evidence_id':eid,'content_sha256':blockhash,'features':features,'edges':links})
            documents[article[0]]={'article':article,'records':unpacked}
        result=cls(library,name,sha,documents,version)
        if canonical(result.wire())!=raw:raise ValueError('noncanonical MEM index representation')
        return result
    def atlas(self):
        return {'schema':'KNOWLEDGE_ATLAS.EXP001','library_id':self.library_id,'build_id':self.identity,
           'source_sha256':self.source_sha,'views':{k:[n['id'] for n in self.nodes_of(k)] for k in KINDS},
           'alphabetical':[n['id'] for n in sorted(self.nodes.values(),key=lambda x:(x['label'].casefold(),x['id']))],
           'nodes':[{k:v for k,v in n.items() if k!='observations'}|{'mem_refs':sorted(self.node_members[n['id']])} for n in sorted(self.nodes.values(),key=lambda n:n['id'])],
           'edges':sorted(self.edges),'mem_records':{rid:{'article_id':aid,'evidence_id':record['evidence_id']} for rid,(aid,record) in sorted(self.records.items())}}


class Federation:
    def __init__(self,indexes):
        self.indexes={x.library_id:x for x in indexes}
        if len(self.indexes)!=len(indexes):raise ValueError('duplicate library identity')
    def scope(self,mode,ids=()):
        selected=list(self.indexes) if mode=='UNIFIED' else list(dict.fromkeys(ids))
        if mode not in {'SINGLE','UNIFIED','CUSTOM'} or not selected or (mode=='SINGLE' and len(selected)!=1) or any(x not in self.indexes for x in selected):raise ValueError('invalid MEM exploration scope')
        return [self.indexes[x] for x in selected]
    def nodes(self,kind,mode='UNIFIED',ids=()):return [n for i in self.scope(mode,ids) for n in i.nodes_of(kind)]
