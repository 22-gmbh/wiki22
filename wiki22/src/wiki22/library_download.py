"""Explicit, resumable downloads from the pinned release catalog; no startup traffic."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import threading
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
import zlib

CATALOG = Path(__file__).with_name('library_catalog.json')
CHUNK = 4 * 1024 * 1024

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Il server ha cambiato indirizzo. Aggiorna il catalogo di Wiki22.')

class Paused(Exception):
    pass


def file_hash(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


class LibraryDownloads:
    def __init__(self, service, catalog=None):
        self.service = service
        self.catalog = catalog if catalog is not None else json.loads(CATALOG.read_text())
        self.base = service.root / 'data/downloads'
        self.base.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.current = dict(status='idle', received=0, message='')
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def status(self):
        with self.lock:
            return dict(self.current)

    def listing(self):
        rows = []
        for c in self.catalog:
            row = self.service.registry.get(c['library']['id'])
            installed = bool(row and self.service.registry.resolve_pack(row['id']))
            rows.append(dict(id=c['id'], name=c['name'], description=c['description'],
                             download_bytes=sum(f['compressed'] for f in c['files']),
                             installed_bytes=sum(f['bytes'] for f in c['files']),
                             license=c['license'], articles=c['library']['article_count'],
                             installed=installed, removed=bool(row and row.get('removed'))))
        return dict(items=rows, transfer=self.status(), free_bytes=shutil.disk_usage(self.base).free)

    def start(self, library_id):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Un download è già in corso.')
            c = next((c for c in self.catalog if c['id'] == library_id), None)
            if c is None:
                raise ValueError('Libreria non presente nel catalogo.')
            row = self.service.registry.get(c['library']['id'])
            if row and self.service.registry.resolve_pack(row['id']):
                raise ValueError('Libreria già presente. Puoi ripristinarla da Librerie.')
            self.stop.clear()
            self.current = dict(id=library_id, status='downloading', received=0,
                                total=sum(f['compressed'] for f in c['files']), message='Preparo il download…')
            self.thread = threading.Thread(target=self._run, args=(c,), daemon=True)
            self.thread.start()
            return dict(self.current)

    def pause(self):
        self.stop.set()
        return self.status()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=25)

    def update(self, **values):
        with self.lock:
            self.current.update(values)

    def _run(self, c):
        try:
            self.install(c)
            self.update(status='complete', message='Libreria pronta da leggere offline.')
        except Paused:
            self.update(status='paused', message='In pausa. Puoi riprendere anche dopo aver riaperto Wiki22.')
        except Exception as e:
            if self.stop.is_set():
                self.update(status='paused', message='In pausa. Puoi riprendere anche dopo aver riaperto Wiki22.')
            else:
                message = 'La connessione si è interrotta. Premi Riprendi: i dati già scaricati sono conservati.' if isinstance(e, OSError) else str(e)
                self.update(status='error', message=message or 'Download interrotto. Puoi riprendere.')

    def install(self, c):
        # Directory and file names come only from the bundled catalog, never the HTTP client.
        if not re.fullmatch(r'[a-z0-9-]+', c['id']):
            raise ValueError('Identificativo catalogo non valido.')
        stage = self.base / c['id']
        stage.mkdir(exist_ok=True)
        final = self.service.root / 'data/catalog-libraries' / c['id']
        if final.exists():
            # A crash after atomic rename but before registry registration can be recovered.
            for f in c['files']:
                p = final / f['path']
                if not p.is_file() or p.stat().st_size != f['bytes'] or file_hash(p) != f['sha256']:
                    raise ValueError('Libreria esistente diversa dal catalogo: i file sono conservati.')
            return self.register(c, final)
        total_done = 0
        for f in c['files']:
            rel = PurePosixPath(f['path'])
            if rel.is_absolute() or '..' in rel.parts or '\\' in f['path'] or ':' in f['path']:
                raise ValueError('Percorso di catalogo non valido.')
            p = stage / f['path']; p.parent.mkdir(parents=True, exist_ok=True)
            part = p.with_name(p.name + '.download')
            if self.stop.is_set():
                raise Paused()
            if p.is_file() and p.stat().st_size == f['bytes'] and file_hash(p) == f['sha256']:
                total_done += f['compressed']; self.update(received=total_done); continue
            offset = part.stat().st_size if part.exists() else 0
            if offset > f['compressed']:
                part.unlink(); offset = 0
            remaining = sum(x['bytes'] for x in c['files'] if not (stage / x['path']).exists())
            required = remaining + max(x['compressed'] for x in c['files']) + 64*1024*1024
            if shutil.disk_usage(stage).free < required:
                raise ValueError('Spazio insufficiente: libera circa %.1f GB e riprendi.' % (required/1e9))
            self.update(message='Scarico ' + f['path'], received=total_done+offset)
            with part.open('ab') as out:
                while offset < f['compressed']:
                    if self.stop.is_set():
                        raise Paused()
                    count = min(CHUNK, f['compressed'] - offset)
                    start = f['offset'] + offset; end = start + count - 1
                    req = Request(c['url'], headers={'Range':f'bytes={start}-{end}', 'Accept-Encoding':'identity', 'User-Agent':'Wiki22/1.10 library-download'})
                    with self.opener.open(req, timeout=20) as r:
                        expected = f'bytes {start}-{end}/{c["archive_bytes"]}'
                        if r.status != 206 or r.headers.get('Content-Range') != expected or r.headers.get('Content-Encoding', 'identity') != 'identity':
                            raise ValueError('Il server non conferma la ripresa del download.')
                        data = bytearray()
                        while len(data) < count:
                            if self.stop.is_set():
                                raise Paused()
                            block = r.read(min(65536,count-len(data)))
                            if not block:break
                            data.extend(block)
                        if len(data) != count:
                            raise ValueError('Trasferimento incompleto. Premi Riprendi.')
                    out.write(data); out.flush(); offset += count
                    self.update(received=total_done+offset)
            self.update(status='verifying', message='Verifico ' + f['path'])
            temp = p.with_name(p.name + '.unpacking')
            try:
                h = hashlib.sha256(); size = 0
                dec = zlib.decompressobj(-15) if f['method'] == 8 else None
                if f['method'] not in (0, 8):
                    raise ValueError('Compressione non supportata.')
                with part.open('rb') as src, temp.open('wb') as dst:
                    while chunk := src.read(65536):
                        if self.stop.is_set():
                            raise Paused()
                        chunk = dec.decompress(chunk, min(8*1024*1024, f['bytes']-size+1)) if dec else chunk
                        if dec and dec.unconsumed_tail:
                            raise ValueError('Blocco compresso oltre il limite.')
                        size += len(chunk)
                        if size > f['bytes']:
                            raise ValueError('Dimensione del file non valida.')
                        dst.write(chunk); h.update(chunk)
                if (dec and (not dec.eof or dec.unused_data)) or size != f['bytes'] or h.hexdigest() != f['sha256']:
                    part.unlink(missing_ok=True)
                    raise ValueError('Impronta SHA-256 diversa: il file non è stato installato. Riprendi per riscaricarlo.')
                temp.replace(p); part.unlink()
            finally:
                temp.unlink(missing_ok=True)
            total_done += f['compressed']; self.update(status='downloading', received=total_done)
        if self.stop.is_set():
            raise Paused()
        final.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(final)
        self.register(c, final)

    def register(self, c, final):
        with self.service.import_lock, self.service.lock:
            data = self.service.registry.load()
            row = dict(c['library'], pack_path=str((final / c['pack']).relative_to(self.service.root)))
            if any(r['id'] == row['id'] for r in data['libraries']):
                # Only replace the unavailable factory reference; never an existing usable library.
                prior = self.service.registry.get(row['id'])
                if self.service.registry.resolve_pack(row['id']):
                    return
                data['libraries'] = [r for r in data['libraries'] if r['id'] != row['id']]
            data['libraries'].append(row)
            if not data.get('default_library_id'):
                data['default_library_id'] = row['id']
            self.service.registry.save(data)
