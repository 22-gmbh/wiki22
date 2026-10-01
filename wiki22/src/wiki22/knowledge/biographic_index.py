"""Read source-bound Bio field spans, never cached factual answers."""
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import threading

FIELDS=('Nome','Cognome','Attività','Attività2','Attività3','Nazionalità',
        'LuogoNascita','LuogoMorte','GiornoMeseNascita','GiornoMeseMorte',
        'AnnoNascita','AnnoMorte')
SCHEMA='wiki22.bio001.structure.v2'
PROMOTION='BIO001_LITERAL_SOURCE_ROLES_V1'
MAX_BYTES=128*1024*1024


def stamp(path):
    stat=path.stat()
    return stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns


class BiographicIndex:
    def __init__(self,path,*,sha256,canonical_sha256,promotion=None,experimental=False):
        self.path=Path(path).resolve();self.db=None;self._lock=threading.RLock()
        if promotion!=PROMOTION and not experimental:
            raise ValueError('Indice biografico non promosso')
        if not 1<=self.path.stat().st_size<=MAX_BYTES:
            raise ValueError('Indice biografico fuori dal limite di spazio')
        self.initial_stamp=stamp(self.path)
        with self.path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest().upper()
        if actual!=sha256.upper():raise ValueError('Identità dell’indice biografico cambiata')
        self.sha256=actual
        try:
            self.db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,check_same_thread=False)
            self.db.execute('PRAGMA trusted_schema=OFF')
            self.db.execute('PRAGMA query_only=ON')
            rows=self.db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            if set(rows)!={('table','bios'),('table','metadata')}:
                raise ValueError('Struttura dell’indice non riconosciuta')
            metadata=self.db.execute('SELECT key,value FROM metadata LIMIT 32').fetchall()
            if len(metadata)>24 or sum(len(k)+len(v) for k,v in metadata)>65536:
                raise ValueError('Metadati biografici fuori limite')
            self.metadata={key:json.loads(value) for key,value in metadata}
            if (self.metadata.get('schema')!=SCHEMA or self.metadata.get('canonical_sha256')!=canonical_sha256.upper()
                or self.metadata.get('field_order')!=list(FIELDS)):
                raise ValueError('Indice e corpus canonico non corrispondono')
            self.unchanged()
        except BaseException:
            self.close();raise

    def unchanged(self):
        if stamp(self.path)!=self.initial_stamp:
            raise ValueError('L’indice biografico è cambiato: riaprire la libreria')

    def close(self):
        with self._lock:
            if self.db is not None:self.db.close();self.db=None

    def record(self,reader,article_id,evidence_id):
        with self._lock:
            if self.db is None:raise ValueError('Lettore biografico chiuso')
            return self._record(reader,article_id,evidence_id)

    def _record(self,reader,article_id,evidence_id):
        self.unchanged()
        if not article_id.startswith('ITWIKI-') or not article_id[7:].isdigit():return None
        found=self.db.execute('SELECT revision,eid,start,end,fields,raw_sha,canonical_span_sha,title_sha FROM bios WHERE aid=?',(int(article_id[7:]),)).fetchone()
        if found is None:return None
        revision,eid,start,end,body,raw_sha,span_sha,title_sha=found
        if len(eid)!=16 or len(raw_sha)!=32 or len(span_sha)!=32 or len(title_sha)!=32 or not body or len(body)%5 or len(body)>5*len(FIELDS):
            raise ValueError('Record biografico malformato')
        local_eid='22E-'+eid.hex().upper()
        if local_eid!=evidence_id:return None
        source=reader.get_evidence(local_eid)
        if source['article_id']!=article_id or not 0<=start<end<=len(source['text']):
            raise ValueError('Fonte della scheda biografica incoerente')
        from .compact_access import article_metadata
        title=(article_metadata(reader,article_id) if hasattr(reader,'store') else reader.get_article(article_id))['title']
        if hashlib.sha256(source['text'][start:end].encode()).digest()!=span_sha or hashlib.sha256(title.encode()).digest()!=title_sha:
            raise ValueError('Testo o titolo della scheda cambiato rispetto all’indice')
        if source['source_ref']!='https://it.wikipedia.org/?curid='+article_id[7:]:
            raise ValueError('Riferimento originale della scheda incoerente')
        fields={};previous_code=0
        for position in range(0,len(body),5):
            code,left,right=struct.unpack_from('<BHH',body,position)
            if not previous_code<code<=len(FIELDS) or not start<=left<right<=end:
                raise ValueError('Campi biografici ambigui o fuori intervallo')
            previous_code=code;name=FIELDS[code-1];pair=source['text'][left:right]
            prefix=name.casefold()+' = '
            if not pair.startswith(prefix) or len(pair)==len(prefix):
                raise ValueError('Ruolo del campo non riproducibile dalla fonte')
            fields[name]=dict(value=pair[len(prefix):],start=left,end=right,pair=pair)
        if 'Nome' not in fields:raise ValueError('Scheda senza nome')
        self.unchanged()
        return dict(schema=SCHEMA,article_id=article_id,evidence_id=evidence_id,revision_id=revision,
            start=start,end=end,fields=fields,raw_template_sha256=raw_sha.hex().upper(),
            canonical_span_sha256=span_sha.hex().upper(),title_sha256=title_sha.hex().upper(),
            index_sha256=self.sha256,canonical_sha256=self.metadata['canonical_sha256'],
            source_sha256=self.metadata['source_sha256'],semantic_claims_authorized=False)
