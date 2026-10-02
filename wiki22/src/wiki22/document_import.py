"""Bounded offline document extraction and transactional 22CK V3 import.

Originals are read, never moved. Extracted typography is a hash-bound sidecar,
checked token-for-token against canonical 22CK at every documentary reading.
"""
from datetime import datetime, timezone
from dataclasses import replace
from contextlib import closing
import sys
from html.parser import HTMLParser
import csv
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import sqlite3
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from .knowledge.compact22 import build_22ck_streaming_v3
from .knowledge.compact22.format import _tokens, _normalize
from .knowledge.compact_provider import CompactKnowledgeProvider
from .knowledge.corpus_import import chunks
from .knowledge.library_registry import slug
from .html_document import html_sections

MAX_FILE=128*1024*1024
MAX_TEXT=16*1024*1024
MAX_BATCH=64*1024*1024
MAX_FILES=5000
NATIVE={'.txt','.md','.markdown','.json','.jsonl','.ndjson','.html','.htm','.xhtml','.epub','.docx','.odt','.fb2','.csv','.tsv','.pptx'}
OPTIONAL={'.pdf':'pdftotext','.mobi':'ebook-convert','.azw':'ebook-convert','.azw3':'ebook-convert'}

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest().upper()

def formats():
    return dict(native=sorted(NATIVE),optional=[dict(extension=x,converter=c,available=bool(shutil.which(c)) or (x=='.pdf' and importlib.util.find_spec('pypdf') is not None)) for x,c in OPTIONAL.items()],
        limits=dict(file_bytes=MAX_FILE,text_bytes=MAX_TEXT,batch_text_bytes=MAX_BATCH,files=MAX_FILES),
        note='Estrazione del testo: immagini, formule grafiche e impaginazione originale non sono convertite. PDF scansiti richiedono OCR esterno; DRM non aggirati.')

class TextHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.out=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','head'):self.hidden+=1
        if not self.hidden and tag in ('p','div','br','li','h1','h2','h3','tr','section'):self.out.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','head') and self.hidden:self.hidden-=1
        if not self.hidden and tag in ('p','div','li','h1','h2','h3','tr','section'):self.out.append('\n')
    def handle_data(self,data):
        if not self.hidden:self.out.append(data)

def html_text(raw):
    p=TextHTML();p.feed(raw);p.close();return ''.join(p.out)

def xml(raw):
    checked = raw.decode('utf-16').encode('utf-8') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else raw
    if re.search(br'<!\s*(DOCTYPE|ENTITY)',checked,re.I):raise ValueError('Dichiarazioni XML esterne non ammesse')
    return ET.fromstring(raw)

def decode(raw):
    if raw.startswith((b'\xff\xfe',b'\xfe\xff')):return raw.decode('utf-16')
    try:return raw.decode('utf-8-sig')
    except UnicodeDecodeError:raise ValueError('Codifica non UTF-8/UTF-16: salva una copia del testo in UTF-8')

def paragraphs(tree):
    return '\n\n'.join(''.join(e.itertext()) for e in tree.iter() if e.tag.split('}')[-1] in ('p','h','title','subtitle'))

def zip_open(path):
    z=zipfile.ZipFile(path)
    try:
        rows=z.infolist()
        if len(rows)>20000 or sum(x.file_size for x in rows)>256*1024*1024:raise ValueError('Archivio oltre il limite di estrazione')
        seen=set()
        for x in rows:
            p=PurePosixPath(x.filename)
            if x.filename in seen or p.is_absolute() or '..' in p.parts or '\\' in x.filename or x.flag_bits&1:
                raise ValueError('Archivio duplicato, cifrato o con percorsi non validi')
            seen.add(x.filename)
        return z
    except BaseException:z.close();raise

def zip_read(z,name):
    if z.getinfo(name).file_size>MAX_TEXT:raise ValueError('Sezione compressa troppo grande')
    return z.read(name)

