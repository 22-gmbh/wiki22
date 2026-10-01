"""User-selected local and public-web sources, previewed before 22CK conversion."""
from html.parser import HTMLParser
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import tempfile
import threading
import time
from urllib.parse import urlsplit, urlunsplit, urljoin
from urllib.robotparser import RobotFileParser
from .document_import import NATIVE, OPTIONAL, MAX_FILE, MAX_FILES, import_documents

WEB_LIMIT = 4 * 1024 * 1024


class PageTitle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.inside=False; self.parts=[]
    def handle_starttag(self, tag, attrs):
        if tag=='title':self.inside=True
    def handle_endtag(self, tag):
        if tag=='title':self.inside=False
    def handle_data(self, data):
        if self.inside:self.parts.append(data)


def public_address(url):
    u = urlsplit(url)
    if u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password:
        raise ValueError('Usa un indirizzo pubblico http o https, senza credenziali.')
    port = u.port or (443 if u.scheme == 'https' else 80)
    if port != (443 if u.scheme == 'https' else 80):
        raise ValueError('Sono supportate soltanto le porte web standard.')
    addresses = socket.getaddrinfo(u.hostname, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('La sonda web accetta solo siti pubblici, non indirizzi locali o privati.')
    return u, addresses[0][4][0], port


def fetch_public(url, limit=WEB_LIMIT, *, redirects=True):
    # Connect to the validated IP: a second DNS lookup cannot redirect into the LAN.
    for _ in range(4):
        u, address, port = public_address(url)
        conn = http.client.HTTPConnection(u.hostname, port, timeout=15)
        sock = socket.create_connection((address, port), timeout=15)
        try:
            if u.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=u.hostname)
            conn.sock = sock
            path = urlunsplit(('', '', u.path or '/', u.query, ''))
            conn.request('GET', path, headers={'Host':u.netloc, 'User-Agent':'Wiki22SourceProbe/1.0 (+https://www.twenty-two.ch/wiki22.html)', 'Accept-Encoding':'identity'})
            response = conn.getresponse()
            if response.status in (301,302,303,307,308):
                if not redirects:
                    return dict(url=url,status=response.status,location=urljoin(url,response.getheader('Location') or ''))
                url = urljoin(url, response.getheader('Location') or '')
                continue
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('Il sito usa una codifica non supportata.')
            raw = response.read(limit+1)
            if len(raw) > limit:
                raise ValueError('Pagina oltre il limite di 4 MiB.')
            return dict(url=url,status=response.status,content_type=response.getheader('Content-Type',''),raw=raw)
        finally:
            conn.close(); sock.close()
    raise ValueError('Troppi reindirizzamenti.')


def fetch_source(url):
    # Check the policy before each page, including a redirected destination.
    for _ in range(4):
        u, _, _ = public_address(url)
        robots_url = urlunsplit((u.scheme,u.netloc,'/robots.txt','',''))
        robots = fetch_public(robots_url,512*1024)
        if robots['status'] == 200:
            rules = RobotFileParser(); rules.parse(robots['raw'].decode('utf-8','replace').splitlines())
            if not rules.can_fetch('Wiki22SourceProbe',url):
                raise ValueError('Il sito non consente questa raccolta nel suo robots.txt.')
        elif robots['status'] not in (404,410):
            raise ValueError('Non posso verificare le regole di raccolta del sito.')
        result = fetch_public(url, redirects=False)
        if result['status'] in (301,302,303,307,308):
            target = urlsplit(result['location'])
            if (target.scheme,target.netloc) != (u.scheme,u.netloc):
                raise ValueError('Il sito rimanda a un altro dominio: usa direttamente il nuovo indirizzo.')
            url = result['location']; continue
        if result['status'] != 200:
            raise ValueError('Pagina non accessibile (HTTP %s).' % result['status'])
        break
    else:
        raise ValueError('Troppi reindirizzamenti.')
    kind = result['content_type'].split(';')[0].strip().lower()
    if kind not in ('text/html','application/xhtml+xml','text/plain','application/pdf'):
        raise ValueError('Sono supportate pagine HTML, testo e PDF pubblici.')
    result['extension'] = '.pdf' if kind == 'application/pdf' else '.html' if 'html' in kind else '.txt'
    if result['extension'] != '.pdf':
        import re
        m = re.search(r'charset\s*=\s*["\x27]?([\w-]+)',result['content_type'],re.I)
        result['raw'] = result['raw'].decode(m[1] if m else 'utf-8',errors='replace').encode('utf-8')
    return result


