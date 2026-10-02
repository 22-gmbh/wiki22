"""Source-first encyclopedia. Uses existing local packs; never calls an LLM."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import threading
from .knowledge.library_registry import LibraryRegistry
from .knowledge.compact_provider import open_library
from .knowledge.scope import resolve_scope
from .knowledge.atlas import browse_titles
from .extended_reading import open_extended
from .research_document import sentence_spans

VERSION = 'LIBRARIES110_PREVIEW1'


def documentary_sentences(text):
    # Keep normalized 22CK era abbreviations intact without changing source bytes.
    masked=list(text)
    for m in re.finditer(r'\b[ad]\s*\.\s*c\s*\.',text,re.I):
        for i in range(m.start(),m.end()):
            if masked[i]=='.':masked[i]='·'
    for _,start,end in sentence_spans(''.join(masked)):
        yield text[start:end],start,end


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def bootstrap_registry(target, source_roots):
    """Independent mutable registry; original installed packages remain untouched.

    Later source roots win for the same library ID (e.g. authenticated reading
    catalog). Pack paths resolve to original files; no multi-gigabyte copy.
    An existing user registry is never replaced on a later launch.
    """
    target = Path(target)
    registry = LibraryRegistry(target)
    if registry.path.exists():
        return registry
    rows = {}
    for root in source_roots:
        root = Path(root).resolve()
        path = root / 'data/libraries/registry.json'
        if not path.is_file():
            continue
        data = json.loads(path.read_text())
        for row in data.get('libraries', []):
            pack = (root / row['pack_path']).resolve()
            if not pack.is_file():
                continue
            rows[row['id']] = dict(row, pack_path=str(pack), linked_from=str(root))
    data = registry.empty()
    data['libraries'] = list(rows.values())
    data['default_library_id'] = next((r['id'] for r in rows.values() if r.get('enabled')), None)
    registry.save(data)
    return registry


class EncyclopediaService:
    def __init__(self, root, *, state_dir=None):
        self.root = Path(root).resolve()
        self.registry = LibraryRegistry(self.root)
        self.registry.ensure()
        self.lock = threading.RLock()
        self.import_lock = threading.Lock()
        self.providers = {}
        self.title_indexes = {}
        self.state_dir = Path(state_dir) if state_dir else self.root / '.runtime'
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.database = self.state_dir / 'encyclopedia.sqlite3'
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS shelf (library TEXT NOT NULL, article TEXT NOT NULL, title TEXT NOT NULL, scope TEXT NOT NULL, page INTEGER NOT NULL, at TEXT NOT NULL, PRIMARY KEY(library,article))')
            db.execute('CREATE TABLE IF NOT EXISTS research_shelf (id TEXT PRIMARY KEY,title TEXT NOT NULL,refs TEXT NOT NULL,scope TEXT NOT NULL,at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS shelf_undo (token TEXT PRIMARY KEY,body TEXT NOT NULL)')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.database, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def close(self):
        with self.lock:
            for index in self.title_indexes.values():index.close()
            self.title_indexes.clear()
            for _, provider, _ in self.providers.values():
                closer = getattr(provider, 'close', None)
                if closer:
                    closer()
            self.providers.clear()

    def libraries(self):
        with self.lock:
            return [dict(id=r['id'], name=r['name'], enabled=bool(r.get('enabled')),
                         articles=r.get('article_count'), source=r.get('source_name', ''),
                         imported=r.get('provenance') == 'LOCAL_USER_IMPORT',removed=bool(r.get('removed')))
                    for r in self.registry.list_libraries()]

    def scope(self, mode, ids):
        if not isinstance(mode, str) or not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
            raise ValueError('Selezione delle librerie non valida.')
        return list(resolve_scope(self.registry, mode=mode, requested_ids=ids).library_ids)

    def provider(self, library):
        row = self.registry.get(library)
        if not row or row.get('enabled') is not True:
            raise ValueError('Libreria non disponibile nella selezione.')
        path = self.registry.resolve_pack(library)
        if path is None:
            raise ValueError('Il contenuto della libreria non è disponibile.')
        stat = path.stat()
        stamp = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        cached = self.providers.get(library)
        if cached and (cached[0] != path or cached[2] != stamp):
            closer = getattr(cached[1], 'close', None)
            if closer:
                closer()
            if library in self.title_indexes:self.title_indexes.pop(library).close()
            del self.providers[library]
            raise ValueError('La libreria è cambiata. Ripeti la ricerca per riaprirla.')
        if library not in self.providers:
            from .document_import import ImportedProvider
            opened = ImportedProvider(path) if row.get('format') == '22CK_DOCUMENTS' else open_library(path)
            self.providers[library] = (path, opened, stamp)
        return self.providers[library][1]

    def preferences(self):
        with self.db() as db:
            row = db.execute('SELECT body FROM settings WHERE id=1').fetchone()
        value = json.loads(row[0]) if row else {}
        return dict(mode=value.get('mode', 'UNIFIED'), ids=value.get('ids', []),
                    columns=value.get('columns', True), font_size=value.get('font_size', 17),
                    research_depth=value.get('research_depth','essential'),
                    palette=value.get('palette','paper'), reading_font=value.get('reading_font','serif'),
                    line_spacing=value.get('line_spacing','normal'),
                    automatic_learning=value.get('automatic_learning',False), learning_budget=value.get('learning_budget',3))

    def save_preferences(self, value):
        if not isinstance(value, dict):
            raise ValueError('Preferenze non valide.')
        result = self.preferences()
        result.update({k: value[k] for k in result if k in value})
        from .encyclopedia_research import profile
        profile(result['research_depth'])
        if type(result['automatic_learning']) is not bool or type(result['learning_budget']) is not int or result['learning_budget'] not in (1,3,8):
            raise ValueError('Configurazione apprendimento non valida.')
        for key,allowed in [('palette',('paper','sand','mist')),('reading_font',('serif','sans')),('line_spacing',('normal','airy'))]:
            if result[key] not in allowed:raise ValueError('Preferenza di lettura non valida.')
        with self.lock:
            if result['ids'] or (result['mode'] == 'UNIFIED' and any(r.get('enabled') for r in self.registry.list_libraries())):
                self.scope(result['mode'], result['ids'])
            elif result['mode'] not in ('CUSTOM','UNIFIED'):
                raise ValueError('Seleziona almeno una libreria.')
            if type(result['columns']) is not bool or type(result['font_size']) is not int or result['font_size'] not in (16,17,19,21):
                raise ValueError('Impostazione di lettura non valida.')
            with self.db() as db:
                db.execute('INSERT OR REPLACE INTO settings VALUES(1,?)', (json.dumps(result),))
        return result

    def title_index(self, library):
        from .title_search import TitleIndex
        provider=self.provider(library)
        if library not in self.title_indexes:
            self.title_indexes[library]=TitleIndex(provider,self.state_dir/'title-search064')
        return self.title_indexes[library]

    def suggest(self, query='', *, mode='UNIFIED', ids=None):
        if not isinstance(query,str) or len(query)>180:raise ValueError('Ricerca non valida.')
        if len(query.strip())<2:return dict(rows=[],query=query,similar=False)
        result=self.search(query,mode=mode,ids=ids,limit=8)
        return dict(rows=(result['rows']+result['suggestions'])[:8],query=query,similar=not bool(result['rows']))

    def search(self, query='', *, mode='UNIFIED', ids=None, after=None, limit=30):
        if not isinstance(query, str) or len(query) > 180 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Inserisci un argomento entro 180 caratteri.')
        if after is not None and (not isinstance(after, list) or len(after) != 3 or any(not isinstance(s, str) for s in after)):
            raise ValueError('Pagina di ricerca non valida.')
        with self.lock:
            selected = self.scope(mode, ids or [])
            rows = []
            for lid in selected:
                provider = self.provider(lid)
                # Include equal-title rows, then apply the complete federation cursor.
                local_after = ([after[0], after[2] if lid == after[1] else ('\uffff' if lid < after[1] else '')] if after else '')
                for row in self.title_index(lid).page(query, after=local_after if isinstance(local_after,list) else ('',''), limit=limit+1):
                    item = dict(title=row['title'], article_id=row['article_id'], library_id=lid,
                                library_name=self.registry.get(lid)['name'], key=row['key'])
                    key = [item['key'], lid, item['article_id']]
                    if after is None or key > after:
                        rows.append(item)
            rows.sort(key=lambda r:(r['key'],r['library_id'],r['article_id']))
            more = len(rows) > limit
            rows = rows[:limit]
            cursor = [rows[-1]['key'],rows[-1]['library_id'],rows[-1]['article_id']] if more else None
            suggestions=[]
            from .title_search import fold
            if len(rows)<8 and after is None and not any(r['key']==fold(query) for r in rows):
                for lid in selected:
                    suggestions.extend(dict(r,library_id=lid,library_name=self.registry.get(lid)['name']) for r in self.title_index(lid).similar(query))
                seen={(r['library_id'],r['article_id']) for r in rows}
                suggestions=sorted((r for r in suggestions if (r['library_id'],r['article_id']) not in seen),key=lambda r:(len(r['key']),r['key'],r['library_id'],r['article_id']))[:8]
            return dict(rows=rows, next=cursor, scope=selected, query=query,suggestions=suggestions)

    def _book(self, provider, article_id):
        documentary = getattr(provider, 'documentary_book', None)
        if documentary:
            return documentary(article_id)
        getter = getattr(provider, 'reading_record', None)
        if getter:
            book = open_extended(provider, article_id, sentence_iterator=documentary_sentences)
            if book.get('status') == 'READY':
                return book
        article = provider.get_article(article_id)
        if article is None:
            raise ValueError('Voce non disponibile in questa libreria.')
        paragraphs = []
        for section in article.sections:
            for item in section.get('evidence', []):
                evidence = provider.get_evidence(item['id'])
                if evidence is None or evidence.article_id != article_id or evidence.text != item['text'] or evidence.source != article.source:
                    raise ValueError('Il testo non corrisponde alla fonte locale.')
                if not evidence.text.strip():
                    continue
                paragraphs.append(dict(text=evidence.text, heading=section.get('title') or section.get('heading') or 'Testo',
                    source=evidence.source, source_revision=evidence.revision,
                    spans=[dict(evidence_id=evidence.evidence_id,start=0,end=len(evidence.text))]))
        if not paragraphs:
            raise ValueError('Questa voce non contiene testo leggibile.')
        return dict(title=article.title, article_id=article_id, paragraphs=paragraphs,
                    links=[], complete_article=True, original_revision_url='',
                    revision_id=article.revision, source=article.source,
                    interpretation='LOCAL_DOCUMENTARY_TEXT')

    def article(self, library_id, article_id, *, mode='UNIFIED', ids=None, expected=None):
        if not isinstance(library_id, str) or not isinstance(article_id, str) or len(article_id)>300:
            raise ValueError('Voce non valida.')
        with self.lock:
            selected = self.scope(mode, ids or [])
            if library_id not in selected:
                raise ValueError('La voce non appartiene alle librerie selezionate.')
            provider = self.provider(library_id)
            book = self._book(provider, article_id)
            # Re-read through provider integrity checks before publication.
            if self._book(provider, article_id) != book:
                raise ValueError('La fonte è cambiata durante la lettura.')
            identity = digest(book)
            if expected and expected != identity:
                raise ValueError('La fonte è cambiata: riapri la voce prima di salvare o esportare.')
            pages, notes, toc = [[]], [], []
            used = 0
            imported_document = book.get('interpretation') == 'EXTRACTED_DOCUMENT_TEXT_NOT_ORIGINAL_LAYOUT'
            grouped = {}
            for paragraph in book['paragraphs']:
                grouped.setdefault(paragraph.get('heading') or 'Introduzione', []).append(paragraph)
            ordered = book['paragraphs'] if imported_document else (paragraph for group in grouped.values() for paragraph in group)
            for p in ordered:
                if pages[-1] and used+len(p['text'])>3600:
                    pages.append([]);used=0
                heading=p.get('heading') or 'Introduzione'
                if heading not in [t['heading'] for t in toc]:
                    toc.append(dict(heading=heading,page=len(pages)-1))
                items=[]
                for text,start,end in documentary_sentences(p['text']):
                    number=len(notes)+1
                    items.append(dict(text=text,note=number))
                    notes.append(dict(number=number,excerpt=text,context=p.get('source_context',p['text']),
                        heading=heading,spans=p.get('spans',[]),revision=p.get('revision_id',p.get('source_revision',book.get('revision_id'))),
                        source=p.get('source') or book.get('original_revision_url') or book.get('source',''),
                        revision_url=p.get('original_revision_url') or book.get('original_revision_url',''),
                        source_hash=identity,canonical_excerpt=bool(p.get('canonical_excerpt'))))
                pages[-1].append(dict(heading=heading,sentences=items));used+=len(p['text'])
            from .encyclopedia_prose import prepare_pages
            pages,toc,presentation=prepare_pages(pages,notes,budget=2400 if imported_document else 3600,preserve_order=imported_document)
            with self.db() as db:
                row=db.execute('SELECT page FROM shelf WHERE library=? AND article=?',(library_id,article_id)).fetchone()
            return dict(title=book['title'],article_id=article_id,library_id=library_id,
                library_name=self.registry.get(library_id)['name'],scope=selected,pages=pages,toc=toc,notes=notes,presentation=presentation,
                related=[x for x in book.get('links',[]) if isinstance(x,str)][:12],
                complete=bool(book.get('complete_article')),source_hash=identity,
                saved=row is not None,saved_page=row[0] if row else 0,model_calls=0,
                reading_kind='Passaggi dalla fonte locale' if not book.get('complete_article') else 'Testo della libreria locale')

    def context_documents(self, documents, mode, ids, maximum=2):
        if not isinstance(documents,list) or not 1<=len(documents)<=maximum:
            raise ValueError(f'Scegli da 1 a {maximum} voci da consultare.')
        result=[]
        for item in documents:
            if not isinstance(item,dict) or set(item)-{'library_id','article_id','source_hash'}:
                raise ValueError('Riferimento alla fonte non valido.')
            result.append(self.article(item['library_id'],item['article_id'],mode=mode,ids=ids,expected=item.get('source_hash')))
        return result

    def compare(self, left, right, *, mode='UNIFIED', ids=None):
        from .encyclopedia_context import compare_documents
        with self.lock:
            documents=self.context_documents([left,right],mode,ids or [])
            if documents[0]['library_id']==documents[1]['library_id']:
                raise ValueError('Scegli due librerie diverse per il confronto.')
            return compare_documents(*documents)

    def timeline(self, documents, *, mode='UNIFIED', ids=None, year=None, month=None, day=None):
        from .encyclopedia_context import timeline_documents
        with self.lock:
            return timeline_documents(self.context_documents(documents,mode,ids or [],maximum=12),year=year,month=month,day=day)

    def timeline_date(self, year, month=None, day=None, *, mode='UNIFIED', ids=None):
        from .encyclopedia_context import validate_date_filter,timeline_documents,MONTHS
        from .title_search import fold
        query=validate_date_filter(year,month,day)
        if year is None:raise ValueError('Scegli un anno per cercare nel calendario delle librerie.')
        titles=[str(abs(year))+(' a.C.' if year<0 else '')]
        if day is not None:titles.append(str(day)+' '+MONTHS[month-1])
        documents=[];seen=set();limited=False
        with self.lock:
            self.scope(mode,ids or [])
            for title in titles:
                rows=self.search(title,mode=mode,ids=ids,limit=50)
                limited=limited or bool(rows['next'])
                for row in rows['rows']:
                    key=(row['library_id'],row['article_id'])
                    if fold(row['title'])!=fold(title) or key in seen:continue
                    if len(documents)>=12:limited=True;continue
                    seen.add(key);documents.append(self.article(*key,mode=mode,ids=ids))
            result=timeline_documents(documents,year=year,month=month,day=day,calendar_context=True)
            result.update(lookup='calendar',searched_titles=titles,limited=result['limited'] or limited)
            result['nearby']=None
            if day is not None and not result['events']:
                nearby=timeline_documents(documents,year=year,month=month,calendar_context=True)
                nearby['events']=sorted((e for e in nearby['events'] if e['date']['day'] is not None),key=lambda e:abs(e['date']['day']-day))[:6]
                nearby['events'].sort(key=lambda e:e['date']['day'])
                result['nearby']=dict(events=nearby['events'],label=nearby['date_filter']['label'])
            result['method']='Ricerca nelle voci calendario «'+'», «'.join(titles)+'» delle librerie selezionate, senza scansione di tutti gli altri articoli. '+result['method']
            return result

    def explore(self, path_id, *, mode='UNIFIED', ids=None):
        from .encyclopedia_explore import resolve
        with self.lock:
            return resolve(self,path_id,mode,ids)

    def shelf(self):
        with self.db() as db:
            rows=db.execute('SELECT library,article,title,scope,page,at FROM shelf ORDER BY at DESC').fetchall()
        return [dict(library_id=r[0],article_id=r[1],title=r[2],scope=json.loads(r[3]),page=r[4],at=r[5]) for r in rows]

    def bookmark(self, library_id, article_id, *, mode, ids, source_hash, page=0, saved=True):
        if type(page) is not int or page<0 or type(saved) is not bool:
            raise ValueError('Segnalibro non valido.')
        document=self.article(library_id,article_id,mode=mode,ids=ids,expected=source_hash)
        if page>=len(document['pages']):
            raise ValueError('Pagina non disponibile.')
        with self.db() as db:
            if saved:
                db.execute('INSERT OR REPLACE INTO shelf VALUES(?,?,?,?,?,?)',(library_id,article_id,document['title'],
                    json.dumps(document['scope']),page,datetime.now(timezone.utc).isoformat()))
            else:
                db.execute('DELETE FROM shelf WHERE library=? AND article=?',(library_id,article_id))
        return dict(saved=saved)

    def research(self, documents, *, mode='UNIFIED', ids=None, depth=None):
        from .encyclopedia_research import compose
        if not isinstance(documents,list) or not 1<=len(documents)<=12:
            raise ValueError('Seleziona da 1 a 12 voci per creare una ricerca.')
        with self.lock:
            refs=[];seen=set()
            for item in documents:
                if not isinstance(item,dict) or set(item)-{'library_id','article_id','source_hash'}:
                    raise ValueError('Riferimento alla fonte non valido.')
                identity=(item.get('library_id'),item.get('article_id'))
                if any(not isinstance(x,str) for x in identity) or identity in seen:
                    raise ValueError('Scegli voci distinte e valide.')
                seen.add(identity)
                refs.append(self.article(*identity,mode=mode,ids=ids,expected=item.get('source_hash')))
            result=compose(refs,depth if depth is not None else self.preferences()['research_depth'])
            result['scope']=refs[0]['scope'];result['source_hash']=digest(result)
            return result

    def research_list(self):
        with self.db() as db:rows=db.execute('SELECT id,title,refs,scope,at FROM research_shelf ORDER BY at DESC').fetchall()
        return [dict(id=r[0],title=r[1],documents=(json.loads(r[2]).get('documents',[]) if isinstance(json.loads(r[2]),dict) else json.loads(r[2])),depth=(json.loads(r[2]).get('depth','essential') if isinstance(json.loads(r[2]),dict) else 'essential'),scope=json.loads(r[3]),at=r[4]) for r in rows]

    def research_save(self, documents, *, mode='UNIFIED', ids=None, depth=None):
        with self.lock:
            result=self.research(documents,mode=mode,ids=ids,depth=depth)
            refs=[{k:d[k] for k in ['library_id','article_id','source_hash']} for d in result['documents']]
            identity=dict(refs=refs,scope=result['scope'])
            if result['depth']!='essential':identity['depth']=result['depth']
            ident=digest(identity)[:32]
            payload=dict(documents=refs,depth=result['depth'])
            with self.db() as db:
                db.execute('INSERT OR REPLACE INTO research_shelf VALUES(?,?,?,?,?)',(ident,result['title'],json.dumps(payload),json.dumps(result['scope']),datetime.now(timezone.utc).isoformat()))
            return dict(id=ident,title=result['title'])

    def research_open(self, id, *, mode='UNIFIED', ids=None):
        if not isinstance(id,str):raise ValueError('Ricerca non valida.')
        with self.db() as db:row=db.execute('SELECT refs FROM research_shelf WHERE id=?',(id,)).fetchone()
        if not row:raise ValueError('Ricerca non più presente nello scaffale.')
        payload=json.loads(row[0]);refs=payload['documents'] if isinstance(payload,dict) else payload
        depth=payload.get('depth','essential') if isinstance(payload,dict) else 'essential'
        result=self.research(refs,mode=mode,ids=ids,depth=depth);result['saved_id']=id
        return result

    def shelf_remove(self, items):
        import secrets
        if not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError('Selezione non valida.')
        removed=[];token=secrets.token_urlsafe(24)
        with self.lock, self.db() as db:
            for item in items:
                if not isinstance(item,dict):raise ValueError('Voce non valida.')
                if item.get('kind')=='article' and set(item)=={'kind','library_id','article_id'} and all(isinstance(item[k],str) for k in ['library_id','article_id']):
                    row=db.execute('SELECT * FROM shelf WHERE library=? AND article=?',(item['library_id'],item['article_id'])).fetchone()
                    if row:
                        removed.append(dict(kind='article',row=row));db.execute('DELETE FROM shelf WHERE library=? AND article=?',(item['library_id'],item['article_id']))
                elif item.get('kind')=='research' and set(item)=={'kind','id'} and isinstance(item['id'],str):
                    row=db.execute('SELECT * FROM research_shelf WHERE id=?',(item['id'],)).fetchone()
                    if row:
                        removed.append(dict(kind='research',row=row));db.execute('DELETE FROM research_shelf WHERE id=?',(item['id'],))
                else:raise ValueError('Voce non valida.')
            if removed:db.execute('INSERT INTO shelf_undo VALUES(?,?)',(token,json.dumps(removed)))
        return dict(removed=len(removed),undo=token if removed else None)

    def shelf_restore(self, token):
        if not isinstance(token,str) or len(token)>100:raise ValueError('Ripristino non valido.')
        with self.lock, self.db() as db:
            row=db.execute('SELECT body FROM shelf_undo WHERE token=?',(token,)).fetchone()
            if not row:raise ValueError('La rimozione è già stata annullata o non è disponibile.')
            count=0
            for item in json.loads(row[0]):
                table,marks=('shelf','?,?,?,?,?,?') if item['kind']=='article' else ('research_shelf','?,?,?,?,?')
                count+=db.execute('INSERT OR IGNORE INTO '+table+' VALUES('+marks+')',item['row']).rowcount
            db.execute('DELETE FROM shelf_undo WHERE token=?',(token,))
        return dict(restored=count)

    def research_export(self, documents, *, mode='UNIFIED', ids=None, depth=None):
        return self.export_document(self.research(documents,mode=mode,ids=ids,depth=depth))

    def import_library(self, path, name):
        if not isinstance(path,str) or not isinstance(name,str) or not 1<=len(name.strip())<=80:
            raise ValueError('Scegli un file o una cartella e assegna un nome alla libreria.')
        with self.import_lock:
            from .document_import import import_documents
            with self.lock:
                return import_documents(self.registry,path,name.strip())

    def export(self, **kwargs):
        return self.export_document(self.article(**kwargs))

    @staticmethod
    def export_document(document):
        from html import escape
        chunks=['<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+escape(document['title'])+' — Wiki22</title>',
            '<style>body{font:18px/1.7 Georgia,serif;color:#25392c;background:#f1efe6;margin:0}.sheet{max-width:850px;margin:24px auto;padding:48px;background:#fffdf7;box-sizing:border-box}h1{font-size:38px}h2{font-size:23px}a{color:#315b42}small{font:13px sans-serif}.columns{columns:2;column-gap:36px}.columns p{margin-top:0}h2{break-after:avoid}li{overflow-wrap:anywhere;margin-bottom:18px}@media(max-width:640px){.columns{columns:1}.sheet{padding:22px}}@media print{body{background:white}.sheet{margin:0;break-after:page;padding:0}}</style>']
        if document.get('depth_label'):
            chunks.append('<section class="sheet"><h2>Ampiezza: '+escape(document['depth_label'])+'</h2><p>'+str(len(document['pages']))+' pagine · '+str(len(document['notes']))+' passaggi con fonte</p></section>')
        if document.get('method'):
            chunks.append('<section class="sheet"><h1>'+escape(document['title'])+'</h1><p>'+escape(document['method'])+'</p><p>'+('Temi condivisi: '+escape(', '.join(t['heading'] for t in document['themes'])) if document.get('themes') else 'Punti di incontro: '+str(len(document['connections'])) if document['connections'] else 'Nessun richiamo esplicito tra i titoli nei passaggi esaminati.')+'</p></section>')
        for i,page in enumerate(document['pages']):
            chunks.append('<article class="sheet"><small>WIKI22 · '+escape(document['library_name'])+f' · {i+1}/{len(document["pages"])}</small><h1>'+escape(document['title'])+'</h1><div class="columns">')
            previous_heading = None
            for block in page:
                chunks.append(('<h2>'+escape(block['heading'])+'</h2>' if block['heading'] != previous_heading else '')+'<p>')
                previous_heading = block['heading']
                for s in block['sentences']:
                    chunks.append(escape(s['text'])+f'<sup><a href="#n{s["note"]}">[{s["note"]}]</a></sup> ')
                chunks.append('</p>')
            chunks.append('</div></article>')
        chunks.append('<section class="sheet"><h1>Fonti</h1><p>'+escape(document['library_name'])+'</p><ol>')
        for n in document['notes']:
            url=n['revision_url'];link='<a href="'+escape(url,quote=True)+'">Revisione della fonte</a>' if url.startswith('https://it.wikipedia.org/') else escape(n['source'])
            chunks.append(f'<li id="n{n["number"]}">'+escape(n['excerpt'])+'<p><small>'+(escape(n['title'])+' · '+escape(n['library_name'])+' · ' if n.get('title') else '')+link+'</small></p><details><summary>Contesto</summary>'+escape(n['context'])+'</details></li>')
        chunks.append('</ol><small>'+escape(document['reading_kind'])+' · Le citazioni documentano la fonte locale.</small></section></html>')
        return ''.join(chunks)
