"""22-owned compact metadata, exact lazy candidate search, and V3 writer.

Search returns lexical candidates, never proposition authorization. SQLite is
only a bounded, temporary writer sort; the reader needs only the stdlib.
"""
from __future__ import annotations
from array import array
from functools import lru_cache
import hashlib
import heapq
import json
import mmap
from pathlib import Path
try:
    import resource
except ImportError:  # Windows: resource metrics are unavailable.
    resource = None
import sqlite3
import struct
import tempfile
import time
import zlib

from .format import _encode_varint as vint, _decode_varint as readint, _tokens, _decode_token_block
from .pages_v3 import TableWriter, PageStore, assemble, DATA_PAGE
from .v2_scan import layout, json_rows


def string(value):
    raw=value.encode('utf-8');return vint(len(raw))+raw


def readstring(raw,pos=0):
    length,pos=readint(raw,pos);end=pos+length
    if end>len(raw):raise ValueError('truncated 22CK string')
    return raw[pos:end].decode('utf-8'),end


def integers(*values):return b''.join(vint(x) for x in values)


def readints(raw,pos,count):
    result=[]
    for _ in range(count):value,pos=readint(raw,pos);result.append(value)
    return result,pos


def encode_postings(ranks,total):
    delta=bytearray(vint(len(ranks)));previous=0
    for rank in ranks:delta+=vint(rank-previous);previous=rank
    result=b'\0'+delta
    if len(ranks)>=128:
        bitmap=bytearray((ranks[-1]>>3)+1)
        for rank in ranks:bitmap[rank>>3]|=1<<(rank&7)
        packed=zlib.compress(bitmap,6)
        if len(packed)<len(delta):result=b'\1'+packed
    return result