class SourceProbe:
    def __init__(self, service):
        self.service=service
        self.lock=threading.Lock()
        self.cache=tempfile.TemporaryDirectory(prefix='wiki22-sources-')
        self.plan=None

    def close(self):
        self.cache.cleanup()

    def scan(self, paths=None, urls=None):
        paths=paths or [];urls=urls or []
        if not isinstance(paths,list) or not isinstance(urls,list) or any(not isinstance(x,str) for x in paths+urls) or len(paths)>20 or len(urls)>20:
            raise ValueError('Scegli fino a 20 percorsi e 20 indirizzi web.')
        if not paths and not urls:
            raise ValueError('Scegli almeno una fonte.')
        with self.lock:
            self.cache.cleanup();self.cache=tempfile.TemporaryDirectory(prefix='wiki22-sources-')
            self.plan=None; rows=[];seen=set(); visited=0
            def add(path):
                nonlocal visited
                visited+=1
                if visited>MAX_FILES:raise ValueError('Oltre 5000 file: scegli cartelle più piccole.')
                if path.is_symlink() or not path.is_file():return
                path=path.resolve()
                if path in seen:return
                seen.add(path)
                st=path.stat(); valid=path.suffix.lower() in NATIVE|OPTIONAL.keys() and 0<st.st_size<=MAX_FILE
                rows.append(dict(id=str(len(rows)),label=path.name,source=str(path),path=str(path),bytes=st.st_size,
                    status='ready' if valid else 'skipped',reason='' if valid else 'Formato o dimensione non supportati',
                    stamp=[st.st_size,st.st_mtime_ns],kind='local'))
            for raw in paths:
                chosen=Path(raw).expanduser()
                if chosen.is_symlink():raise ValueError('Scegli una cartella o un file originale, non un collegamento.')
                p=chosen.resolve(strict=True)
                if self.service.root.is_relative_to(p) or p.is_relative_to(self.service.root):
                    raise ValueError('Scegli documenti esterni ai dati di Wiki22.')
                if p.is_dir():
                    for base,dirs,files in os.walk(p,followlinks=False):
                        dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not (Path(base)/d).is_symlink())
                        for name in sorted(files):
                            if not name.startswith('.'):add(Path(base)/name)
                else:add(p)
            for url in dict.fromkeys(urls):
                item=dict(id=str(len(rows)),label=url,source=url,kind='web',status='skipped',bytes=0)
                rows.append(item)
                try:
                    fetched=fetch_source(url)
                    import re
                    title=urlsplit(fetched['url']).path.rstrip('/').rsplit('/',1)[-1] or urlsplit(fetched['url']).hostname
                    if fetched['extension']=='.html':
                        parser=PageTitle();parser.feed(fetched['raw'].decode('utf-8','replace'))
                        title=''.join(parser.parts).strip() or title
                    title=re.sub(r'[^\w .-]',' ',title).strip(' .')[:100] or 'Pagina web'
                    folder=Path(self.cache.name)/item['id'];folder.mkdir()
                    path=folder/(title+fetched['extension'])
                    item['label']=title
                    path.write_bytes(fetched['raw']);st=path.stat()
                    item.update(path=str(path),source=fetched['url'],bytes=st.st_size,stamp=[st.st_size,st.st_mtime_ns],
                                sha256=hashlib.sha256(fetched['raw']).hexdigest(),status='ready',reason='')
                except (OSError,ValueError,http.client.HTTPException) as exc:
                    item['reason']=str(exc)
            token=secrets.token_urlsafe(24)
            self.plan=dict(token=token,rows=rows,created=time.time())
            return dict(token=token,rows=[{k:v for k,v in r.items() if k not in ('path','stamp')} for r in rows])

    def create(self, token, selected, name):
        if not isinstance(selected,list) or any(not isinstance(x,str) for x in selected) or not 1<=len(selected)<=500:
            raise ValueError('Scegli da 1 a 500 documenti per libreria.')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:
            raise ValueError('Assegna un nome alla libreria (massimo 80 caratteri).')
        with self.lock, self.service.import_lock, self.service.lock:
            if not self.plan or token!=self.plan['token'] or time.time()-self.plan['created']>3600:
                raise ValueError('Anteprima scaduta. Esplora nuovamente le fonti.')
            rows={r['id']:r for r in self.plan['rows']}
            chosen=[];refs={}
            for key in dict.fromkeys(selected):
                row=rows.get(key)
                if not row or row['status']!='ready':raise ValueError('Fonte non disponibile.')
                p=Path(row['path']);st=p.stat()
                if p.is_symlink() or [st.st_size,st.st_mtime_ns]!=row['stamp']:
                    raise ValueError('Una fonte è cambiata. Esplora nuovamente prima di importare.')
                chosen.append(p)
                if row['kind']=='web':refs[str(p)]=row['source']
            return import_documents(self.service.registry,Path(self.cache.name),name.strip(),selected_files=chosen,source_refs=refs)