def archive_sections(path,ext):
    with zip_open(path) as z:
        if ext=='.epub':
            if 'META-INF/encryption.xml' in z.namelist():
                enc=xml(zip_read(z,'META-INF/encryption.xml'))
                # Font obfuscation does not encrypt textual reading content.
                if any(e.attrib.get('Algorithm','') not in ('http://www.idpf.org/2008/embedding','http://ns.adobe.com/pdf/enc#RC') for e in enc.iter() if e.tag.endswith('EncryptionMethod')):
                    raise ValueError('EPUB con contenuto cifrato: serve una copia senza DRM')
            container=xml(zip_read(z,'META-INF/container.xml'))
            package=next(e.attrib['full-path'] for e in container.iter() if e.tag.endswith('rootfile'))
            opf=xml(zip_read(z,package));items={e.attrib['id']:e for e in opf.iter() if e.tag.endswith('}item')}
            sections=[]
            for n,e in enumerate(e for e in opf.iter() if e.tag.endswith('itemref')):
                item=items[e.attrib['idref']];href=item.attrib['href'].split('#')[0]
                from urllib.parse import unquote
                href=unquote(href)
                if ':' in href or href.startswith('/'):raise ValueError('Riferimento EPUB non locale')
                name=posixpath.normpath(posixpath.join(posixpath.dirname(package),href))
                if name.startswith('../'):raise ValueError('Percorso EPUB non valido')
                sections.append((f'Capitolo {n+1} · {name}',html_text(decode(zip_read(z,name)))))
            return sections
        if ext=='.docx':
            t=xml(zip_read(z,'word/document.xml'))
            ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            lines=[]
            for p in t.iter(ns+'p'):
                lines.append(''.join((e.text or '') if e.tag==ns+'t' else '\t' if e.tag==ns+'tab' else '\n' if e.tag==ns+'br' else '' for e in p.iter()))
            return [('Documento','\n\n'.join(lines))]
        if ext=='.odt':return [('Documento',paragraphs(xml(zip_read(z,'content.xml'))))]
        if ext=='.pptx':
            names=sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)),key=lambda n:int(re.search(r'(\d+)\.xml',n)[1]))
            return [(f'Diapositiva {i+1}','\n'.join(''.join(p.itertext()) for p in xml(zip_read(z,n)).iter() if p.tag.endswith('}p'))) for i,n in enumerate(names)]
    raise ValueError('Archivio non supportato')