def decode_postings(raw,total):
    if not raw:raise ValueError('missing 22CK posting codec')
    if raw[0]==1:
        d=zlib.decompressobj();bitmap=d.decompress(raw[1:],(total+7)//8+1)
        if not d.eof or d.unused_data or d.unconsumed_tail or len(bitmap)>(total+7)//8:
            raise ValueError('invalid 22CK bitmap bounds')
    elif raw[0]==0:
        count,pos=readint(raw,1);bitmap=bytearray((total+7)//8);rank=0
        if count>total:raise ValueError('invalid 22CK posting count')
        for i in range(count):
            delta,pos=readint(raw,pos);rank+=delta
            if rank>=total or (i and not delta):raise ValueError('invalid 22CK posting rank')
            bitmap[rank>>3]|=1<<(rank&7)
        if pos!=len(raw):raise ValueError('22CK posting trailing bytes')
    else:raise ValueError('unknown 22CK posting codec')
    value=int.from_bytes(bitmap,'little')
    if value.bit_length()>total:raise ValueError('22CK bitmap rank out of bounds')
    return value


class TwentyTwoCKReaderV3:
    def __init__(self,path):
        self.store=PageStore(path);self.path=Path(path)
        self._string=lru_cache(maxsize=4096)(self._string_uncached)
        self._token=lru_cache(maxsize=8192)(self._token_uncached)
        self._posting=lru_cache(maxsize=32)(self._posting_uncached)
        self._map_page=lru_cache(maxsize=16)(lambda name,page:self.store.record(name,page))
        self.last_search_profile={}

    @property
    def manifest(self):return dict(self.store.root['manifest'])

    def _string_uncached(self,i):return self.store.record('strings',i).decode('utf-8')
    def _token_uncached(self,i):return self.store.record('dictionary',i).decode('utf-8')

    def _find(self,table,key,binary=False):
        low=0;high=self.store.tables[table]['count']
        while low<high:
            mid=(low+high)//2;raw=self.store.record(table,mid)
            value=raw[:16] if binary else readstring(raw)[0]
            if value<key:low=mid+1
            else:high=mid
        if low==self.store.tables[table]['count']:raise KeyError(key)
        raw=self.store.record(table,low);value=raw[:16] if binary else readstring(raw)[0]
        if value!=key:raise KeyError(key)
        return low,raw

    def _article_meta(self,ordinal):
        raw=self.store.record('articles',ordinal);ident,pos=readstring(raw)
        (title,source,locale,n),pos=readints(raw,pos,4)
        ranks,pos=readints(raw,pos,n)
        if pos!=len(raw):raise ValueError('22CK article trailing bytes')
        return {'article_id':ident,'title':self._string(title),'source_ref':self._string(source),
                'locale':self._string(locale),'ranks':ranks}

    def _evidence(self,rank,with_text=True):
        raw=self.store.record('evidence',rank);ident='22E-'+raw[:16].hex().upper()
        (ordinal,article,sid,stitle,offset,length),pos=readints(raw,16,6)
        if pos!=len(raw):raise ValueError('22CK evidence trailing bytes')
        parent=self._article_meta(article)
        result={k:parent[k] for k in ('article_id','title','source_ref','locale')}
        result.update(evidence_id=ident,ordinal=ordinal,library_id=self.manifest['library_id'],
            section_id=self._string(sid),section_title=self._string(stitle),block_offset=offset,block_length=length)
        if with_text:
            block=self.store.data(offset,length)
            result['block_sha256']=hashlib.sha256(block).hexdigest().upper()
            result['text']=' '.join(self._token(i) for i in _decode_token_block(block))
        return result

    def get_evidence(self,evidence_id):
        if not evidence_id.startswith('22E-') or len(evidence_id)!=36:raise KeyError(evidence_id)
        try:key=bytes.fromhex(evidence_id[4:])
        except ValueError:raise KeyError(evidence_id) from None
        rank,_=self._find('evidence',key,True)
        return self._evidence(rank)

    def get_article(self,article_or_title):
        try:_,raw=self._find('article_lookup',article_or_title)
        except KeyError:_,raw=self._find('title_lookup',article_or_title.casefold())
        _,pos=readstring(raw);ordinal,pos=readint(raw,pos)
        result=self._article_meta(ordinal);ranks=result.pop('ranks')
        evidence=[self._evidence(rank) for rank in ranks]
        result.update(evidence_ids=[x['evidence_id'] for x in evidence],evidence=evidence)
        return result

    def iter_articles(self):
        for ordinal in range(self.store.tables['articles']['count']):
            result=self._article_meta(ordinal);ranks=result.pop('ranks')
            result['evidence']=[self._evidence(rank) for rank in ranks]
            result['evidence_ids']=[x['evidence_id'] for x in result['evidence']]
            yield result

    def _posting_uncached(self,token):
        try:_,raw=self._find('postings',token)
        except KeyError:return 0
        _,pos=readstring(raw);_,pos=readint(raw,pos)
        return decode_postings(raw[pos:],self.manifest['evidence_count'])

    def _map(self,name,number):
        offset=number*4
        return struct.unpack_from('<I',self._map_page(name,offset//DATA_PAGE),offset%DATA_PAGE)[0]

    def _top_ranks(self,selected,limit):
        total=self.manifest['evidence_count'];count=selected.bit_count()
        if count<max(32,total//64):
            def ranks():
                # Iterating a million-bit integer one bit at a time repeatedly
                # copies its whole tail. Iterate bounded 64-bit words instead.
                raw=selected.to_bytes(((total+63)//64)*8,'little')
                for base,(word,) in enumerate(struct.iter_unpack('<Q',raw)):
                    while word:
                        bit=word&-word;word^=bit
                        yield self._map('ordinal_to_rank',base*64+bit.bit_length()-1)
            return heapq.nsmallest(limit,ranks())
        # Hash identities are independent of document order. Dense score sets
        # scan rank order; sparse sets map only their members. Both are exact.
        bitmap=selected.to_bytes((total+7)//8,'little');result=[]
        for rank in range(total):
            ordinal=self._map('rank_to_ordinal',rank)
            if bitmap[ordinal>>3]&(1<<(ordinal&7)):
                result.append(rank)
                if len(result)==limit:break
        return result

    def search_references(self,query,limit=5):
        if limit<=0:return []
        started=time.perf_counter();tokens=sorted(set(_tokens(query)));planes=[];union=0
        for token in tokens:
            carry=self._posting(token);union|=carry;bit=0
            while carry:
                if bit==len(planes):planes.append(carry);break
                carry,planes[bit]=planes[bit]&carry,planes[bit]^carry;bit+=1
        ranked=[];ranking=time.perf_counter()
        for score in range(len(tokens),0,-1):
            selected=union
            for bit,plane in enumerate(planes):selected &= plane if score&(1<<bit) else union^plane
            if score >= (1<<len(planes)):continue
            if selected:ranked.extend((rank,score) for rank in self._top_ranks(selected,limit-len(ranked)))
            if len(ranked)==limit:break
        decode=time.perf_counter()
        # No token blocks are decoded before federation chooses its global budget.
        results=[dict(evidence_id='22E-'+self.store.record('evidence',rank)[:16].hex().upper(),
                      score=score) for rank,score in ranked]
        done=time.perf_counter()
        self.last_search_profile={'postings_and_scoring_ms':(ranking-started)*1000,
            'ranking_ms':(decode-ranking)*1000,'evidence_decode_ms':(done-decode)*1000,'total_ms':(done-started)*1000}
        return results

    def search(self,query,limit=5):
        if limit <= 0: return []
        references = self.search_references(query, limit)
        started = time.perf_counter()
        rows = [dict(self.get_evidence(row['evidence_id']), score=row['score']) for row in references]
        elapsed = (time.perf_counter() - started) * 1000
        self.last_search_profile['evidence_decode_ms'] = elapsed
        self.last_search_profile['total_ms'] += elapsed
        return rows

    def verify_integrity(self):return self.store.verify_integrity()
    def close(self):
        self._string.cache_clear();self._token.cache_clear();self._posting.cache_clear();self._map_page.cache_clear();self.store.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def compact_v2_to_v3(source,output,progress=None):
    """Losslessly compact canonical V2 records, data and exact search semantics."""
    started=time.perf_counter();source=Path(source);output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    header,articles_offset,evidence_offset,manifest=layout(source)
    def status(phase):
        if progress:progress(phase)
    # Validate source identity incrementally before consuming its records.
    digest=hashlib.sha256()
    with source.open('rb') as f:
        remaining=source.stat().st_size-32
        while remaining:
            block=f.read(min(1024*1024,remaining));digest.update(block);remaining-=len(block)
        if digest.digest()!=f.read(32):raise ValueError('V2 source integrity failure')
    with tempfile.TemporaryDirectory(prefix='22ck-v3-',dir=output.parent) as tmp:
        tmp=Path(tmp);db=sqlite3.connect(tmp/'sort.sqlite')
        db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE; PRAGMA cache_size=-16384;'
          'CREATE TABLE strings(id INTEGER PRIMARY KEY,value TEXT UNIQUE);'
          'CREATE TABLE articles(ordinal INTEGER PRIMARY KEY,id TEXT UNIQUE,title INTEGER,source INTEGER,locale INTEGER);'
          'CREATE TABLE titles(value TEXT PRIMARY KEY,ordinal INTEGER);'
          'CREATE TABLE evidence(ordinal INTEGER PRIMARY KEY,article INTEGER,sid INTEGER,stitle INTEGER,id BLOB UNIQUE,off INTEGER,len INTEGER);'
          'CREATE TABLE tokens(id INTEGER PRIMARY KEY,value TEXT UNIQUE,off INTEGER,len INTEGER);')
        tables={};strings=TableWriter(tmp,'strings');next_string=0
        @lru_cache(maxsize=16384)
        def intern(value):
            nonlocal next_string
            found=db.execute('SELECT id FROM strings WHERE value=?',(value,)).fetchone()
            if found:return found[0]
            ident=next_string;next_string+=1
            db.execute('INSERT INTO strings VALUES (?,?)',(ident,value));strings.add(value.encode())
            return ident
        status('shared article metadata')
        for ordinal,row in enumerate(json_rows(source,articles_offset)):
            db.execute('INSERT INTO articles VALUES (?,?,?,?,?)',(ordinal,row['article_id'],intern(row['title']),intern(row['source_ref']),intern(row['locale'])))
            db.execute('INSERT OR REPLACE INTO titles VALUES (?,?)',(row['title'].casefold(),ordinal))
            if ordinal%1000==0:db.commit()
        db.commit();last_article=None;article_ordinal=None
        status('evidence references')
        for row in json_rows(source,evidence_offset):
            if row['article_id']!=last_article:
                last_article=row['article_id'];article_ordinal=db.execute('SELECT ordinal FROM articles WHERE id=?',(last_article,)).fetchone()[0]
            ident=row['evidence_id']
            if len(ident)!=36 or not ident.startswith('22E-'):raise ValueError('V3 migration requires V2 streaming evidence identities')
            db.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?)',(row['ordinal'],article_ordinal,intern(row['section_id']),intern(row['section_title']),bytes.fromhex(ident[4:]),row['block_offset'],row['block_length']))
            if row['ordinal']%10000==0:db.commit()
        db.commit();tables['strings']=strings.finish();intern.cache_clear()
        count=manifest['evidence_count']
        rankpath=tmp/'rank-map';rankpath.write_bytes(b'')
        with rankpath.open('r+b') as f:f.truncate(max(4,count*4))
        with rankpath.open('r+b') as rf, mmap.mmap(rf.fileno(),0) as ranks:
            status('binary evidence and article tables')
            writer=TableWriter(tmp,'evidence')
            rank_to_ordinal=TableWriter(tmp,'rank_to_ordinal',rows=1);rank_buffer=bytearray()
            for rank,(ordinal,article,sid,stitle,ident,off,length) in enumerate(db.execute('SELECT ordinal,article,sid,stitle,id,off,len FROM evidence ORDER BY id')):
                struct.pack_into('<I',ranks,ordinal*4,rank)
                rank_buffer+=struct.pack('<I',ordinal)
                if len(rank_buffer)==DATA_PAGE:rank_to_ordinal.add(rank_buffer);rank_buffer.clear()
                writer.add(ident+integers(ordinal,article,sid,stitle,off,length))
            if rank_buffer:rank_to_ordinal.add(rank_buffer)
            tables['rank_to_ordinal']=rank_to_ordinal.finish()
            ordinal_to_rank=TableWriter(tmp,'ordinal_to_rank',rows=1)
            for start in range(0,count*4,DATA_PAGE):ordinal_to_rank.add(ranks[start:min(start+DATA_PAGE,count*4)])
            tables['ordinal_to_rank']=ordinal_to_rank.finish()
            tables['evidence']=writer.finish()
            db.execute('CREATE INDEX evidence_article ON evidence(article,ordinal)')
            writer=TableWriter(tmp,'articles')
            for ordinal,ident,title,source_ref,locale in db.execute('SELECT * FROM articles ORDER BY ordinal'):
                refs=[struct.unpack_from('<I',ranks,x[0]*4)[0] for x in db.execute('SELECT ordinal FROM evidence WHERE article=? ORDER BY ordinal',(ordinal,))]
                writer.add(string(ident)+integers(title,source_ref,locale,len(refs),*refs))
            tables['articles']=writer.finish()
            for name,query in [('article_lookup','SELECT id,ordinal FROM articles ORDER BY id'),('title_lookup','SELECT value,ordinal FROM titles ORDER BY value')]:
                writer=TableWriter(tmp,name)
                for key,ordinal in db.execute(query):writer.add(string(key)+vint(ordinal))
                tables[name]=writer.finish()
            status('dictionary and token data pages')
            with source.open('rb') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
                dictionary=TableWriter(tmp,'dictionary',compress=True);pos=header[2];tokens,pos=readint(m,pos)
                for tokenid in range(tokens):
                    length,pos=readint(m,pos);raw=m[pos:pos+length];pos+=length;dictionary.add(raw)
                    db.execute('INSERT INTO tokens(id,value) VALUES (?,?)',(tokenid,raw.decode()))
                    if tokenid%10000==0:m.madvise(mmap.MADV_DONTNEED) if hasattr(m, 'madvise') else None
                db.commit();tables['dictionary']=dictionary.finish()
                writer=TableWriter(tmp,'data',rows=1,compress=True)
                for page,pos in enumerate(range(header[4],header[4]+header[5],DATA_PAGE)):
                    writer.add(m[pos:min(pos+DATA_PAGE,header[4]+header[5])])
                    if page%100==0:m.madvise(mmap.MADV_DONTNEED) if hasattr(m, 'madvise') else None
                tables['data']=writer.finish()
                status('ranked adaptive postings')
                postings=tmp/'postings-spool'
                with postings.open('wb') as out:
                    pos=header[8];entries,pos=readint(m,pos)
                    for entry in range(entries):
                        tokenid,pos=readint(m,pos);n,pos=readint(m,pos);ordinal=0;selected=[]
                        for _ in range(n):
                            delta,pos=readint(m,pos);ordinal+=delta
                            selected.append(ordinal)
                        encoded=encode_postings(selected,count);offset=out.tell();out.write(encoded)
                        db.execute('UPDATE tokens SET off=?,len=? WHERE id=?',(offset,len(encoded),tokenid))
                        if entry%10000==0:
                            db.commit();m.madvise(mmap.MADV_DONTNEED) if hasattr(m, 'madvise') else None
                    if pos!=header[8]+header[9]:raise ValueError('V2 index bounds')
                db.commit();writer=TableWriter(tmp,'postings',compress=True)
                with postings.open('rb') as inp:
                    for tokenid,token,offset,length in db.execute('SELECT id,value,off,len FROM tokens ORDER BY value'):
                        inp.seek(offset);writer.add(string(token)+vint(tokenid)+inp.read(length))
                tables['postings']=writer.finish()
        status('container assembly')
        manifest=dict(manifest,representation='22CK_COMPACT_V3',search_semantics='EXACT_TOKEN_OVERLAP_THEN_EVIDENCE_ID',data_semantics='V2_CANONICAL_TOKEN_SEQUENCE')
        root=assemble(output,tables,manifest)
        tempbytes=sum(p.stat().st_size for p in tmp.rglob('*') if p.is_file())+output.stat().st_size
        db.close()
    sizes={name:t['payload_bytes']+t['directory_bytes'] for name,t in root['tables'].items()}
    result={'writer':'KC001_22CK_COMPACT_RUNTIME_V3','total_22ck_bytes':output.stat().st_size,
        'metadata_bytes':sum(v for k,v in sizes.items() if k in {'strings','articles','evidence'}),
        'index_bytes':sum(v for k,v in sizes.items() if k in {'postings','article_lookup','title_lookup','rank_to_ordinal','ordinal_to_rank'}),
        'dictionary_bytes':sizes['dictionary'],'data_bytes':sizes['data'],'table_bytes':sizes,
        'root_header_footer_bytes':output.stat().st_size-sum(sizes.values()),
        'article_count':manifest['article_count'],'evidence_count':count,'source_text_bytes':manifest['source_text_bytes'],
        'build_seconds':time.perf_counter()-started,'peak_temp_disk_bytes':tempbytes,
        'process_max_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024 if resource is not None else None,
        'bounded_memory':True,'source_integrity':True}
    with output.open('rb') as f:result['artifact_sha256']=hashlib.file_digest(f,'sha256').hexdigest().upper()
    return result


def build_22ck_streaming_v3(library,output,**kwargs):
    from .streaming_v2 import build_22ck_streaming_v2
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='22ck-stage-',dir=output.parent) as temp:
        stage=Path(temp)/'canonical-v2.22ck'
        baseline=build_22ck_streaming_v2(library,stage,**kwargs)
        result=compact_v2_to_v3(stage,output)
        result['canonical_staging']=baseline;result['build_seconds']=time.perf_counter()-started
        result['peak_temp_disk_bytes']=max(result['peak_temp_disk_bytes']+stage.stat().st_size,baseline['peak_temp_estimate_bytes'])
        return result
