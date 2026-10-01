"""READ001 source-structured reading, reconstructed from canonical 22CK spans.

The index stores layout/case instructions, never autonomous factual answers.
Its documentary paragraphs are quoted reading material, not native deductions.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import zlib
import unicodedata

SCHEMA='wiki22.reading.spans.v4'
PROMOTION='READ001_DOCUMENTARY_READING_V1'
MAX_RECORD=65536
MAX_INDEX=256*1024*1024

def stamp(path):
    s=path.stat();return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns

def unpack(blob):
    if not isinstance(blob,bytes) or len(blob)>MAX_RECORD:raise ValueError('Reading record too large')
    z=zlib.decompressobj();raw=z.decompress(blob,MAX_RECORD+1)
    if len(raw)>MAX_RECORD or not z.eof or z.unused_data or z.unconsumed_tail:raise ValueError('Malformed reading compression')
    data=json.loads(raw)
    if not isinstance(data,list) or len(data)!=3:raise ValueError('Malformed reading record')
    return data

def reconstruct(reader,article_id,data):
    eids,paragraphs,links=data
    if not isinstance(eids,list) or len(eids)>64 or not isinstance(paragraphs,list) or len(paragraphs)>8:
        raise ValueError('Reading bounds exceeded')
    if not isinstance(links,list) or len(links)>12 or any(not isinstance(x,str) or not 1<=len(x)<=180 or any(c in x for c in '\r\n\x00') for x in links):
        raise ValueError('Invalid navigation hints')
    sources=[]
    for eid in eids:
        if not isinstance(eid,str) or not re.fullmatch(r'22E-[0-9A-F]{32}',eid):raise ValueError('Invalid evidence identity')
        e=reader.get_evidence(eid)
        if e['article_id']!=article_id:raise ValueError('Cross-article reading source')
        sources.append(e)
    result=[]
    for paragraph in paragraphs:
        if not isinstance(paragraph,list) or len(paragraph)!=3:raise ValueError('Invalid paragraph')
        runs,spacecode,cases=paragraph
        if not isinstance(runs,list) or not 1<=len(runs)<=32:raise ValueError('Invalid source runs')
        tokens=[];refs=[]
        for run in runs:
            if not isinstance(run,list) or len(run)!=3 or any(type(x) is not int for x in run):raise ValueError('Invalid source span')
            index,left,right=run
            if not 0<=index<len(sources):raise ValueError('Invalid source pointer')
            e=sources[index]
            if not 0<=left<right<=len(e['text']):raise ValueError('Source span outside evidence')
            if (left and e['text'][left-1]!=' ') or (right<len(e['text']) and e['text'][right]!=' '):raise ValueError('Partial token')
            tokens.extend(c for c in e['text'][left:right] if not c.isspace());refs.append(dict(evidence_id=e['evidence_id'],start=left,end=right))
        if len(tokens)>1800 or not isinstance(spacecode,str) or len(spacecode)>1000:raise ValueError('Display bounds exceeded')
        spaces=int(spacecode,16)
        if spaces<0 or spaces.bit_length()>len(tokens):raise ValueError('Invalid whitespace map')
        if not isinstance(cases,list) or len(cases)>len(tokens):raise ValueError('Invalid case map')
        seen=set()
        for pair in cases:
            if not isinstance(pair,list) or len(pair)!=2:raise ValueError('Invalid case pair')
            i,value=pair
            if type(i) is not int or i in seen or not 0<=i<len(tokens) or not isinstance(value,str) or unicodedata.normalize('NFKC',value).casefold()!=tokens[i]:
                raise ValueError('Formatting changes source meaning')
            seen.add(i);tokens[i]=value
        text=''.join((' ' if (spaces>>i)&1 else '')+value for i,value in enumerate(tokens))
        if not 80<=len(text)<=1800:raise ValueError('Paragraph size outside source contract')
        first=sources[runs[0][0]]
        heading=re.sub(r' \(parte \d+\)$','',first['section_title'])
        result.append(dict(text=text,heading=heading,spans=refs,source=first['source_ref'],
                           evidence_id=first['evidence_id'],article_id=article_id))
    return result

class ReadingIndex:
    def __init__(self,path,*,sha256,canonical_sha256,promotion=None,experimental=False,proof=None):
        if promotion!=PROMOTION and not experimental:raise ValueError('Reading index not promoted')
        self.path=Path(path).resolve();self.db=None;self.proof=None;self.lock=threading.RLock()
        self.initial_stamp=stamp(self.path)
        if not 1<=self.path.stat().st_size<=MAX_INDEX:raise ValueError('Reading index outside storage budget')
        if not re.fullmatch(r'[0-9a-fA-F]{64}',sha256):raise ValueError('Invalid reading index identity')
        self.sha256=sha256.upper()
        self.integrity_mode='AUTHENTICATED_RECORD' if proof else 'FULL_INDEX_SHA256'
        if not proof:
            with self.path.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest().upper()
            if actual!=self.sha256:raise ValueError('Reading index identity changed')
        try:
            if proof:
                from .reading_integrity import RecordProof
                pp=Path(proof['path']).resolve()
                if not pp.is_relative_to(self.path.parent) or pp==self.path or pp.stat().st_size!=proof['bytes']:
                    raise ValueError('Unsafe reading proof path')
                self.proof=RecordProof(pp,root=proof['root'],rows=proof['rows'],capacity=proof['capacity'],canonical_sha256=canonical_sha256)
            self.db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,check_same_thread=False)
            self.db.execute('PRAGMA trusted_schema=OFF');self.db.execute('PRAGMA query_only=ON')
            objects=set(self.db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
            expected={('table','reading'),('table','metadata')}
            if proof:expected.add(('table','reading_integrity'))
            if objects!=expected:raise ValueError('Unknown reading schema')
            meta=list(self.db.execute('SELECT key,value FROM metadata LIMIT 32'))
            if len(meta)>24 or sum(len(k)+len(v) for k,v in meta)>65536:raise ValueError('Reading metadata exceeds budget')
            self.metadata={k:json.loads(v) for k,v in meta}
            if self.metadata.get('schema')!=SCHEMA or self.metadata.get('canonical_sha256')!=canonical_sha256.upper():
                raise ValueError('Reading index belongs to another corpus')
            self.unchanged()
        except BaseException:self.close();raise

    def unchanged(self):
        if stamp(self.path)!=self.initial_stamp:raise ValueError('Reading index changed: reopen library')
        if self.proof:self.proof.unchanged()

    def close(self):
        with self.lock:
            if self.db is not None:self.db.close();self.db=None
            if self.proof is not None:self.proof.close();self.proof=None

    def read(self,reader,article_id):
        from .knowledge.compact_access import article_metadata
        with self.lock:
            self.unchanged()
            if not re.fullmatch(r'ITWIKI-\d+',article_id):return None
            row=self.db.execute('SELECT revision,raw_sha,body FROM reading WHERE aid=?',(int(article_id[7:]),)).fetchone()
            if row is None:return None
            revision,rawsha,blob=row
            if self.proof:
                position=self.db.execute('SELECT position FROM reading_integrity WHERE aid=?',(int(article_id[7:]),)).fetchone()
                if position is None:raise ValueError('Missing authenticated reading position')
                self.proof.verify(position[0],int(article_id[7:]),revision,rawsha,blob)
            if type(revision) is not int or revision<=0 or len(rawsha)!=32:raise ValueError('Invalid reading provenance')
            a=article_metadata(reader,article_id)
            data=unpack(blob)
            paragraphs=reconstruct(reader,article_id,data)
            url=f'https://it.wikipedia.org/w/index.php?oldid={revision}'
            for p in paragraphs:p.update(article_title=a['title'],original_revision_url=url,revision_id=revision,index_sha256=self.sha256)
            self.unchanged()
            return dict(article_id=article_id,title=a['title'],paragraphs=paragraphs,revision_id=revision,
                original_revision_url=url,raw_sha256=rawsha.hex().upper(),index_sha256=self.sha256,
                integrity_mode=self.integrity_mode,links=data[2],complete_article=False,interpretation='ATTRIBUTED_DOCUMENTARY_READING',model_calls=0)