def extract(path):
    """Return documents (title, sections); all external conversions are bounded."""
    ext=path.suffix.lower();title=path.stem.replace('_',' ')
    if ext in ('.epub','.docx','.odt','.pptx'):return [(title,archive_sections(path,ext))]
    if ext=='.pdf' and importlib.util.find_spec('pypdf') is not None and (os.name=='nt' or not shutil.which('pdftotext')):
        with tempfile.TemporaryDirectory(prefix='wiki22-pdf-') as tmp:
            output=Path(tmp)/'pages.json'
            proc=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).with_name('pdf_worker.py')),str(path),str(output)],
                                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120)
            if proc.returncode or not output.exists():raise ValueError('PDF protetto, danneggiato o oltre i limiti di estrazione')
            if output.stat().st_size>MAX_TEXT:raise ValueError('Testo convertito oltre il limite')
            sections=json.loads(output.read_text(encoding='utf-8'))
            if not sections:raise ValueError('PDF senza testo estraibile: serve OCR prima dell’importazione')
            return [(title,sections)]
    if ext in OPTIONAL:
        converter=shutil.which(OPTIONAL[ext])
        if not converter:raise ValueError('Convertitore non disponibile: '+OPTIONAL[ext])
        with tempfile.TemporaryDirectory(prefix='wiki22-convert-') as tmp:
            output=Path(tmp)/('text.txt' if ext=='.pdf' else 'converted.epub')
            args=[converter,'-enc','UTF-8',str(path),str(output)] if ext=='.pdf' else [converter,str(path),str(output)]
            # Resource limits inherited by child, no shell or file-controlled options.
            launcher='import os,resource,sys;resource.setrlimit(resource.RLIMIT_FSIZE,(67108864,67108864));resource.setrlimit(resource.RLIMIT_CPU,(90,90));os.execv(sys.argv[1],sys.argv[1:])'
            with (Path(tmp)/'errors').open('wb') as err:
                result=subprocess.run(args if os.name=='nt' else [sys.executable,'-c',launcher,*args],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=err,timeout=120)
            if result.returncode or not output.is_file():raise ValueError('Conversione fallita: file protetto, danneggiato o non leggibile')
            if output.stat().st_size>MAX_TEXT:raise ValueError('Testo convertito oltre il limite')
            if ext!='.pdf':return [(title,archive_sections(output,'.epub'))]
            pages=decode(output.read_bytes()).split('\f')
            sections=[(f'Pagina {i+1}',t) for i,t in enumerate(pages) if t.strip()]
            if not sections:raise ValueError('PDF senza testo estraibile: serve OCR prima dell’importazione')
            return [(title,sections)]
    raw=decode(path.read_bytes())
    if ext in ('.html','.htm','.xhtml'):sections=html_sections(raw)
    elif ext=='.fb2':sections=[('Libro',paragraphs(xml(path.read_bytes())))]
    elif ext in ('.csv','.tsv'):
        rows=list(csv.reader(io.StringIO(raw),delimiter='\t' if ext=='.tsv' else ','))
        sections=[('Tabella','\n'.join(' | '.join(row) for row in rows))]
    elif ext in ('.json','.jsonl','.ndjson'):
        value=json.loads(raw) if ext=='.json' else [json.loads(x) for x in raw.splitlines() if x.strip()]
        rows=value if isinstance(value,list) else [value];docs=[]
        for r in rows:
            if not isinstance(r,dict):raise ValueError('JSON richiede oggetti con text, content o body')
            t=r.get('text') or r.get('content') or r.get('body')
            if not isinstance(t,str):raise ValueError('Campo text, content o body assente')
            docs.append((str(r.get('title') or r.get('name') or title),[('Testo',t)]))
        return docs
    elif ext in NATIVE:
        title=next((x[2:].strip() for x in raw.splitlines() if x.startswith('# ')),title)
        sections=[('Testo',raw)]
    else:raise ValueError('Formato non supportato: '+(ext or 'senza estensione'))
    return [(title,sections)]

class ImportedProvider(CompactKnowledgeProvider):
    def __init__(self,path):
        self.document_db=None
        super().__init__(path)
        try:
            spec=json.loads(self.path.read_text())['document_index'];p=(self.path.parent/spec['path']).resolve()
            if p.parent!=self.path.parent or p.stat().st_size!=spec['bytes'] or sha(p)!=spec['sha256']:raise ValueError('Indice documentale modificato')
            self._file_stamps[p]=self._stamp(p)
            self.document_db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,check_same_thread=False)
            self.document_db.execute('PRAGMA trusted_schema=OFF');self.document_db.execute('PRAGMA query_only=ON')
            self.verify_integrity()
        except BaseException:self.close();raise
    def close(self):
        if self.document_db is not None:self.document_db.close();self.document_db=None
        super().close()
    def browse_titles(self,prefix='',*,after='',limit=30):
        self._ensure_unchanged()
        if not 1<=limit<=100:raise ValueError('Pagina troppo grande')
        cursor=tuple(after) if isinstance(after,(list,tuple)) else (after,'\uffff' if after else '')
        key=prefix.casefold()
        rows=self.document_db.execute('SELECT aid,title,title_key FROM documents WHERE title_key>=? AND title_key<? AND (title_key,aid)>(?,?) ORDER BY title_key,aid LIMIT ?', (key,key+'\U0010ffff',*cursor,limit)).fetchall()
        result=[]
        for aid,title,k in rows:
            a=self.get_article_summary(aid)
            if a is None or a.title!=title:raise ValueError('Indice titoli diverso da 22CK')
            result.append(dict(article_id=aid,title=title,key=k))
        self._ensure_unchanged();return result
    def _restored(self,evidence):
        if evidence is None:return None
        self._ensure_unchanged()
        row=self.document_db.execute('SELECT body FROM documents WHERE aid=?',(evidence.article_id,)).fetchone()
        if row is None:raise ValueError('Testo documentale mancante')
        data=json.loads(row[0]);parts=[s for s in data['sections'] if s['section_id']==evidence.section_id]
        if len(parts)!=1 or ' '.join(_tokens(parts[0]['text']))!=evidence.text:raise ValueError('Testo documentale diverso da 22CK')
        self._ensure_unchanged()
        return replace(evidence,text=parts[0]['text'],revision=evidence.revision+';DOCUMENT_SHA256:'+data['file_sha256'])
    def get_evidence(self,evidence_id):
        return self._restored(super().get_evidence(evidence_id))
    def get_article(self,article_id):
        a=super().get_article(article_id)
        if a is None:return None
        sections=[]
        for section in a.sections:
            evs=[dict(id=e['id'],text=self.get_evidence(e['id']).text) for e in section['evidence']]
            sections.append(dict(section,evidence=evs))
        return replace(a,sections=tuple(sections))
    def documentary_book(self,aid):
        self._ensure_unchanged();a=super().get_article(aid)
        row=self.document_db.execute('SELECT body FROM documents WHERE aid=?',(aid,)).fetchone()
        if not row or a is None:raise ValueError('Documento non disponibile')
        data=json.loads(row[0]);out=[]
        if len(data['sections'])!=len(a.sections):raise ValueError('Sezioni documentali incoerenti')
        for original,canonical in zip(data['sections'],a.sections):
            text=original['text'];ev=canonical['evidence']
            if original['section_id']!=canonical['id'] or original['title']!=canonical['title'] or ' '.join(_tokens(text))!=' '.join(e['text'] for e in ev):raise ValueError('Testo documentale diverso da 22CK')
            spans=[]
            for e in ev:
                live=self.get_evidence(e['id'])
                if ' '.join(_tokens(live.text))!=e['text'] or live.article_id!=aid:raise ValueError('Evidenza documentale modificata')
                spans.append(dict(evidence_id=live.evidence_id,start=0,end=len(live.text)))
            # Restore paragraph boundaries only after validating the complete
            # stored section against 22CK. Notes retain its full source context.
            for paragraph in re.split(r'\n\s*\n', text):
                if paragraph.strip():
                    out.append(dict(text=paragraph.strip(),heading=original['title'],source=a.source,
                        source_context=text,source_revision=data['file_sha256'],spans=spans))
        self._ensure_unchanged()
        return dict(title=a.title,article_id=aid,paragraphs=out,links=[],complete_article=True,source=a.source,
            revision_id=data['file_sha256'],interpretation='EXTRACTED_DOCUMENT_TEXT_NOT_ORIGINAL_LAYOUT')

def import_documents(registry,source,name,*,selected_files=None,source_refs=None):
    source=Path(source).expanduser().resolve(strict=True);lid=slug(name)
    target=registry.base/lid
    if registry.get(lid) or target.exists():raise ValueError('Esiste già una libreria con questo nome')
    files=[]
    if selected_files is not None:files=list(selected_files)
    elif source.is_file():files=[source]
    elif source.is_dir():
        if registry.root.is_relative_to(source):raise ValueError('Scegli una cartella di documenti, non la cartella che contiene Wiki22')
        for base,dirs,names in os.walk(source,followlinks=False):
            dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not (Path(base)/d).is_symlink())
            files.extend(Path(base)/n for n in sorted(names) if not n.startswith('.'))
            if len(files)>MAX_FILES:raise ValueError('Cartella oltre 5000 file: importa sottocartelle separate')
    else:raise ValueError('Scegli un file regolare o una cartella')
    report=[];articles=[];documents=[];total=0
    for path in files:
        item=dict(file=(source_refs or {}).get(str(path),str(path)) if selected_files is not None else str(path.relative_to(source)) if source.is_dir() else path.name,status='REJECTED')
        report.append(item)
        try:
            if path.is_symlink() or not path.is_file():raise ValueError('Collegamento simbolico o file speciale non importato')
            if not 0<path.stat().st_size<=MAX_FILE:raise ValueError('File vuoto o oltre 128 MiB')
            if path.suffix.lower() not in NATIVE|OPTIONAL.keys():raise ValueError('Formato non supportato: '+path.suffix)
            before=sha(path);parsed=extract(path)
            if sha(path)!=before:raise ValueError('Il file è cambiato durante la conversione')
            size=sum(len(t.encode()) for _,parts in parsed for _,t in parts)
            if not size or size>MAX_TEXT or total+size>MAX_BATCH:raise ValueError('Testo vuoto o limite di conversione raggiunto')
            added=[];records=[]
            for title,parts in parsed:
                sections=[]
                for label,text in parts:
                    for n,part in enumerate(chunks(text,3000)):
                        sections.append(dict(section_id='S'+str(len(sections)+1),title=_normalize(label+(f' · parte {n+1}' if n else '')),text=part))
                if not sections:raise ValueError('Documento privo di testo leggibile')
                if len(sections)>10000:raise ValueError('Documento troppo lungo: suddividilo in volumi')
                aid='DOC-'+hashlib.sha256((item['file']+'\0'+str(len(added))).encode()).hexdigest()[:24].upper()
                added.append(dict(article_id=aid,title=_normalize(title)[:300],source_ref=(source_refs or {}).get(str(path),path.as_uri())+'#sha256='+before,sections=sections))
                records.append((aid,dict(file_sha256=before,sections=sections)))
            if len(articles)+len(added)>20000:raise ValueError('Troppe voci: importa raccolte più piccole')
            articles.extend(added);documents.extend(records);total+=size
            item.update(status='IMPORTED',sha256=before,articles=len(added),text_bytes=size)
        except (ValueError,OSError,KeyError,StopIteration,ET.ParseError,zipfile.BadZipFile,subprocess.TimeoutExpired) as exc:item['reason']=str(exc) or type(exc).__name__
    if not articles:return dict(id=None,name=name,articles=0,evidence=0,format='22CK V3',report=report,status='NOT_IMPORTED')
    registry.base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.import-',dir=registry.base) as temp:
        stage=Path(temp);pack=stage/'library.22ck'
        result=build_22ck_streaming_v3(dict(library_id=lid,library_name=name,locale='it-IT',articles=articles),pack)
        index=stage/'documents.sqlite3'
        with closing(sqlite3.connect(index)) as db:
            db.execute('CREATE TABLE documents(aid TEXT PRIMARY KEY,body TEXT NOT NULL,title TEXT NOT NULL,title_key TEXT NOT NULL)')
            db.executemany('INSERT INTO documents VALUES(?,?,?,?)',[(a,json.dumps(d,ensure_ascii=False),article['title'],article['title'].casefold()) for (a,d),article in zip(documents,articles)])
            db.execute('CREATE INDEX titles ON documents(title_key,aid)');db.commit()
        catalog=dict(schema='wiki22.22ck.library.v1',library_id=lid,name=name,complete=True,parts=[dict(path=pack.name,bytes=pack.stat().st_size,sha256=sha(pack))],document_index=dict(path=index.name,bytes=index.stat().st_size,sha256=sha(index)))
        cat=stage/'library.22lib.json';cat.write_text(json.dumps(catalog))
        provider=ImportedProvider(cat)
        try:
            for a,_ in documents:provider.documentary_book(a)
        finally:provider.close()
        receipt=dict(status='PARTIAL' if any(x['status']!='IMPORTED' for x in report) else 'IMPORTED',id=lid,name=name,articles=len(articles),evidence=result['evidence_count'],format='22CK V3',report=report,created_utc=datetime.now(timezone.utc).isoformat(),model_calls=0)
        (stage/'import-report.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
        os.rename(stage,target)
        row=dict(id=lid,name=name,enabled=True,pack_path=str((target/cat.name).relative_to(registry.root)),pack_bytes=pack.stat().st_size if pack.exists() else (target/pack.name).stat().st_size,article_count=len(articles),evidence_count=result['evidence_count'],source_name=source.name,provenance='LOCAL_USER_IMPORT',format='22CK_DOCUMENTS',created_utc=receipt['created_utc'])
        data=registry.load();data['libraries'].append(row)
        if not data.get('default_library_id'):data['default_library_id']=lid
        try:registry.save(data)
        except BaseException:
            # Only this newly generated import; never the source or existing data.
            shutil.rmtree(target);raise
        return receipt
